"""Report routes — run the pipeline, analyst review/approve, customer view, PDF."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..models.report import Report
from pipeline.orchestrator import generate_report
from pipeline.report_builder import SECTION_ORDER, SECTION_TITLES
from .report_view import render_report_html

router = APIRouter(prefix="/api/reports", tags=["reports"])
view = APIRouter(tags=["report-view"])


class GenerateBody(BaseModel):
    company_name: str
    sector: str | None = None
    report_type: str = "deal_due_diligence"
    time_horizon: str = "current"
    request_id: str | None = None


class EditBody(BaseModel):
    sections: dict[str, str] | None = None
    analyst_notes: str | None = None


def _summary(r: Report) -> dict[str, Any]:
    return {
        "id": r.id, "company_name": r.company_name, "report_type": r.report_type,
        "status": r.status, "generated_by": r.generated_by,
        "overall": (r.risk_scores or {}).get("overall"),
        "created_at": r.created_at.isoformat(),
        "approved_at": r.approved_at.isoformat() if r.approved_at else None,
    }


async def _get(session: AsyncSession, report_id: str) -> Report:
    r = (await session.execute(select(Report).where(Report.id == report_id))).scalar_one_or_none()
    if not r:
        raise HTTPException(404, "Report not found")
    return r


@router.post("/generate")
async def generate(body: GenerateBody, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    r = await generate_report(
        session, company=body.company_name.strip(), sector=body.sector,
        report_type=body.report_type, time_horizon=body.time_horizon, request_id=body.request_id,
    )
    return {**_summary(r), "risk_scores": r.risk_scores, "evidence": r.evidence}


@router.get("")
async def list_reports(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    rows = (await session.execute(select(Report).order_by(Report.created_at.desc()))).scalars().all()
    return {"count": len(rows), "reports": [_summary(r) for r in rows]}


@router.get("/{report_id}")
async def get_report(report_id: str, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    r = await _get(session, report_id)
    return {
        **_summary(r), "risk_scores": r.risk_scores, "evidence": r.evidence,
        "analyst_notes": r.analyst_notes,
        "sections": [{"key": k, "title": SECTION_TITLES[k], "html": r.sections.get(k, "")} for k in SECTION_ORDER],
    }


@router.patch("/{report_id}")
async def edit_report(report_id: str, body: EditBody, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    r = await _get(session, report_id)
    if body.sections:
        merged = dict(r.sections or {})
        merged.update(body.sections)
        r.sections = merged
    if body.analyst_notes is not None:
        r.analyst_notes = body.analyst_notes
    await session.commit()
    return _summary(r)


@router.patch("/{report_id}/approve")
async def approve_report(report_id: str, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    r = await _get(session, report_id)
    r.status = "approved"
    r.approved_at = datetime.now(timezone.utc)
    await session.commit()
    return _summary(r)


# ── Customer-facing views ────────────────────────────────────────────────────
@view.get("/report/{report_id}", response_class=HTMLResponse)
async def report_page(report_id: str, session: AsyncSession = Depends(get_session)) -> HTMLResponse:
    r = await _get(session, report_id)
    return HTMLResponse(render_report_html(r))


@view.get("/report/{report_id}/pdf")
async def report_pdf(report_id: str, session: AsyncSession = Depends(get_session)):
    r = await _get(session, report_id)
    html = render_report_html(r, for_pdf=True)
    try:
        from weasyprint import HTML  # heavy; optional
        pdf = HTML(string=html).write_pdf()
        return Response(pdf, media_type="application/pdf",
                        headers={"Content-Disposition": f'inline; filename="polaris-{report_id}.pdf"'})
    except Exception:
        # WeasyPrint not installed (needs system libs) — serve print-ready HTML instead.
        return HTMLResponse(html)
