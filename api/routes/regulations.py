"""Regulations routes — Canada Gazette entries and tribunal decisions."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.cache import invalidate_workspace_caches
from api.database import get_session
from api.models.regulation import GazetteEntry, TribunalDecision
from api.schemas import IngestStartedResponse, SourceSearchResponse, StatsResponse
from pipeline.connector_crtc_decisions import fetch_crtc_decisions
from pipeline.ingest import fetch_gazette_entries

router = APIRouter(prefix="/api/regulations", tags=["regulations"])


async def _run_gazette_ingest() -> None:
    from api.database import AsyncSessionLocal
    rows = await fetch_gazette_entries()
    async with AsyncSessionLocal() as session:
        for r in rows:
            exists = (await session.execute(
                select(GazetteEntry).where(GazetteEntry.guid == r["guid"]).limit(1)
            )).scalar_one_or_none() if r.get("guid") else None
            if exists:
                continue
            session.add(GazetteEntry(**r))
        await session.commit()
    invalidate_workspace_caches("manual_gazette_ingest")


async def _run_crtc_ingest() -> None:
    from api.database import AsyncSessionLocal
    rows = await fetch_crtc_decisions()
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
        await session.commit()
    invalidate_workspace_caches("manual_crtc_ingest")


@router.post("/gazette/ingest", response_model=IngestStartedResponse)
async def ingest_gazette(background_tasks: BackgroundTasks):
    background_tasks.add_task(_run_gazette_ingest)
    return {"status": "started", "source": "Canada Gazette Part I + II RSS"}


@router.post("/crtc/ingest", response_model=IngestStartedResponse)
async def ingest_crtc(background_tasks: BackgroundTasks):
    background_tasks.add_task(_run_crtc_ingest)
    return {"status": "started", "source": "CRTC Decisions RSS"}


@router.get("/stats", response_model=StatsResponse)
async def regulations_stats(session: AsyncSession = Depends(get_session)):
    gazette = (await session.execute(select(func.count(GazetteEntry.id)))).scalar_one()
    gazette_i = (await session.execute(select(func.count(GazetteEntry.id)).where(GazetteEntry.gazette_part == "I"))).scalar_one()
    gazette_ii = (await session.execute(select(func.count(GazetteEntry.id)).where(GazetteEntry.gazette_part == "II"))).scalar_one()
    decisions = (await session.execute(select(func.count(TribunalDecision.id)))).scalar_one()
    return {
        "gazette_entries": gazette,
        "gazette_part_i": gazette_i,
        "gazette_part_ii": gazette_ii,
        "tribunal_decisions": decisions,
    }


@router.get("/gazette/search", response_model=SourceSearchResponse)
async def search_gazette(
    q: str = Query(..., min_length=1, max_length=255),
    limit: int = Query(default=30, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> dict:
    res = await session.execute(
        select(GazetteEntry)
        .where(
            or_(
                GazetteEntry.title.ilike(f"%{q}%"),
                GazetteEntry.description.ilike(f"%{q}%"),
                GazetteEntry.department.ilike(f"%{q}%"),
            )
        )
        .order_by(GazetteEntry.published_date.desc())
        .limit(limit)
    )
    rows = res.scalars().all()
    return {
        "query": q,
        "count": len(rows),
        "records": [
            {
                "gazette_part": r.gazette_part,
                "title": r.title,
                "published_date": r.published_date,
                "department": r.department,
                "regulation_id": r.regulation_id,
                "url": r.url,
                "description": (r.description or "")[:300],
            }
            for r in rows
        ],
    }


@router.get("/decisions/search", response_model=SourceSearchResponse)
async def search_decisions(
    q: str = Query(..., min_length=1, max_length=255),
    limit: int = Query(default=30, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> dict:
    res = await session.execute(
        select(TribunalDecision)
        .where(
            or_(
                TribunalDecision.title.ilike(f"%{q}%"),
                TribunalDecision.summary.ilike(f"%{q}%"),
                TribunalDecision.parties.ilike(f"%{q}%"),
            )
        )
        .order_by(TribunalDecision.decision_date.desc())
        .limit(limit)
    )
    rows = res.scalars().all()
    return {
        "query": q,
        "count": len(rows),
        "records": [
            {
                "body": r.body,
                "decision_number": r.decision_number,
                "title": r.title,
                "decision_date": r.decision_date,
                "outcome": r.outcome,
                "summary": r.summary,
                "url": r.url,
            }
            for r in rows
        ],
    }
