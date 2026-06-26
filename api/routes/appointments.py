"""GIC Appointments routes — ingest and search Governor in Council appointments."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.cache import invalidate_workspace_caches
from api.database import get_session
from api.models.appointment import Appointment
from api.models.source_record import SourceRecord
from api.schemas import IngestStartedResponse, SourceSearchResponse, StatsResponse
from pipeline.entity_resolver import normalize
from pipeline.ingest import parse_appointments_from_precis

router = APIRouter(prefix="/api/appointments", tags=["appointments"])


class IngestRequest(BaseModel):
    max_rows: int = 10000  # vestigial — kept for API/UI compatibility; this
    # source now derives from already-ingested orders_in_council rows rather
    # than paginating a network resource, so there's nothing to cap.


async def _run_appointment_ingest(max_rows: int) -> None:
    from sqlalchemy import delete
    from api.database import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        raw_rows = (await session.execute(
            select(SourceRecord.raw).where(SourceRecord.source == "orders_in_council")
        )).scalars().all()
    rows = parse_appointments_from_precis(list(raw_rows))
    async with AsyncSessionLocal() as session:
        await session.execute(delete(Appointment))
        session.add_all([Appointment(**r) for r in rows])
        await session.commit()
    invalidate_workspace_caches("manual_appointments_ingest")


@router.post("/ingest", response_model=IngestStartedResponse)
async def ingest_appointments(body: IngestRequest, background_tasks: BackgroundTasks):
    background_tasks.add_task(_run_appointment_ingest, body.max_rows)
    return {"status": "started", "max_rows": body.max_rows}


@router.get("/stats", response_model=StatsResponse)
async def appointments_stats(session: AsyncSession = Depends(get_session)):
    total = (await session.execute(select(func.count(Appointment.id)))).scalar_one()
    unique_orgs = (await session.execute(select(func.count(func.distinct(Appointment.organization))))).scalar_one()
    return {"total_records": total, "unique_organizations": unique_orgs}


@router.get("/search", response_model=SourceSearchResponse)
async def search_appointments(
    q: str = Query(..., min_length=1, max_length=255),
    limit: int = Query(default=50, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> dict:
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
