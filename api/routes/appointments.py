"""GIC Appointments routes — ingest and search Governor in Council appointments."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_session
from api.models.appointment import Appointment
from pipeline.entity_resolver import normalize
from pipeline.ingest import fetch_appointment_rows

router = APIRouter(prefix="/api/appointments", tags=["appointments"])


class IngestRequest(BaseModel):
    max_rows: int = 10000


async def _run_appointment_ingest(max_rows: int) -> None:
    from api.database import AsyncSessionLocal
    rows = await fetch_appointment_rows(max_rows=max_rows)
    batch_size = 1000
    async with AsyncSessionLocal() as session:
        for i in range(0, len(rows), batch_size):
            for r in rows[i : i + batch_size]:
                session.add(Appointment(**r))
            await session.commit()


@router.post("/ingest")
async def ingest_appointments(body: IngestRequest, background_tasks: BackgroundTasks):
    background_tasks.add_task(_run_appointment_ingest, body.max_rows)
    return {"status": "started", "max_rows": body.max_rows}


@router.get("/stats")
async def appointments_stats(session: AsyncSession = Depends(get_session)):
    total = (await session.execute(select(func.count(Appointment.id)))).scalar_one()
    unique_orgs = (await session.execute(select(func.count(func.distinct(Appointment.organization))))).scalar_one()
    return {"total_records": total, "unique_organizations": unique_orgs}


@router.get("/search")
async def search_appointments(
    q: str,
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
):
    canonical = normalize(q)
    res = await session.execute(
        select(Appointment)
        .where(
            or_(
                Appointment.canonical_name == canonical,
                Appointment.appointee_name.ilike(f"%{q}%"),
                Appointment.organization.ilike(f"%{q}%"),
                Appointment.position_title.ilike(f"%{q}%"),
            )
        )
        .order_by(Appointment.appointment_date.desc())
        .limit(limit)
    )
    rows = res.scalars().all()
    return {
        "query": q,
        "count": len(rows),
        "records": [
            {
                "appointee_name": r.appointee_name,
                "position_title": r.position_title,
                "organization": r.organization,
                "appointment_date": r.appointment_date,
                "end_date": r.end_date,
                "order_in_council": r.order_in_council,
                "appointment_type": r.appointment_type,
                "province": r.province,
            }
            for r in rows
        ],
    }
