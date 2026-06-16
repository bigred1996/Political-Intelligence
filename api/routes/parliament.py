"""Parliament routes — openparliament.ca data: MPs, speeches, votes.

POST /api/parliament/seed-politicians  → pull all MPs from openparliament.ca → DB
POST /api/parliament/search-speeches   → search Hansard by keyword → DB + return
GET  /api/parliament/politicians       → list stored politicians
GET  /api/parliament/committees        → live committee list from openparliament.ca
GET  /api/parliament/votes             → recent House votes
"""
from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..models.politician import HansardMention, Politician
from pipeline.entity_resolver import normalize
from scrapers.hansard import OpenParliamentClient

router = APIRouter(prefix="/api/parliament", tags=["parliament"])


@router.post("/seed-politicians")
async def seed_politicians(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Pull all current MPs from openparliament.ca and upsert into the DB."""
    async with OpenParliamentClient() as client:
        politicians = await client.get_politicians()

    inserted = 0
    for p in politicians:
        if not p.get("slug"):
            continue
        existing = await session.execute(
            select(Politician).where(Politician.slug == p["slug"])
        )
        row = existing.scalar_one_or_none()
        if row is None:
            session.add(
                Politician(
                    slug=p["slug"],
                    name=p["name"],
                    party=p.get("party"),
                    riding=p.get("riding"),
                    province=p.get("province"),
                    url=p.get("url"),
                )
            )
            inserted += 1
        else:
            row.party = p.get("party")
            row.riding = p.get("riding")
            row.province = p.get("province")

    await session.commit()
    return {"seeded": len(politicians), "new": inserted}


class SpeechSearchRequest(BaseModel):
    keyword: str
    canonical_name: str | None = None
    limit: int = 20


@router.post("/search-speeches")
async def search_speeches(
    body: SpeechSearchRequest, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """Search Hansard for speeches mentioning a keyword; persist and return results."""
    canonical = body.canonical_name or normalize(body.keyword)
    async with OpenParliamentClient() as client:
        speeches = await client.search_speeches(body.keyword, limit=body.limit)

    for s in speeches:
        session.add(
            HansardMention(
                canonical_name=canonical,
                keyword=body.keyword,
                speech_date=s.get("date"),
                speaker=s.get("speaker"),
                excerpt=s.get("excerpt"),
                speech_url=s.get("url"),
            )
        )
    await session.commit()

    return {
        "keyword": body.keyword,
        "canonical_name": canonical,
        "count": len(speeches),
        "speeches": speeches,
    }


@router.get("/politicians")
async def list_politicians(
    party: str | None = None,
    province: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    q = select(Politician).order_by(Politician.name)
    if party:
        q = q.where(Politician.party.ilike(f"%{party}%"))
    if province:
        q = q.where(Politician.province == province.upper())
    result = await session.execute(q)
    politicians = result.scalars().all()
    return {
        "count": len(politicians),
        "politicians": [
            {
                "name": p.name,
                "party": p.party,
                "riding": p.riding,
                "province": p.province,
                "slug": p.slug,
            }
            for p in politicians
        ],
    }


@router.get("/committees")
async def list_committees() -> dict[str, Any]:
    """Live committee list from openparliament.ca."""
    async with OpenParliamentClient() as client:
        committees = await client.get_committees()
    return {"count": len(committees), "committees": committees}


@router.get("/votes")
async def recent_votes(limit: int = 50) -> dict[str, Any]:
    """Recent House divisions from openparliament.ca."""
    async with OpenParliamentClient() as client:
        votes = await client.get_votes(limit=limit)
    return {"count": len(votes), "votes": votes}
