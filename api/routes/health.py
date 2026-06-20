"""Backend health and readiness checks."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_session
from api.routes.sources import get_sources_status
from api.schemas import ReadinessResponse
from search.index import index_status

router = APIRouter(prefix="/api/health", tags=["health"])


def readiness_status(*, db_ok: bool, sources: dict[str, Any], index: dict[str, Any]) -> tuple[str, list[str]]:
    """Collapse dependency checks into an operator-facing readiness state."""
    reasons: list[str] = []
    if not db_ok:
        reasons.append("database_unreachable")
    summary = sources.get("summary") or {}
    if summary.get("live", 0) == 0:
        reasons.append("no_live_sources")
    if summary.get("empty", 0) >= 4:
        reasons.append("multiple_empty_sources")
    if summary.get("stale", 0):
        reasons.append("stale_sources")
    if summary.get("unknown_freshness", 0) >= 2:
        reasons.append("unknown_source_freshness")
    if not index.get("built"):
        reasons.append("semantic_index_missing")
    status = "ok" if not reasons else "degraded" if db_ok else "down"
    return status, reasons


@router.get("/ready", response_model=ReadinessResponse)
async def ready(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    db_ok = True
    try:
        await session.execute(text("select 1"))
    except Exception:
        db_ok = False

    sources = await get_sources_status(session) if db_ok else {"summary": {}}
    index = index_status()
    status, reasons = readiness_status(db_ok=db_ok, sources=sources, index=index)
    return {
        "status": status,
        "reasons": reasons,
        "checks": {
            "database": {"ok": db_ok},
            "sources": sources.get("summary", {}),
            "source_quality": sources.get("quality", {}),
            "semantic_index": index,
        },
    }
