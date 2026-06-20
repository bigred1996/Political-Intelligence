"""Unified search API — natural-language hybrid search + index management."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..routes.sources import get_sources_status
from ..schemas import SearchIndexStatusResponse, SearchReindexResponse, SearchResponse, SearchSourcesResponse

router = APIRouter(prefix="/api/search", tags=["search"])


class SearchQuery(BaseModel):
    q: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=40, ge=1, le=100)
    answer: bool = True


@router.post("", response_model=SearchResponse)
async def run_search(body: SearchQuery, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Natural-language hybrid search across every data source."""
    from search.engine import search
    return await search(session, body.q, limit=body.limit, answer=body.answer)


@router.get("", response_model=SearchResponse)
async def run_search_get(
    q: str = Query(..., min_length=1, max_length=500, description="Natural-language query"),
    limit: int = Query(default=40, ge=1, le=100),
    answer: bool = True,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    from search.engine import search
    return await search(session, q, limit=limit, answer=answer)


@router.post("/reindex", response_model=SearchReindexResponse)
async def reindex(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """(Re)build the semantic vector index from the current DB contents."""
    from search.index import build_index
    return await build_index(session)


@router.get("/index/status", response_model=SearchIndexStatusResponse)
async def index_status() -> dict[str, Any]:
    from search.index import index_status as _status
    return _status()


@router.get("/sources", response_model=SearchSourcesResponse)
async def search_sources(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Row counts for every searchable source — proves coverage at a glance."""
    status = await get_sources_status(session)
    mapped = {
        "lobbying_communications": "lobbying",
        "gazette_entries": "gazette",
        "tribunal_decisions": "tribunal",
    }
    out: dict[str, int] = {}
    approximate_sources: list[str] = []
    row_count_methods: dict[str, str] = {}
    for item in status.get("sources", []):
        if not item.get("table"):
            continue
        key = mapped.get(item["id"], item["id"])
        out[key] = int(item.get("rows") or 0)
        row_count_methods[key] = item.get("row_count_method") or "exact"
        if item.get("approximate"):
            approximate_sources.append(key)
    for src in status.get("breadth_sources", []):
        out[src["source"]] = int(src.get("rows") or 0)
        row_count_methods[src["source"]] = "exact"
    return {
        "sources": out,
        "total_records": sum(out.values()),
        "approximate_sources": approximate_sources,
        "row_count_methods": row_count_methods,
    }
