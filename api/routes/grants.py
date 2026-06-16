"""Grants & Contributions routes — ingest and search federal funding records."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_session
from api.models.grant import Grant
from pipeline.entity_resolver import normalize
from pipeline.ingest import fetch_grant_rows

router = APIRouter(prefix="/api/grants", tags=["grants"])


class IngestRequest(BaseModel):
    max_rows: int = 30000


async def _run_grant_ingest(max_rows: int) -> None:
    from api.database import AsyncSessionLocal
    rows = await fetch_grant_rows(max_rows=max_rows)
    batch_size = 2000
    async with AsyncSessionLocal() as session:
        for i in range(0, len(rows), batch_size):
            for r in rows[i : i + batch_size]:
                exists = await session.execute(
                    select(Grant).where(Grant.ref_number == r["ref_number"]).limit(1)
                ) if r["ref_number"] else None
                if exists and exists.scalar_one_or_none():
                    continue
                session.add(Grant(**r))
            await session.commit()


@router.post("/ingest")
async def ingest_grants(body: IngestRequest, background_tasks: BackgroundTasks):
    background_tasks.add_task(_run_grant_ingest, body.max_rows)
    return {"status": "started", "max_rows": body.max_rows}


@router.get("/stats")
async def grants_stats(session: AsyncSession = Depends(get_session)):
    total = (await session.execute(select(func.count(Grant.id)))).scalar_one()
    unique = (await session.execute(select(func.count(func.distinct(Grant.canonical_name))))).scalar_one()
    total_val = (await session.execute(select(func.coalesce(func.sum(Grant.agreement_value), 0.0)))).scalar_one()
    return {"total_records": total, "unique_recipients": unique, "total_value": round(total_val, 2)}


@router.get("/search")
async def search_grants(
    q: str,
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
):
    canonical = normalize(q)
    res = await session.execute(
        select(Grant)
        .where(or_(Grant.canonical_name == canonical, Grant.recipient_name.ilike(f"%{q}%")))
        .order_by(Grant.agreement_value.desc())
        .limit(limit)
    )
    rows = res.scalars().all()
    return {
        "query": q,
        "count": len(rows),
        "total_value": round(sum(r.agreement_value or 0 for r in rows), 2),
        "records": [
            {
                "recipient_name": r.recipient_name,
                "owner_org_title": r.owner_org_title,
                "program_name": r.program_name,
                "agreement_type": r.agreement_type,
                "agreement_value": r.agreement_value,
                "agreement_start": r.agreement_start,
                "description": r.description,
            }
            for r in rows
        ],
    }
