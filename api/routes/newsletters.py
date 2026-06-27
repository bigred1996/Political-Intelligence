"""Weekly newsletter routes."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_session
from api.models.newsletter import NewsletterIssue
from api.schemas import (
    NewsletterGenerateBody,
    NewsletterGenerateResponse,
    NewsletterIssueResponse,
    NewsletterListResponse,
)
from pipeline.newsletter import NewsletterGenerationError, generate_newsletter_issue, issue_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/newsletters", tags=["newsletters"])
view = APIRouter(tags=["newsletter-view"])


def _summary(issue: NewsletterIssue) -> dict[str, Any]:
    return {
        "id": issue.id,
        "week_start": issue.week_start,
        "week_end": issue.week_end,
        "title": issue.title,
        "status": issue.status,
        "generated_by": issue.generated_by,
        "model": issue.model,
        "word_count": issue.word_count,
        "created_at": issue.created_at.isoformat(),
    }


async def _get(session: AsyncSession, issue_id: str) -> NewsletterIssue:
    issue = (
        await session.execute(select(NewsletterIssue).where(NewsletterIssue.id == issue_id))
    ).scalar_one_or_none()
    if issue is None:
        raise HTTPException(404, "Newsletter issue not found")
    return issue


@router.post("/generate", response_model=NewsletterGenerateResponse)
async def generate(body: NewsletterGenerateBody, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    try:
        issue = await generate_newsletter_issue(session, week_start=body.week_start, week_end=body.week_end)
    except NewsletterGenerationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — surface the cause instead of a bare 500
        logger.exception("newsletter generation failed")
        raise HTTPException(status_code=500, detail=f"newsletter generation failed: {exc}") from exc
    return issue_response(issue)


@router.get("", response_model=NewsletterListResponse)
async def list_issues(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    rows = (
        await session.execute(select(NewsletterIssue).order_by(NewsletterIssue.created_at.desc()))
    ).scalars().all()
    return {"count": len(rows), "issues": [_summary(row) for row in rows]}


@router.get("/{issue_id}", response_model=NewsletterIssueResponse)
async def get_issue(issue_id: str, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    return issue_response(await _get(session, issue_id))


@view.get("/newsletter/{issue_id}", response_class=HTMLResponse)
async def newsletter_page(issue_id: str, session: AsyncSession = Depends(get_session)) -> HTMLResponse:
    issue = await _get(session, issue_id)
    return HTMLResponse(issue.html or "<p>Newsletter HTML unavailable.</p>")
