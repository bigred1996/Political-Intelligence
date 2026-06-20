"""Briefing route — the editorial landing feed.

Deliberately built from cheap queries only (small tables + indexed/recent ordering)
so the front door loads fast. The expensive cross-source scoring lives on the
sector pages. Surfaces "what moved" across Parliament, regulation and operations,
plus the sector entry points.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_session
from api.models.donation import Bill
from api.models.regulation import GazetteEntry
from api.models.source_record import SourceRecord
from api.schemas import BriefingResponse
from pipeline.sector_mapper import list_sectors

router = APIRouter(prefix="/api", tags=["briefing"])


def _dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for it in items:
        key = (it.get("title") or "").strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(it)
    return out


@router.get("/briefing", response_model=BriefingResponse)
async def briefing(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Three categorized streams — legislation, regulation, operations.

    Dates across sources use incompatible formats (ISO vs M/D/YYYY), so we avoid a
    cross-source merge-sort and instead present each stream on its own native order.
    """
    bills = (
        await session.execute(select(Bill).order_by(Bill.introduced_date.desc()).limit(6))
    ).scalars().all()
    legislation = [{
        "kind": "bill", "label": "Bill",
        "title": f"{b.bill_number} — {b.title_en}",
        "meta": b.status or b.latest_activity or "", "date": b.introduced_date, "url": None,
    } for b in bills]

    gazette = (
        await session.execute(select(GazetteEntry).order_by(GazetteEntry.published_date.desc()).limit(6))
    ).scalars().all()
    regulation = [{
        "kind": "regulation", "label": f"Gazette Part {g.gazette_part}",
        "title": g.title, "meta": g.department or "", "date": g.published_date, "url": g.url,
    } for g in gazette]

    events = (
        await session.execute(
            select(SourceRecord).where(SourceRecord.event_date.isnot(None))
            .order_by(SourceRecord.event_date.desc()).limit(12)
        )
    ).scalars().all()
    operations = _dedupe([{
        "kind": "event", "label": e.source,
        "title": e.title, "meta": e.province or "", "date": e.event_date, "url": e.url,
    } for e in events])[:6]

    return {
        "sectors": list_sectors(),
        "streams": {
            "legislation": legislation,
            "regulation": regulation,
            "operations": operations,
        },
    }
