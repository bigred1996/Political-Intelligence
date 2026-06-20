"""Overview dashboard route — one fast call backing the home workspace.

Cheap aggregates only (small tables + indexed/groupby), so the dashboard paints
fast. No external market data — the ticker is political/legislative status drawn
from our own corpus.
"""
from __future__ import annotations

from copy import deepcopy
from time import monotonic
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_session
from api.models.contract import Contract
from api.models.donation import Bill, Donation
from api.models.entity import LobbyingRecord
from api.models.politician import HansardMention
from api.models.regulation import GazetteEntry
from api.models.source_record import SourceRecord
from api.schemas import OverviewResponse
from pipeline.evidence_graph import resolve_politician
from pipeline.sector_intel import finding_from_signal, movement_windows, risk_band_from_score
from pipeline.sector_mapper import PROVINCES, SECTORS, Sector

router = APIRouter(prefix="/api", tags=["overview"])

_OVERVIEW_CACHE_TTL_SECONDS = 300  # operator-freshness contract: short-lived (see test_product_contracts)
_OVERVIEW_CACHE: dict[str, Any] = {"expires_at": 0.0, "payload": None}


def clear_overview_cache() -> None:
    """Clear cached dashboard payloads after data refreshes."""
    _OVERVIEW_CACHE["expires_at"] = 0.0
    _OVERVIEW_CACHE["payload"] = None


def _impact_for_bill(status: str | None) -> str:
    s = (status or "").lower()
    if any(t in s for t in ("royal assent", "third reading", "senate")):
        return "High"
    if any(t in s for t in ("second reading", "committee", "report stage")):
        return "Medium"
    return "Low"


def _kw_filter(columns: list, keywords: list[str]):
    clauses = [col.ilike(f"%{kw}%") for kw in keywords for col in columns]
    return or_(*clauses) if clauses else None


def _record_ref(table: str, pk: int, source: str, title: str, date: str | None = None) -> dict[str, Any]:
    return {"table": table, "id": pk, "pk": pk, "source": source, "title": title, "date": date}


def _risk_label(score: float) -> str:
    if score >= 7:
        return "High"
    if score >= 4:
        return "Medium"
    return "Low"


def _signal(
    *,
    title: str,
    theme: str,
    impact: str,
    summary: str,
    why: str,
    sectors: list[dict[str, str]] | None = None,
    references: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "title": title,
        "theme": theme,
        "impact": impact,
        "summary": summary,
        "why": why,
        "sectors": sectors or [],
        "references": references or [],
    }


async def _sector_snapshot(session: AsyncSession, sector: Sector) -> dict[str, Any]:
    ents = sector.entities
    kw = sector.keywords
    sector_ref = {"slug": sector.slug, "name": sector.name}

    contract_total, contract_count = (
        await session.execute(
            select(func.coalesce(func.sum(Contract.contract_value), 0.0), func.count(Contract.id))
            .where(Contract.canonical_name.in_(ents))
        )
    ).one()
    lobbying_count = (
        await session.execute(
            select(func.count(LobbyingRecord.id)).where(LobbyingRecord.canonical_name.in_(ents))
        )
    ).scalar_one()

    bill_filter = _kw_filter([Bill.title_en, Bill.bill_number, Bill.status], kw)
    bill_stmt = select(Bill).order_by(Bill.introduced_date.desc()).limit(3)
    if bill_filter is not None:
        bill_stmt = bill_stmt.where(bill_filter)
    bills = (await session.execute(bill_stmt)).scalars().all()

    gazette_filter = _kw_filter([GazetteEntry.title, GazetteEntry.description, GazetteEntry.department], kw + sector.regulators)
    gazette_stmt = select(GazetteEntry).order_by(GazetteEntry.published_date.desc()).limit(3)
    if gazette_filter is not None:
        gazette_stmt = gazette_stmt.where(gazette_filter)
    gazette = (await session.execute(gazette_stmt)).scalars().all()

    # Sector drill-down pages do rich operational/source-record evidence. The
    # homepage stays fast and uses global recent operations instead.
    ops: list[SourceRecord] = []
    ops_count = 0

    hansard_filter = _kw_filter([HansardMention.keyword, HansardMention.excerpt], kw)
    hansard = []
    if hansard_filter is not None:
        hansard = (
            await session.execute(
                select(HansardMention).where(hansard_filter).order_by(HansardMention.speech_date.desc()).limit(2)
            )
        ).scalars().all()

    score = min(10.0, (
        min(lobbying_count / 80, 3.0)
        + min(len(bills) * 1.2, 2.4)
        + min(len(gazette) * 1.0, 2.0)
        + min(ops_count / 4000, 1.6)
        + min((contract_total or 0) / 500_000_000, 1.0)
    ))
    refs: list[dict[str, Any]] = []
    refs.extend(_record_ref("bills", b.id, "LEGISinfo", f"{b.bill_number} — {b.title_en or ''}".strip(" —"), b.introduced_date) for b in bills[:2])
    refs.extend(_record_ref("gazette", g.id, "Canada Gazette", g.title, g.published_date) for g in gazette[:2])
    refs.extend(_record_ref("source_records", o.id, o.source, o.title, o.event_date) for o in ops[:2])
    refs.extend(_record_ref("hansard_mentions", h.id, h.source, f"{h.speaker or 'House'} — {h.keyword}", h.speech_date) for h in hansard[:2])

    drivers = []
    if lobbying_count:
        drivers.append(f"{lobbying_count:,} lobbying communications")
    if bills:
        drivers.append(f"{len(bills)} recent bill match(es)")
    if gazette:
        drivers.append(f"{len(gazette)} Gazette item(s)")
    if ops_count:
        drivers.append(f"{ops_count:,} operational/source records")

    evidence_count = lobbying_count + len(bills) + len(gazette) + ops_count + contract_count + len(hansard)
    return {
        "sector": sector_ref,
        "score": round(score, 1),
        "risk_band": risk_band_from_score(score, evidence_count=evidence_count),
        "impact": _risk_label(score),
        "summary": "; ".join(drivers[:3]) or "No major cross-source movement at current data depth.",
        "movement": movement_windows(evidence_count),
        "metrics": {
            "contracts": contract_count,
            "contract_value": round(contract_total or 0, 2),
            "lobbying": lobbying_count,
            "bills": len(bills),
            "gazette": len(gazette),
            "operations": ops_count,
            "hansard": len(hansard),
        },
        "references": refs[:5],
    }


async def _actor_movement(session: AsyncSession) -> list[dict[str, Any]]:
    mentions = (
        await session.execute(
            select(HansardMention)
            .where(HansardMention.speech_date.isnot(None))
            .order_by(HansardMention.speech_date.desc())
            .limit(10)
        )
    ).scalars().all()
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str | None, str]] = set()
    for m in mentions:
        dedupe_key = (m.speaker or "House intervention", m.speech_date, m.keyword)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        matched = [
            {"slug": s.slug, "name": s.name}
            for s in SECTORS.values()
            if any(k.lower() in f"{m.keyword} {m.excerpt or ''}".lower() for k in s.keywords)
        ][:2]
        pol = await resolve_politician(session, m.speaker)
        out.append({
            "actor": (pol or {}).get("name") or m.speaker or "House intervention",
            "role": (pol or {}).get("role"),
            "party": (pol or {}).get("party"),
            "politician_slug": (pol or {}).get("slug"),
            "confidence": (pol or {}).get("confidence") or "unresolved",
            "date": m.speech_date,
            "keyword": m.keyword,
            "excerpt": (m.excerpt or "")[:220],
            "sectors": matched,
            "reference": _record_ref("hansard_mentions", m.id, m.source, f"{m.speaker or 'House'} — {m.keyword}", m.speech_date),
        })
    return out[:6]


async def _build_overview(session: AsyncSession) -> dict[str, Any]:
    # ── Regional exposure (cross-sector) — province groupby over breadth records ──
    prov_rows = (
        await session.execute(
            select(SourceRecord.province, func.count(SourceRecord.id))
            .where(SourceRecord.province.isnot(None))
            .group_by(SourceRecord.province)
        )
    ).all()
    tally: dict[str, int] = {}
    for prov, n in prov_rows:
        code = (prov or "").strip().upper()[:2]
        if code in PROVINCES:
            tally[code] = tally.get(code, 0) + n
    max_n = max(tally.values()) if tally else 1
    regional_exposure = sorted(
        [
            {"code": c, "province": PROVINCES[c], "records": n, "score": round(100 * n / max_n)}
            for c, n in tally.items()
        ],
        key=lambda r: -r["records"],
    )

    # ── Regulatory movement — recent bills + gazette with an impact heuristic ──
    bills = (await session.execute(select(Bill).order_by(Bill.introduced_date.desc()).limit(5))).scalars().all()
    gazette = (await session.execute(select(GazetteEntry).order_by(GazetteEntry.published_date.desc()).limit(5))).scalars().all()
    regulatory_movement = [
        {"title": f"{b.bill_number} — {b.title_en}", "body": "Parliament", "date": b.introduced_date,
         "impact": _impact_for_bill(b.status), "kind": "bill", "url": None, "meta": b.status or "",
         "table": "bills", "pk": b.id, "source": "LEGISinfo"}
        for b in bills
    ] + [
        {"title": g.title, "body": g.department or "Canada Gazette", "date": g.published_date,
         "impact": "High" if g.gazette_part == "II" else "Medium", "kind": "regulation",
         "url": g.url, "meta": f"Gazette Part {g.gazette_part}",
         "table": "gazette", "pk": g.id, "source": "Canada Gazette"}
        for g in gazette
    ]

    # ── Activity by source (corpus coverage) ──
    # SQLite count(*) full-scans (no cached row count), so for the big append-only
    # tables use max(id) as an instant total-records proxy; real count for small ones.
    async def _approx(model) -> int:
        return (await session.execute(select(func.max(model.id)))).scalar_one() or 0

    async def _count(model) -> int:
        return (await session.execute(select(func.count(model.id)))).scalar_one()

    activity = [
        {"source": "Contracts", "count": await _approx(Contract)},
        {"source": "Donations", "count": await _approx(Donation)},
        {"source": "Lobbying", "count": await _approx(LobbyingRecord)},
        {"source": "Operations", "count": await _approx(SourceRecord)},
        {"source": "Gazette", "count": await _count(GazetteEntry)},
        {"source": "Bills", "count": await _count(Bill)},
    ]

    # ── Sector watchlist + cross-source findings ──
    sector_watchlist = [await _sector_snapshot(session, s) for s in SECTORS.values() if s.enabled]
    sector_watchlist.sort(key=lambda s: s["score"], reverse=True)

    dashboard_signals: list[dict[str, Any]] = []
    for s in sector_watchlist[:4]:
        dashboard_signals.append(_signal(
            title=f"{s['sector']['name']} risk environment is active",
            theme="Sector watch",
            impact=s["impact"],
            summary=s["summary"],
            why="The dashboard is connecting lobbying, legislative, regulatory, operational, and speech records into one sector view.",
            sectors=[s["sector"]],
            references=s["references"],
        ))
    if bills:
        dashboard_signals.append(_signal(
            title="Legislative file movement requires sector review",
            theme="Regulatory movement",
            impact=max((_impact_for_bill(b.status) for b in bills[:3]), key={"Low": 0, "Medium": 1, "High": 2}.get),
            summary=f"{len(bills)} recent bill(s) are in the federal corpus. Review sector matches before assuming low exposure.",
            why="Bills can become business risk when they intersect with lobbying, committee work, or regulator activity.",
            references=[_record_ref("bills", b.id, "LEGISinfo", f"{b.bill_number} — {b.title_en or ''}".strip(" —"), b.introduced_date) for b in bills[:3]],
        ))
    recent_ops = (
        await session.execute(select(SourceRecord).where(SourceRecord.event_date.isnot(None)).order_by(SourceRecord.id.desc()).limit(3))
    ).scalars().all()
    if recent_ops:
        dashboard_signals.append(_signal(
            title="Operational records are adding place-based exposure",
            theme="Operations",
            impact="Medium",
            summary=f"{len(recent_ops)} recent operational/source records are available for geographic and sector context.",
            why="Operational data turns abstract policy movement into concrete assets, places, events, or environmental records.",
            references=[_record_ref("source_records", e.id, e.source, e.title, e.event_date) for e in recent_ops],
        ))

    actor_movement = await _actor_movement(session)
    if actor_movement:
        first = actor_movement[0]
        dashboard_signals.append(_signal(
            title="House interventions are available as risk context",
            theme="Political actor movement",
            impact="Medium",
            summary=f"{first['actor']} referenced {first['keyword']}; connect this to sector, committee, lobbying, and bill movement as the graph matures.",
            why="Political speech is not a prediction, but it is useful evidence when it later aligns with formal roles, bills, or lobbying.",
            sectors=first["sectors"],
            references=[first["reference"]],
        ))

    # Back-compat compact feed used by older widgets.
    signals = [
        {"title": s["title"], "category": s["theme"], "impact": s["impact"], "meta": s["summary"][:80]}
        for s in dashboard_signals[:8]
    ]
    intelligence_findings = [finding_from_signal(s) for s in dashboard_signals[:8]]
    sector_comparison = [
        {
            "sector": s["sector"],
            "risk_band": s["risk_band"],
            "movement": s["movement"],
            "political_attention": s["metrics"]["hansard"],
            "regulatory_activity": s["metrics"]["bills"] + s["metrics"]["gazette"],
            "lobbying_intensity": s["metrics"]["lobbying"],
            "evidence_volume": sum(v for k, v in s["metrics"].items() if k != "contract_value"),
            "source_coverage": "partial" if s["references"] else "weak",
            "confidence": "medium" if s["references"] else "low",
            "note": "Comparisons are evidence-normalized; raw source volume is not treated as risk by itself.",
        }
        for s in sector_watchlist
    ]
    high_priority = [f for f in intelligence_findings if f["risk_level"] in {"high", "elevated"}]
    what_changed = {
        "summary": (
            f"{len(high_priority)} high-priority signal(s) and {len(sector_watchlist)} active sector lens(es) "
            "are available. Period deltas remain marked insufficient until historical snapshots are collected."
        ),
        "movement_status": "insufficient_history",
        "requires_attention": [s["sector"] for s in sector_watchlist[:3]],
        "source_limits": "Unequal source coverage can explain apparent sector differences.",
    }

    # ── Political ticker ──
    ticker = {
        "house_status": "House of Commons · In session",
        "next_item": f"{bills[0].bill_number} debate" if bills else "—",
        "bills_in_motion": activity[5]["count"],
        "gazette_entries": activity[4]["count"],
        "contracts": activity[0]["count"],
        "operations": activity[3]["count"],
    }

    return {
        "regional_exposure": regional_exposure,
        "regulatory_movement": regulatory_movement,
        "activity": activity,
        "signals": signals,
        "dashboard_signals": dashboard_signals[:8],
        "intelligence_findings": intelligence_findings,
        "sector_watchlist": sector_watchlist[:8],
        "sector_comparison": sector_comparison[:8],
        "actor_movement": actor_movement,
        "what_changed": what_changed,
        "ticker": ticker,
    }


@router.get("/overview", response_model=OverviewResponse)
async def overview(
    refresh: bool = Query(default=False, description="Bypass short-lived overview cache."),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    now = monotonic()
    cached = _OVERVIEW_CACHE.get("payload")
    if not refresh and cached is not None and now < float(_OVERVIEW_CACHE.get("expires_at") or 0):
        payload = deepcopy(cached)
        payload["cache"] = {"status": "hit", "ttl_seconds": _OVERVIEW_CACHE_TTL_SECONDS}
        return payload

    payload = await _build_overview(session)
    _OVERVIEW_CACHE["payload"] = deepcopy(payload)
    _OVERVIEW_CACHE["expires_at"] = now + _OVERVIEW_CACHE_TTL_SECONDS
    payload["cache"] = {"status": "refresh" if refresh else "miss", "ttl_seconds": _OVERVIEW_CACHE_TTL_SECONDS}
    return payload
