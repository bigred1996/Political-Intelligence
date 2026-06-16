"""Unified search API — natural-language hybrid search + index management."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session

router = APIRouter(prefix="/api/search", tags=["search"])


class SearchQuery(BaseModel):
    q: str
    limit: int = 40
    answer: bool = True


@router.post("")
async def run_search(body: SearchQuery, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Natural-language hybrid search across every data source."""
    from search.engine import search
    return await search(session, body.q, limit=body.limit, answer=body.answer)


@router.get("")
async def run_search_get(
    q: str = Query(..., description="Natural-language query"),
    limit: int = 40,
    answer: bool = True,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    from search.engine import search
    return await search(session, q, limit=limit, answer=answer)


@router.post("/reindex")
async def reindex(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """(Re)build the semantic vector index from the current DB contents."""
    from search.index import build_index
    return await build_index(session)


@router.get("/index/status")
async def index_status() -> dict[str, Any]:
    from search.index import index_status as _status
    return _status()


@router.get("/sources")
async def search_sources(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Row counts for every searchable source — proves coverage at a glance."""
    from ..models.source_record import SourceRecord
    from search.sql_search import SPECS, _import_model

    out: dict[str, int] = {}
    for spec in SPECS:
        if spec.source == "source_records":
            continue
        model = _import_model(spec.model_path)
        out[spec.source] = (await session.execute(select(func.count(model.id)))).scalar_one()
    # Break out the breadth sources inside source_records
    res = await session.execute(
        select(SourceRecord.source, func.count(SourceRecord.id)).group_by(SourceRecord.source)
    )
    for src, n in res.all():
        out[src] = n
    return {"sources": out, "total_records": sum(out.values())}
