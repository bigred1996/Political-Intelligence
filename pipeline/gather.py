"""Gather all source evidence for a company into one structured bundle.

Reads the ingested DB tables (contracts, donations, bills) + the lobbying store,
keyed by canonical entity. This bundle is what the risk scorer and report builder
consume — the single cross-source view the entity-resolution moat enables.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.appointment import Appointment
from api.models.contract import Contract
from api.models.donation import Bill, Donation
from api.models.entity import LobbyingRecord
from api.models.grant import Grant
from api.models.ocl_registration import OCLRegistration
from api.models.politician import HansardMention, Politician
from api.models.regulation import GazetteEntry, TribunalDecision
from pipeline.entity_resolver import normalize
from scrapers.ocl import OCLScraper

# Fallback stakeholder seed when no Hansard data is available.
_STAKEHOLDER_SEED = [
    {"name": "Minister of Innovation, Science and Industry", "role": "Portfolio minister", "position": "neutral"},
    {"name": "Standing Committee on Industry and Technology (INDU)", "role": "Committee jurisdiction", "position": "neutral"},
]


async def _lobbying(session: AsyncSession, company: str, canonical: str) -> list[dict[str, Any]]:
    # Query DB: exact canonical match OR raw client partial match (catches aliases).
    # We use exact canonical match (not LIKE) to avoid short canonicals like "bce"
    # matching unrelated names like "AbCellera".
    res = await session.execute(
        select(LobbyingRecord)
        .where(
            or_(
                LobbyingRecord.canonical_name == canonical,
                LobbyingRecord.client.ilike(f"%{company}%"),
            )
        )
        .order_by(LobbyingRecord.communication_date.desc())
        .limit(200)
    )
    rows = res.scalars().all()
    if rows:
        return [
            {
                "registration_id": r.registration_id,
                "client": r.client,
                "registrant": r.registrant,
                "subject_matters": r.subject_matters,
                "institutions": r.institutions,
                "communication_date": r.communication_date,
                "type": r.type,
                "dpoh_contacts": (r.raw or {}).get("dpoh_contacts", []),
            }
            for r in rows
        ]

    # Fallback: run the OCL sample scraper on demand (pre-ingest path).
    async with OCLScraper() as s:
        records = await s.search(company)
    for r in records:
        session.add(
            LobbyingRecord(
                company_query=company,
                canonical_name=canonical,
                registration_id=r.get("registration_id", ""),
                client=r.get("client", ""),
                registrant=r.get("registrant", ""),
                subject_matters=r.get("subject_matters", []),
                institutions=r.get("institutions", []),
                communication_date=r.get("communication_date"),
                type=r.get("type"),
                source=r.get("source", "OCL Lobbying Registry"),
                raw=r,
            )
        )
    await session.commit()
    return records


async def _stakeholders(
    session: AsyncSession, company: str, canonical: str, sector: str | None
) -> list[dict[str, Any]]:
    """Build stakeholder list from stored Hansard mentions + politician DB."""
    keywords = [canonical] + ([normalize(sector)] if sector else [])
    stakeholders: list[dict[str, Any]] = []

    for kw in keywords:
        res = await session.execute(
            select(HansardMention)
            .where(HansardMention.canonical_name.like(f"%{kw}%"))
            .order_by(HansardMention.speech_date.desc())
            .limit(10)
        )
        for m in res.scalars().all():
            if m.speaker:
                stakeholders.append(
                    {
                        "name": m.speaker,
                        "role": "MP (Hansard mention)",
                        "position": "neutral",
                        "date": m.speech_date,
                        "excerpt": m.excerpt,
                    }
                )

    # Deduplicate by name
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for s in stakeholders:
        if s["name"] not in seen:
            seen.add(s["name"])
            unique.append(s)

    if not unique:
        return _STAKEHOLDER_SEED

    return unique[:15]


async def _grants(session: AsyncSession, company: str, canonical: str) -> list[dict[str, Any]]:
    res = await session.execute(
        select(Grant)
        .where(or_(Grant.canonical_name == canonical, Grant.recipient_name.ilike(f"%{company}%")))
        .order_by(Grant.agreement_value.desc())
        .limit(50)
    )
    return [
        {
            "recipient_name": r.recipient_name,
            "owner_org_title": r.owner_org_title,
            "program_name": r.program_name,
            "agreement_type": r.agreement_type,
            "agreement_value": r.agreement_value,
            "agreement_start": r.agreement_start,
        }
        for r in res.scalars().all()
    ]


async def _regulations(session: AsyncSession, company: str, sector: str | None) -> list[dict[str, Any]]:
    keywords = [company] + ([sector] if sector else [])
    filters = [
        or_(
            GazetteEntry.title.ilike(f"%{kw}%"),
            GazetteEntry.description.ilike(f"%{kw}%"),
            GazetteEntry.department.ilike(f"%{kw}%"),
        )
        for kw in keywords
    ]
    combined = or_(*filters) if filters else None
    q = select(GazetteEntry).order_by(GazetteEntry.published_date.desc()).limit(20)
    if combined is not None:
        q = q.where(combined)
    res = await session.execute(q)
    return [
        {
            "gazette_part": r.gazette_part,
            "title": r.title,
            "published_date": r.published_date,
            "department": r.department,
            "regulation_id": r.regulation_id,
            "url": r.url,
        }
        for r in res.scalars().all()
    ]


async def _tribunal_decisions(session: AsyncSession, company: str, sector: str | None) -> list[dict[str, Any]]:
    keywords = [company] + ([sector] if sector else [])
    filters = [
        or_(
            TribunalDecision.title.ilike(f"%{kw}%"),
            TribunalDecision.summary.ilike(f"%{kw}%"),
            TribunalDecision.parties.ilike(f"%{kw}%"),
        )
        for kw in keywords
    ]
    combined = or_(*filters) if filters else None
    q = select(TribunalDecision).order_by(TribunalDecision.decision_date.desc()).limit(20)
    if combined is not None:
        q = q.where(combined)
    res = await session.execute(q)
    return [
        {
            "body": r.body,
            "decision_number": r.decision_number,
            "title": r.title,
            "decision_date": r.decision_date,
            "outcome": r.outcome,
            "summary": r.summary,
            "url": r.url,
        }
        for r in res.scalars().all()
    ]


async def _appointments(session: AsyncSession, sector: str | None) -> list[dict[str, Any]]:
    """Return recent GIC appointments to regulatory bodies relevant to sector."""
    regulatory_orgs = [
        "CRTC", "Competition Bureau", "NEB", "CER", "OSFI",
        "Health Canada", "Treasury Board", "Bank of Canada",
    ]
    if sector:
        # Add sector-specific orgs if recognizable
        sector_lower = sector.lower()
        if any(t in sector_lower for t in ("telecom", "broadcast", "media")):
            regulatory_orgs += ["Canadian Radio-television"]
        if any(t in sector_lower for t in ("energy", "pipeline", "oil", "gas")):
            regulatory_orgs += ["National Energy Board", "Canada Energy Regulator"]

    filters = [Appointment.organization.ilike(f"%{org}%") for org in regulatory_orgs]
    res = await session.execute(
        select(Appointment)
        .where(or_(*filters))
        .order_by(Appointment.appointment_date.desc())
        .limit(20)
    )
    return [
        {
            "appointee_name": r.appointee_name,
            "position_title": r.position_title,
            "organization": r.organization,
            "appointment_date": r.appointment_date,
            "appointment_type": r.appointment_type,
        }
        for r in res.scalars().all()
    ]


async def _ocl_registrations(session: AsyncSession, company: str, canonical: str) -> list[dict[str, Any]]:
    res = await session.execute(
        select(OCLRegistration)
        .where(or_(OCLRegistration.canonical_name == canonical, OCLRegistration.client_org.ilike(f"%{company}%")))
        .order_by(OCLRegistration.effective_date.desc())
        .limit(20)
    )
    return [
        {
            "registration_num": r.registration_num,
            "registrant_name": r.registrant_name,
            "firm_name": r.firm_name,
            "registration_type": r.registration_type,
            "status": r.status,
            "effective_date": r.effective_date,
            "subject_matters": r.subject_matters,
            "federal_benefits": r.federal_benefits,
        }
        for r in res.scalars().all()
    ]


async def gather_company_data(
    session: AsyncSession, company: str, sector: str | None, report_type: str
) -> dict[str, Any]:
    canonical = normalize(company)

    # Build a WHERE clause that uses exact canonical match (avoids short-string false
    # positives) but also tries vendor_name/client partial match as a fallback.
    def _contract_filter(col_canonical, col_raw):
        return or_(col_canonical == canonical, col_raw.ilike(f"%{company}%"))

    # Contracts
    cf = _contract_filter(Contract.canonical_name, Contract.vendor_name)
    cres = await session.execute(
        select(Contract).where(cf)
        .order_by(Contract.contract_value.desc()).limit(100)
    )
    contracts = cres.scalars().all()
    contracts_total = (
        await session.execute(
            select(func.coalesce(func.sum(Contract.contract_value), 0.0)).where(cf)
        )
    ).scalar_one()
    dept_rows = await session.execute(
        select(Contract.owner_org_title, func.sum(Contract.contract_value), func.count(Contract.id))
        .where(cf)
        .group_by(Contract.owner_org_title).order_by(func.sum(Contract.contract_value).desc()).limit(6)
    )

    # Donations (by contributor name match)
    df = _contract_filter(Donation.canonical_name, Donation.contributor_name)
    dres = await session.execute(
        select(Donation).where(df).order_by(Donation.amount.desc()).limit(50)
    )
    donations = dres.scalars().all()

    # Bills relevant by sector/company keyword
    keywords = [t for t in (normalize(sector or "") + " " + canonical).split() if len(t) > 3]
    bill_filter = or_(*[Bill.title_en.ilike(f"%{k}%") for k in keywords]) if keywords else None
    bquery = select(Bill)
    if bill_filter is not None:
        bquery = bquery.where(bill_filter)
    bills = (await session.execute(bquery.limit(15))).scalars().all()

    # Lobbying
    lobbying = await _lobbying(session, company, canonical)

    # New sources
    grants = await _grants(session, company, canonical)
    regulations = await _regulations(session, company, sector)
    tribunal = await _tribunal_decisions(session, company, sector)
    appointments = await _appointments(session, sector)
    ocl_regs = await _ocl_registrations(session, company, canonical)

    return {
        "company": company,
        "canonical": canonical,
        "sector": sector,
        "report_type": report_type,
        "lobbying": {
            "count": len(lobbying),
            "records": lobbying,
            "registrants": sorted({r.get("registrant", "") for r in lobbying if r.get("registrant")}),
            "institutions": sorted({i for r in lobbying for i in (r.get("institutions") or [])}),
        },
        "ocl_registrations": {
            "count": len(ocl_regs),
            "records": ocl_regs,
            "active": [r for r in ocl_regs if (r.get("status") or "").lower() == "active"],
        },
        "contracts": {
            "count": len(contracts),
            "total_value": round(contracts_total or 0, 2),
            "by_department": [
                {"dept": d[0], "value": round(d[1] or 0, 2), "count": d[2]} for d in dept_rows
            ],
            "records": [
                {"vendor_name": c.vendor_name, "description": c.description,
                 "contract_value": c.contract_value, "owner_org_title": c.owner_org_title,
                 "contract_date": c.contract_date}
                for c in contracts[:25]
            ],
        },
        "grants": {
            "count": len(grants),
            "total_value": round(sum(r.get("agreement_value") or 0 for r in grants), 2),
            "records": grants[:25],
        },
        "donations": {
            "count": len(donations),
            "total_value": round(sum(d.amount or 0 for d in donations), 2),
            "records": [
                {"contributor_name": d.contributor_name, "party": d.party,
                 "amount": d.amount, "received_date": d.received_date}
                for d in donations[:25]
            ],
        },
        "bills": {
            "count": len(bills),
            "records": [
                {"bill_number": b.bill_number, "title_en": b.title_en, "status": b.status,
                 "sponsor": b.sponsor, "latest_activity": b.latest_activity}
                for b in bills
            ],
        },
        "regulations": {
            "count": len(regulations),
            "records": regulations,
        },
        "tribunal_decisions": {
            "count": len(tribunal),
            "records": tribunal,
        },
        "appointments": {
            "count": len(appointments),
            "records": appointments,
        },
        "stakeholders": await _stakeholders(session, company, canonical, sector),
    }
