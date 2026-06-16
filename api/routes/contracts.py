"""Contracts routes — ingest real federal contract data, then query the DB."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..models.contract import Contract
from pipeline.entity_resolver import normalize
from pipeline.ingest import fetch_contract_rows

router = APIRouter(prefix="/api/contracts", tags=["contracts"])


class IngestRequest(BaseModel):
    max_rows: int = 20000


@router.post("/ingest")
async def ingest_contracts(body: IngestRequest, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Stream real contract rows from open.canada.ca into the local DB."""
    rows = await fetch_contract_rows(max_rows=body.max_rows)

    # Fresh load each run for the MVP (full incremental sync is a later step).
    await session.execute(delete(Contract))
    session.add_all([Contract(**r) for r in rows])
    await session.commit()

    total_value = sum(r["contract_value"] or 0 for r in rows)
    distinct = len({r["canonical_name"] for r in rows})
    return {
        "ingested": len(rows),
        "distinct_vendors": distinct,
        "total_value": round(total_value, 2),
        "source": "Proactive Publication — Contracts over $10,000 (open.canada.ca)",
    }


@router.get("/stats")
async def stats(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Headline numbers + top vendors/departments over ingested data."""
    total = (await session.execute(select(func.count(Contract.id)))).scalar_one()
    if not total:
        return {"total": 0, "total_value": 0, "top_vendors": [], "top_departments": []}

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
    }


@router.get("/search")
async def search(company: str = Query(...), session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
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
