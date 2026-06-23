"""Ingestion-completeness dashboard endpoint (Goal 12).

One route backing the ops-console "Data Completeness" panel and any other
dashboard consumer — same pipeline.data_audit.build_inventory() snapshot the
scripts/nessus.py CLI renders, just as JSON. No response_model: the shape is
intentionally a single evolving snapshot dict (mirrors pipeline/
catalogue_discovery.py's catalogue_report, which is exposed the same way),
not a stable public contract yet.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from pipeline.data_audit import build_inventory

router = APIRouter(prefix="/api/data", tags=["data-health"])


@router.get("/health")
async def data_health(
    deep: bool = Query(default=False, description="Also scan for missing years on >1M-row tables — slower."),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await build_inventory(session, deep=deep)
