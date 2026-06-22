"""Ingestion routes and source coverage for Nessus data sources."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from time import monotonic
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..cache import invalidate_workspace_caches
from ..database import get_session
from ..models.donation import Bill, Donation
from ..schemas import EvidenceReference, IngestCompletedResponse, SourceDetailResponse, SourceStatusResponse
from pipeline.evidence_graph import build_global_findings, sectors_for_text
from pipeline.ingest import fetch_bill_rows, fetch_donation_rows

router = APIRouter(prefix="/api", tags=["sources"])

_SOURCE_STATUS_CACHE_TTL_SECONDS = 300  # operator-freshness contract: short-lived (see test_product_contracts)
_SOURCE_STATUS_CACHE: dict[str, Any] = {"payload": None, "expires_at": 0.0}


def clear_sources_status_cache() -> None:
    """Clear cached source-health metadata after data refreshes."""
    _SOURCE_STATUS_CACHE["payload"] = None
    _SOURCE_STATUS_CACHE["expires_at"] = 0.0


class DonationIngest(BaseModel):
    max_rows: int = 50000


@router.post("/donations/ingest", response_model=IngestCompletedResponse)
async def ingest_donations(body: DonationIngest, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    rows = await fetch_donation_rows(max_rows=body.max_rows)
    await session.execute(delete(Donation))
    session.add_all([Donation(**r) for r in rows])
    await session.commit()
    invalidate_workspace_caches("manual_donations_ingest")
    total = sum(r["amount"] or 0 for r in rows)
    return {"ingested": len(rows), "total_value": round(total, 2),
            "source": "Elections Canada — Contributions (as reviewed)"}


@router.post("/bills/ingest", response_model=IngestCompletedResponse)
async def ingest_bills(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    rows = await fetch_bill_rows()
    await session.execute(delete(Bill))
    session.add_all([Bill(**r) for r in rows])
    await session.commit()
    invalidate_workspace_caches("manual_bills_ingest")
    return {"ingested": len(rows), "source": "LEGISinfo (current Parliament)"}


_RECORD_TABLE_ALIASES = {
    "lobbying_records": "lobbying",
    "gazette_entries": "gazette",
    "tribunal_decisions": "tribunal",
}


def _record_table(table: str | None) -> str | None:
    if not table:
        return None
    return _RECORD_TABLE_ALIASES.get(table, table)


def _record_title(row: Any, table: str) -> str:
    if table == "contracts":
        return f"{getattr(row, 'vendor_name', '') or 'Contract'} — {(getattr(row, 'description', '') or '')[:90]}"
    if table == "donations":
        return f"{getattr(row, 'contributor_name', '') or 'Contributor'} → {getattr(row, 'party', '') or getattr(row, 'recipient', '') or 'Recipient'}"
    if table == "grants":
        return f"{getattr(row, 'recipient_name', '') or 'Recipient'} — {(getattr(row, 'program_name', '') or '')[:90]}"
    if table == "lobbying_records":
        return f"{getattr(row, 'client', '') or 'Client'} lobbied (registrant {getattr(row, 'registrant', '') or 'unknown'})"
    if table == "ocl_registrations":
        return f"{getattr(row, 'client_org', '') or 'Client'} registration ({getattr(row, 'firm_name', '') or 'in-house'})"
    if table == "bills":
        return f"{getattr(row, 'bill_number', '') or 'Bill'} — {(getattr(row, 'title_en', '') or '')[:90]}"
    if table == "gazette_entries":
        return (getattr(row, 'title', '') or 'Canada Gazette record')[:120]
    if table == "politicians":
        return getattr(row, 'name', '') or 'Political figure'
    if table == "hansard_mentions":
        return f"{getattr(row, 'speaker', '') or 'House intervention'} — {getattr(row, 'keyword', '') or 'Hansard'}"
    if table == "appointments":
        return f"{getattr(row, 'appointee_name', '') or 'Appointee'} — {(getattr(row, 'position_title', '') or '')[:90]}"
    if table == "tribunal_decisions":
        return (getattr(row, 'title', '') or 'Tribunal decision')[:120]
    if table == "source_records":
        return (getattr(row, 'title', '') or 'Source record')[:120]
    return f"{table.replace('_', ' ').title()} #{getattr(row, 'id', '')}"


def _ref_from_row(row: Any, table: str, label: str) -> dict[str, Any]:
    date = None
    for attr in ("contract_date", "received_date", "agreement_start", "communication_date", "effective_date", "introduced_date", "published_date", "since_date", "speech_date", "appointment_date", "decision_date", "event_date"):
        if hasattr(row, attr):
            date = getattr(row, attr)
            if date:
                break
    url = None
    for attr in ("url", "speech_url"):
        if hasattr(row, attr):
            url = getattr(row, attr)
            if url:
                break
    record_table = _record_table(table) or table
    return EvidenceReference.model_validate({
        "table": record_table,
        "pk": row.id,
        "id": row.id,
        "source": label,
        "title": _record_title(row, table),
        "date": date,
        "url": url,
        "record_type": getattr(row, "record_type", None) or record_table,
    }).model_dump()


SOURCE_DEFS: list[dict[str, Any]] = [
    {
        "id": "contracts", "label": "Federal contracts", "table": "contracts",
        "job_id": "contracts_monthly", "status_when_rows": "live",
        "description": "Federal contracts over $10,000 from open.canada.ca.",
        "approx": True, "date_strategy": "skip", "fresh_days": 120,
    },
    {
        "id": "donations", "label": "Political donations", "table": "donations",
        "job_id": "donations_quarterly", "status_when_rows": "live",
        "description": "Elections Canada federal contribution records.",
        "approx": True, "date_strategy": "skip", "fresh_days": 180,
    },
    {
        "id": "lobbying_communications", "label": "Lobbying communications", "table": "lobbying_records",
        "job_id": "ocl_monthly", "status_when_rows": "live",
        "description": "OCL monthly communication returns with DPOH/institution contacts.",
        "date_strategy": "latest_id", "fresh_days": 75,
    },
    {
        "id": "bills", "label": "Bills & legislation", "table": "bills",
        "job_id": "bills_daily", "status_when_rows": "live",
        "description": "LEGISinfo current Parliament bills.",
        "fresh_days": 45,
    },
    {
        "id": "gazette_entries", "label": "Canada Gazette", "table": "gazette_entries",
        "job_id": "gazette_weekly", "status_when_rows": "partial",
        "description": "Canada Gazette Part I/II regulatory notices.",
        "fresh_days": 45,
    },
    {
        "id": "politicians", "label": "MP profiles", "table": "politicians",
        "job_id": "parliament_seed", "status_when_rows": "partial",
        "description": "OpenParliament MP profiles and local photo metadata.",
        "fresh_days": 365,
    },
    {
        "id": "hansard_mentions", "label": "Hansard mentions", "table": "hansard_mentions",
        "job_id": "hansard_search", "status_when_rows": "partial",
        "description": "Keyword-driven House speech mentions.",
        "fresh_days": 30,
    },
    {
        "id": "operations", "label": "Operations breadth", "table": "source_records",
        "job_id": None, "status_when_rows": "partial",
        "description": "CER, NPRI, GC News, StatCan/IAAC/Transport/geospatial catalogues.",
        "fresh_days": 120,
    },
    {
        "id": "grants", "label": "Grants & contributions", "table": "grants",
        "job_id": "grants_quarterly", "status_when_rows": "live",
        "description": "Federal grants and contributions recipients.",
        "fresh_days": 180,
    },
    {
        "id": "appointments", "label": "GIC appointments", "table": "appointments",
        "job_id": "appointments_weekly", "status_when_rows": "live",
        "description": "Governor in Council appointments to public bodies.",
        "fresh_days": 90,
    },
    {
        "id": "ocl_registrations", "label": "Lobbying registrations", "table": "ocl_registrations",
        "job_id": "ocl_registrations", "status_when_rows": "live",
        "description": "OCL registration filings, subject matter, funding and status.",
        "fresh_days": 75,
    },
    {
        "id": "tribunal_decisions", "label": "Tribunal decisions", "table": "tribunal_decisions",
        "job_id": "tribunal_decisions", "status_when_rows": "live",
        "description": "Regulatory decisions such as CRTC/Competition/CER proceedings.",
        "fresh_days": 120,
    },
    {
        "id": "social_statements", "label": "Public statements", "table": "source_records",
        "job_id": None, "status_when_rows": "partial",
        "source_values": ["social_statements", "public_statements"],
        "description": "Minister/MP/company press releases and public statements.",
        "fresh_days": 30,
        "known_gaps": ["No dedicated public-statement ingestion job is active yet."],
    },
    {
        "id": "gov_publications", "label": "Government publications & RSS", "table": "source_records",
        "job_id": None, "status_when_rows": "partial",
        "source_values": [
            "pmo_news", "boc_news", "nrcan_news", "eccc_news", "ised_news", "gac_news",
            "transport_news", "health_news", "competition_news", "crtc_news", "cer_news",
        ],
        "description": "PMO, Bank of Canada, NRCan, ECCC, ISED, GAC, Transport Canada, Health Canada, "
                        "Competition Bureau and CRTC news/publications via generic RSS/Atom connectors (Goal 9).",
        "fresh_days": 14,
        "known_gaps": [
            "IAAC, OSFI and the Canadian Nuclear Safety Commission publish no working RSS/Atom feed "
            "as of this writing (dead links / HTML-404-with-200 / email-only notifications) — no "
            "connector is wired for them rather than guessing a URL.",
            "Finance Canada has no separate departmental feed; its releases flow through the "
            "existing gc_news connector (filter entity_name = \"Department of Finance Canada\").",
            "Only a short (~320 char) publisher-supplied snippet is stored/displayed per item, not "
            "the full release text — Canada.ca's Terms and Conditions license reproduction for "
            "non-commercial use only; Nessus is commercial and holds no separate written permission.",
        ],
    },
]


def _source_values_for(cfg: dict[str, Any]) -> list[str] | None:
    values = cfg.get("source_values")
    if values:
        return list(values)
    if cfg.get("table") == "source_records" and cfg.get("id") != "operations":
        return [str(cfg["id"])]
    return None


def _source_value_condition(model: Any, source_values: list[str] | None):
    if not source_values or not hasattr(model, "source"):
        return None
    return getattr(model, "source").in_(source_values)


async def _table_count(session: AsyncSession, model, approximate: bool = False, source_values: list[str] | None = None) -> int:
    cond = _source_value_condition(model, source_values)
    if approximate:
        stmt = select(func.max(model.id))
        if cond is not None:
            stmt = stmt.where(cond)
        return (await session.execute(stmt)).scalar_one() or 0
    stmt = select(func.count(model.id))
    if cond is not None:
        stmt = stmt.where(cond)
    return (await session.execute(stmt)).scalar_one()


def _row_count_method(cfg: dict[str, Any], model: Any | None) -> str:
    if cfg["status_when_rows"] == "planned":
        return "planned"
    if model is None:
        return "unavailable"
    return "max_id" if cfg.get("approx") else "exact"


async def _latest_record_date(
    session: AsyncSession,
    model,
    date_col: str | None,
    strategy: str | None = None,
    source_values: list[str] | None = None,
) -> str | None:
    """Return a cheap latest-date hint without scanning dirty large text fields."""
    if not date_col or not hasattr(model, date_col):
        return None
    col = getattr(model, date_col)
    if strategy == "skip":
        return None
    cond = _source_value_condition(model, source_values)
    if strategy == "latest_id":
        stmt = select(col).where(col.isnot(None), col != "")
        if cond is not None:
            stmt = stmt.where(cond)
        row = (await session.execute(stmt.order_by(model.id.desc()).limit(1))).scalar_one_or_none()
        return row
    stmt = select(func.max(col))
    if cond is not None:
        stmt = stmt.where(cond)
    return (await session.execute(stmt)).scalar_one()


def _coverage_status(rows: int, status_when_rows: str) -> str:
    if status_when_rows == "planned":
        return "planned"
    return status_when_rows if rows > 0 else "empty"


def _parse_date(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(text[:len(fmt)], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _freshness_status(
    *,
    status: str,
    latest_record_date: str | None,
    last_success_at: str | None,
    fresh_days: int | None,
    now: datetime | None = None,
) -> str:
    if status == "planned":
        return "planned"
    if status == "empty":
        return "missing"
    threshold = fresh_days or 180
    anchor = _parse_date(latest_record_date) or _parse_date(last_success_at)
    if not anchor:
        return "unknown"
    current = now or datetime.now(timezone.utc)
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=timezone.utc)
    return "current" if (current - anchor).days <= threshold else "stale"


def _confidence(status: str, freshness: str) -> str:
    if status == "live" and freshness in {"current", "unknown"}:
        return "high"
    if status in {"live", "partial"} and freshness != "missing":
        return "medium"
    if status == "planned":
        return "planned"
    return "low"


def _known_gaps(cfg: dict[str, Any], status: str, freshness: str) -> list[str]:
    gaps: list[str] = []
    if status == "empty":
        gaps.append("No rows loaded yet.")
    if status == "planned":
        gaps.append("Source is planned but no table or ingestion job is active yet.")
    if status == "partial":
        gaps.append("Coverage is useful but not yet comprehensive.")
    if freshness == "stale":
        gaps.append("Latest known record or successful ingest is outside the expected freshness window.")
    if freshness == "unknown" and status in {"live", "partial"}:
        gaps.append("Freshness could not be determined from loaded rows or scheduler history.")
    if cfg["id"] in {"grants", "appointments", "ocl_registrations", "tribunal_decisions"} and status == "empty":
        gaps.append("Explicit MVP data gap; model/route exists but source ingestion still needs to be loaded.")
    gaps.extend(cfg.get("known_gaps", []))
    return gaps


def source_quality_summary(sources: list[dict[str, Any]]) -> dict[str, Any]:
    """Operator-facing rollup of source caveats that affect confidence."""
    approximate = [s["id"] for s in sources if s.get("approximate")]
    stale = [s["id"] for s in sources if s.get("freshness") == "stale"]
    unknown_freshness = [s["id"] for s in sources if s.get("freshness") == "unknown"]
    empty = [s["id"] for s in sources if s.get("status") == "empty"]
    planned = [s["id"] for s in sources if s.get("status") == "planned"]
    explicit_gaps = [
        {"id": s["id"], "label": s["label"], "gaps": s.get("known_gaps", [])}
        for s in sources
        if s.get("known_gaps")
    ]
    return {
        "approximate_sources": approximate,
        "stale_sources": stale,
        "unknown_freshness_sources": unknown_freshness,
        "empty_sources": empty,
        "planned_sources": planned,
        "explicit_gaps": explicit_gaps,
        "confidence": "low" if len(empty) >= 4 else "medium" if stale or unknown_freshness or approximate else "high",
    }


async def get_sources_status(session: AsyncSession, *, refresh: bool = False) -> dict[str, Any]:
    """Return cheap source coverage metadata for product and ops surfaces.

    Big append-only tables use max(id) as a fast row proxy; SQLite count(*) over
    multi-million-row tables is slow enough to hurt the workspace.
    """
    now = monotonic()
    cached = _SOURCE_STATUS_CACHE.get("payload")
    if not refresh and cached and now < float(_SOURCE_STATUS_CACHE.get("expires_at") or 0):
        payload = deepcopy(cached)
        payload["cache"] = {"status": "hit", "ttl_seconds": _SOURCE_STATUS_CACHE_TTL_SECONDS}
        return payload

    from ..models.appointment import Appointment
    from ..models.contract import Contract
    from ..models.entity import LobbyingRecord
    from ..models.grant import Grant
    from ..models.ocl_registration import OCLRegistration
    from ..models.politician import HansardMention, Politician
    from ..models.regulation import GazetteEntry, TribunalDecision
    from ..models.scheduler_log import SchedulerLog
    from ..models.source_record import SourceRecord

    models: dict[str, tuple[Any, str | None]] = {
        "appointments": (Appointment, "appointment_date"),
        "bills": (Bill, "introduced_date"),
        "contracts": (Contract, "contract_date"),
        "donations": (Donation, "received_date"),
        "gazette_entries": (GazetteEntry, "published_date"),
        "grants": (Grant, "agreement_start"),
        "hansard_mentions": (HansardMention, "speech_date"),
        "lobbying_records": (LobbyingRecord, "communication_date"),
        "ocl_registrations": (OCLRegistration, "effective_date"),
        "politicians": (Politician, "since_date"),
        "source_records": (SourceRecord, "event_date"),
        "tribunal_decisions": (TribunalDecision, "decision_date"),
    }

    # Per-source coverage is independent across sources, so compute each on its
    # own connection concurrently. The lobbying count(*) stays exact (product
    # contract) but no longer serializes behind every other source's scan.
    from ..database import AsyncSessionLocal

    async def _source_item(cfg: dict[str, Any]) -> dict[str, Any]:
        model_cfg = models.get(cfg.get("table"))
        model = model_cfg[0] if model_cfg else None
        date_col = model_cfg[1] if model_cfg else None
        async with AsyncSessionLocal() as s:
            rows = 0
            latest_record_date = None
            source_values = _source_values_for(cfg)
            if model is not None:
                rows = await _table_count(s, model, bool(cfg.get("approx")), source_values)
                if rows:
                    latest_record_date = await _latest_record_date(
                        s, model, date_col, cfg.get("date_strategy"), source_values
                    )

            last_run = None
            last_success_at = None
            job_id = cfg.get("job_id")
            if job_id:
                last = (
                    await s.execute(
                        select(SchedulerLog)
                        .where(SchedulerLog.job_id == job_id)
                        .order_by(SchedulerLog.started_at.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if last:
                    if last.status == "ok":
                        last_success_at = last.finished_at.isoformat() if last.finished_at else None
                    last_run = {
                        "status": last.status,
                        "started_at": last.started_at.isoformat() if last.started_at else None,
                        "finished_at": last.finished_at.isoformat() if last.finished_at else None,
                        "rows_added": last.rows_added,
                        "rows_total": last.rows_total,
                        "error": last.error,
                    }

        status = _coverage_status(rows, cfg["status_when_rows"])
        freshness = _freshness_status(
            status=status,
            latest_record_date=latest_record_date,
            last_success_at=last_success_at,
            fresh_days=cfg.get("fresh_days"),
        )
        return {
            "id": cfg["id"],
            "label": cfg["label"],
            "table": cfg.get("table"),
            "status": status,
            "freshness": freshness,
            "confidence": _confidence(status, freshness),
            "rows": rows,
            "approximate": bool(cfg.get("approx")),
            "row_count_method": _row_count_method(cfg, model),
            "source_values": cfg.get("source_values"),
            "latest_record_date": latest_record_date,
            "description": cfg["description"],
            "known_gaps": _known_gaps(cfg, status, freshness),
            "last_run": last_run,
        }

    items: list[dict[str, Any]] = list(await asyncio.gather(*(_source_item(cfg) for cfg in SOURCE_DEFS)))

    breadth_rows = (
        await session.execute(
            select(SourceRecord.source, func.count(SourceRecord.id), func.min(SourceRecord.event_date), func.max(SourceRecord.event_date))
            .group_by(SourceRecord.source)
            .order_by(func.count(SourceRecord.id).desc())
        )
    ).all()
    breadth = [
        {"source": s, "rows": n, "min_date": mn, "max_date": mx,
         "status": "live" if s in {"cer", "npri", "gc_news"} and n else "partial" if n else "empty"}
        for s, n, mn, mx in breadth_rows
    ]

    counts = {item["id"]: item["rows"] for item in items}
    payload = {
        "sources": items,
        "counts": counts,
        "breadth_sources": breadth,
        "summary": {
            "live": sum(1 for i in items if i["status"] == "live"),
            "partial": sum(1 for i in items if i["status"] == "partial"),
            "empty": sum(1 for i in items if i["status"] == "empty"),
            "planned": sum(1 for i in items if i["status"] == "planned"),
            "stale": sum(1 for i in items if i["freshness"] == "stale"),
            "unknown_freshness": sum(1 for i in items if i["freshness"] == "unknown"),
        },
        "quality": source_quality_summary(items),
    }
    _SOURCE_STATUS_CACHE["payload"] = deepcopy(payload)
    _SOURCE_STATUS_CACHE["expires_at"] = now + _SOURCE_STATUS_CACHE_TTL_SECONDS
    payload["cache"] = {"status": "refresh" if refresh else "miss", "ttl_seconds": _SOURCE_STATUS_CACHE_TTL_SECONDS}
    return payload



@router.get("/sources/status", response_model=SourceStatusResponse)
async def sources_status(
    refresh: bool = Query(default=False, description="Bypass short-lived source-status cache."),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await get_sources_status(session, refresh=refresh)



async def _source_records_for_detail(session: AsyncSession, source: dict[str, Any], limit: int = 12) -> list[dict[str, Any]]:
    table = source.get("table")
    if not table:
        return []
    from ..models.appointment import Appointment
    from ..models.contract import Contract
    from ..models.entity import LobbyingRecord
    from ..models.grant import Grant
    from ..models.ocl_registration import OCLRegistration
    from ..models.politician import HansardMention, Politician
    from ..models.regulation import GazetteEntry, TribunalDecision
    from ..models.source_record import SourceRecord

    models: dict[str, tuple[Any, str | None]] = {
        "appointments": (Appointment, "appointment_date"),
        "bills": (Bill, "introduced_date"),
        "contracts": (Contract, "contract_date"),
        "donations": (Donation, "received_date"),
        "gazette_entries": (GazetteEntry, "published_date"),
        "grants": (Grant, "agreement_start"),
        "hansard_mentions": (HansardMention, "speech_date"),
        "lobbying_records": (LobbyingRecord, "communication_date"),
        "ocl_registrations": (OCLRegistration, "effective_date"),
        "politicians": (Politician, "since_date"),
        "source_records": (SourceRecord, "event_date"),
        "tribunal_decisions": (TribunalDecision, "decision_date"),
    }
    model_cfg = models.get(table)
    if not model_cfg:
        return []
    model, date_col = model_cfg
    stmt = select(model)
    source_values = _source_values_for(source)
    if table == "source_records" and source_values:
        stmt = stmt.where(SourceRecord.source.in_(source_values))
    if date_col and hasattr(model, date_col):
        stmt = stmt.order_by(getattr(model, date_col).desc())
    else:
        stmt = stmt.order_by(model.id.desc())
    rows = (await session.execute(stmt.limit(limit))).scalars().all()
    return [_ref_from_row(row, table, source["label"]) for row in rows]


@router.get("/sources/{source_id}", response_model=SourceDetailResponse)
async def source_detail(source_id: str, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    status_payload = await get_sources_status(session)
    source = next((item for item in status_payload.get("sources", []) if item.get("id") == source_id), None)
    if not source:
        raise HTTPException(status_code=404, detail="Unsupported source")

    records = await _source_records_for_detail(session, source)
    evidence_text = " ".join([source.get("label", ""), source.get("description", ""), *(record.get("title", "") for record in records[:8])])
    affected_sectors = sectors_for_text(evidence_text, limit=4)
    record_tables = {source.get("table"), _record_table(source.get("table")), source.get("id")}
    related_findings = []
    for finding in await build_global_findings(session):
        refs = finding.get("references", []) or []
        if any(ref.get("table") in record_tables or ref.get("source") == source.get("label") for ref in refs):
            related_findings.append({**finding, "relationship_strength": "supported"})
        if len(related_findings) >= 5:
            break

    groups = []
    if records:
        groups.append({
            "table": _record_table(source.get("table")) or source.get("table") or source["id"],
            "label": "Recent internal records",
            "count": len(records),
            "records": records,
            "partial": source.get("row_count_method") == "max_id" or len(records) < int(source.get("rows") or 0),
        })

    row_count = int(source.get("rows") or 0)
    return {
        "id": source["id"],
        "label": source["label"],
        "type": "Source",
        "status": source["status"],
        "freshness": source["freshness"],
        "confidence": source["confidence"],
        "summary": f"{source['label']} is a {source['status']} Nessus source with {row_count:,} loaded row{'s' if row_count != 1 else ''}.",
        "why_it_matters": source.get("description") or "This source contributes evidence to Nessus investigations.",
        "important_data": {
            "rows": row_count,
            "table": source.get("table"),
            "row_count_method": source.get("row_count_method"),
            "latest_record_date": source.get("latest_record_date"),
            "approximate": source.get("approximate", False),
            "last_run": source.get("last_run"),
        },
        "affected_sectors": affected_sectors,
        "related_findings": related_findings,
        "connected_people": [],
        "connected_organizations": [],
        "connected_records": records,
        "groups": groups,
        "timeline": records[:10],
        "known_gaps": source.get("known_gaps", []),
        "original_source_url": None,
    }
