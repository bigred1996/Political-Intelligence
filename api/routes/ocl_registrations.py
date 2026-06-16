"""OCL Registrations routes — lobbying registration filings (who is lobbying and why)."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_session
from api.models.ocl_registration import OCLRegistration
from pipeline.entity_resolver import normalize
from pipeline.ingest import fetch_ocl_registration_rows

router = APIRouter(prefix="/api/ocl-registrations", tags=["ocl-registrations"])


class IngestRequest(BaseModel):
    max_rows: int = 0


async def _run_ocl_reg_ingest(max_rows: int) -> None:
    from api.database import AsyncSessionLocal
    rows = await fetch_ocl_registration_rows(max_rows=max_rows)
    batch_size = 2000
    async with AsyncSessionLocal() as session:
        for i in range(0, len(rows), batch_size):
            for r in rows[i : i + batch_size]:
                exists = (await session.execute(
                    select(OCLRegistration).where(
                        OCLRegistration.registration_num == r["registration_num"]
                    ).limit(1)
                )).scalar_one_or_none() if r.get("registration_num") else None
                if exists:
                    continue
                session.add(OCLRegistration(**r))
            await session.commit()


@router.post("/ingest")
async def ingest_ocl_registrations(body: IngestRequest, background_tasks: BackgroundTasks):
    background_tasks.add_task(_run_ocl_reg_ingest, body.max_rows)
    return {"status": "started", "max_rows": body.max_rows or "all"}


@router.get("/stats")
async def ocl_reg_stats(session: AsyncSession = Depends(get_session)):
    total = (await session.execute(select(func.count(OCLRegistration.id)))).scalar_one()
    unique = (await session.execute(select(func.count(func.distinct(OCLRegistration.canonical_name))))).scalar_one()
    return {"total_records": total, "unique_clients": unique}


@router.get("/search")
async def search_ocl_registrations(
    q: str,
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
):
    canonical = normalize(q)
    res = await session.execute(
        select(OCLRegistration)
        .where(
            or_(
                OCLRegistration.canonical_name == canonical,
                OCLRegistration.client_org.ilike(f"%{q}%"),
                OCLRegistration.firm_name.ilike(f"%{q}%"),
            )
        )
        .order_by(OCLRegistration.effective_date.desc())
        .limit(limit)
    )
    rows = res.scalars().all()
    return {
        "query": q,
        "count": len(rows),
        "records": [
            {
                "registration_num": r.registration_num,
                "client_org": r.client_org,
                "registrant_name": r.registrant_name,
                "firm_name": r.firm_name,
                "registration_type": r.registration_type,
                "status": r.status,
                "effective_date": r.effective_date,
                "end_date": r.end_date,
                "subject_matters": r.subject_matters,
                "federal_benefits": r.federal_benefits,
            }
            for r in rows
        ],
    }
