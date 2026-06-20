"""Sector intelligence routes — the centerpiece data API.

Rolls up cross-source political-risk signals by industry (and optionally province)
rather than by a single company. See :mod:`pipeline.sector_intel`.
"""
from __future__ import annotations

from copy import deepcopy
from time import monotonic
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_session
from api.routes.sources import get_sources_status
from api.schemas import SectorListResponse, SectorOverviewResponse
from pipeline.evidence_graph import build_sector_graph
from pipeline.sector_intel import enrich_sector_coverage, gather_sector_data
from pipeline.sector_mapper import PROVINCES, get_sector, list_sectors

router = APIRouter(prefix="/api/sectors", tags=["sectors"])

_SECTOR_CACHE_TTL_SECONDS = 300  # operator-freshness contract: short-lived (see test_product_contracts)
_SECTOR_CACHE: dict[tuple[str, str | None], dict[str, Any]] = {}


def clear_sector_cache() -> None:
    """Clear cached sector payloads after source data refreshes."""
    _SECTOR_CACHE.clear()


@router.get("", response_model=SectorListResponse)
async def sectors() -> dict[str, Any]:
    return {
        "count": len(list_sectors()),
        "sectors": list_sectors(),
        "provinces": [{"code": c, "name": n} for c, n in PROVINCES.items()],
    }


@router.get("/{slug}/overview", response_model=SectorOverviewResponse)
async def overview(
    slug: str,
    province: str | None = Query(default=None, description="2-letter province code, e.g. AB"),
    refresh: bool = Query(default=False, description="Bypass short-lived sector cache."),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    sector = get_sector(slug)
    if not sector:
        raise HTTPException(status_code=404, detail=f"Unknown sector '{slug}'")
    prov = province.strip().upper()[:2] if province else None
    if prov and prov not in PROVINCES:
        raise HTTPException(status_code=400, detail=f"Unknown province '{province}'")
    key = (sector.slug, prov)
    now = monotonic()
    cached = _SECTOR_CACHE.get(key)
    if not refresh and cached and now < cached["expires_at"]:
        payload = deepcopy(cached["payload"])
        payload["cache"] = {"status": "hit", "ttl_seconds": _SECTOR_CACHE_TTL_SECONDS}
        return payload

    payload = await gather_sector_data(session, sector, prov)
    source_status = await get_sources_status(session)
    payload["source_status"] = source_status
    payload["source_coverage"] = enrich_sector_coverage(payload.get("source_coverage", []), source_status)
    payload["graph"] = await build_sector_graph(session, sector.slug)
    _SECTOR_CACHE[key] = {"payload": deepcopy(payload), "expires_at": now + _SECTOR_CACHE_TTL_SECONDS}
    payload["cache"] = {"status": "refresh" if refresh else "miss", "ttl_seconds": _SECTOR_CACHE_TTL_SECONDS}
    return payload
