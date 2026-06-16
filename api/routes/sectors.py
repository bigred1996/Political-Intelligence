"""Sector intelligence routes — the centerpiece data API.

Rolls up cross-source political-risk signals by industry (and optionally province)
rather than by a single company. See :mod:`pipeline.sector_intel`.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_session
from pipeline.sector_intel import gather_sector_data
from pipeline.sector_mapper import PROVINCES, get_sector, list_sectors

router = APIRouter(prefix="/api/sectors", tags=["sectors"])


@router.get("")
async def sectors() -> dict[str, Any]:
    return {
        "count": len(list_sectors()),
        "sectors": list_sectors(),
        "provinces": [{"code": c, "name": n} for c, n in PROVINCES.items()],
    }


@router.get("/{slug}/overview")
async def overview(
    slug: str,
    province: str | None = Query(default=None, description="2-letter province code, e.g. AB"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    sector = get_sector(slug)
    if not sector:
        raise HTTPException(status_code=404, detail=f"Unknown sector '{slug}'")
    prov = province.strip().upper()[:2] if province else None
    if prov and prov not in PROVINCES:
        raise HTTPException(status_code=400, detail=f"Unknown province '{province}'")
    return await gather_sector_data(session, sector, prov)
