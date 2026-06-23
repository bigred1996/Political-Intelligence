"""Multi-step research loop (Goal B3) — the "deep research" engine.

Strictly downstream of /api/retrieve (B1) and /api/interpret (B2): a run plans
gap-driven queries, retrieves, interprets each evidentiary finding, loops under
a hard per-tier round/interpretation cap, then synthesizes across findings. No
PDF (B6), no intake form (B4) — the depth tier is passed in.

Responses are plain dicts (the run trail is deeply nested with resolved
finding links); see `pipeline/research.py` for the full contract and the
in-code cost caps.
"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from pipeline.research import (
    get_research_run_response,
    list_research_runs,
    run_research,
)

router = APIRouter(prefix="/api/research", tags=["research"])


class ResearchBody(BaseModel):
    topic: str = Field(min_length=1, max_length=500)
    depth_tier: Literal["brief", "standard", "deep"] = "standard"


@router.post("")
async def start_research(body: ResearchBody, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    return await run_research(session, body.topic, body.depth_tier)


@router.get("")
async def list_runs(
    limit: int = Query(default=25, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return {"runs": await list_research_runs(session, limit)}


@router.get("/{run_id}")
async def get_run(run_id: str, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    response = await get_research_run_response(session, run_id)
    if response is None:
        raise HTTPException(404, "Unknown research run id")
    return response
