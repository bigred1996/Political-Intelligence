"""Entity intelligence route — read-only cross-source profile for one company.

Uses ``gather_entity_data`` (indexed canonical lookups, no ILIKE full-scans) and
the risk scorer, but writes nothing — unlike ``/api/reports/generate`` which
persists a Report. Gives the entity page scorecard + connection parity with the
sector surface, fast enough for an interactive page.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_session
from api.schemas import EntityProfileResponse
from pipeline.sector_intel import gather_entity_data

router = APIRouter(prefix="/api/entities", tags=["entities"])


@router.get("/{name}", response_model=EntityProfileResponse)
async def entity_profile(
    name: str,
    sector: str | None = Query(default=None, max_length=120),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await gather_entity_data(session, name.strip(), sector)
