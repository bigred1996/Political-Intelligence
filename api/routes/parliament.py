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

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import String, cast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..models.donation import Bill
from ..models.entity import LobbyingRecord
from ..models.politician import HansardMention, Politician
from ..models.source_record import SourceRecord
from ..schemas import CommitteeProfileResponse, EvidenceReference, ParliamentListResponse, ParliamentSeedResponse, SpeechSearchResponse
from pipeline.entity_resolver import normalize
from pipeline.evidence_graph import build_global_findings, resolve_politician, sectors_for_text
from scrapers.hansard import OpenParliamentClient

router = APIRouter(prefix="/api/parliament", tags=["parliament"])

_COMMON_COMMITTEES = {
    "indu": "Standing Committee on Industry and Technology",
    "fina": "Standing Committee on Finance",
    "envi": "Standing Committee on Environment and Sustainable Development",
    "heth": "Standing Committee on Health",
    "tran": "Standing Committee on Transport, Infrastructure and Communities",
    "rnnr": "Standing Committee on Natural Resources",
    "agri": "Standing Committee on Agriculture and Agri-Food",
    "oggo": "Standing Committee on Government Operations and Estimates",
    "ethi": "Standing Committee on Access to Information, Privacy and Ethics",
}


def _committee_name(slug: str) -> str:
    clean = slug.lower().replace("-", " ").strip()
    return _COMMON_COMMITTEES.get(clean, clean.upper() if len(clean) <= 6 else clean.title())


def _committee_terms(slug: str, name: str) -> list[str]:
    cleaned_slug = slug.lower().replace("-", " ").strip()
    terms = {slug, cleaned_slug, name, "committee"}
    if len(cleaned_slug) <= 8:
        terms.add(cleaned_slug.upper())
    return [term for term in terms if term]


def _eref(table: str, pk: int, source: str, title: str, date: str | None = None, url: str | None = None, record_type: str = "record") -> dict[str, Any]:
    return EvidenceReference.model_validate({
        "table": table, "pk": pk, "id": pk, "source": source, "title": title,
        "date": date, "url": url, "record_type": record_type,
    }).model_dump()


def _ilike_any(columns: list[Any], terms: list[str]):
    return or_(*[column.ilike(f"%{term}%") for column in columns for term in terms])


def _sort_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(refs, key=lambda ref: str(ref.get("date") or ""), reverse=True)



@router.post("/seed-politicians", response_model=ParliamentSeedResponse)
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
    keyword: str = Field(min_length=1, max_length=255)
    canonical_name: str | None = Field(default=None, max_length=255)
    limit: int = Field(default=20, ge=1, le=100)


@router.post("/search-speeches", response_model=SpeechSearchResponse)
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


@router.get("/politicians", response_model=ParliamentListResponse)
async def list_politicians(
    party: str | None = Query(default=None, max_length=120),
    province: str | None = Query(default=None, min_length=2, max_length=2),
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




@router.get("/committee/{slug}", response_model=CommitteeProfileResponse)
async def committee_profile(slug: str, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    name = _committee_name(slug)
    terms = _committee_terms(slug, name)

    hansard_rows = (await session.execute(
        select(HansardMention)
        .where(_ilike_any([HansardMention.keyword, HansardMention.excerpt, HansardMention.speaker], terms))
        .order_by(HansardMention.speech_date.desc())
        .limit(8)
    )).scalars().all()
    bill_rows = (await session.execute(
        select(Bill)
        .where(_ilike_any([Bill.title_en, Bill.status, Bill.latest_activity, Bill.sponsor], terms))
        .order_by(Bill.introduced_date.desc())
        .limit(8)
    )).scalars().all()
    lobbying_rows = (await session.execute(
        select(LobbyingRecord)
        .where(_ilike_any([cast(LobbyingRecord.institutions, String), cast(LobbyingRecord.subject_matters, String), LobbyingRecord.client], terms))
        .order_by(LobbyingRecord.communication_date.desc())
        .limit(8)
    )).scalars().all()
    source_rows = (await session.execute(
        select(SourceRecord)
        .where(_ilike_any([SourceRecord.title, SourceRecord.summary, SourceRecord.full_text], terms))
        .order_by(SourceRecord.event_date.desc())
        .limit(8)
    )).scalars().all()

    groups = [
        {"table": "hansard_mentions", "label": "House interventions", "count": len(hansard_rows), "records": [
            _eref("hansard_mentions", row.id, row.source, f"{row.speaker or 'House intervention'} — {row.keyword}", row.speech_date, row.speech_url, "hansard_mention") for row in hansard_rows
        ], "partial": False},
        {"table": "bills", "label": "Bills and legislation", "count": len(bill_rows), "records": [
            _eref("bills", row.id, row.source, f"{row.bill_number} — {(row.title_en or '')[:90]}", row.introduced_date, None, "bill") for row in bill_rows
        ], "partial": False},
        {"table": "lobbying", "label": "Lobbying communications", "count": len(lobbying_rows), "records": [
            _eref("lobbying", row.id, row.source, f"{row.client} lobbied around {name}", row.communication_date, None, "lobbying_communication") for row in lobbying_rows
        ], "partial": False},
        {"table": "source_records", "label": "Source records", "count": len(source_rows), "records": [
            _eref("source_records", row.id, row.source, row.title, row.event_date, row.url, row.record_type or "source_record") for row in source_rows
        ], "partial": False},
    ]
    groups = [group for group in groups if group["records"]]
    connected_records = _sort_refs([record for group in groups for record in group["records"]])
    evidence_text = " ".join(record["title"] for record in connected_records[:12])
    affected_sectors = sectors_for_text(f"{name} {evidence_text}", limit=4)

    findings = []
    for finding in await build_global_findings(session):
        haystack = f"{finding.get('title', '')} {finding.get('summary', '')}"
        if any(term.lower() in haystack.lower() for term in terms):
            findings.append({**finding, "relationship_strength": "supported"})
        if len(findings) >= 4:
            break

    people = []
    seen_people = set()
    for row in hansard_rows:
        actor = await resolve_politician(session, row.speaker)
        if actor and actor.get("name") not in seen_people:
            seen_people.add(actor.get("name"))
            people.append({**actor, "relationship": "person mentioned committee", "strength": "supported"})

    return {
        "slug": slug,
        "name": name,
        "chamber": "House of Commons",
        "summary": f"Nessus found {len(connected_records)} internal records connected to {name}.",
        "why_it_matters": "Committees shape amendments, witness testimony, studies, and political pressure before policy becomes binding law or regulatory action.",
        "affected_sectors": affected_sectors,
        "related_findings": findings,
        "connected_people": people,
        "connected_organizations": [],
        "connected_records": connected_records[:24],
        "groups": groups,
        "timeline": connected_records[:12],
    }


@router.get("/committees", response_model=ParliamentListResponse)
async def list_committees() -> dict[str, Any]:
    """Live committee list from openparliament.ca."""
    async with OpenParliamentClient() as client:
        committees = await client.get_committees()
    return {"count": len(committees), "committees": committees}


@router.get("/votes", response_model=ParliamentListResponse)
async def recent_votes(limit: int = Query(default=50, ge=1, le=100)) -> dict[str, Any]:
    """Recent House divisions from openparliament.ca."""
    async with OpenParliamentClient() as client:
        votes = await client.get_votes(limit=limit)
    return {"count": len(votes), "votes": votes}
