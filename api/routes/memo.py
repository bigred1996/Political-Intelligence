"""Goal B6 — branded PDF memo routes: JSON data, HTML view, PDF export.

Pure consumer of B4 (`pipeline.diligence`) via `pipeline.memo_builder`. No
route here computes anything — `get_memo_response` already re-validated every
citation against the run's retrieval sets before this module ever sees it.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from pipeline.memo_builder import get_memo_response
from pipeline.memo_render import render_memo_html

router = APIRouter(prefix="/api/memo", tags=["memo"])
view = APIRouter(tags=["memo-view"])


async def _get(session: AsyncSession, review_id: str) -> dict[str, Any]:
    memo = await get_memo_response(session, review_id)
    if memo is None:
        raise HTTPException(404, "Unknown review id")
    return memo


@router.get("/{review_id}")
async def get_memo(review_id: str, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    return await _get(session, review_id)


@view.get("/memo/{review_id}", response_class=HTMLResponse)
async def memo_page(review_id: str, session: AsyncSession = Depends(get_session)) -> HTMLResponse:
    memo = await _get(session, review_id)
    return HTMLResponse(render_memo_html(memo))


@view.get("/memo/{review_id}/pdf")
async def memo_pdf(review_id: str, session: AsyncSession = Depends(get_session)):
    memo = await _get(session, review_id)
    html = render_memo_html(memo, for_pdf=True)
    try:
        from weasyprint import HTML  # heavy; optional

        pdf = HTML(string=html).write_pdf()
        return Response(
            pdf, media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="nessus-memo-{review_id}.pdf"'},
        )
    except Exception:
        # WeasyPrint not installed (needs system libs) — serve print-ready HTML instead.
        return HTMLResponse(html)
