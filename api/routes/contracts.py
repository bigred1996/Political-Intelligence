"""Contracts routes — ingest real federal contract data, then query the DB."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..cache import invalidate_workspace_caches
from ..database import get_session
from ..models.contract import Contract
from ..schemas import IngestCompletedResponse, SourceSearchResponse, StatsResponse
from pipeline.entity_resolver import normalize
from pipeline.ingest import fetch_contract_rows

router = APIRouter(prefix="/api/contracts", tags=["contracts"])


class IngestRequest(BaseModel):
    max_rows: int = 20000


@router.post("/ingest", response_model=IngestCompletedResponse)
async def ingest_contracts(body: IngestRequest, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Stream real contract rows from open.canada.ca into the local DB."""
    rows = await fetch_contract_rows(max_rows=body.max_rows)

    # Fresh load each run for the MVP (full incremental sync is a later step).
    await session.execute(delete(Contract))
    session.add_all([Contract(**r) for r in rows])
    await session.commit()
    invalidate_workspace_caches("manual_contracts_ingest")

    total_value = sum(r["contract_value"] or 0 for r in rows)
    distinct = len({r["canonical_name"] for r in rows})
    return {
        "ingested": len(rows),
        "distinct_vendors": distinct,
        "total_value": round(total_value, 2),
        "source": "Proactive Publication — Contracts over $10,000 (open.canada.ca)",
    }


@router.get("/stats", response_model=StatsResponse)
async def stats(
    include_breakdown: bool = Query(default=False, description="Run slower full-table value/top-vendor aggregates."),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Headline numbers over ingested data; expensive group-bys are opt-in."""
    total = (await session.execute(select(func.max(Contract.id)))).scalar_one() or 0
    if not total:
        return {"total": 0, "total_value": 0, "top_vendors": [], "top_departments": []}

    if not include_breakdown:
        return {
            "total": total,
            "total_value": 0,
            "top_vendors": [],
            "top_departments": [],
            "approximate": True,
            "summary_only": True,
        }

    total_value = (await session.execute(select(func.sum(Contract.contract_value)))).scalar_one() or 0

    tv = await session.execute(
        select(Contract.vendor_name, func.sum(Contract.contract_value).label("v"), func.count(Contract.id))
        .group_by(Contract.canonical_name)
        .order_by(func.sum(Contract.contract_value).desc())
        .limit(8)
    )
    td = await session.execute(
        select(Contract.owner_org_title, func.sum(Contract.contract_value).label("v"), func.count(Contract.id))
        .group_by(Contract.owner_org_title)
        .order_by(func.sum(Contract.contract_value).desc())
        .limit(8)
    )
    return {
        "total": total,
        "total_value": round(total_value, 2),
        "top_vendors": [{"vendor": r[0], "value": round(r[1] or 0, 2), "count": r[2]} for r in tv],
        "top_departments": [{"dept": r[0], "value": round(r[1] or 0, 2), "count": r[2]} for r in td],
        "approximate": False,
        "summary_only": False,
    }


@router.get("/search", response_model=SourceSearchResponse)
async def search(
    company: str = Query(..., min_length=1, max_length=255),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Find ingested contracts for a company by canonical entity match."""
    canonical = normalize(company)
    result = await session.execute(
        select(Contract)
        .where(Contract.canonical_name.like(f"%{canonical}%"))
        .order_by(Contract.contract_value.desc())
        .limit(50)
    )
    items = result.scalars().all()
    return {
        "company": company,
        "canonical_name": canonical,
        "count": len(items),
        "total_value": round(sum(i.contract_value or 0 for i in items), 2),
        "contracts": [
            {
                "vendor_name": i.vendor_name,
                "description": i.description,
                "contract_value": i.contract_value,
                "contract_date": i.contract_date,
                "owner_org_title": i.owner_org_title,
            }
            for i in items
        ],
    }
