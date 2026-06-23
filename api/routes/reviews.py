"""Goal B4 — Start-Diligence form + persistent workspace routes.

POST creates one Review and launches exactly one B3 run at the chosen depth
tier (the form's single source of truth for tier); GET rehydrates the same
review + run + workspace projection with no model calls. One Review = one run =
one workspace, revisitable by id.
"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from pipeline.diligence import create_review, get_review_response, list_reviews

router = APIRouter(prefix="/api/reviews", tags=["reviews"])


class ReviewBody(BaseModel):
    company: str = Field(min_length=1, max_length=300)
    sectors: list[str] = Field(default_factory=list)
    transaction_type: str | None = Field(default=None, max_length=64)
    jurisdiction: str | None = Field(default=None, max_length=64)
    date_from: str | None = Field(default=None, max_length=16)
    date_to: str | None = Field(default=None, max_length=16)
    key_concerns: str | None = Field(default=None, max_length=2000)
    keywords: list[str] = Field(default_factory=list)
    research_question: str | None = Field(default=None, max_length=500)
    depth_tier: Literal["brief", "standard", "deep"] = "standard"


@router.post("")
async def start_review(body: ReviewBody, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    return await create_review(session, body.model_dump())


@router.get("")
async def list_runs(
    limit: int = Query(default=50, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return {"reviews": await list_reviews(session, limit)}


@router.get("/{review_id}")
async def get_review_workspace(review_id: str, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    response = await get_review_response(session, review_id)
    if response is None:
        raise HTTPException(404, "Unknown review id")
    return response
