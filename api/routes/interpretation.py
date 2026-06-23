"""AI interpretation layer (Goal B2) — turns ONE retrieved finding into a
structured, citation-safe interpretation. Strictly downstream of /api/retrieve:
every call must name a real `retrieval_set_id`, and the `(table, pk)` finding
must be a member of that exact retrieval set. No multi-step research, no
report assembly — see `pipeline/interpretation.py` for the full contract.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..schemas import InterpretationResponse
from pipeline.interpretation import (
    FindingNotRetrievedError,
    UnknownRetrievalSetError,
    get_interpretation_response,
    interpret_finding,
)

router = APIRouter(prefix="/api/interpret", tags=["interpretation"])


class InterpretBody(BaseModel):
    retrieval_set_id: str = Field(min_length=1)
    table: str = Field(min_length=1)
    pk: int | str
    force_refresh: bool = False


@router.post("", response_model=InterpretationResponse)
async def interpret(body: InterpretBody, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    try:
        return await interpret_finding(
            session, body.retrieval_set_id, body.table, body.pk, force_refresh=body.force_refresh,
        )
    except UnknownRetrievalSetError:
        raise HTTPException(404, f"Unknown retrieval set: {body.retrieval_set_id}")
    except FindingNotRetrievedError as exc:
        raise HTTPException(400, str(exc))


@router.get("/{interpretation_id}", response_model=InterpretationResponse)
async def get_one(interpretation_id: str, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    response = await get_interpretation_response(session, interpretation_id)
    if response is None:
        raise HTTPException(404, "Unknown interpretation id")
    return response
