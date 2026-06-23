"""Internal-records retrieval API — natural-language query in, ranked internal
records out, grouped by type. No AI/provider logic lives here: deterministic
SQL filters plus the local embedding model only (see `search/retrieval.py`).

Every call persists its retrieval set (`pipeline/citation_registry.py`) so a
later AI-interpretation layer can validate any citation against exactly what
was returned here, never against records it merely guessed at.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..schemas import CitationValidationResponse, RetrievalResponse
from pipeline.citation_registry import save_retrieval_set, validate_citations_for_set
from search.retrieval import retrieve

router = APIRouter(prefix="/api/retrieve", tags=["retrieval"])


class RetrieveBody(BaseModel):
    q: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=40, ge=1, le=100)


async def _run(session: AsyncSession, q: str, limit: int) -> dict[str, Any]:
    result = await retrieve(session, q, limit=limit)
    saved = await save_retrieval_set(
        session, q, result["results"],
        planner=result["plan"].get("planner", "fallback"),
        embedding_model=result["embedding_model"],
    )
    return {**result, "retrieval_set_id": saved.id, "generated_at": saved.created_at.isoformat()}


@router.post("", response_model=RetrievalResponse)
async def retrieve_post(body: RetrieveBody, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    return await _run(session, body.q, body.limit)


@router.get("", response_model=RetrievalResponse)
async def retrieve_get(
    q: str = Query(..., min_length=1, max_length=500, description="Natural-language query"),
    limit: int = Query(default=40, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await _run(session, q, limit)


class ValidateCitationsBody(BaseModel):
    retrieval_set_id: str = Field(min_length=1)
    cited: list[list[Any]] = Field(default_factory=list, description="[[table, pk], ...]")


@router.post("/validate-citations", response_model=CitationValidationResponse)
async def validate_citations_route(
    body: ValidateCitationsBody, session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    cited = [(c[0], c[1]) for c in body.cited]
    result = await validate_citations_for_set(session, body.retrieval_set_id, cited)
    return {
        "retrieval_set_id": body.retrieval_set_id,
        "all_valid": result["all_valid"],
        "valid": [{"table": t, "pk": p} for t, p in result["valid"]],
        "invalid": [{"table": t, "pk": p} for t, p in result["invalid"]],
    }
