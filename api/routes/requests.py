"""Report-request intake routes (Step 2 slice)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..models.request import ReportRequestRow, ReportType, TimeHorizon

router = APIRouter(prefix="/api/requests", tags=["requests"])


class CreateRequest(BaseModel):
    company_name: str
    sector: str | None = None
    deal_context: str | None = None
    specific_asset: str | None = None
    report_type: ReportType = ReportType.deal_due_diligence
    time_horizon: TimeHorizon = TimeHorizon.current
    customer_name: str | None = None


@router.post("")
async def create_request(body: CreateRequest, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    row = ReportRequestRow(
        company_name=body.company_name.strip(),
        sector=body.sector,
        deal_context=body.deal_context,
        specific_asset=body.specific_asset,
        report_type=body.report_type.value,
        time_horizon=body.time_horizon.value,
        customer_name=body.customer_name,
    )
    session.add(row)
    await session.commit()
    return {"id": row.id, "status": row.status, "company_name": row.company_name}


@router.get("")
async def list_requests(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    result = await session.execute(select(ReportRequestRow).order_by(ReportRequestRow.created_at.desc()))
    items = result.scalars().all()
    return {
        "count": len(items),
        "requests": [
            {
                "id": r.id,
                "company_name": r.company_name,
                "sector": r.sector,
                "report_type": r.report_type,
                "time_horizon": r.time_horizon,
                "status": r.status,
                "created_at": r.created_at.isoformat(),
            }
            for r in items
        ],
    }
