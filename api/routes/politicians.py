"""Politicians & political players — directory + full profile.

Every federal MP (seeded from openparliament, enriched with photo/role/contact)
is a first-class page: a directory with photos and summaries, and a profile that
reads their activity through the *industry* lens — which sectors they touch via
sponsored bills and House interventions, plus the records connected to them.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..models.politician import HansardMention, Politician
from pipeline.sector_mapper import SECTORS

router = APIRouter(prefix="/api/politicians", tags=["politicians"])


def _card(p: Politician) -> dict[str, Any]:
    return {
        "slug": p.slug, "name": p.name, "party": p.party, "riding": p.riding,
        "province": p.province, "role": p.role, "photo_url": p.photo_url,
    }


def _industries_from(texts: list[str]) -> list[dict[str, str]]:
    """Which tracked sectors these texts (bill titles, speech keywords) touch."""
    blob = " ".join(t.lower() for t in texts if t)
    out = []
    for s in SECTORS.values():
        if any(kw in blob for kw in s.keywords):
            out.append({"slug": s.slug, "name": s.name})
    return out


@router.get("")
async def list_politicians(
    q: str | None = None, party: str | None = None, province: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    stmt = select(Politician)
    if q:
        stmt = stmt.where(or_(Politician.name.ilike(f"%{q}%"), Politician.riding.ilike(f"%{q}%")))
    if party:
        stmt = stmt.where(Politician.party == party)
    if province:
        stmt = stmt.where(Politician.province == province)
    stmt = stmt.order_by(Politician.name)
    rows = (await session.execute(stmt)).scalars().all()

    # Facets for filter chips.
    parties = (await session.execute(
        select(Politician.party, func.count()).group_by(Politician.party).order_by(func.count().desc())
    )).all()
    provinces = (await session.execute(
        select(Politician.province, func.count()).where(Politician.province.is_not(None))
        .group_by(Politician.province).order_by(Politician.province)
    )).all()

    return {
        "count": len(rows),
        "politicians": [_card(p) for p in rows],
        "parties": [{"party": p or "Unknown", "count": n} for p, n in parties if p],
        "provinces": [{"province": pv, "count": n} for pv, n in provinces],
    }


@router.get("/{slug}")
async def get_politician(slug: str, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    p = (await session.execute(
        select(Politician).where(Politician.slug == slug))).scalar_one_or_none()
    if p is None:
        raise HTTPException(404, f"No politician '{slug}'")

    name = p.name
    # Their House interventions (speaker carries prefixes like "Mr."/"Hon.", so substring match).
    speeches = (await session.execute(
        select(HansardMention).where(HansardMention.speaker.ilike(f"%{name}%"))
        .order_by(HansardMention.speech_date.desc()).limit(25)
    )).scalars().all()

    # Bills they sponsored (best-effort name match).
    from api.models.donation import Bill
    bills = (await session.execute(
        select(Bill).where(Bill.sponsor.ilike(f"%{name}%"))
        .order_by(Bill.introduced_date.desc()).limit(25)
    )).scalars().all()

    industries = _industries_from(
        [s.keyword for s in speeches] + [b.title_en for b in bills]
    )

    # Composed plain-language summary from structured facts.
    bits = [f"{name} is the {p.role or 'a federal politician'}"]
    if p.riding:
        bits.append(f"representing {p.riding}{', ' + p.province if p.province else ''}")
    if p.since_date:
        bits.append(f"in office since {p.since_date}")
    summary = ", ".join(bits) + "."
    activity = []
    if bills:
        activity.append(f"sponsored {len(bills)} tracked bill(s)")
    if speeches:
        activity.append(f"recorded on {len(speeches)} House intervention(s) touching tracked sectors")
    if industries:
        activity.append("active across " + ", ".join(i["name"] for i in industries))
    if activity:
        summary += " They have " + "; ".join(activity) + "."

    return {
        "slug": p.slug, "name": p.name, "party": p.party, "riding": p.riding,
        "province": p.province, "role": p.role, "photo_url": p.photo_url,
        "email": p.email, "since_date": p.since_date, "commons_url": p.commons_url,
        "openparliament_url": (f"https://openparliament.ca{p.url}" if p.url and p.url.startswith("/") else p.url),
        "summary": summary,
        "industries": industries,
        "bills": [{
            "table": "bills", "pk": b.id, "bill_number": b.bill_number,
            "title": b.title_en, "status": b.status, "date": b.introduced_date,
        } for b in bills],
        "speeches": [{
            "keyword": s.keyword, "date": s.speech_date, "excerpt": s.excerpt,
            "url": s.speech_url,
        } for s in speeches],
    }
