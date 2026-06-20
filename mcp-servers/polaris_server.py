"""Nessus Intelligence MCP Server.

Exposes all Nessus data sources as callable tools for LLM decision-making.
The LLM calls these tools to gather evidence, assess risk, and build context
for political due diligence on Canadian companies and sectors.

Run:
    cd polaris
    .venv/bin/python mcp-servers/polaris_server.py

Then configure in Claude Code settings or any MCP-compatible client:
    {
      "polaris": {
        "command": "/path/to/polaris/.venv/bin/python",
        "args": ["/path/to/polaris/mcp-servers/polaris_server.py"]
      }
    }
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Add polaris root to sys.path so we can import api/pipeline modules directly.
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

os.chdir(_ROOT)  # Ensure relative paths (database, data/cache) resolve correctly.

import asyncio
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "Nessus Intelligence",
    instructions=(
        "You have access to Nessus, a Canadian political due-diligence database. "
        "Use these tools to gather evidence about companies, sectors, lobbyists, "
        "government contracts, grants, appointments, and regulatory activity. "
        "Always call gather_company_evidence first for a company-level analysis, "
        "then drill into specific sources as needed. "
        "All monetary values are in Canadian dollars."
    ),
)


# ── DB helpers ────────────────────────────────────────────────────────────────

def _run(coro) -> Any:
    """Run an async coroutine from a sync context."""
    return asyncio.get_event_loop().run_until_complete(coro)


async def _get_session():
    from api.database import init_db, AsyncSessionLocal
    await init_db()
    return AsyncSessionLocal()


# ── Tools ─────────────────────────────────────────────────────────────────────

@mcp.tool()
def list_data_sources() -> str:
    """List all available Nessus data sources and their current record counts."""
    async def _go():
        from sqlalchemy import func, select
        session = await _get_session()
        async with session as s:
            from api.models.appointment import Appointment
            from api.models.contract import Contract
            from api.models.donation import Bill, Donation
            from api.models.entity import LobbyingRecord
            from api.models.grant import Grant
            from api.models.ocl_registration import OCLRegistration
            from api.models.politician import HansardMention, Politician
            from api.models.regulation import GazetteEntry, TribunalDecision

            async def cnt(model) -> int:
                return (await s.execute(select(func.count(model.id)))).scalar_one()

            return {
                "sources": [
                    {"name": "Federal Contracts (Proactive Disclosure >$10k)", "table": "contracts", "records": await cnt(Contract)},
                    {"name": "Political Donations (Elections Canada)", "table": "donations", "records": await cnt(Donation)},
                    {"name": "Bills & Legislation (LEGISinfo)", "table": "bills", "records": await cnt(Bill)},
                    {"name": "OCL Lobbying Communications", "table": "lobbying_records", "records": await cnt(LobbyingRecord)},
                    {"name": "OCL Lobbying Registrations", "table": "ocl_registrations", "records": await cnt(OCLRegistration)},
                    {"name": "Grants & Contributions", "table": "grants", "records": await cnt(Grant)},
                    {"name": "GIC Appointments", "table": "appointments", "records": await cnt(Appointment)},
                    {"name": "Canada Gazette (Proposed/Final Regulations)", "table": "gazette_entries", "records": await cnt(GazetteEntry)},
                    {"name": "Tribunal Decisions (CRTC etc.)", "table": "tribunal_decisions", "records": await cnt(TribunalDecision)},
                    {"name": "MPs / Politicians (openparliament.ca)", "table": "politicians", "records": await cnt(Politician)},
                    {"name": "Hansard Mentions", "table": "hansard_mentions", "records": await cnt(HansardMention)},
                ],
                "coverage": "Federal Canada only. Provincial data is Phase 2.",
                "currency": "All monetary values are Canadian dollars.",
            }
    return json.dumps(_run(_go()), indent=2)


@mcp.tool()
def gather_company_evidence(company_name: str, sector: str = "", report_type: str = "deal_due_diligence") -> str:
    """Gather all available political and regulatory evidence for a Canadian company.

    This is the primary research tool. Returns a structured bundle covering:
    - Lobbying communications and registrations (who is lobbying, on what, to whom)
    - Federal contracts (government revenue and departmental relationships)
    - Grants and contributions (federal funding received)
    - Political donations (party alignment signals)
    - Relevant bills before Parliament
    - Canada Gazette regulations affecting the sector
    - CRTC and tribunal decisions naming the company
    - GIC appointments to regulatory bodies relevant to the sector
    - Political stakeholders (MPs who've mentioned the company in Hansard)

    Args:
        company_name: The company to research (e.g., "Rogers Communications", "BCE Inc", "Loblaws")
        sector: Optional sector context to improve relevance (e.g., "telecom", "grocery", "energy")
        report_type: One of deal_due_diligence | sector_monitoring | regulatory_risk
    """
    async def _go():
        from api.database import init_db
        from api.database import AsyncSessionLocal
        from pipeline.gather import gather_company_data
        from pipeline.risk_scorer import score

        await init_db()
        async with AsyncSessionLocal() as session:
            evidence = await gather_company_data(session, company_name, sector or None, report_type)
            scores = score(evidence)
            return {"evidence": evidence, "risk_scores": scores}

    result = _run(_go())
    # Truncate large record arrays for LLM context efficiency
    ev = result["evidence"]
    for key in ("lobbying", "contracts", "donations", "bills", "regulations", "tribunal_decisions"):
        if key in ev and "records" in ev[key]:
            ev[key]["records"] = ev[key]["records"][:10]
    if "lobbying" in ev:
        ev["lobbying"]["records"] = ev["lobbying"]["records"][:15]
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
def get_risk_scores(company_name: str, sector: str = "") -> str:
    """Calculate political risk scores (0–10) for a company across four dimensions.

    Returns:
        - regulatory_risk: Active regulatory oversight, relevant bills, departmental breadth
        - policy_volatility: Legislation in motion, lobbying proxy for contested policy
        - election_sensitivity: Consumer-facing sector exposure, donation signals
        - lobbying_intensity: Frequency and institutional breadth of lobbying activity
        - overall: Weighted composite score

    Each score includes a driver string explaining what pushed it up or down.
    """
    async def _go():
        from api.database import init_db, AsyncSessionLocal
        from pipeline.gather import gather_company_data
        from pipeline.risk_scorer import score

        await init_db()
        async with AsyncSessionLocal() as session:
            evidence = await gather_company_data(session, company_name, sector or None, "deal_due_diligence")
            return score(evidence)

    return json.dumps(_run(_go()), indent=2)


@mcp.tool()
def search_lobbying(company_name: str, limit: int = 30) -> str:
    """Search OCL lobbying communications for a company.

    Returns communications with subject matters, institutions lobbied, DPOH contacts
    (specific government officials), and dates. Sort order: most recent first.

    Use this to understand:
    - What policy areas the company is lobbying on
    - Which government departments and officials they've contacted
    - How active their Ottawa presence is
    - Who their lobbyist registrants are
    """
    async def _go():
        from sqlalchemy import or_, select
        from api.database import init_db, AsyncSessionLocal
        from api.models.entity import LobbyingRecord
        from pipeline.entity_resolver import normalize

        await init_db()
        canonical = normalize(company_name)
        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(LobbyingRecord)
                .where(or_(
                    LobbyingRecord.canonical_name == canonical,
                    LobbyingRecord.client.ilike(f"%{company_name}%"),
                ))
                .order_by(LobbyingRecord.communication_date.desc())
                .limit(limit)
            )
            rows = res.scalars().all()
            return {
                "company": company_name,
                "count": len(rows),
                "records": [
                    {
                        "client": r.client,
                        "registrant": r.registrant,
                        "subject_matters": r.subject_matters,
                        "institutions": r.institutions,
                        "communication_date": r.communication_date,
                        "dpoh_contacts": (r.raw or {}).get("dpoh_contacts", [])[:5],
                    }
                    for r in rows
                ],
            }

    return json.dumps(_run(_go()), indent=2, default=str)


@mcp.tool()
def search_contracts(company_name: str, limit: int = 30) -> str:
    """Search federal government contracts awarded to a company.

    Returns contracts with value, department, description, and date.
    Use this to understand a company's federal revenue exposure and
    which departments they have relationships with.
    """
    async def _go():
        from sqlalchemy import func, or_, select
        from api.database import init_db, AsyncSessionLocal
        from api.models.contract import Contract
        from pipeline.entity_resolver import normalize

        await init_db()
        canonical = normalize(company_name)
        async with AsyncSessionLocal() as session:
            filt = or_(Contract.canonical_name == canonical, Contract.vendor_name.ilike(f"%{company_name}%"))
            res = await session.execute(select(Contract).where(filt).order_by(Contract.contract_value.desc()).limit(limit))
            rows = res.scalars().all()
            total = (await session.execute(select(func.coalesce(func.sum(Contract.contract_value), 0.0)).where(filt))).scalar_one()
            return {
                "company": company_name,
                "count": len(rows),
                "total_value_cad": round(total, 2),
                "records": [
                    {"vendor_name": r.vendor_name, "contract_value": r.contract_value,
                     "description": r.description, "owner_org_title": r.owner_org_title,
                     "contract_date": r.contract_date}
                    for r in rows
                ],
            }

    return json.dumps(_run(_go()), indent=2, default=str)


@mcp.tool()
def search_grants(company_name: str, limit: int = 30) -> str:
    """Search federal grants and contributions awarded to a company or organization.

    Returns grants with value, department, program name, and dates.
    Note: grants and contributions are distinct from contracts — they represent
    federal money transferred to organizations, not procurement.
    """
    async def _go():
        from sqlalchemy import or_, select
        from api.database import init_db, AsyncSessionLocal
        from api.models.grant import Grant
        from pipeline.entity_resolver import normalize

        await init_db()
        canonical = normalize(company_name)
        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(Grant)
                .where(or_(Grant.canonical_name == canonical, Grant.recipient_name.ilike(f"%{company_name}%")))
                .order_by(Grant.agreement_value.desc())
                .limit(limit)
            )
            rows = res.scalars().all()
            return {
                "company": company_name,
                "count": len(rows),
                "total_value_cad": round(sum(r.agreement_value or 0 for r in rows), 2),
                "records": [
                    {"recipient_name": r.recipient_name, "agreement_value": r.agreement_value,
                     "owner_org_title": r.owner_org_title, "program_name": r.program_name,
                     "agreement_type": r.agreement_type, "agreement_start": r.agreement_start}
                    for r in rows
                ],
            }

    return json.dumps(_run(_go()), indent=2, default=str)


@mcp.tool()
def search_donations(company_or_person: str, limit: int = 30) -> str:
    """Search federal political contributions linked to a company or individual.

    Note: Federal law has banned corporate and union donations since 2007. An absence
    of corporate donations is expected. Relevant signals are individual donations from
    named executives or employees. Use this to assess party alignment.
    """
    async def _go():
        from sqlalchemy import or_, select
        from api.database import init_db, AsyncSessionLocal
        from api.models.donation import Donation
        from pipeline.entity_resolver import normalize

        await init_db()
        canonical = normalize(company_or_person)
        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(Donation)
                .where(or_(Donation.canonical_name == canonical, Donation.contributor_name.ilike(f"%{company_or_person}%")))
                .order_by(Donation.amount.desc())
                .limit(limit)
            )
            rows = res.scalars().all()
            return {
                "query": company_or_person,
                "count": len(rows),
                "total_value_cad": round(sum(r.amount or 0 for r in rows), 2),
                "records": [
                    {"contributor_name": r.contributor_name, "party": r.party,
                     "amount": r.amount, "received_date": r.received_date}
                    for r in rows
                ],
            }

    return json.dumps(_run(_go()), indent=2, default=str)


@mcp.tool()
def search_bills(keywords: str, limit: int = 20) -> str:
    """Search bills currently before Parliament by keyword.

    Args:
        keywords: Space-separated terms to match against bill titles (e.g., "telecom spectrum broadcasting")

    Returns bills with bill number, title, current status, sponsor, and latest activity.
    Use this to identify legislative risk to a company or sector.
    """
    async def _go():
        from sqlalchemy import or_, select
        from api.database import init_db, AsyncSessionLocal
        from api.models.donation import Bill

        await init_db()
        terms = [t.strip() for t in keywords.split() if len(t.strip()) > 2]
        async with AsyncSessionLocal() as session:
            if terms:
                filt = or_(*[Bill.title_en.ilike(f"%{t}%") for t in terms])
                res = await session.execute(select(Bill).where(filt).limit(limit))
            else:
                res = await session.execute(select(Bill).limit(limit))
            rows = res.scalars().all()
            return {
                "keywords": keywords,
                "count": len(rows),
                "records": [
                    {"bill_number": r.bill_number, "title_en": r.title_en, "status": r.status,
                     "sponsor": r.sponsor, "latest_activity": r.latest_activity}
                    for r in rows
                ],
            }

    return json.dumps(_run(_go()), indent=2, default=str)


@mcp.tool()
def search_regulations(keywords: str, gazette_part: str = "both", limit: int = 20) -> str:
    """Search Canada Gazette entries (proposed and final federal regulations) by keyword.

    Args:
        keywords: Terms to search in regulation titles and descriptions
        gazette_part: "I" for proposed regulations, "II" for final regulations, "both" for all

    Use this to identify pending regulatory changes that could affect a company or sector.
    Part I = proposed (open for comment), Part II = enacted (in force).
    """
    async def _go():
        from sqlalchemy import or_, select
        from api.database import init_db, AsyncSessionLocal
        from api.models.regulation import GazetteEntry

        await init_db()
        terms = [t.strip() for t in keywords.split() if len(t.strip()) > 2]
        async with AsyncSessionLocal() as session:
            filters = []
            if terms:
                filters.append(or_(*[
                    or_(GazetteEntry.title.ilike(f"%{t}%"), GazetteEntry.description.ilike(f"%{t}%"))
                    for t in terms
                ]))
            if gazette_part in ("I", "II"):
                filters.append(GazetteEntry.gazette_part == gazette_part)

            q = select(GazetteEntry).order_by(GazetteEntry.published_date.desc()).limit(limit)
            if filters:
                from sqlalchemy import and_
                q = q.where(and_(*filters))
            res = await session.execute(q)
            rows = res.scalars().all()
            return {
                "keywords": keywords,
                "gazette_part": gazette_part,
                "count": len(rows),
                "records": [
                    {"gazette_part": r.gazette_part, "title": r.title, "published_date": r.published_date,
                     "department": r.department, "regulation_id": r.regulation_id,
                     "description": (r.description or "")[:400], "url": r.url}
                    for r in rows
                ],
            }

    return json.dumps(_run(_go()), indent=2, default=str)


@mcp.tool()
def search_tribunal_decisions(query: str, body: str = "all", limit: int = 20) -> str:
    """Search CRTC and regulatory tribunal decisions by keyword, company, or party name.

    Args:
        query: Company name, topic, or keyword to search in decision titles and summaries
        body: Filter by regulatory body — "CRTC", "Competition Bureau", or "all"

    Use this to find regulatory decisions that directly affect a company,
    reveal enforcement history, or signal how the regulator views a sector.
    """
    async def _go():
        from sqlalchemy import and_, or_, select
        from api.database import init_db, AsyncSessionLocal
        from api.models.regulation import TribunalDecision

        await init_db()
        async with AsyncSessionLocal() as session:
            filters = [
                or_(
                    TribunalDecision.title.ilike(f"%{query}%"),
                    TribunalDecision.summary.ilike(f"%{query}%"),
                    TribunalDecision.parties.ilike(f"%{query}%"),
                )
            ]
            if body != "all":
                filters.append(TribunalDecision.body == body)
            res = await session.execute(
                select(TribunalDecision)
                .where(and_(*filters))
                .order_by(TribunalDecision.decision_date.desc())
                .limit(limit)
            )
            rows = res.scalars().all()
            return {
                "query": query,
                "body": body,
                "count": len(rows),
                "records": [
                    {"body": r.body, "decision_number": r.decision_number, "title": r.title,
                     "decision_date": r.decision_date, "outcome": r.outcome,
                     "summary": r.summary, "url": r.url}
                    for r in rows
                ],
            }

    return json.dumps(_run(_go()), indent=2, default=str)


@mcp.tool()
def search_appointments(keywords: str, organization: str = "", limit: int = 30) -> str:
    """Search Governor in Council appointments to regulatory bodies and crown corporations.

    Args:
        keywords: Person name or role to search
        organization: Optional filter by organization (e.g., "CRTC", "Bank of Canada")

    Use this to understand who is running key regulatory bodies, identify
    revolving-door risk, and assess political alignment of decision-makers.
    """
    async def _go():
        from sqlalchemy import and_, or_, select
        from api.database import init_db, AsyncSessionLocal
        from api.models.appointment import Appointment

        await init_db()
        async with AsyncSessionLocal() as session:
            filters = [
                or_(
                    Appointment.appointee_name.ilike(f"%{keywords}%"),
                    Appointment.position_title.ilike(f"%{keywords}%"),
                    Appointment.organization.ilike(f"%{keywords}%"),
                )
            ]
            if organization:
                filters.append(Appointment.organization.ilike(f"%{organization}%"))
            res = await session.execute(
                select(Appointment)
                .where(and_(*filters))
                .order_by(Appointment.appointment_date.desc())
                .limit(limit)
            )
            rows = res.scalars().all()
            return {
                "keywords": keywords,
                "organization_filter": organization,
                "count": len(rows),
                "records": [
                    {"appointee_name": r.appointee_name, "position_title": r.position_title,
                     "organization": r.organization, "appointment_date": r.appointment_date,
                     "end_date": r.end_date, "order_in_council": r.order_in_council,
                     "appointment_type": r.appointment_type, "province": r.province}
                    for r in rows
                ],
            }

    return json.dumps(_run(_go()), indent=2, default=str)


@mcp.tool()
def search_hansard(keywords: str, limit: int = 20) -> str:
    """Search Hansard (Parliamentary debates) for mentions of a company, person, or topic.

    Returns speeches with speaker name, date, and excerpt. Use this to assess
    which MPs are paying attention to a company or sector, and what position they hold.
    """
    async def _go():
        from sqlalchemy import or_, select
        from api.database import init_db, AsyncSessionLocal
        from api.models.politician import HansardMention

        await init_db()
        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(HansardMention)
                .where(or_(
                    HansardMention.keyword.ilike(f"%{keywords}%"),
                    HansardMention.excerpt.ilike(f"%{keywords}%"),
                    HansardMention.speaker.ilike(f"%{keywords}%"),
                ))
                .order_by(HansardMention.speech_date.desc())
                .limit(limit)
            )
            rows = res.scalars().all()
            return {
                "keywords": keywords,
                "count": len(rows),
                "records": [
                    {"speaker": r.speaker, "speech_date": r.speech_date,
                     "keyword": r.keyword, "excerpt": r.excerpt, "speech_url": r.speech_url}
                    for r in rows
                ],
            }

    return json.dumps(_run(_go()), indent=2, default=str)


@mcp.tool()
def search_politicians(name_or_party: str = "", province: str = "", limit: int = 30) -> str:
    """Search the MP database for politicians by name, party, or province.

    Use this to identify which MPs sit on relevant committees, find party leadership,
    or look up a specific politician's riding and contact details.
    """
    async def _go():
        from sqlalchemy import or_, select
        from api.database import init_db, AsyncSessionLocal
        from api.models.politician import Politician

        await init_db()
        async with AsyncSessionLocal() as session:
            filters = []
            if name_or_party:
                filters.append(or_(
                    Politician.name.ilike(f"%{name_or_party}%"),
                    Politician.party.ilike(f"%{name_or_party}%"),
                ))
            if province:
                filters.append(Politician.province.ilike(f"%{province}%"))

            q = select(Politician).order_by(Politician.name).limit(limit)
            if filters:
                from sqlalchemy import and_
                q = q.where(and_(*filters))
            res = await session.execute(q)
            rows = res.scalars().all()
            return {
                "query": name_or_party,
                "count": len(rows),
                "records": [
                    {"name": r.name, "party": r.party, "riding": r.riding,
                     "province": r.province, "url": r.url}
                    for r in rows
                ],
            }

    return json.dumps(_run(_go()), indent=2, default=str)


@mcp.tool()
def search_ocl_registrations(company_name: str, limit: int = 20) -> str:
    """Search OCL lobbying registration filings for a company.

    Registrations are distinct from communications — they are the formal filing
    that declares a company is lobbying, what issues they are lobbying on, and
    what federal benefits they are seeking. More detailed than communications.
    """
    async def _go():
        from sqlalchemy import or_, select
        from api.database import init_db, AsyncSessionLocal
        from api.models.ocl_registration import OCLRegistration
        from pipeline.entity_resolver import normalize

        await init_db()
        canonical = normalize(company_name)
        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(OCLRegistration)
                .where(or_(OCLRegistration.canonical_name == canonical, OCLRegistration.client_org.ilike(f"%{company_name}%")))
                .order_by(OCLRegistration.effective_date.desc())
                .limit(limit)
            )
            rows = res.scalars().all()
            return {
                "company": company_name,
                "count": len(rows),
                "records": [
                    {"registration_num": r.registration_num, "client_org": r.client_org,
                     "registrant_name": r.registrant_name, "firm_name": r.firm_name,
                     "registration_type": r.registration_type, "status": r.status,
                     "effective_date": r.effective_date, "subject_matters": r.subject_matters,
                     "federal_benefits": r.federal_benefits}
                    for r in rows
                ],
            }

    return json.dumps(_run(_go()), indent=2, default=str)


@mcp.tool()
def compare_companies(company_a: str, company_b: str, sector: str = "") -> str:
    """Compare political risk profiles of two companies side-by-side.

    Returns risk scores and key evidence counts for both companies to support
    comparative analysis (e.g., target vs. acquirer in M&A context).
    """
    async def _go():
        from api.database import init_db, AsyncSessionLocal
        from pipeline.gather import gather_company_data
        from pipeline.risk_scorer import score

        await init_db()
        async with AsyncSessionLocal() as session:
            ev_a = await gather_company_data(session, company_a, sector or None, "deal_due_diligence")
            sc_a = score(ev_a)
        async with AsyncSessionLocal() as session:
            ev_b = await gather_company_data(session, company_b, sector or None, "deal_due_diligence")
            sc_b = score(ev_b)

        def _summary(ev, sc):
            return {
                "company": ev["company"],
                "risk_scores": sc,
                "lobbying_communications": ev["lobbying"]["count"],
                "contracts_value_cad": ev["contracts"]["total_value"],
                "grants_value_cad": ev["grants"]["total_value"],
                "donations": ev["donations"]["count"],
                "relevant_bills": ev["bills"]["count"],
                "gazette_regulations": ev["regulations"]["count"],
                "tribunal_decisions": ev["tribunal_decisions"]["count"],
            }

        return {"company_a": _summary(ev_a, sc_a), "company_b": _summary(ev_b, sc_b)}

    return json.dumps(_run(_go()), indent=2, default=str)


if __name__ == "__main__":
    mcp.run(transport="stdio")
