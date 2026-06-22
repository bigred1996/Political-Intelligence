"""Nessus data-refresh scheduler.

Runs inside the FastAPI process via APScheduler AsyncIOScheduler.
Each source has a configured cadence matching its upstream publish frequency.

Update cadences:
  daily       — Bills (LEGISinfo, Parliament sits daily), Canada Gazette RSS
  weekly      — GIC Appointments (OIC appointments published weekly)
  monthly     — Federal Contracts, OCL Lobbying Communications
  quarterly   — Elections Canada Donations, Grants & Contributions

The scheduler persists job state to the DB so next-run times survive restarts.
Each run is logged to the scheduler_log table for auditing and dashboard display.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from api.cache import invalidate_workspace_caches

log = structlog.get_logger()

scheduler = AsyncIOScheduler(timezone="America/Toronto")


# ── Source job registry ───────────────────────────────────────────────────────

SOURCE_CONFIGS: list[dict[str, Any]] = [
    {
        "id": "bills_daily",
        "name": "Bills & Legislation (LEGISinfo)",
        "cadence": "daily",
        "trigger": CronTrigger(hour=6, minute=0, timezone="America/Toronto"),
        "description": "LEGISinfo JSON API — Parliament sits daily; bills move status frequently.",
        "typical_rows": 200,
    },
    {
        "id": "gazette_weekly",
        "name": "Canada Gazette Part I + II",
        "cadence": "weekly",
        "trigger": CronTrigger(day_of_week="sat", hour=8, minute=0, timezone="America/Toronto"),
        "description": "Part I published every Saturday; Part II bi-weekly. RSS pull is fast (~2s).",
        "typical_rows": 15,
    },
    {
        "id": "parliament_seed",
        "name": "MP Profiles",
        "cadence": "weekly",
        "trigger": CronTrigger(day_of_week="sun", hour=7, minute=0, timezone="America/Toronto"),
        "description": "OpenParliament MP roster refresh for politician profiles and actor resolution.",
        "typical_rows": 350,
    },
    {
        "id": "hansard_search",
        "name": "Hansard Sector Mentions",
        "cadence": "daily",
        "trigger": CronTrigger(hour=7, minute=30, timezone="America/Toronto"),
        "description": "Lightweight OpenParliament speech search over sector keywords for actor-risk context.",
        "typical_rows": 100,
    },
    {
        "id": "appointments_weekly",
        "name": "GIC Appointments",
        "cadence": "weekly",
        "trigger": CronTrigger(day_of_week="mon", hour=7, minute=0, timezone="America/Toronto"),
        "description": "Governor in Council appointments published on Orders in Council weekly.",
        "typical_rows": 50,
    },
    {
        "id": "contracts_monthly",
        "name": "Federal Contracts (Proactive Disclosure)",
        "cadence": "monthly",
        "trigger": CronTrigger(day=3, hour=2, minute=0, timezone="America/Toronto"),
        "description": "open.canada.ca publishes the proactive disclosure CSV monthly. Full ingest; 15k-row cap during MVP.",
        "typical_rows": 15000,
    },
    {
        "id": "ocl_monthly",
        "name": "OCL Lobbying Communications",
        "cadence": "monthly",
        "trigger": CronTrigger(day=4, hour=3, minute=0, timezone="America/Toronto"),
        "description": "Office of the Commissioner of Lobbying publishes the monthly communications ZIP.",
        "typical_rows": 370000,
    },
    {
        "id": "ocl_registrations",
        "name": "OCL Lobbying Registrations",
        "cadence": "monthly",
        "trigger": CronTrigger(day=4, hour=4, minute=30, timezone="America/Toronto"),
        "description": "Office of the Commissioner of Lobbying registration filings: clients, subjects, funding and status.",
        "typical_rows": 25000,
    },
    {
        "id": "grants_quarterly",
        "name": "Grants & Contributions",
        "cadence": "quarterly",
        "trigger": CronTrigger(month="1,4,7,10", day=5, hour=2, minute=30, timezone="America/Toronto"),
        "description": "open.canada.ca publishes G&C data quarterly. 30k-row cap during MVP.",
        "typical_rows": 30000,
    },
    {
        "id": "donations_quarterly",
        "name": "Elections Canada Donations",
        "cadence": "quarterly",
        "trigger": CronTrigger(month="1,4,7,10", day=6, hour=3, minute=30, timezone="America/Toronto"),
        "description": "Elections Canada reviews and publishes contributions quarterly. 80k-row cap.",
        "typical_rows": 80000,
    },
    {
        "id": "tribunal_decisions",
        "name": "Tribunal Decisions",
        "cadence": "weekly",
        "trigger": CronTrigger(day_of_week="sat", hour=9, minute=0, timezone="America/Toronto"),
        "description": "Regulatory tribunal decisions; MVP connector currently loads CRTC decisions.",
        "typical_rows": 1000,
    },
]


# ── Job implementations ───────────────────────────────────────────────────────

async def _log_start(job_id: str, source_name: str, triggered_by: str = "scheduler") -> int:
    from api.database import AsyncSessionLocal
    from api.models.scheduler_log import SchedulerLog
    async with AsyncSessionLocal() as session:
        entry = SchedulerLog(job_id=job_id, source_name=source_name, triggered_by=triggered_by)
        session.add(entry)
        await session.commit()
        await session.refresh(entry)
        return entry.id


async def _log_finish(log_id: int, status: str, rows_added: int, rows_total: int,
                      duration_s: float, error: str | None = None) -> None:
    from sqlalchemy import select
    from api.database import AsyncSessionLocal
    from api.models.scheduler_log import SchedulerLog
    async with AsyncSessionLocal() as session:
        res = await session.execute(select(SchedulerLog).where(SchedulerLog.id == log_id))
        entry = res.scalar_one_or_none()
        if entry:
            entry.finished_at = datetime.now(timezone.utc)
            entry.status = status
            entry.rows_added = rows_added
            entry.rows_total = rows_total
            entry.duration_s = duration_s
            entry.error = error
            await session.commit()


async def _rebuild_search_index() -> None:
    """Rebuild the semantic vector index so search reflects freshly-ingested data.

    Called after any ingest that touches a text-bearing (embedded) source. Cheap
    at current corpus size; failures are logged but never fail the ingest itself.
    """
    try:
        from api.database import AsyncSessionLocal
        from search.index import build_index
        async with AsyncSessionLocal() as session:
            res = await build_index(session)
        log.info("auto_reindex_done", documents=res.get("documents"))
    except Exception as exc:
        log.error("auto_reindex_failed", error=str(exc))


class StreamLoadError(Exception):
    """Wraps a mid-stream failure with how many rows were already committed.

    A dropped connection near the tail of a multi-million-row stream does NOT
    lose committed batches (each batch is its own commit) — but the bare
    exception that used to propagate out of _stream_load gave callers no way
    to report that, so scheduler_log recorded rows_added=0 even when most of
    the corpus had actually landed. See CLAUDE.md: "A dropped stream at the
    tail != data lost."
    """

    def __init__(self, loaded: int, cause: BaseException) -> None:
        super().__init__(f"{type(cause).__name__}: {cause} (partial: {loaded} rows committed before failure)")
        self.loaded = loaded
        self.cause = cause


async def _stream_load(model, agen, *, delete_first: bool = True, batch_size: int = 5000) -> int:
    """Stream rows from an async iterator into the DB in batches.

    Keeps memory flat for full-corpus ingests (contracts ~1M rows, donations
    multi-million) — we never materialize the whole dataset. Returns row count.
    Raises StreamLoadError (not the bare original exception) on failure so
    callers can still log how much was actually committed.
    """
    from api.database import AsyncSessionLocal
    from sqlalchemy import delete as _delete

    loaded = 0
    async with AsyncSessionLocal() as session:
        if delete_first:
            await session.execute(_delete(model))
            await session.commit()
        batch: list = []
        try:
            async for row in agen:
                batch.append(model(**row))
                if len(batch) >= batch_size:
                    session.add_all(batch)
                    await session.commit()
                    loaded += len(batch)
                    batch = []
            if batch:
                session.add_all(batch)
                await session.commit()
                loaded += len(batch)
        except Exception as exc:
            raise StreamLoadError(loaded, exc) from exc
    return loaded


async def _run_bills(triggered_by: str = "scheduler") -> None:
    from sqlalchemy import delete
    from api.database import AsyncSessionLocal
    from api.models.donation import Bill
    from pipeline.ingest import fetch_bill_rows
    log_id = await _log_start("bills_daily", "Bills & Legislation (LEGISinfo)", triggered_by)
    t0 = time.monotonic()
    try:
        rows = await fetch_bill_rows()
        async with AsyncSessionLocal() as session:
            await session.execute(delete(Bill))
            session.add_all([Bill(**r) for r in rows])
            await session.commit()
        await _log_finish(log_id, "ok", len(rows), len(rows), time.monotonic() - t0)
        invalidate_workspace_caches("bills_daily")
        await _rebuild_search_index()  # bills are embedded
        log.info("scheduler_bills_done", count=len(rows))
    except Exception as exc:
        await _log_finish(log_id, "error", 0, 0, time.monotonic() - t0, f"{type(exc).__name__}: {exc}")
        log.error("scheduler_bills_failed", error=str(exc))


async def _run_gazette(triggered_by: str = "scheduler") -> None:
    from sqlalchemy import select
    from api.database import AsyncSessionLocal
    from api.models.regulation import GazetteEntry
    from pipeline.ingest import fetch_gazette_entries
    log_id = await _log_start("gazette_weekly", "Canada Gazette Part I + II", triggered_by)
    t0 = time.monotonic()
    try:
        rows = await fetch_gazette_entries()
        added = 0
        async with AsyncSessionLocal() as session:
            for r in rows:
                if r.get("guid"):
                    exists = (await session.execute(
                        select(GazetteEntry).where(GazetteEntry.guid == r["guid"]).limit(1)
                    )).scalar_one_or_none()
                    if exists:
                        continue
                session.add(GazetteEntry(**r))
                added += 1
            await session.commit()
        await _log_finish(log_id, "ok", added, len(rows), time.monotonic() - t0)
        invalidate_workspace_caches("gazette_weekly")
        await _rebuild_search_index()  # gazette + tribunal are embedded
        log.info("scheduler_gazette_done", added=added, total=len(rows))
    except Exception as exc:
        await _log_finish(log_id, "error", 0, 0, time.monotonic() - t0, f"{type(exc).__name__}: {exc}")
        log.error("scheduler_gazette_failed", error=str(exc))


async def _run_parliament_seed(triggered_by: str = "scheduler") -> None:
    from api.database import AsyncSessionLocal
    from api.models.politician import Politician
    from scrapers.hansard import OpenParliamentClient
    from sqlalchemy import select
    log_id = await _log_start("parliament_seed", "MP Profiles", triggered_by)
    t0 = time.monotonic()
    try:
        async with OpenParliamentClient() as client:
            politicians = await client.get_politicians()
        changed = 0
        async with AsyncSessionLocal() as session:
            for p in politicians:
                if not p.get("slug"):
                    continue
                row = (await session.execute(
                    select(Politician).where(Politician.slug == p["slug"])
                )).scalar_one_or_none()
                if row is None:
                    session.add(Politician(
                        slug=p["slug"],
                        name=p["name"],
                        party=p.get("party"),
                        riding=p.get("riding"),
                        province=p.get("province"),
                        url=p.get("url"),
                    ))
                    changed += 1
                else:
                    row.name = p["name"]
                    row.party = p.get("party")
                    row.riding = p.get("riding")
                    row.province = p.get("province")
                    row.url = p.get("url")
            await session.commit()
        await _log_finish(log_id, "ok", changed, len(politicians), time.monotonic() - t0)
        invalidate_workspace_caches("parliament_seed")
        log.info("scheduler_parliament_seed_done", changed=changed, total=len(politicians))
    except Exception as exc:
        await _log_finish(log_id, "error", 0, 0, time.monotonic() - t0, f"{type(exc).__name__}: {exc}")
        log.error("scheduler_parliament_seed_failed", error=str(exc))


async def _run_hansard_search(triggered_by: str = "scheduler") -> None:
    from api.database import AsyncSessionLocal
    from api.models.politician import HansardMention
    from pipeline.entity_resolver import normalize
    from pipeline.sector_mapper import SECTORS
    from scrapers.hansard import OpenParliamentClient
    from sqlalchemy import select

    log_id = await _log_start("hansard_search", "Hansard Sector Mentions", triggered_by)
    t0 = time.monotonic()
    try:
        keywords: list[str] = []
        for sector in SECTORS.values():
            keywords.extend(sector.keywords[:3])
        # Preserve order while avoiding duplicate broad terms.
        keywords = list(dict.fromkeys(k for k in keywords if len(k) >= 4))[:24]

        total = 0
        added = 0
        async with OpenParliamentClient() as client:
            async with AsyncSessionLocal() as session:
                for keyword in keywords:
                    speeches = await client.search_speeches(keyword, limit=8)
                    total += len(speeches)
                    canonical = normalize(keyword)
                    for speech in speeches:
                        exists = (await session.execute(
                            select(HansardMention).where(
                                HansardMention.keyword == keyword,
                                HansardMention.speech_url == speech.get("url"),
                                HansardMention.speaker == speech.get("speaker"),
                            ).limit(1)
                        )).scalar_one_or_none() if speech.get("url") else None
                        if exists:
                            continue
                        session.add(HansardMention(
                            canonical_name=canonical,
                            keyword=keyword,
                            speech_date=speech.get("date"),
                            speaker=speech.get("speaker"),
                            excerpt=speech.get("excerpt"),
                            speech_url=speech.get("url"),
                        ))
                        added += 1
                await session.commit()
        await _log_finish(log_id, "ok", added, total, time.monotonic() - t0)
        invalidate_workspace_caches("hansard_search")
        await _rebuild_search_index()
        log.info("scheduler_hansard_search_done", added=added, total=total)
    except Exception as exc:
        await _log_finish(log_id, "error", 0, 0, time.monotonic() - t0, f"{type(exc).__name__}: {exc}")
        log.error("scheduler_hansard_search_failed", error=str(exc))


async def _run_appointments(triggered_by: str = "scheduler") -> None:
    from sqlalchemy import delete
    from api.database import AsyncSessionLocal
    from api.models.appointment import Appointment
    from pipeline.ingest import fetch_appointment_rows
    log_id = await _log_start("appointments_weekly", "GIC Appointments", triggered_by)
    t0 = time.monotonic()
    try:
        rows = await fetch_appointment_rows(max_rows=10000)
        async with AsyncSessionLocal() as session:
            # Full replace, like bills/contracts/donations — GIC appointments has no
            # stable natural key (a person can hold multiple appointments; one OIC
            # can name multiple appointees), so a plain insert-without-delete would
            # duplicate every row on every recurrence.
            await session.execute(delete(Appointment))
            session.add_all([Appointment(**r) for r in rows])
            await session.commit()
        added = len(rows)
        await _log_finish(log_id, "ok", added, len(rows), time.monotonic() - t0)
        invalidate_workspace_caches("appointments_weekly")
        log.info("scheduler_appointments_done", count=added)
    except Exception as exc:
        await _log_finish(log_id, "error", 0, 0, time.monotonic() - t0, f"{type(exc).__name__}: {exc}")
        log.error("scheduler_appointments_failed", error=str(exc))


async def _run_contracts(triggered_by: str = "scheduler") -> None:
    from api.models.contract import Contract
    from pipeline.ingest import iter_contract_rows
    log_id = await _log_start("contracts_monthly", "Federal Contracts (Proactive Disclosure)", triggered_by)
    t0 = time.monotonic()
    try:
        # Full corpus, streamed (max_rows=0). Memory stays flat via _stream_load.
        n = await _stream_load(Contract, iter_contract_rows(max_rows=0))
        await _log_finish(log_id, "ok", n, n, time.monotonic() - t0)
        invalidate_workspace_caches("contracts_monthly")
        log.info("scheduler_contracts_done", count=n)
    except StreamLoadError as exc:
        await _log_finish(log_id, "error", exc.loaded, exc.loaded, time.monotonic() - t0, str(exc))
        log.error("scheduler_contracts_failed", error=str(exc.cause), rows_committed=exc.loaded)
    except Exception as exc:
        await _log_finish(log_id, "error", 0, 0, time.monotonic() - t0, f"{type(exc).__name__}: {exc}")
        log.error("scheduler_contracts_failed", error=str(exc))


async def _run_ocl(triggered_by: str = "scheduler") -> None:
    from sqlalchemy import delete
    from api.database import AsyncSessionLocal
    from api.models.entity import LobbyingRecord
    from pipeline.ingest import fetch_ocl_communication_rows
    log_id = await _log_start("ocl_monthly", "OCL Lobbying Communications", triggered_by)
    t0 = time.monotonic()
    try:
        # Delete cached ZIP so fresh data is pulled
        from pipeline.ingest import OCL_COMMS_CACHE
        if OCL_COMMS_CACHE.exists():
            OCL_COMMS_CACHE.unlink()

        rows = await fetch_ocl_communication_rows(max_rows=0)
        async with AsyncSessionLocal() as session:
            await session.execute(delete(LobbyingRecord).where(
                LobbyingRecord.source == "OCL Monthly Communications"
            ))
            await session.commit()
            batch = 2000
            for i in range(0, len(rows), batch):
                for r in rows[i:i+batch]:
                    session.add(LobbyingRecord(
                        company_query=r["client_org"],
                        canonical_name=r["canonical_name"],
                        registration_id=r["comlog_id"],
                        client=r["client_org"],
                        registrant=r["registrant"],
                        subject_matters=r.get("subject_codes", []),
                        institutions=r.get("institutions", []),
                        communication_date=r.get("comm_date"),
                        type=r.get("reg_type"),
                        source="OCL Monthly Communications",
                        raw={"dpoh_contacts": r.get("dpoh_contacts", [])},
                    ))
                await session.commit()
        await _log_finish(log_id, "ok", len(rows), len(rows), time.monotonic() - t0)
        invalidate_workspace_caches("ocl_monthly")
        log.info("scheduler_ocl_done", count=len(rows))
    except Exception as exc:
        await _log_finish(log_id, "error", 0, 0, time.monotonic() - t0, f"{type(exc).__name__}: {exc}")
        log.error("scheduler_ocl_failed", error=str(exc))


async def _run_grants(triggered_by: str = "scheduler") -> None:
    from api.models.grant import Grant
    from pipeline.ingest import iter_grant_rows
    log_id = await _log_start("grants_quarterly", "Grants & Contributions", triggered_by)
    t0 = time.monotonic()
    try:
        # Full corpus, streamed (max_rows=0). Memory stays flat via _stream_load —
        # fixed 2026-06-22, this used to materialize the whole ~2.25GB CSV into a
        # list first (see DATA_CHECKLIST.md "Goal 6"). Full replace, like
        # bills/contracts/donations: ref_number is nullable on a meaningful
        # fraction of source rows, so an existence-check upsert can't reliably
        # dedupe; a plain insert-without-delete would duplicate every row on
        # every recurrence.
        n = await _stream_load(Grant, iter_grant_rows(max_rows=0))
        await _log_finish(log_id, "ok", n, n, time.monotonic() - t0)
        invalidate_workspace_caches("grants_quarterly")
        log.info("scheduler_grants_done", count=n)
    except StreamLoadError as exc:
        await _log_finish(log_id, "error", exc.loaded, exc.loaded, time.monotonic() - t0, str(exc))
        log.error("scheduler_grants_failed", error=str(exc.cause), rows_committed=exc.loaded)
    except Exception as exc:
        await _log_finish(log_id, "error", 0, 0, time.monotonic() - t0, f"{type(exc).__name__}: {exc}")
        log.error("scheduler_grants_failed", error=str(exc))


async def _run_ocl_registrations(triggered_by: str = "scheduler") -> None:
    from sqlalchemy import select
    from api.database import AsyncSessionLocal
    from api.models.ocl_registration import OCLRegistration
    from pipeline.ingest import fetch_ocl_registration_rows
    log_id = await _log_start("ocl_registrations", "OCL Lobbying Registrations", triggered_by)
    t0 = time.monotonic()
    try:
        rows = await fetch_ocl_registration_rows(max_rows=0)
        added = 0
        async with AsyncSessionLocal() as session:
            batch = 2000
            for i in range(0, len(rows), batch):
                for r in rows[i:i+batch]:
                    exists = (await session.execute(
                        select(OCLRegistration).where(
                            OCLRegistration.registration_num == r["registration_num"]
                        ).limit(1)
                    )).scalar_one_or_none() if r.get("registration_num") else None
                    if exists:
                        continue
                    session.add(OCLRegistration(**r))
                    added += 1
                await session.commit()
        await _log_finish(log_id, "ok", added, len(rows), time.monotonic() - t0)
        invalidate_workspace_caches("ocl_registrations")
        log.info("scheduler_ocl_registrations_done", added=added, total=len(rows))
    except Exception as exc:
        await _log_finish(log_id, "error", 0, 0, time.monotonic() - t0, f"{type(exc).__name__}: {exc}")
        log.error("scheduler_ocl_registrations_failed", error=str(exc))


async def _run_tribunal_decisions(triggered_by: str = "scheduler") -> None:
    from sqlalchemy import select
    from api.database import AsyncSessionLocal
    from api.models.regulation import TribunalDecision
    from pipeline.ingest import fetch_crtc_decisions
    log_id = await _log_start("tribunal_decisions", "Tribunal Decisions", triggered_by)
    t0 = time.monotonic()
    try:
        rows = await fetch_crtc_decisions()
        added = 0
        async with AsyncSessionLocal() as session:
            for r in rows:
                exists = (await session.execute(
                    select(TribunalDecision).where(
                        TribunalDecision.decision_number == r["decision_number"],
                        TribunalDecision.body == r["body"],
                    ).limit(1)
                )).scalar_one_or_none() if r.get("decision_number") else None
                if exists:
                    continue
                session.add(TribunalDecision(**r))
                added += 1
            await session.commit()
        await _log_finish(log_id, "ok", added, len(rows), time.monotonic() - t0)
        invalidate_workspace_caches("tribunal_decisions")
        await _rebuild_search_index()
        log.info("scheduler_tribunal_decisions_done", added=added, total=len(rows))
    except Exception as exc:
        await _log_finish(log_id, "error", 0, 0, time.monotonic() - t0, f"{type(exc).__name__}: {exc}")
        log.error("scheduler_tribunal_decisions_failed", error=str(exc))


async def _run_donations(triggered_by: str = "scheduler") -> None:
    from api.models.donation import Donation
    from pipeline.ingest import iter_donation_rows
    log_id = await _log_start("donations_quarterly", "Elections Canada Donations", triggered_by)
    t0 = time.monotonic()
    try:
        # Full corpus, streamed (max_rows=0).
        n = await _stream_load(Donation, iter_donation_rows(max_rows=0))
        await _log_finish(log_id, "ok", n, n, time.monotonic() - t0)
        invalidate_workspace_caches("donations_quarterly")
        log.info("scheduler_donations_done", count=n)
    except StreamLoadError as exc:
        await _log_finish(log_id, "error", exc.loaded, exc.loaded, time.monotonic() - t0, str(exc))
        log.error("scheduler_donations_failed", error=str(exc.cause), rows_committed=exc.loaded)
    except Exception as exc:
        await _log_finish(log_id, "error", 0, 0, time.monotonic() - t0, f"{type(exc).__name__}: {exc}")
        log.error("scheduler_donations_failed", error=str(exc))


# Map job_id → async function
JOB_RUNNERS = {
    "bills_daily": _run_bills,
    "gazette_weekly": _run_gazette,
    "parliament_seed": _run_parliament_seed,
    "hansard_search": _run_hansard_search,
    "appointments_weekly": _run_appointments,
    "contracts_monthly": _run_contracts,
    "ocl_monthly": _run_ocl,
    "ocl_registrations": _run_ocl_registrations,
    "grants_quarterly": _run_grants,
    "donations_quarterly": _run_donations,
    "tribunal_decisions": _run_tribunal_decisions,
}


# ── Breadth sources (unified source_records table) ────────────────────────────
# Declared once in pipeline/connectors.py; adapted here into scheduler jobs +
# configs so they show up on the dashboard beside the core typed sources.
def _make_connector_runner(conn):
    async def _runner(triggered_by: str = "scheduler") -> None:
        from pipeline.connectors import run_connector
        try:
            await run_connector(conn, max_rows=0, triggered_by=triggered_by)
            invalidate_workspace_caches(conn.id)
            if conn.embed:  # refresh the semantic index for embedded sources
                await _rebuild_search_index()
        except Exception as exc:  # already logged to scheduler_log inside run_connector
            log.error("scheduler_connector_failed", id=conn.id, error=str(exc))
    return _runner


def _register_breadth_connectors() -> None:
    from pipeline.connectors import CONNECTORS
    for conn in CONNECTORS:
        SOURCE_CONFIGS.append({
            "id": conn.id, "name": conn.name, "cadence": conn.cadence,
            "trigger": conn.trigger, "description": conn.description,
            "typical_rows": conn.typical_rows,
        })
        JOB_RUNNERS[conn.id] = _make_connector_runner(conn)


_register_breadth_connectors()


# ── Scheduler lifecycle ───────────────────────────────────────────────────────

def start_scheduler() -> None:
    for cfg in SOURCE_CONFIGS:
        scheduler.add_job(
            JOB_RUNNERS[cfg["id"]],
            trigger=cfg["trigger"],
            id=cfg["id"],
            name=cfg["name"],
            replace_existing=True,
            misfire_grace_time=3600,  # run up to 1h late if the server was down
        )
    scheduler.start()
    log.info("scheduler_started", jobs=len(SOURCE_CONFIGS))


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        log.info("scheduler_stopped")
