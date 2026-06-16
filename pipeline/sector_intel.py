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

from typing import Any

from sqlalchemy import Float, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.appointment import Appointment
from api.models.contract import Contract
from api.models.donation import Bill, Donation
from api.models.entity import LobbyingRecord
from api.models.grant import Grant
from api.models.regulation import GazetteEntry, TribunalDecision
from api.models.source_record import SourceRecord
from pipeline.entity_resolver import normalize
from pipeline.risk_scorer import score as score_evidence
from pipeline.sector_mapper import PROVINCES, Sector, get_sector, sector_for_entity


def _kw_filter(columns: list, keywords: list[str]):
    """OR of ``col ILIKE %kw%`` across the given columns and keywords."""
    clauses = [col.ilike(f"%{kw}%") for kw in keywords for col in columns]
    return or_(*clauses) if clauses else None


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
    return {
        "count": count,
        "total_value": round(total or 0, 2),
        "by_department": [{"dept": d[0], "value": round(d[1] or 0, 2), "count": d[2]} for d in by_dept],
        "by_entity": [{"entity": v[0], "value": round(v[1] or 0, 2), "count": v[2]} for v in by_vendor],
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
    return {
        "count": count,
        "total_value": round(total or 0, 2),
        "by_party": [{"party": p[0] or "—", "value": round(p[1] or 0, 2), "count": p[2]} for p in by_party],
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
    return {
        "count": count,
        "institutions": [i for i, _ in top_insts],
        "top_institutions": [{"institution": i, "count": n} for i, n in top_insts],
        "by_entity": [{"entity": e[0], "count": e[1]} for e in by_entity],
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
            {"id": b.id, "table": "bills", "bill_number": b.bill_number, "title_en": b.title_en,
             "status": b.status, "sponsor": b.sponsor, "latest_activity": b.latest_activity}
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
            {"id": r.id, "table": "gazette", "gazette_part": r.gazette_part, "title": r.title,
             "published_date": r.published_date, "department": r.department, "url": r.url}
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
            {"id": r.id, "table": "tribunal", "body": r.body, "decision_number": r.decision_number,
             "title": r.title, "decision_date": r.decision_date, "outcome": r.outcome, "url": r.url}
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
            {"id": r.id, "table": "appointments", "appointee_name": r.appointee_name,
             "position_title": r.position_title, "organization": r.organization,
             "appointment_date": r.appointment_date}
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
            {"id": r.id, "table": "source_records", "source": r.source, "title": r.title,
             "summary": (r.summary or "")[:240], "event_date": r.event_date,
             "province": r.province, "url": r.url}
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
        })

    # 3. Regulatory activity in motion (gazette / tribunal) against a lobbying-heavy sector.
    if regs["count"] > 0 and lob["count"] >= 25:
        out.append({
            "title": "Regulatory change against an engaged sector",
            "detail": f"{regs['count']} recent Canada Gazette item(s) intersect the sector while lobbying runs hot — "
                      "rule-making and industry engagement are moving together.",
            "sources": ["regulations", "lobbying"], "severity": "elevated",
        })

    # 4. On-the-ground breadth events (CER incidents, NPRI releases, assessments).
    if breadth["count"] > 0:
        sample = breadth["records"][0]
        out.append({
            "title": "Operational/environmental events on file",
            "detail": f"{breadth['count']:,} breadth record(s) (e.g. {sample['source']}: "
                      f"{sample['title'][:90]}) tie physical operations to the sector's risk picture.",
            "sources": ["source_records"], "severity": "watch",
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
            })

    return out


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
        })

    if don["count"] > 0 and lob["count"] >= 5:
        out.append({
            "title": "Contributions alongside active lobbying",
            "detail": f"{don['count']} political contribution record(s) sit alongside sustained "
                      "lobbying — relationship-building across both channels.",
            "sources": ["donations", "lobbying"], "severity": "watch",
        })

    if (regs["count"] + ev.get("tribunal_decisions", {}).get("count", 0)) > 0:
        out.append({
            "title": "Direct regulatory exposure on file",
            "detail": f"{regs['count']} Gazette item(s) and "
                      f"{ev.get('tribunal_decisions', {}).get('count', 0)} tribunal decision(s) intersect this entity.",
            "sources": ["regulations"], "severity": "watch",
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

    contracts = await _contracts(session, ents)
    donations = await _donations(session, ents, province)
    lobbying = await _lobbying(session, ents)
    bills = await _bills(session, kw)
    regulations = await _regulations(session, kw)
    tribunal = await _tribunal(session, kw, sector.regulators)
    appointments = await _appointments(session, sector.regulators)
    breadth = await _breadth(session, ents, kw, province)
    provinces = await _province_breakdown(session, ents, kw)

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

    # Most active players, ranked by combined footprint.
    rank: dict[str, dict[str, Any]] = {}
    for c in contracts["by_entity"]:
        rank.setdefault(c["entity"], {"entity": c["entity"], "contracts": 0.0, "lobbying": 0})
        rank[c["entity"]]["contracts"] = c["value"]
    for l in lobbying["by_entity"]:
        rank.setdefault(l["entity"], {"entity": l["entity"], "contracts": 0.0, "lobbying": 0})
        rank[l["entity"]]["lobbying"] = l["count"]
    top_entities = sorted(rank.values(), key=lambda r: (-r["lobbying"], -r["contracts"]))[:8]

    return {
        "sector": sector.to_dict(),
        "province": province,
        "province_name": PROVINCES.get(province) if province else None,
        "scores": scores,
        "connections": connections,
        "narrative": _narrative(sector, scores, connections, province),
        "trends": await _trends(session, ents, province),
        "top_entities": top_entities,
        "province_breakdown": provinces,
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
