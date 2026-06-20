"""Sector-level intelligence — cross-source rollups, risk scoring, connections.

This is the engine behind the client-facing *Sector Intelligence* surface. Given a
curated :class:`~pipeline.sector_mapper.Sector`, it aggregates every source by the
sector's entity roster (big tables, via the indexed ``canonical_name``) and by
keyword (small tables), builds an evidence bundle in the exact shape
:func:`pipeline.risk_scorer.score` already consumes, and runs a deterministic
**connection detector** that surfaces the cross-source patterns that make the
product valuable ("lobbying concentrated on the same body advancing a bill").

No model call is required — the connections and narrative are deterministic, so the
surface stays useful without an ``ANTHROPIC_API_KEY``. When a key is present the
route layer can add narrative synthesis on top; this module is the evidence floor.
"""
from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import Float, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.appointment import Appointment
from api.models.contract import Contract
from api.models.donation import Bill, Donation
from api.models.entity import LobbyingRecord
from api.models.grant import Grant
from api.models.regulation import GazetteEntry, TribunalDecision
from api.models.report import Report
from api.models.source_record import SourceRecord
from pipeline.entity_resolver import normalize
from pipeline.risk_scorer import score as score_evidence
from pipeline.sector_mapper import PROVINCES, Sector, get_sector, sector_for_entity


def _kw_filter(columns: list, keywords: list[str]):
    """OR of ``col ILIKE %kw%`` across the given columns and keywords."""
    clauses = [col.ilike(f"%{kw}%") for kw in keywords for col in columns]
    return or_(*clauses) if clauses else None


def _ref(
    *,
    table: str,
    pk: int,
    source: str,
    title: str,
    date: str | None = None,
    url: str | None = None,
    entity: str | None = None,
) -> dict[str, Any]:
    """Normalized record reference used by workspace pages and report evidence."""
    return {
        "table": table,
        "id": pk,
        "pk": pk,
        "source": source,
        "title": title,
        "date": date,
        "url": url,
        "entity": entity,
    }


def _coverage(ev: dict[str, Any]) -> list[dict[str, Any]]:
    """Sector-hit coverage for evidence bundles already loaded for the page.

    ``rows`` is the count matching this sector lens. It is not global source
    health; API routes can enrich these rows with source-status metadata so the
    UI can distinguish "source is empty" from "source is live, no sector hits."
    """
    labels = [
        ("contracts", "Federal contracts", "live"),
        ("lobbying", "Lobbying communications", "live"),
        ("donations", "Political donations", "live"),
        ("bills", "Bills & legislation", "live"),
        ("regulations", "Canada Gazette", "partial"),
        ("tribunal_decisions", "Tribunal decisions", "empty"),
        ("appointments", "GIC appointments", "empty"),
        ("breadth", "Operations breadth", "partial"),
    ]
    out: list[dict[str, Any]] = []
    for key, label, status_when_rows in labels:
        rows = int((ev.get(key) or {}).get("count") or 0)
        status = status_when_rows if rows else "empty"
        out.append({"id": key, "label": label, "status": status, "rows": rows})
    return out


_COVERAGE_SOURCE_IDS = {
    "contracts": "contracts",
    "lobbying": "lobbying_communications",
    "donations": "donations",
    "bills": "bills",
    "regulations": "gazette_entries",
    "tribunal_decisions": "tribunal_decisions",
    "appointments": "appointments",
    "breadth": "operations",
}


def enrich_sector_coverage(
    coverage: list[dict[str, Any]],
    source_status: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Attach global source health to sector-local coverage rows.

    This prevents a common diligence error: treating zero sector matches as if
    the underlying source itself were unloaded. ``status`` remains the sector
    hit status for backward compatibility; ``global_status`` and
    ``sector_status`` make the distinction explicit for newer clients.
    """
    if not source_status:
        return coverage

    by_id = {row.get("id"): row for row in source_status.get("sources", [])}
    enriched: list[dict[str, Any]] = []
    for row in coverage:
        item = dict(row)
        item["sector_rows"] = int(item.get("rows") or 0)
        item["sector_status"] = item.get("status")
        source_id = _COVERAGE_SOURCE_IDS.get(str(item.get("id")))
        item["source_id"] = source_id
        global_row = by_id.get(source_id) if source_id else None
        if global_row:
            item["global_status"] = global_row.get("status")
            item["global_rows"] = int(global_row.get("rows") or 0)
            item["freshness"] = global_row.get("freshness")
            item["confidence"] = global_row.get("confidence")
            item["known_gaps"] = global_row.get("known_gaps") or []
            item["description"] = global_row.get("description") or item.get("description")
            item["table"] = global_row.get("table") or item.get("table")
            item["approximate"] = bool(global_row.get("approximate"))
            item["latest_record_date"] = global_row.get("latest_record_date")
            if item["sector_rows"] == 0 and global_row.get("status") in {"live", "partial"}:
                item["sector_status"] = "no_sector_hits"
        enriched.append(item)
    return enriched


def risk_band_from_score(score: float | int | None, *, evidence_count: int = 0) -> str:
    """Translate explainable score components into a reader-facing band."""
    if evidence_count <= 0:
        return "insufficient evidence"
    value = float(score or 0)
    if value >= 7:
        return "high"
    if value >= 4:
        return "elevated"
    if value >= 2:
        return "moderate"
    return "low"


def movement_windows(current: int | float | None = None) -> list[dict[str, Any]]:
    """Return honest delta windows until period snapshots exist."""
    return [
        {
            "window_days": days,
            "status": "insufficient_history",
            "direction": "unclear",
            "current": current,
            "previous": None,
            "delta": None,
            "note": "Historical period snapshots are not yet available for this sector lens.",
        }
        for days in (7, 30, 90)
    ]


def _coverage_strength(ref_count: int, source_count: int) -> str:
    if ref_count >= 3 and source_count >= 2:
        return "strong"
    if ref_count >= 1:
        return "partial"
    return "weak"


def _confidence_for_coverage(coverage: str) -> str:
    return {"strong": "high", "partial": "medium", "weak": "low"}.get(coverage, "medium")


def _source_type(table: str) -> str:
    return {
        "bills": "bill",
        "gazette": "regulatory event",
        "tribunal": "regulatory event",
        "lobbying": "lobbying activity",
        "contracts": "contract",
        "donations": "political contribution",
        "source_records": "source record",
        "hansard_mentions": "political statement",
    }.get(table, "record")


def evidence_item(ref: dict[str, Any], *, coverage: str = "partial", confidence: str | None = None) -> dict[str, Any]:
    pk = ref.get("pk", ref.get("id"))
    table = str(ref.get("table") or "")
    return {
        "source_name": ref.get("source") or table,
        "source_type": _source_type(table),
        "title": ref.get("title") or "Untitled record",
        "publication_date": ref.get("date"),
        "ingestion_date": ref.get("ingestion_date"),
        "coverage_status": coverage,
        "confidence": confidence or _confidence_for_coverage(coverage),
        "table": table,
        "pk": pk,
        "internal_url": f"/records/{table}/{pk}" if table and pk is not None else "",
        "external_url": ref.get("url"),
    }


def finding_from_signal(signal: dict[str, Any], sector: Sector | None = None) -> dict[str, Any]:
    refs = [r for r in signal.get("references", []) if r.get("table") and r.get("pk", r.get("id")) is not None]
    sources = {r.get("source") or r.get("table") for r in refs}
    coverage = _coverage_strength(len(refs), len(sources))
    severity = signal.get("severity") or signal.get("impact") or "watch"
    risk_level = {
        "High": "high",
        "Medium": "elevated",
        "Low": "moderate",
        "high": "high",
        "elevated": "elevated",
        "watch": "moderate",
    }.get(str(severity), "unknown")
    theme = str(signal.get("theme") or "").lower()
    signal_type = "portfolio monitoring"
    if "regulatory" in theme:
        signal_type = "regulatory watch"
    elif "lobby" in theme or "influence" in theme:
        signal_type = "lobbying intensity"
    elif "actor" in theme or "political" in theme:
        signal_type = "political attention"
    elif "opportunity" in theme:
        signal_type = "policy opportunity"
    return {
        "title": signal.get("title") or "Untitled finding",
        "concise_summary": signal.get("summary") or signal.get("detail") or "",
        "why_it_matters": signal.get("why") or "This signal may affect diligence, strategy, timing, or exposure decisions.",
        "primary_sector": {"slug": sector.slug, "name": sector.name} if sector else (signal.get("sectors") or [None])[0],
        "related_sectors": signal.get("sectors") or ([] if not sector else [{"slug": sector.slug, "name": sector.name}]),
        "signal_type": signal_type,
        "risk_direction": "unclear",
        "risk_level": risk_level,
        "confidence": _confidence_for_coverage(coverage),
        "source_coverage": coverage,
        "recency": "fresh" if refs else "aging",
        "interpretation_type": "observed" if len(sources) <= 1 else "inferred",
        "evidence_references": [evidence_item(r, coverage=coverage) for r in refs[:6]],
        "related_records": refs[:6],
        "related_bills": [r for r in refs if r.get("table") == "bills"],
        "related_lobbying_activity": [r for r in refs if r.get("table") == "lobbying"],
        "related_regulatory_events": [r for r in refs if r.get("table") in {"gazette", "tribunal"}],
        "suggested_questions": decision_questions(signal, sector),
    }


def decision_questions(signal: dict[str, Any] | None = None, sector: Sector | None = None) -> list[str]:
    questions = [
        "Are the available sources complete enough to support a conclusion?",
        "What additional evidence should the user review before acting?",
    ]
    text = f"{(signal or {}).get('theme', '')} {(signal or {}).get('title', '')}".lower()
    if "regulatory" in text or "gazette" in text or "bill" in text:
        questions.insert(0, "Could this change affect approvals, compliance costs, timelines, demand, competition, or market access?")
        questions.insert(1, "Is the organization exposed to a regulatory consultation, bill stage, or rule-making process currently underway?")
    if "lobby" in text or "influence" in text:
        questions.insert(0, "Has lobbying activity around this issue increased, concentrated, or shifted to a new institution?")
    if sector and sector.regulators:
        questions.append(f"Which of {', '.join(sector.regulators[:3])} should be reviewed for the next evidence point?")
    return questions[:5]


def sector_brief(payload: dict[str, Any]) -> dict[str, Any]:
    findings = payload.get("findings", [])
    return {
        "title": f"{payload['sector']['name']} intelligence brief",
        "risk_summary": payload.get("narrative") or "",
        "what_changed": "Period-over-period movement is not yet available; current findings are based on loaded evidence.",
        "top_findings": findings[:3],
        "confidence_and_limits": payload.get("source_coverage", [])[:6],
        "suggested_questions": payload.get("suggested_questions", [])[:6],
    }


async def _contracts(session: AsyncSession, ents: list[str]) -> dict[str, Any]:
    cf = Contract.canonical_name.in_(ents)
    total, count = (
        await session.execute(
            select(func.coalesce(func.sum(Contract.contract_value), 0.0), func.count(Contract.id)).where(cf)
        )
    ).one()
    by_dept = (
        await session.execute(
            select(Contract.owner_org_title, func.sum(Contract.contract_value), func.count(Contract.id))
            .where(cf).group_by(Contract.owner_org_title)
            .order_by(func.sum(Contract.contract_value).desc()).limit(8)
        )
    ).all()
    by_vendor = (
        await session.execute(
            select(Contract.canonical_name, func.sum(Contract.contract_value), func.count(Contract.id))
            .where(cf).group_by(Contract.canonical_name)
            .order_by(func.sum(Contract.contract_value).desc()).limit(10)
        )
    ).all()
    records = (
        await session.execute(
            select(Contract)
            .where(cf)
            .order_by(Contract.contract_value.desc().nullslast(), Contract.contract_date.desc())
            .limit(12)
        )
    ).scalars().all()
    return {
        "count": count,
        "total_value": round(total or 0, 2),
        "by_department": [{"dept": d[0], "value": round(d[1] or 0, 2), "count": d[2]} for d in by_dept],
        "by_entity": [{"entity": v[0], "value": round(v[1] or 0, 2), "count": v[2]} for v in by_vendor],
        "records": [
            {
                **_ref(
                    table="contracts", pk=r.id, source=r.source,
                    title=f"{r.vendor_name} — {(r.description or '')[:100]}".strip(" —"),
                    date=r.contract_date, entity=r.vendor_name,
                ),
                "department": r.owner_org_title,
                "value": r.contract_value or 0,
                "description": r.description,
            }
            for r in records
        ],
    }


async def _donations(session: AsyncSession, ents: list[str], province: str | None) -> dict[str, Any]:
    df = Donation.canonical_name.in_(ents)
    if province:
        df = df & (Donation.contributor_province == province)
    total, count = (
        await session.execute(
            select(func.coalesce(func.sum(Donation.amount), 0.0), func.count(Donation.id)).where(df)
        )
    ).one()
    by_party = (
        await session.execute(
            select(Donation.party, func.coalesce(func.sum(Donation.amount), 0.0), func.count(Donation.id))
            .where(df).group_by(Donation.party)
            .order_by(func.sum(Donation.amount).desc()).limit(6)
        )
    ).all()
    records = (
        await session.execute(
            select(Donation)
            .where(df)
            .order_by(Donation.amount.desc().nullslast(), Donation.received_date.desc())
            .limit(10)
        )
    ).scalars().all()
    return {
        "count": count,
        "total_value": round(total or 0, 2),
        "by_party": [{"party": p[0] or "—", "value": round(p[1] or 0, 2), "count": p[2]} for p in by_party],
        "records": [
            {
                **_ref(
                    table="donations", pk=r.id, source=r.source,
                    title=f"{r.contributor_name} -> {r.party or r.recipient or 'recipient'}",
                    date=r.received_date, entity=r.contributor_name,
                ),
                "party": r.party,
                "amount": r.amount or 0,
                "province": r.contributor_province,
            }
            for r in records
        ],
    }


async def _lobbying(session: AsyncSession, ents: list[str]) -> dict[str, Any]:
    lf = LobbyingRecord.canonical_name.in_(ents)
    count = (await session.execute(select(func.count(LobbyingRecord.id)).where(lf))).scalar_one()
    by_entity = (
        await session.execute(
            select(LobbyingRecord.canonical_name, func.count(LobbyingRecord.id))
            .where(lf).group_by(LobbyingRecord.canonical_name)
            .order_by(func.count(LobbyingRecord.id).desc()).limit(10)
        )
    ).all()
    # Sample the most recent comms to tally which institutions are being lobbied.
    rows = (
        await session.execute(
            select(LobbyingRecord.institutions)
            .where(lf).order_by(LobbyingRecord.communication_date.desc()).limit(600)
        )
    ).scalars().all()
    inst_tally: dict[str, int] = {}
    for insts in rows:
        for i in (insts or []):
            if i:
                inst_tally[i] = inst_tally.get(i, 0) + 1
    top_insts = sorted(inst_tally.items(), key=lambda kv: -kv[1])[:10]
    recs = (
        await session.execute(
            select(LobbyingRecord)
            .where(lf)
            .order_by(LobbyingRecord.communication_date.desc())
            .limit(12)
        )
    ).scalars().all()
    return {
        "count": count,
        "institutions": [i for i, _ in top_insts],
        "top_institutions": [{"institution": i, "count": n} for i, n in top_insts],
        "by_entity": [{"entity": e[0], "count": e[1]} for e in by_entity],
        "records": [
            {
                **_ref(
                    table="lobbying", pk=r.id, source=r.source,
                    title=f"{r.client} lobbying communication",
                    date=r.communication_date, entity=r.client,
                ),
                "registrant": r.registrant,
                "institutions": r.institutions or [],
                "subjects": r.subject_matters or [],
            }
            for r in recs
        ],
    }


async def _bills(session: AsyncSession, keywords: list[str]) -> dict[str, Any]:
    f = _kw_filter([Bill.title_en], keywords)
    q = select(Bill).order_by(Bill.introduced_date.desc()).limit(12)
    if f is not None:
        q = q.where(f)
    rows = (await session.execute(q)).scalars().all()
    return {
        "count": len(rows),
        "records": [
            {
                **_ref(
                    table="bills", pk=b.id, source="LEGISinfo",
                    title=f"{b.bill_number} — {b.title_en or ''}".strip(" —"),
                    date=b.introduced_date,
                ),
                "bill_number": b.bill_number,
                "title_en": b.title_en,
                "status": b.status,
                "sponsor": b.sponsor,
                "latest_activity": b.latest_activity,
            }
            for b in rows
        ],
    }


async def _regulations(session: AsyncSession, keywords: list[str]) -> dict[str, Any]:
    f = _kw_filter([GazetteEntry.title, GazetteEntry.description, GazetteEntry.department], keywords)
    q = select(GazetteEntry).order_by(GazetteEntry.published_date.desc()).limit(12)
    if f is not None:
        q = q.where(f)
    rows = (await session.execute(q)).scalars().all()
    return {
        "count": len(rows),
        "records": [
            {
                **_ref(
                    table="gazette", pk=r.id, source="Canada Gazette",
                    title=r.title, date=r.published_date, url=r.url,
                    entity=r.department,
                ),
                "gazette_part": r.gazette_part,
                "published_date": r.published_date,
                "department": r.department,
            }
            for r in rows
        ],
    }


async def _tribunal(session: AsyncSession, keywords: list[str], regulators: list[str]) -> dict[str, Any]:
    f = _kw_filter([TribunalDecision.title, TribunalDecision.summary, TribunalDecision.body], keywords + regulators)
    q = select(TribunalDecision).order_by(TribunalDecision.decision_date.desc()).limit(10)
    if f is not None:
        q = q.where(f)
    rows = (await session.execute(q)).scalars().all()
    return {
        "count": len(rows),
        "records": [
            {
                **_ref(
                    table="tribunal", pk=r.id, source=r.body or "Tribunal",
                    title=r.title, date=r.decision_date, url=r.url,
                    entity=r.parties,
                ),
                "body": r.body,
                "decision_number": r.decision_number,
                "decision_date": r.decision_date,
                "outcome": r.outcome,
            }
            for r in rows
        ],
    }


async def _appointments(session: AsyncSession, regulators: list[str]) -> dict[str, Any]:
    f = _kw_filter([Appointment.organization], regulators)
    q = select(Appointment).order_by(Appointment.appointment_date.desc()).limit(12)
    if f is not None:
        q = q.where(f)
    rows = (await session.execute(q)).scalars().all()
    return {
        "count": len(rows),
        "records": [
            {
                **_ref(
                    table="appointments", pk=r.id, source=r.source,
                    title=f"{r.appointee_name} — {r.position_title or ''}".strip(" —"),
                    date=r.appointment_date, entity=r.appointee_name,
                ),
                "appointee_name": r.appointee_name,
                "position_title": r.position_title,
                "organization": r.organization,
                "appointment_date": r.appointment_date,
            }
            for r in rows
        ],
    }


async def _breadth(session: AsyncSession, ents: list[str], keywords: list[str], province: str | None) -> dict[str, Any]:
    """Breadth signals (CER incidents, NPRI releases, IAAC, news) from source_records."""
    match = or_(SourceRecord.canonical_name.in_(ents), _kw_filter([SourceRecord.title, SourceRecord.summary], keywords))
    f = match
    if province:
        f = match & (SourceRecord.province == province)
    rows = (
        await session.execute(
            select(SourceRecord).where(f).order_by(SourceRecord.event_date.desc()).limit(15)
        )
    ).scalars().all()
    count = (await session.execute(select(func.count(SourceRecord.id)).where(f))).scalar_one()
    return {
        "count": count,
        "records": [
            {
                **_ref(
                    table="source_records", pk=r.id, source=r.source,
                    title=r.title, date=r.event_date, url=r.url,
                    entity=r.entity_name or r.canonical_name,
                ),
                "summary": (r.summary or "")[:240],
                "event_date": r.event_date,
                "province": r.province,
            }
            for r in rows
        ],
    }


async def _province_breakdown(session: AsyncSession, ents: list[str], keywords: list[str]) -> list[dict[str, Any]]:
    """Where the sector's footprint concentrates — across province-bearing sources."""
    tally: dict[str, dict[str, float]] = {code: {"records": 0, "amount": 0.0} for code in PROVINCES}

    don = (
        await session.execute(
            select(Donation.contributor_province, func.count(Donation.id), func.coalesce(func.sum(Donation.amount), 0.0))
            .where(Donation.canonical_name.in_(ents)).group_by(Donation.contributor_province)
        )
    ).all()
    sr_match = or_(SourceRecord.canonical_name.in_(ents), _kw_filter([SourceRecord.title, SourceRecord.summary], keywords))
    sr = (
        await session.execute(
            select(SourceRecord.province, func.count(SourceRecord.id),
                   func.coalesce(func.sum(func.cast(SourceRecord.amount, Float)), 0.0))
            .where(sr_match).group_by(SourceRecord.province)
        )
    ).all()
    gr = (
        await session.execute(
            select(Grant.recipient_province, func.count(Grant.id), func.coalesce(func.sum(Grant.agreement_value), 0.0))
            .where(Grant.canonical_name.in_(ents)).group_by(Grant.recipient_province)
        )
    ).all()

    for rows in (don, sr, gr):
        for prov, n, amt in rows:
            code = (prov or "").strip().upper()[:2]
            if code in tally:
                tally[code]["records"] += n
                tally[code]["amount"] += float(amt or 0)

    out = [
        {"code": c, "province": PROVINCES[c], "records": int(v["records"]), "amount": round(v["amount"], 2)}
        for c, v in tally.items() if v["records"] > 0
    ]
    out.sort(key=lambda r: -r["records"])
    return out


_YEAR_MIN, _YEAR_MAX = "2008", "2026"


async def _yearly(session: AsyncSession, model, date_col, where, value_col=None) -> list[dict[str, Any]]:
    """Year-bucketed series from an ISO (YYYY-MM-DD) date column."""
    yr = func.substr(date_col, 1, 4)
    cols = [yr, func.count(model.id)]
    if value_col is not None:
        cols.append(func.coalesce(func.sum(value_col), 0.0))
    q = (
        select(*cols)
        .where(where, date_col.isnot(None), yr >= _YEAR_MIN, yr <= _YEAR_MAX)
        .group_by(yr).order_by(yr)
    )
    rows = (await session.execute(q)).all()
    out: list[dict[str, Any]] = []
    for r in rows:
        item: dict[str, Any] = {"year": r[0], "count": r[1]}
        if value_col is not None:
            item["value"] = round(r[2] or 0, 2)
        out.append(item)
    return out


async def _trends(session: AsyncSession, ents: list[str], province: str | None = None) -> dict[str, Any]:
    """Yearly time-series for the terminal charts — contracts $, lobbying cadence, donations."""
    contracts = await _yearly(session, Contract, Contract.contract_date,
                              Contract.canonical_name.in_(ents), Contract.contract_value)
    lobbying = await _yearly(session, LobbyingRecord, LobbyingRecord.communication_date,
                             LobbyingRecord.canonical_name.in_(ents))
    df = Donation.canonical_name.in_(ents)
    if province:
        df = df & (Donation.contributor_province == province)
    donations = await _yearly(session, Donation, Donation.received_date, df, Donation.amount)
    return {"contracts": contracts, "lobbying": lobbying, "donations": donations}


def detect_connections(ev: dict[str, Any]) -> list[dict[str, Any]]:
    """Deterministic cross-source pattern detection — the 'so what' layer.

    Each connection cites the sources that produced it so an analyst can verify.
    Severity ('high'/'elevated'/'watch') drives the red/brass/slate UI treatment.
    """
    out: list[dict[str, Any]] = []
    lob = ev["lobbying"]
    con = ev["contracts"]
    bills = ev["bills"]
    regs = ev["regulations"]
    breadth = ev["breadth"]

    # 1. Lobbying targeted at a body while a bill on the sector's subject advances.
    if lob["count"] >= 25 and bills["count"] > 0:
        top_inst = lob["top_institutions"][0]["institution"] if lob["top_institutions"] else "federal institutions"
        bill_nums = ", ".join(b["bill_number"] for b in bills["records"][:3])
        out.append({
            "title": "Active lobbying alongside live legislation",
            "detail": f"{lob['count']:,} lobbying communications — concentrated on {top_inst} — "
                      f"coincide with {bills['count']} bill(s) touching the sector ({bill_nums}). "
                      "Engagement is tracking the legislative agenda.",
            "sources": ["lobbying", "bills"], "severity": "high",
            "references": bills["records"][:3],
        })

    # 2. Same department both contracting with the sector and being lobbied.
    contract_depts = {d["dept"] for d in con["by_department"] if d["dept"]}
    lobbied = {i["institution"] for i in lob["top_institutions"]}
    overlap = sorted(
        d for d in contract_depts
        for inst in lobbied
        if d and inst and (d.split()[0].lower() in inst.lower() or inst.split()[0].lower() in d.lower())
    )
    if overlap:
        dept = overlap[0]
        out.append({
            "title": "Procurement and lobbying point at the same department",
            "detail": f"{dept} is among both the sector's largest contracting departments and the "
                      "institutions it lobbies most — a procurement-plus-access pattern worth diligence.",
            "sources": ["contracts", "lobbying"], "severity": "elevated",
            "references": con.get("records", [])[:2] + lob.get("records", [])[:2],
        })

    # 3. Regulatory activity in motion (gazette / tribunal) against a lobbying-heavy sector.
    if regs["count"] > 0 and lob["count"] >= 25:
        out.append({
            "title": "Regulatory change against an engaged sector",
            "detail": f"{regs['count']} recent Canada Gazette item(s) intersect the sector while lobbying runs hot — "
                      "rule-making and industry engagement are moving together.",
            "sources": ["regulations", "lobbying"], "severity": "elevated",
            "references": regs["records"][:3],
        })

    # 4. On-the-ground breadth events (CER incidents, NPRI releases, assessments).
    if breadth["count"] > 0:
        sample = breadth["records"][0]
        out.append({
            "title": "Operational/environmental events on file",
            "detail": f"{breadth['count']:,} breadth record(s) (e.g. {sample['source']}: "
                      f"{sample['title'][:90]}) tie physical operations to the sector's risk picture.",
            "sources": ["source_records"], "severity": "watch",
            "references": breadth["records"][:3],
        })

    # 5. Contract concentration in a single player.
    if con["by_entity"] and con["total_value"] > 0:
        top = con["by_entity"][0]
        share = top["value"] / con["total_value"] if con["total_value"] else 0
        if share >= 0.5 and top["value"] > 0:
            out.append({
                "title": "Federal spend concentrated in one player",
                "detail": f"{top['entity']} accounts for {share:.0%} of the sector's "
                          f"${con['total_value']:,.0f} in federal contracts — concentration risk for a deal thesis.",
                "sources": ["contracts"], "severity": "watch",
                "references": con.get("records", [])[:3],
            })

    return out


def build_sector_signals(ev: dict[str, Any], connections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ranked sector-level signals with internal evidence references.

    Connections explain cross-source patterns. Signals are the workspace-facing
    layer that groups related data points by diligence question.
    """
    signals: list[dict[str, Any]] = []
    con = ev["contracts"]
    lob = ev["lobbying"]
    bills = ev["bills"]
    regs = ev["regulations"]
    tribunal = ev.get("tribunal_decisions", {"count": 0, "records": []})
    donations = ev["donations"]
    breadth = ev["breadth"]

    if connections:
        c = connections[0]
        signals.append({
            "theme": "Cross-source pattern",
            "title": c["title"],
            "summary": c["detail"],
            "severity": c["severity"],
            "why": "Multiple source families are pointing at the same sector exposure.",
            "metrics": [
                {"label": "Lobbying", "value": lob["count"]},
                {"label": "Bills", "value": bills["count"]},
                {"label": "Gazette", "value": regs["count"]},
            ],
            "sources": c["sources"],
            "references": c.get("references", [])[:4],
        })

    if regs["count"] or tribunal["count"] or bills["count"]:
        refs = (regs["records"][:2] + tribunal.get("records", [])[:2] + bills["records"][:2])[:5]
        signals.append({
            "theme": "Regulatory movement",
            "title": "Rules, legislation, or adjudication touching the sector",
            "summary": (
                f"{regs['count']} Gazette item(s), {bills['count']} bill(s), and "
                f"{tribunal.get('count', 0)} tribunal decision(s) are currently attached to this sector lens."
            ),
            "severity": "elevated" if regs["count"] or tribunal.get("count", 0) else "watch",
            "why": "Regulatory movement can alter timing, compliance costs, approvals, or market access.",
            "metrics": [
                {"label": "Gazette", "value": regs["count"]},
                {"label": "Bills", "value": bills["count"]},
                {"label": "Tribunal", "value": tribunal.get("count", 0)},
            ],
            "sources": ["regulations", "bills", "tribunal_decisions"],
            "references": refs,
        })

    if lob["count"]:
        top = lob["top_institutions"][0]["institution"] if lob["top_institutions"] else "federal institutions"
        signals.append({
            "theme": "Influence activity",
            "title": "Lobbying concentrates around federal decision points",
            "summary": f"{lob['count']:,} communications are on file; the most visible target is {top}.",
            "severity": "elevated" if lob["count"] >= 25 else "watch",
            "why": "Sustained lobbying can reveal pressure points before they appear in formal rule-making.",
            "metrics": [
                {"label": "Comms", "value": lob["count"]},
                {"label": "Institutions", "value": len(lob["top_institutions"])},
            ],
            "sources": ["lobbying"],
            "references": lob.get("records", [])[:4],
        })

    if con["count"] or con["total_value"]:
        top_dept = con["by_department"][0]["dept"] if con["by_department"] else "federal departments"
        signals.append({
            "theme": "Public-sector exposure",
            "title": "Federal contracts create buyer and department dependencies",
            "summary": (
                f"{con['count']:,} contract record(s) total ${con['total_value']:,.0f}; "
                f"top exposure sits with {top_dept}."
            ),
            "severity": "watch",
            "why": "Procurement concentration matters for revenue quality, renewal risk, and diligence questions.",
            "metrics": [
                {"label": "Contracts", "value": con["count"]},
                {"label": "Spend", "value": con["total_value"], "format": "money"},
                {"label": "Departments", "value": len(con["by_department"])},
            ],
            "sources": ["contracts"],
            "references": con.get("records", [])[:4],
        })

    if breadth["count"]:
        signals.append({
            "theme": "Operational footprint",
            "title": "Operational and environmental records extend the risk picture",
            "summary": f"{breadth['count']:,} breadth record(s) connect sector activity to places, assets, or incidents.",
            "severity": "watch",
            "why": "Physical footprint data helps separate abstract policy risk from concrete operating exposure.",
            "metrics": [
                {"label": "Records", "value": breadth["count"]},
            ],
            "sources": ["source_records"],
            "references": breadth["records"][:5],
        })

    if donations["count"]:
        signals.append({
            "theme": "Political finance",
            "title": "Contribution records appear in the sector graph",
            "summary": f"{donations['count']:,} contribution record(s) total ${donations['total_value']:,.0f}.",
            "severity": "watch",
            "why": "Federal corporate donations are banned; records usually indicate individuals linked by name.",
            "metrics": [
                {"label": "Records", "value": donations["count"]},
                {"label": "Amount", "value": donations["total_value"], "format": "money"},
            ],
            "sources": ["donations"],
            "references": donations.get("records", [])[:4],
        })

    order = {"high": 0, "elevated": 1, "watch": 2}
    signals.sort(key=lambda s: (order.get(s["severity"], 3), -sum(float(m["value"] or 0) for m in s["metrics"][:2])))
    return signals[:6]


def detect_entity_connections(ev: dict[str, Any]) -> list[dict[str, Any]]:
    """Deterministic cross-source patterns for a single company.

    Works on the bundle shape from ``pipeline.gather.gather_company_data`` (which
    has no ``breadth`` key), unlike :func:`detect_connections` for sectors.
    """
    out: list[dict[str, Any]] = []
    lob = ev["lobbying"]
    con = ev["contracts"]
    don = ev["donations"]
    bills = ev["bills"]
    regs = ev["regulations"]

    if lob["count"] >= 5 and bills["count"] > 0:
        bill_nums = ", ".join(b["bill_number"] for b in bills["records"][:3])
        out.append({
            "title": "Lobbying alongside live legislation",
            "detail": f"{lob['count']:,} lobbying communications coincide with {bills['count']} "
                      f"bill(s) touching this entity or its sector ({bill_nums}).",
            "sources": ["lobbying", "bills"], "severity": "elevated",
            "references": bills["records"][:3],
        })

    contract_depts = {d["dept"] for d in con.get("by_department", []) if d["dept"]}
    lobbied = set(lob.get("institutions", []))
    overlap = sorted(
        d for d in contract_depts for inst in lobbied
        if d and inst and (d.split()[0].lower() in inst.lower() or inst.split()[0].lower() in d.lower())
    )
    if overlap:
        out.append({
            "title": "Procurement and lobbying point at the same department",
            "detail": f"{overlap[0]} both contracts with this entity and is among the institutions it "
                      "lobbies — a procurement-plus-access pattern worth diligence.",
            "sources": ["contracts", "lobbying"], "severity": "high",
            "references": [],
        })

    if don["count"] > 0 and lob["count"] >= 5:
        out.append({
            "title": "Contributions alongside active lobbying",
            "detail": f"{don['count']} political contribution record(s) sit alongside sustained "
                      "lobbying — relationship-building across both channels.",
            "sources": ["donations", "lobbying"], "severity": "watch",
            "references": [],
        })

    if (regs["count"] + ev.get("tribunal_decisions", {}).get("count", 0)) > 0:
        out.append({
            "title": "Direct regulatory exposure on file",
            "detail": f"{regs['count']} Gazette item(s) and "
                      f"{ev.get('tribunal_decisions', {}).get('count', 0)} tribunal decision(s) intersect this entity.",
            "sources": ["regulations"], "severity": "watch",
            "references": regs["records"][:3] + ev.get("tribunal_decisions", {}).get("records", [])[:2],
        })

    return out


def entity_narrative(ev: dict[str, Any], scores: dict[str, Any], connections: list[dict[str, Any]]) -> str:
    band = "elevated" if scores["overall"] >= 7 else "moderate" if scores["overall"] >= 4 else "contained"
    article = "an" if band[0] in "aeiou" else "a"
    lead = (
        f"{ev['company'].title()} presents {article} {band} federal-political risk profile "
        f"({scores['overall']}/10), drawing on {ev['lobbying']['count']:,} lobbying communications, "
        f"{ev['contracts']['count']:,} federal contracts (${ev['contracts']['total_value']:,.0f}) "
        f"and {ev['donations']['count']} contribution record(s)."
    )
    if connections:
        lead += " " + " ".join(c["title"] + "." for c in connections[:2])
    return lead


async def _entity_reports(session: AsyncSession, canonical: str, limit: int = 6) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(Report)
            .where(Report.canonical_name == canonical)
            .order_by(Report.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [
        {
            "id": report.id,
            "company_name": report.company_name,
            "report_type": report.report_type,
            "status": report.status,
            "generated_by": report.generated_by,
            "overall": (report.risk_scores or {}).get("overall"),
            "created_at": report.created_at.isoformat(),
            "approved_at": report.approved_at.isoformat() if report.approved_at else None,
        }
        for report in rows
    ]


def _narrative(sector: Sector, scores: dict[str, Any], connections: list[dict[str, Any]], region: str | None) -> str:
    band = "elevated" if scores["overall"] >= 7 else "moderate" if scores["overall"] >= 4 else "contained"
    article = "an" if band[0] in "aeiou" else "a"
    where = f" in {PROVINCES.get(region, region)}" if region else ""
    lead = (
        f"{sector.name}{where} carries {article} {band} federal-political risk profile "
        f"({scores['overall']}/10). Regulatory risk scores {scores['regulatory_risk']}/10 and "
        f"policy volatility {scores['policy_volatility']}/10."
    )
    if connections:
        lead += " Key connections: " + " ".join(c["title"] + "." for c in connections[:3])
    return lead


async def gather_entity_data(
    session: AsyncSession, name: str, sector_slug: str | None = None
) -> dict[str, Any]:
    """Fast, read-only cross-source profile for one company.

    Matches the big tables by the indexed ``canonical_name`` (no ``ILIKE``
    full-scans, so it returns in ~1–2s rather than ~27s). Bills/regulations use the
    entity's sector keywords when its sector can be resolved, so the profile is
    enriched even when no sector is passed explicitly.
    """
    canonical = normalize(name)
    sector = get_sector(sector_slug) if sector_slug else sector_for_entity(canonical)
    kw = ([name] + sector.keywords) if sector else [name]
    ents = [canonical]

    contracts = await _contracts(session, ents)
    donations = await _donations(session, ents, None)
    lobbying = await _lobbying(session, ents)
    bills = await _bills(session, kw)
    regulations = await _regulations(session, kw)
    tribunal = await _tribunal(session, kw, sector.regulators if sector else [])
    breadth = await _breadth(session, ents, kw, None)

    evidence = {
        "company": name,
        "canonical": canonical,
        "sector": sector.name if sector else None,
        "lobbying": lobbying,
        "contracts": contracts,
        "donations": donations,
        "bills": bills,
        "regulations": regulations,
        "tribunal_decisions": tribunal,
        "breadth": breadth,
    }
    scores = score_evidence(evidence)
    connections = detect_entity_connections(evidence)
    return {
        "company": name,
        "canonical": canonical,
        "sector": sector.to_dict() if sector else None,
        "scores": scores,
        "connections": connections,
        "narrative": entity_narrative(evidence, scores, connections),
        "trends": await _trends(session, ents),
        "source_coverage": _coverage(evidence),
        "reports": await _entity_reports(session, canonical),
        "evidence": {
            "contracts": contracts,
            "donations": donations,
            "lobbying": lobbying,
            "bills": bills,
            "regulations": regulations,
            "tribunal_decisions": tribunal,
            "breadth": breadth,
        },
    }


async def gather_sector_data(
    session: AsyncSession, sector: Sector, province: str | None = None
) -> dict[str, Any]:
    ents = sector.entities
    kw = sector.keywords

    # These reads are independent, so run them concurrently — each on its own
    # connection. SQLite serves concurrent readers, so wall-clock drops to the
    # slowest single query instead of the sum (this was the bulk of the cold-load
    # cost on dense sectors). Downstream scoring/connections stay sequential (CPU).
    from api.database import AsyncSessionLocal

    async def _run(fn):
        async with AsyncSessionLocal() as s:
            return await fn(s)

    (
        contracts, donations, lobbying, bills, regulations, tribunal,
        appointments, breadth, provinces, trends,
    ) = await asyncio.gather(
        _run(lambda s: _contracts(s, ents)),
        _run(lambda s: _donations(s, ents, province)),
        _run(lambda s: _lobbying(s, ents)),
        _run(lambda s: _bills(s, kw)),
        _run(lambda s: _regulations(s, kw)),
        _run(lambda s: _tribunal(s, kw, sector.regulators)),
        _run(lambda s: _appointments(s, sector.regulators)),
        _run(lambda s: _breadth(s, ents, kw, province)),
        _run(lambda s: _province_breakdown(s, ents, kw)),
        _run(lambda s: _trends(s, ents, province)),
    )

    # Evidence bundle in the shape risk_scorer.score() consumes (sector as pseudo-entity).
    evidence = {
        "company": sector.name,
        "canonical": sector.slug,
        "sector": sector.name,
        "lobbying": lobbying,
        "contracts": contracts,
        "donations": donations,
        "bills": bills,
        "regulations": regulations,
        "tribunal_decisions": tribunal,
        "appointments": appointments,
        "breadth": breadth,
    }
    scores = score_evidence(evidence)
    connections = detect_connections(evidence)
    signals = build_sector_signals(evidence, connections)
    evidence_count = sum(int((evidence.get(k) or {}).get("count") or 0) for k in (
        "lobbying", "contracts", "donations", "bills", "regulations",
        "tribunal_decisions", "appointments", "breadth",
    ))
    findings = [finding_from_signal(signal, sector) for signal in signals]
    suggested_questions = []
    for finding in findings:
        for question in finding.get("suggested_questions", []):
            if question not in suggested_questions:
                suggested_questions.append(question)

    # Most active players, ranked by combined footprint.
    rank: dict[str, dict[str, Any]] = {}
    for c in contracts["by_entity"]:
        rank.setdefault(c["entity"], {"entity": c["entity"], "contracts": 0.0, "lobbying": 0})
        rank[c["entity"]]["contracts"] = c["value"]
    for l in lobbying["by_entity"]:
        rank.setdefault(l["entity"], {"entity": l["entity"], "contracts": 0.0, "lobbying": 0})
        rank[l["entity"]]["lobbying"] = l["count"]
    top_entities = sorted(rank.values(), key=lambda r: (-r["lobbying"], -r["contracts"]))[:8]

    payload = {
        "sector": sector.to_dict(),
        "province": province,
        "province_name": PROVINCES.get(province) if province else None,
        "scores": scores,
        "risk_band": risk_band_from_score(scores.get("overall"), evidence_count=evidence_count),
        "movement": movement_windows(evidence_count),
        "connections": connections,
        "signals": signals,
        "findings": findings,
        "suggested_questions": suggested_questions[:8],
        "narrative": _narrative(sector, scores, connections, province),
        "trends": trends,
        "top_entities": top_entities,
        "province_breakdown": provinces,
        "source_coverage": _coverage(evidence),
        "evidence": {
            "contracts": contracts,
            "donations": donations,
            "lobbying": lobbying,
            "bills": bills,
            "regulations": regulations,
            "tribunal_decisions": tribunal,
            "appointments": appointments,
            "breadth": breadth,
        },
    }
    payload["intelligence_brief"] = sector_brief(payload)
    return payload
