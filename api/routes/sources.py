"""Ingestion routes for donations (Elections Canada) and bills (LEGISinfo)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..models.donation import Bill, Donation
from pipeline.ingest import fetch_bill_rows, fetch_donation_rows

router = APIRouter(prefix="/api", tags=["sources"])


class DonationIngest(BaseModel):
    max_rows: int = 50000


@router.post("/donations/ingest")
async def ingest_donations(body: DonationIngest, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    rows = await fetch_donation_rows(max_rows=body.max_rows)
    await session.execute(delete(Donation))
    session.add_all([Donation(**r) for r in rows])
    await session.commit()
    total = sum(r["amount"] or 0 for r in rows)
    return {"ingested": len(rows), "total_value": round(total, 2),
            "source": "Elections Canada — Contributions (as reviewed)"}


@router.post("/bills/ingest")
async def ingest_bills(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    rows = await fetch_bill_rows()
    await session.execute(delete(Bill))
    session.add_all([Bill(**r) for r in rows])
    await session.commit()
    return {"ingested": len(rows), "source": "LEGISinfo (current Parliament)"}


@router.get("/sources/status")
async def sources_status(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    from ..models.appointment import Appointment
    from ..models.contract import Contract
    from ..models.entity import LobbyingRecord
    from ..models.grant import Grant
    from ..models.ocl_registration import OCLRegistration
    from ..models.politician import HansardMention, Politician
    from ..models.regulation import GazetteEntry, TribunalDecision

    async def count(model) -> int:
        return (await session.execute(select(func.count(model.id)))).scalar_one()

    return {
        "contracts": await count(Contract),
        "donations": await count(Donation),
        "bills": await count(Bill),
        "lobbying_communications": await count(LobbyingRecord),
        "ocl_registrations": await count(OCLRegistration),
        "grants": await count(Grant),
        "appointments": await count(Appointment),
        "gazette_entries": await count(GazetteEntry),
        "tribunal_decisions": await count(TribunalDecision),
        "politicians": await count(Politician),
        "hansard_mentions": await count(HansardMention),
    }
