"""Ingestion-completeness audit (Goal 12): "what data do we have, what period
does it cover, and what are we missing?" answered from one computed snapshot
instead of cross-referencing the registry doc, the scheduler dashboard, the
raw-storage manifests and a database console by hand.

config/data-sources.yaml is a hand-maintained, prose-heavy DOCUMENT — useful
for category/priority/jurisdiction metadata, but its `enabled`/`last_checked`/
`health_status` fields are snapshots frozen at goal-writing time, not live
truth (the yaml's own header makes this point about its licensing fields; the
same caution applies to its operational fields). Every number in this module
that can be computed from a live system — DB row/date ranges, scheduler_log
history, raw_storage manifests/checkpoints, disk usage — IS, rather than
trusted from the yaml. The yaml is cross-referenced for drift (a source
documented as enabled with no matching scheduler job, or vice versa) rather
than taken at face value; see `run_validation`.

`build_inventory()` is the one entry point: it returns a single dict that
scripts/nessus.py's six subcommands and the /api/data/health route each
render a slice of, so the underlying queries run once, not six times.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog
import yaml
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pipeline import raw_storage as rs

log = structlog.get_logger()

REGISTRY_PATH = Path("./config/data-sources.yaml")

# Tables big enough (>1M rows) that even a single MIN/MAX aggregate scan is
# worth gating behind --deep by default — the same two tables CLAUDE.md's
# PERFORMANCE RULE already singles out for the product's interactive routes.
# Every other Tier 1 table (including OCL's 363k-row lobbying table) gets its
# date range computed unconditionally: this is a manual, on-demand diagnostic
# command, not a hot product path, and a few seconds is an acceptable cost.
_TIER1_BIG_TABLE_JOB_IDS = {"contracts_monthly", "donations_quarterly"}

# Breadth (source_records) sources above this row count only get a real
# distinct-year scan when --deep is passed; smaller ones always do.
_BREADTH_DEEP_ROW_THRESHOLD = 5000

_CADENCE_STALE_DAYS = {
    "every 4 hours": 1, "every business day": 3, "daily": 2, "weekly": 10,
    "monthly": 40, "quarterly": 110,
}

_PLAUSIBLE_YEAR_MIN = 1990  # mirrors the existing Hansard-date sanity bound (CLAUDE.md gotchas)


# ── Registry (config/data-sources.yaml) ──────────────────────────────────────

def load_registry(path: Path | None = None) -> list[dict[str, Any]]:
    # `path` defaults to the REGISTRY_PATH *global*, looked up at call time
    # (not bound as a default-argument value at function-definition time) —
    # tests monkeypatch da.REGISTRY_PATH and expect that to take effect.
    path = path or REGISTRY_PATH
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return list(data.get("sources", []))


# ── Live scheduler registry (api/scheduler.py — the actual cron jobs) ───────

def scheduler_job_configs() -> list[dict[str, Any]]:
    """The live job list, including breadth connectors registered at import
    time. Imported lazily — api.scheduler pulls in APScheduler/FastAPI's
    whole dependency chain, which a CLI-only invocation of this module
    shouldn't pay for unless it actually needs the live registry."""
    from api.scheduler import SOURCE_CONFIGS
    return SOURCE_CONFIGS


def next_fire_times(*, now: datetime | None = None) -> dict[str, str | None]:
    now = now or datetime.now(timezone.utc)
    out: dict[str, str | None] = {}
    for cfg in scheduler_job_configs():
        trigger = cfg.get("trigger")
        try:
            nxt = trigger.get_next_fire_time(None, now) if trigger else None
        except Exception:
            nxt = None
        out[cfg["id"]] = nxt.isoformat() if nxt else None
    return out


# ── Raw-storage manifests / checkpoints / backfill records ──────────────────

def manifest_summary() -> dict[str, dict[str, Any]]:
    """source_id -> {category, entries, files, duplicates, bytes,
    last_saved_at, missing_on_disk}. `files`/`bytes` count only non-duplicate
    manifest entries (save_raw's own content-hash dedup means a `duplicate`
    entry never wrote a new file) — counting them would double-count bytes
    that are already on disk under an earlier entry's path."""
    out: dict[str, dict[str, Any]] = {}
    if not rs.MANIFESTS_DIR.exists():
        return out
    for path in sorted(rs.MANIFESTS_DIR.glob("*.jsonl")):
        category, _, source_id = path.stem.partition("__")
        if not source_id:
            continue
        entry = out.setdefault(source_id, {
            "category": category, "entries": 0, "files": 0, "duplicates": 0,
            "bytes": 0, "last_saved_at": None, "missing_on_disk": [],
        })
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            entry["entries"] += 1
            if rec.get("duplicate"):
                entry["duplicates"] += 1
            else:
                entry["files"] += 1
                entry["bytes"] += rec.get("size") or 0
                if rec.get("path") and not Path(rec["path"]).exists():
                    entry["missing_on_disk"].append(rec["path"])
            saved_at = rec.get("saved_at")
            if saved_at and (entry["last_saved_at"] is None or saved_at > entry["last_saved_at"]):
                entry["last_saved_at"] = saved_at
    return out


def checkpoint_summary(source_id: str) -> dict[str, Any] | None:
    """Two distinct writers share data/checkpoints/<source_id>.json: a paged
    walk (pipeline/api_paginator.py — has "status"/"gaps"/"last_cursor") or a
    full-snapshot conditional-fetch gate (pipeline/conditional_fetch.py — has
    only "_conditional_fetch_fingerprint"). No source currently uses both, so
    there's no merge conflict to resolve, just two shapes to recognise."""
    cp = rs.read_checkpoint(source_id)
    if not cp:
        return None
    gaps = cp.get("gaps") or []
    if "status" in cp:
        kind = "paginated"
    elif "_conditional_fetch_fingerprint" in cp:
        kind = "conditional_fetch"
    else:
        kind = "other"
    return {
        "kind": kind, "status": cp.get("status"), "open_gaps": len(gaps), "gaps": gaps,
        "last_cursor": cp.get("last_cursor"), "updated_at": cp.get("updated_at"),
    }


def backfill_records_index() -> dict[str, dict[str, Any]]:
    return {rec["source_id"]: rec for rec in rs.all_backfill_records()}


# ── Disk usage ────────────────────────────────────────────────────────────────

def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return total


def disk_usage_summary() -> dict[str, Any]:
    base = rs.DATA_DIR if rs.DATA_DIR.exists() else Path(".")
    usage = shutil.disk_usage(base)
    breakdown = {
        "raw": _dir_size(rs.RAW_DIR),
        "cache": _dir_size(rs.DATA_DIR / "cache"),
        "manifests": _dir_size(rs.MANIFESTS_DIR),
        "checkpoints": _dir_size(rs.CHECKPOINTS_DIR),
        "quarantine": _dir_size(rs.QUARANTINE_DIR),
        "extracted": _dir_size(rs.EXTRACTED_DIR),
        "index": _dir_size(rs.DATA_DIR / "index"),
    }
    db_path = Path("./polaris.db")
    db_bytes = db_path.stat().st_size if db_path.exists() else None
    return {
        "total_bytes": usage.total, "used_bytes": usage.used, "free_bytes": usage.free,
        "free_pct": round(usage.free / usage.total * 100, 1) if usage.total else None,
        "breakdown_bytes": breakdown,
        "db_file_bytes": db_bytes,
        "db_file_note": None if db_bytes is not None else "no local polaris.db — DATABASE_URL likely points at Postgres",
    }


# ── Scheduler run history ────────────────────────────────────────────────────

async def scheduler_history(session: AsyncSession) -> dict[str, dict[str, Any]]:
    """job_id -> last_run (any status), last_success (ok or skipped — a
    conditional-fetch "skipped" IS a successful check, just no new data),
    last_error, last_definitive (most recent ok/error, ignoring
    skipped/running — the signal _classify_backfill needs), counts."""
    from api.models.scheduler_log import SchedulerLog

    rows = (await session.execute(
        select(SchedulerLog).order_by(SchedulerLog.started_at.desc())
    )).scalars().all()

    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        bucket = out.setdefault(r.job_id, {
            "last_run": None, "last_success": None, "last_error": None,
            "last_definitive": None, "total_runs": 0, "error_count": 0, "skipped_count": 0,
        })
        bucket["total_runs"] += 1
        as_dict = {
            "status": r.status,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "rows_added": r.rows_added, "rows_total": r.rows_total,
            "duration_s": round(r.duration_s, 1) if r.duration_s else None,
            "error": r.error, "triggered_by": r.triggered_by,
        }
        if bucket["last_run"] is None:
            bucket["last_run"] = as_dict
        if r.status == "error":
            bucket["error_count"] += 1
            if bucket["last_error"] is None:
                bucket["last_error"] = as_dict
        elif r.status == "skipped":
            bucket["skipped_count"] += 1
            if bucket["last_success"] is None:
                bucket["last_success"] = as_dict
        elif r.status == "ok" and bucket["last_success"] is None:
            bucket["last_success"] = as_dict
        if r.status in ("ok", "error") and bucket["last_definitive"] is None:
            bucket["last_definitive"] = as_dict
    return out


# ── Tier 1 (typed-table) row counts + date ranges ────────────────────────────

async def _tier1_models() -> dict[str, tuple[Any, str]]:
    """job_id -> (Model, date_col) — mirrors api/routes/sources.py's table/
    date-column map (same models, same columns) but keyed by job_id since
    that's this module's join key against the scheduler and yaml registry."""
    from api.models.appointment import Appointment
    from api.models.contract import Contract
    from api.models.donation import Bill, Donation
    from api.models.entity import LobbyingRecord
    from api.models.grant import Grant
    from api.models.ocl_registration import OCLRegistration
    from api.models.politician import HansardMention, Politician
    from api.models.regulation import GazetteEntry, TribunalDecision

    return {
        "contracts_monthly": (Contract, "contract_date"),
        "donations_quarterly": (Donation, "received_date"),
        "ocl_monthly": (LobbyingRecord, "communication_date"),
        "bills_daily": (Bill, "introduced_date"),
        "gazette_weekly": (GazetteEntry, "published_date"),
        "parliament_seed": (Politician, "since_date"),
        "hansard_search": (HansardMention, "speech_date"),
        "grants_quarterly": (Grant, "agreement_start"),
        "appointments_weekly": (Appointment, "appointment_date"),
        "ocl_registrations": (OCLRegistration, "effective_date"),
        "tribunal_decisions": (TribunalDecision, "decision_date"),
    }


async def _count_exact(session: AsyncSession, model: Any) -> int:
    return (await session.execute(select(func.count(model.id)))).scalar_one()


async def _count_approx(session: AsyncSession, model: Any) -> int:
    return (await session.execute(select(func.max(model.id)))).scalar_one() or 0


async def _min_max_date(session: AsyncSession, model: Any, date_col: str) -> tuple[str | None, str | None]:
    col = getattr(model, date_col)
    row = (await session.execute(
        select(func.min(col), func.max(col)).where(col.isnot(None), col != "")
    )).first()
    return (row[0], row[1]) if row else (None, None)


async def _years_present(session: AsyncSession, model: Any, date_col: str, *,
                          source_col: Any | None = None, source_value: str | None = None) -> set[int]:
    """Distinct years present in a date/text column, via substr(col,1,4) — every
    date format used in this codebase ("%Y-%m-%d", "%Y-%m", "%Y") starts with
    a 4-digit year, so this works across all of them without per-source
    parsing. Bounds reject obvious garbage (Hansard's well-known year-4043
    bug) while still surfacing real-but-anomalous values (e.g. grants'
    documented 1899 Excel-epoch placeholder) — see run_validation's plausible-
    date check for flagging those instead of silently discarding them."""
    col = getattr(model, date_col)
    stmt = select(func.substr(col, 1, 4)).where(col.isnot(None), col != "").distinct()
    if source_col is not None and source_value is not None:
        stmt = stmt.where(source_col == source_value)
    rows = (await session.execute(stmt)).scalars().all()
    years: set[int] = set()
    for raw in rows:
        try:
            y = int(str(raw)[:4])
        except (TypeError, ValueError):
            continue
        if 1800 <= y <= 2100:
            years.add(y)
    return years


def _missing_years(present: set[int]) -> list[int]:
    if not present:
        return []
    return sorted(set(range(min(present), max(present) + 1)) - present)


async def tier1_metrics(session: AsyncSession, *, deep: bool) -> dict[str, dict[str, Any]]:
    models = await _tier1_models()
    out: dict[str, dict[str, Any]] = {}
    for job_id, (model, date_col) in models.items():
        approx = job_id in _TIER1_BIG_TABLE_JOB_IDS
        rows = await (_count_approx(session, model) if approx else _count_exact(session, model))
        earliest = latest = None
        missing_years: list[int] | None = None
        years_computed = False
        if rows and (not approx or deep):
            earliest, latest = await _min_max_date(session, model, date_col)
            missing_years = _missing_years(await _years_present(session, model, date_col))
            years_computed = True
        out[job_id] = {
            "table": model.__tablename__, "rows": rows,
            "row_count_method": "max_id" if approx else "exact",
            "earliest_date": earliest, "latest_date": latest,
            "missing_years": missing_years, "missing_years_computed": years_computed,
        }
    return out


async def breadth_metrics(session: AsyncSession, *, deep: bool) -> dict[str, dict[str, Any]]:
    """One source_records value -> {rows, earliest, latest, missing_years}
    per breadth connector (npri, cer, iaac, statcan, gc_news, every feeds.py/
    news_feeds.py id, ...). A GROUP BY gives every connector's count+date
    range in one pass; a source with zero rows has no group and is filled in
    by build_inventory's union of (yaml ∪ scheduler ∪ these) ids."""
    from api.models.source_record import SourceRecord

    grouped = (await session.execute(
        select(SourceRecord.source, func.count(SourceRecord.id),
               func.min(SourceRecord.event_date), func.max(SourceRecord.event_date))
        .where(SourceRecord.event_date.isnot(None), SourceRecord.event_date != "")
        .group_by(SourceRecord.source)
    )).all()

    out: dict[str, dict[str, Any]] = {}
    for source, count, mn, mx in grouped:
        missing_years: list[int] | None = None
        years_computed = False
        if count and (count <= _BREADTH_DEEP_ROW_THRESHOLD or deep):
            present = await _years_present(session, SourceRecord, "event_date",
                                            source_col=SourceRecord.source, source_value=source)
            missing_years = _missing_years(present)
            years_computed = True
        out[source] = {
            "table": "source_records", "rows": count, "row_count_method": "exact",
            "earliest_date": mn, "latest_date": mx,
            "missing_years": missing_years, "missing_years_computed": years_computed,
        }
    return out


# ── Backfill / staleness classification ──────────────────────────────────────

def _classify_backfill(rows: int, checkpoint: dict[str, Any] | None,
                        last_definitive: dict[str, Any] | None) -> str:
    """"full" | "partial" | "not_started" — derived from live state, not the
    yaml's prose `backfill_strategy` field:
      - 0 rows: not_started.
      - a paginated checkpoint: "complete" with no open gaps is full, anything
        else (in_progress, or complete-but-still-gappy) is partial.
      - no checkpoint (a full-snapshot bulk source, or a source with no
        checkpoint at all): partial only if the most recent ok/error run was
        an error that still committed rows — exactly the StreamLoadError
        "dropped stream at the tail != data lost" case CLAUDE.md documents.
    """
    if rows == 0:
        return "not_started"
    if checkpoint and checkpoint.get("status"):
        if checkpoint["status"] == "complete" and not checkpoint.get("open_gaps"):
            return "full"
        return "partial"
    if last_definitive and last_definitive.get("status") == "error" and (last_definitive.get("rows_added") or 0) > 0:
        return "partial"
    return "full"


def _is_stale(cadence: str | None, last_success: dict[str, Any] | None) -> bool | None:
    if not cadence or not last_success or not last_success.get("finished_at"):
        return None
    threshold_days = _CADENCE_STALE_DAYS.get(cadence)
    if threshold_days is None:
        return None
    finished = datetime.fromisoformat(last_success["finished_at"])
    if finished.tzinfo is None:
        finished = finished.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - finished).days > threshold_days


# ── Validation checks ─────────────────────────────────────────────────────────

def _check(name: str, ok: bool, detail: str, *, warn_only: bool = False) -> dict[str, Any]:
    return {"check": name, "status": "pass" if ok else ("warn" if warn_only else "fail"), "detail": detail}


def run_validation(sources: list[dict[str, Any]], registry: list[dict[str, Any]],
                    wired_ids: set[str], disk: dict[str, Any],
                    manifests: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    registry_ids = {s["id"] for s in registry}

    enabled_not_wired = sorted(s["id"] for s in registry if s.get("enabled") and s["id"] not in wired_ids)
    checks.append(_check(
        "registry_enabled_sources_are_wired", not enabled_not_wired,
        "Every yaml-enabled source has a matching scheduler job." if not enabled_not_wired else
        f"{len(enabled_not_wired)} source(s) marked enabled in config/data-sources.yaml have no "
        f"matching scheduler job id: {enabled_not_wired}",
        warn_only=True,
    ))

    wired_not_registered = sorted(wired_ids - registry_ids)
    checks.append(_check(
        "wired_jobs_are_documented", not wired_not_registered,
        "Every scheduled job has a config/data-sources.yaml entry." if not wired_not_registered else
        f"{len(wired_not_registered)} scheduled job id(s) have no config/data-sources.yaml entry "
        f"under that exact id (may be a naming drift, e.g. yaml uses a different id for the same "
        f"source): {wired_not_registered}",
        warn_only=True,
    ))

    zero_row = sorted(s["id"] for s in sources if s["wired_in_scheduler"] and s["rows"] == 0)
    checks.append(_check(
        "wired_sources_have_data", not zero_row,
        "Every scheduled source has at least one row loaded." if not zero_row else
        f"{len(zero_row)} scheduled source(s) are wired but have zero rows loaded: {zero_row}",
    ))

    recent_errors = sorted(s["id"] for s in sources if s["last_run"] and s["last_run"]["status"] == "error")
    checks.append(_check(
        "most_recent_run_not_an_error", not recent_errors,
        "No source's most recent run ended in error." if not recent_errors else
        f"{len(recent_errors)} source(s) whose most recent scheduled/manual run failed: {recent_errors}",
    ))

    open_gaps = sorted(s["id"] for s in sources if s["checkpoint"] and s["checkpoint"]["open_gaps"])
    checks.append(_check(
        "no_open_pagination_gaps", not open_gaps,
        "No source has an unresolved page-fetch gap." if not open_gaps else
        f"{len(open_gaps)} source(s) have an unresolved page-fetch gap recorded in their checkpoint: {open_gaps}",
        warn_only=True,
    ))

    missing_on_disk = {sid: m["missing_on_disk"] for sid, m in manifests.items() if m.get("missing_on_disk")}
    checks.append(_check(
        "manifest_files_exist_on_disk", not missing_on_disk,
        "Every manifest-recorded raw file is present on disk." if not missing_on_disk else
        f"{sum(len(v) for v in missing_on_disk.values())} manifest-recorded file(s) are missing on "
        f"disk across {len(missing_on_disk)} source(s): {list(missing_on_disk)}",
    ))

    stale = sorted(s["id"] for s in sources if s["stale"])
    checks.append(_check(
        "sources_within_freshness_window", not stale,
        "Every source with a known cadence has synced within its expected window." if not stale else
        f"{len(stale)} source(s) haven't had a successful sync within their cadence's expected window: {stale}",
        warn_only=True,
    ))

    free_pct = disk.get("free_pct")
    low_disk = free_pct is not None and free_pct <= 5
    checks.append(_check(
        "disk_headroom", not low_disk,
        f"Only {free_pct}% disk free — a full-corpus ingest can hit 'database or disk is full' mid-run."
        if low_disk else (f"{free_pct}% disk free." if free_pct is not None else "Disk usage unknown."),
    ))

    now_year = datetime.now(timezone.utc).year
    implausible: list[str] = []
    for s in sources:
        for label, val in (("earliest_date", s.get("earliest_date")), ("latest_date", s.get("latest_date"))):
            if not val:
                continue
            try:
                y = int(str(val)[:4])
            except ValueError:
                continue
            if y < _PLAUSIBLE_YEAR_MIN or y > now_year + 1:
                implausible.append(f"{s['id']}.{label}={val}")
    checks.append(_check(
        "dates_within_plausible_range", not implausible,
        f"All earliest/latest dates fall within {_PLAUSIBLE_YEAR_MIN}-{now_year + 1}." if not implausible else
        f"{len(implausible)} implausible date value(s) outside {_PLAUSIBLE_YEAR_MIN}-{now_year + 1} "
        f"(often a parsing artifact, e.g. an Excel-epoch placeholder — verify, don't assume corrupt): "
        f"{implausible[:10]}",
        warn_only=True,
    ))

    return checks


# ── The composite report ─────────────────────────────────────────────────────

async def build_inventory(session: AsyncSession, *, deep: bool = False) -> dict[str, Any]:
    registry = load_registry()
    registry_by_id = {s["id"]: s for s in registry}
    configs = scheduler_job_configs()
    wired_ids = {c["id"] for c in configs}
    name_by_id = {c["id"]: c.get("name") for c in configs}
    cadence_by_id = {c["id"]: c.get("cadence") for c in configs}
    next_sync = next_fire_times()

    history = await scheduler_history(session)
    tier1 = await tier1_metrics(session, deep=deep)
    breadth = await breadth_metrics(session, deep=deep)
    manifests = manifest_summary()
    backfills = backfill_records_index()

    all_ids = set(registry_by_id) | wired_ids | set(tier1) | set(breadth)

    sources: list[dict[str, Any]] = []
    for sid in sorted(all_ids):
        reg = registry_by_id.get(sid, {})
        metrics = tier1.get(sid) or breadth.get(sid) or {}
        rows = metrics.get("rows", 0)
        hist = history.get(sid, {})
        cp = checkpoint_summary(sid)
        table = metrics.get("table") or ("source_records" if sid not in tier1 and sid in wired_ids else None)

        state = _classify_backfill(rows, cp, hist.get("last_definitive"))
        cadence = cadence_by_id.get(sid) or reg.get("check_frequency")

        sources.append({
            "id": sid,
            "name": reg.get("name") or name_by_id.get(sid) or sid,
            "category": reg.get("category"),
            "jurisdiction": reg.get("jurisdiction"),
            "priority": reg.get("priority"),
            "enabled_in_registry": bool(reg.get("enabled")) if reg else None,
            "wired_in_scheduler": sid in wired_ids,
            "cadence": cadence,
            "table": table,
            "rows": rows,
            "row_count_method": metrics.get("row_count_method", "n/a"),
            "earliest_date": metrics.get("earliest_date"),
            "latest_date": metrics.get("latest_date"),
            "missing_years": metrics.get("missing_years"),
            "missing_years_computed": metrics.get("missing_years_computed", False),
            "checkpoint": cp,
            "manifest": manifests.get(sid),
            "backfill_record": backfills.get(sid),
            "backfill_state": state,
            "last_run": hist.get("last_run"),
            "last_success": hist.get("last_success"),
            "last_error": hist.get("last_error"),
            "total_runs": hist.get("total_runs", 0),
            "error_count": hist.get("error_count", 0),
            "next_scheduled_sync": next_sync.get(sid),
            "stale": _is_stale(cadence, hist.get("last_success")),
        })

    files_downloaded = sum(m["files"] for m in manifests.values())
    bytes_downloaded = sum(m["bytes"] for m in manifests.values())
    duplicate_files = sum(m["duplicates"] for m in manifests.values())
    last_successes = [s["last_success"]["finished_at"] for s in sources
                       if s["last_success"] and s["last_success"].get("finished_at")]
    upcoming = [s["next_scheduled_sync"] for s in sources if s["next_scheduled_sync"]]

    totals = {
        "files_downloaded": files_downloaded,
        "bytes_downloaded": bytes_downloaded,
        "duplicate_files": duplicate_files,
        "failed_downloads": sum(s["error_count"] for s in sources),
        "last_successful_sync": max(last_successes) if last_successes else None,
        "next_scheduled_sync": min(upcoming) if upcoming else None,
        "fully_backfilled": sum(1 for s in sources if s["backfill_state"] == "full"),
        "partially_backfilled": sum(1 for s in sources if s["backfill_state"] == "partial"),
        "not_started": sum(1 for s in sources if s["backfill_state"] == "not_started"),
    }

    disk = disk_usage_summary()
    validate = run_validation(sources, registry, wired_ids, disk, manifests)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "deep": deep,
        "registry_summary": {
            "total_registered": len(registry),
            "enabled_in_registry": sum(1 for s in registry if s.get("enabled")),
            "disabled_in_registry": sum(1 for s in registry if not s.get("enabled")),
            "wired_in_scheduler": len(wired_ids),
        },
        "sources": sources,
        "totals": totals,
        "disk": disk,
        "validate": validate,
    }
