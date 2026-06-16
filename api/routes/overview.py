"""Overview dashboard route — one fast call backing the home workspace.

Cheap aggregates only (small tables + indexed/groupby), so the dashboard paints
fast. No external market data — the ticker is political/legislative status drawn
from our own corpus.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_session
from api.models.contract import Contract
from api.models.donation import Bill, Donation
from api.models.entity import LobbyingRecord
from api.models.regulation import GazetteEntry
from api.models.source_record import SourceRecord
from pipeline.sector_mapper import PROVINCES

router = APIRouter(prefix="/api", tags=["overview"])


def _impact_for_bill(status: str | None) -> str:
    s = (status or "").lower()
    if any(t in s for t in ("royal assent", "third reading", "senate")):
        return "High"
    if any(t in s for t in ("second reading", "committee", "report stage")):
        return "Medium"
    return "Low"


@router.get("/overview")
async def overview(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
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
         "impact": _impact_for_bill(b.status), "kind": "bill", "url": None, "meta": b.status or ""}
        for b in bills
    ] + [
        {"title": g.title, "body": g.department or "Canada Gazette", "date": g.published_date,
         "impact": "High" if g.gazette_part == "II" else "Medium", "kind": "regulation",
         "url": g.url, "meta": f"Gazette Part {g.gazette_part}"}
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

    # ── Signals — recent notable items across sources ──
    signals: list[dict[str, Any]] = []
    for b in bills[:3]:
        signals.append({"title": f"{b.bill_number} {(b.title_en or '')[:60]}", "category": "Legislation",
                        "impact": _impact_for_bill(b.status), "meta": b.status or ""})
    for g in gazette[:2]:
        signals.append({"title": g.title[:70], "category": "Regulation",
                        "impact": "High" if g.gazette_part == "II" else "Medium", "meta": g.department or ""})
    recent_ops = (
        await session.execute(select(SourceRecord).where(SourceRecord.event_date.isnot(None)).order_by(SourceRecord.id.desc()).limit(3))
    ).scalars().all()
    for e in recent_ops:
        signals.append({"title": e.title[:70], "category": e.source, "impact": "Medium", "meta": e.province or ""})

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
        "ticker": ticker,
    }
