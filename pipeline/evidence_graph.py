"""Evidence graph helpers for deterministic Nessus findings.

This module is the shared "connect the dots" layer. It keeps the MVP cheap and
explainable: no paid model call, no new database, just normalized references and
small graph-shaped findings that the dashboard, sector pages, reports, and
record pages can reuse.
"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas import EvidenceReference, GraphFinding
from api.models.donation import Bill
from api.models.entity import LobbyingRecord
from api.models.politician import HansardMention, Politician
from api.models.regulation import GazetteEntry
from pipeline.sector_mapper import SECTORS, Sector, get_sector


SEVERITY_RANK = {"high": 3, "elevated": 2, "watch": 1, "low": 0}


def normalize_reference(ref: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return one canonical evidence-reference shape, or ``None`` if un-linkable."""
    if not ref:
        return None
    table = ref.get("table")
    pk = ref.get("pk", ref.get("id"))
    title = ref.get("title")
    if not table or pk is None or not title:
        return None
    return EvidenceReference.model_validate({
        "table": table,
        "pk": pk,
        "id": pk,
        "source": ref.get("source") or table,
        "title": str(title),
        "date": ref.get("date"),
        "url": ref.get("url"),
        "record_type": ref.get("record_type") or ref.get("type") or "record",
        "sector": ref.get("sector"),
        "confidence": ref.get("confidence") or "linked",
    }).model_dump()


def ref(
    table: str,
    pk: int,
    source: str,
    title: str,
    date: str | None = None,
    *,
    url: str | None = None,
    record_type: str = "record",
    sector: str | None = None,
    confidence: str = "linked",
) -> dict[str, Any]:
    """Build a normalized, internally linkable evidence reference."""
    return normalize_reference({
        "table": table,
        "pk": pk,
        "source": source,
        "title": title,
        "date": date,
        "url": url,
        "record_type": record_type,
        "sector": sector,
        "confidence": confidence,
    }) or {}


def parse_speaker_name(speaker: str | None) -> str | None:
    """Extract a likely person name from Hansard speaker labels.

    Handles labels like ``The Assistant Deputy Speaker (John Nater):`` and leaves
    ordinary names untouched. This is deliberately conservative because a wrong
    actor link is worse than no actor link.
    """
    if not speaker:
        return None
    s = re.sub(r"\s+", " ", speaker).strip(" :")
    paren = re.search(r"\(([^()]+)\)", s)
    if paren:
        s = paren.group(1).strip()
    s = re.sub(r"^(Hon\.|Mr\.|Mrs\.|Ms\.|Miss|Dr\.)\s+", "", s, flags=re.I)
    s = re.sub(r",\s*(MP|M\.P\.).*$", "", s, flags=re.I).strip()
    if not s or len(s.split()) < 2:
        return None
    return s


async def resolve_politician(session: AsyncSession, speaker: str | None) -> dict[str, Any] | None:
    """Resolve a Hansard speaker label to a seeded politician row when possible."""
    name = parse_speaker_name(speaker)
    if not name:
        return None
    pol = (
        await session.execute(
            select(Politician).where(Politician.name.ilike(f"%{name}%")).limit(1)
        )
    ).scalar_one_or_none()
    if not pol:
        return {"name": name, "slug": None, "party": None, "role": None, "confidence": "parsed"}
    return {
        "name": pol.name,
        "slug": pol.slug,
        "party": pol.party,
        "role": pol.role,
        "riding": pol.riding,
        "province": pol.province,
        "confidence": "matched",
    }


def sectors_for_text(text: str | None, limit: int = 3) -> list[dict[str, str]]:
    """Match a blob of text to sector keywords for lightweight graph edges."""
    haystack = (text or "").lower()
    matches: list[dict[str, str]] = []
    for sector in SECTORS.values():
        if any(k.lower() in haystack for k in sector.keywords):
            matches.append({"slug": sector.slug, "name": sector.name})
        if len(matches) >= limit:
            break
    return matches


def _kw_filter(columns: list, keywords: list[str]):
    clauses = [col.ilike(f"%{kw}%") for kw in keywords for col in columns]
    return or_(*clauses) if clauses else None


def _finding(
    *,
    title: str,
    summary: str,
    severity: str,
    finding_type: str,
    sector: Sector | None = None,
    actors: list[dict[str, Any]] | None = None,
    references: list[dict[str, Any]] | None = None,
    related_sectors: list[dict[str, str]] | None = None,
    metrics: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    refs = [r for r in (normalize_reference(x) for x in (references or [])) if r]
    return GraphFinding.model_validate({
        "title": title,
        "summary": summary,
        "severity": severity,
        "type": finding_type,
        "sector": {"slug": sector.slug, "name": sector.name} if sector else None,
        "related_sectors": related_sectors or ([] if not sector else [{"slug": sector.slug, "name": sector.name}]),
        "actors": actors or [],
        "references": refs,
        "metrics": metrics or [],
        "confidence": "deterministic",
    }).model_dump()


async def build_actor_findings(session: AsyncSession, *, limit: int = 8) -> list[dict[str, Any]]:
    """Recent Hansard mentions with actor, sector, and record links attached."""
    rows = (
        await session.execute(
            select(HansardMention)
            .where(HansardMention.speech_date.isnot(None))
            .order_by(HansardMention.speech_date.desc(), HansardMention.id.desc())
            .limit(limit * 3)
        )
    ).scalars().all()

    findings: list[dict[str, Any]] = []
    seen: set[tuple[str, str | None, str]] = set()
    for row in rows:
        key = (row.speaker or "House intervention", row.speech_date, row.keyword)
        if key in seen:
            continue
        seen.add(key)
        actor = await resolve_politician(session, row.speaker)
        related = sectors_for_text(f"{row.keyword} {row.excerpt or ''}", limit=3)
        findings.append(_finding(
            title=f"{(actor or {}).get('name') or row.speaker or 'House intervention'} raised {row.keyword}",
            summary=(row.excerpt or "")[:240],
            severity="watch",
            finding_type="actor_movement",
            actors=[actor] if actor else [],
            related_sectors=related,
            references=[ref(
                "hansard_mentions", row.id, row.source,
                f"{row.speaker or 'House intervention'} — {row.keyword}",
                row.speech_date, url=row.speech_url, record_type="hansard_mention",
            )],
        ))
        if len(findings) >= limit:
            break
    return findings


async def build_politician_graph(session: AsyncSession, slug: str) -> dict[str, Any]:
    """Return recent Hansard-sector links for one seeded politician."""
    pol = (
        await session.execute(select(Politician).where(Politician.slug == slug).limit(1))
    ).scalar_one_or_none()
    if not pol:
        return {"actor": None, "findings": [], "nodes": [], "edges": []}

    last = pol.name.split()[-1] if pol.name else slug
    rows = (
        await session.execute(
            select(HansardMention)
            .where(or_(HansardMention.speaker.ilike(f"%{pol.name}%"), HansardMention.speaker.ilike(f"%{last}%")))
            .order_by(HansardMention.speech_date.desc(), HansardMention.id.desc())
            .limit(12)
        )
    ).scalars().all()

    actor = {
        "name": pol.name,
        "slug": pol.slug,
        "party": pol.party,
        "role": pol.role,
        "riding": pol.riding,
        "province": pol.province,
        "confidence": "matched",
    }
    findings = [
        _finding(
            title=f"{pol.name} raised {row.keyword}",
            summary=(row.excerpt or "")[:240],
            severity="watch",
            finding_type="actor_sector_speech",
            actors=[actor],
            related_sectors=sectors_for_text(f"{row.keyword} {row.excerpt or ''}", limit=3),
            references=[ref(
                "hansard_mentions", row.id, row.source,
                f"{row.speaker or pol.name} — {row.keyword}",
                row.speech_date, url=row.speech_url, record_type="hansard_mention",
            )],
        )
        for row in rows
    ]

    nodes = [{"id": f"actor:{pol.slug}", "type": "actor", "label": pol.name, "meta": actor}]
    edges: list[dict[str, Any]] = []
    seen = {nodes[0]["id"]}
    for finding in findings:
        for sector in finding["related_sectors"]:
            node_id = f"sector:{sector['slug']}"
            if node_id not in seen:
                nodes.append({"id": node_id, "type": "sector", "label": sector["name"], "meta": sector})
                seen.add(node_id)
            edges.append({"from": nodes[0]["id"], "to": node_id, "type": finding["type"]})
        for evidence in finding["references"]:
            node_id = f"record:{evidence['table']}:{evidence['pk']}"
            if node_id not in seen:
                nodes.append({"id": node_id, "type": "record", "label": evidence["title"], "meta": evidence})
                seen.add(node_id)
            edges.append({"from": nodes[0]["id"], "to": node_id, "type": "mentioned"})

    return {"actor": actor, "findings": findings[:8], "nodes": nodes[:40], "edges": edges[:80]}


async def build_sector_graph(session: AsyncSession, slug: str) -> dict[str, Any]:
    """Return deterministic sector findings and graph nodes for one sector."""
    sector = get_sector(slug)
    if not sector:
        return {"sector": None, "findings": [], "nodes": [], "edges": []}

    bill_filter = _kw_filter([Bill.title_en, Bill.bill_number, Bill.status, Bill.sponsor], sector.keywords)
    bills_stmt = select(Bill).order_by(Bill.introduced_date.desc()).limit(5)
    if bill_filter is not None:
        bills_stmt = bills_stmt.where(bill_filter)
    bills = (await session.execute(bills_stmt)).scalars().all()

    gazette_filter = _kw_filter([GazetteEntry.title, GazetteEntry.description, GazetteEntry.department], sector.keywords + sector.regulators)
    gazette_stmt = select(GazetteEntry).order_by(GazetteEntry.published_date.desc()).limit(5)
    if gazette_filter is not None:
        gazette_stmt = gazette_stmt.where(gazette_filter)
    gazette = (await session.execute(gazette_stmt)).scalars().all()

    lobbying_count = (
        await session.execute(
            select(func.count(LobbyingRecord.id)).where(LobbyingRecord.canonical_name.in_(sector.entities))
        )
    ).scalar_one()

    hansard_filter = _kw_filter([HansardMention.keyword, HansardMention.excerpt], sector.keywords)
    hansard = []
    if hansard_filter is not None:
        hansard = (
            await session.execute(
                select(HansardMention).where(hansard_filter).order_by(HansardMention.speech_date.desc()).limit(5)
            )
        ).scalars().all()

    findings: list[dict[str, Any]] = []
    if lobbying_count and bills:
        findings.append(_finding(
            title="Lobbying and legislation are active in the same sector lens",
            summary=f"{lobbying_count:,} lobbying communication(s) align with {len(bills)} recent bill match(es).",
            severity="high" if lobbying_count >= 50 else "elevated",
            finding_type="lobbying_legislation_overlap",
            sector=sector,
            references=[
                ref("bills", b.id, "LEGISinfo", f"{b.bill_number} — {b.title_en or ''}".strip(" —"), b.introduced_date, record_type="bill", sector=sector.slug)
                for b in bills[:3]
            ],
            metrics=[{"label": "Lobbying", "value": lobbying_count}, {"label": "Bills", "value": len(bills)}],
        ))

    if gazette:
        findings.append(_finding(
            title="Regulatory material is attached to the sector",
            summary=f"{len(gazette)} Canada Gazette item(s) match the sector's keywords or regulators.",
            severity="elevated",
            finding_type="regulatory_movement",
            sector=sector,
            references=[
                ref("gazette", g.id, "Canada Gazette", g.title, g.published_date, url=g.url, record_type="regulation", sector=sector.slug)
                for g in gazette[:3]
            ],
            metrics=[{"label": "Gazette", "value": len(gazette)}],
        ))

    for h in hansard[:3]:
        actor = await resolve_politician(session, h.speaker)
        findings.append(_finding(
            title=f"{(actor or {}).get('name') or h.speaker or 'House intervention'} mentioned {h.keyword}",
            summary=(h.excerpt or "")[:220],
            severity="watch",
            finding_type="political_speech",
            sector=sector,
            actors=[actor] if actor else [],
            references=[ref(
                "hansard_mentions", h.id, h.source,
                f"{h.speaker or 'House intervention'} — {h.keyword}",
                h.speech_date, url=h.speech_url, record_type="hansard_mention", sector=sector.slug,
            )],
        ))

    findings.sort(key=lambda f: SEVERITY_RANK.get(f["severity"], 0), reverse=True)
    nodes = [{"id": f"sector:{sector.slug}", "type": "sector", "label": sector.name}]
    edges = []
    seen_nodes = {nodes[0]["id"]}
    for finding in findings:
        for actor in finding["actors"]:
            if actor and actor.get("name"):
                node_id = f"actor:{actor.get('slug') or actor['name']}"
                if node_id not in seen_nodes:
                    nodes.append({"id": node_id, "type": "actor", "label": actor["name"], "meta": actor})
                    seen_nodes.add(node_id)
                edges.append({"from": node_id, "to": f"sector:{sector.slug}", "type": finding["type"]})
        for evidence in finding["references"]:
            node_id = f"record:{evidence['table']}:{evidence['pk']}"
            if node_id not in seen_nodes:
                nodes.append({"id": node_id, "type": "record", "label": evidence["title"], "meta": evidence})
                seen_nodes.add(node_id)
            edges.append({"from": node_id, "to": f"sector:{sector.slug}", "type": finding["type"]})

    return {
        "sector": {"slug": sector.slug, "name": sector.name, "blurb": sector.blurb},
        "findings": findings[:8],
        "nodes": nodes[:40],
        "edges": edges[:80],
    }


async def build_global_findings(session: AsyncSession, *, limit: int = 10) -> list[dict[str, Any]]:
    """Small homepage-ready finding set across actor movement and sector graphs."""
    findings = await build_actor_findings(session, limit=limit)
    for slug in list(SECTORS.keys())[:4]:
        graph = await build_sector_graph(session, slug)
        findings.extend(graph.get("findings", [])[:2])
    findings.sort(key=lambda f: SEVERITY_RANK.get(f["severity"], 0), reverse=True)
    return findings[:limit]


def build_report_findings(ev: dict[str, Any]) -> list[dict[str, Any]]:
    """Report-ready findings from gathered evidence.

    This lets generated briefs consume the same normalized finding/reference
    contract as the workspace without requiring an async sector graph call.
    """
    findings: list[dict[str, Any]] = []
    refs = [r for r in (normalize_reference(x) for x in ev.get("source_references", [])) if r]
    by_table: dict[str, list[dict[str, Any]]] = {}
    for evidence in refs:
        by_table.setdefault(evidence["table"], []).append(evidence)

    lob = ev.get("lobbying", {})
    bills = ev.get("bills", {})
    regs = ev.get("regulations", {})
    tribunal = ev.get("tribunal_decisions", {})
    contracts = ev.get("contracts", {})
    breadth = ev.get("breadth", {})

    if lob.get("count", 0) and bills.get("count", 0):
        findings.append(_finding(
            title="Lobbying and legislative exposure overlap",
            summary=(
                f"{lob.get('count', 0):,} lobbying communication(s) appear alongside "
                f"{bills.get('count', 0)} relevant bill match(es)."
            ),
            severity="high" if lob.get("count", 0) >= 25 else "elevated",
            finding_type="report_lobbying_legislation_overlap",
            references=(by_table.get("lobbying", [])[:2] + by_table.get("bills", [])[:3]),
            metrics=[
                {"label": "Lobbying", "value": lob.get("count", 0)},
                {"label": "Bills", "value": bills.get("count", 0)},
            ],
        ))

    if regs.get("count", 0) or tribunal.get("count", 0):
        findings.append(_finding(
            title="Regulatory record activity requires review",
            summary=(
                f"{regs.get('count', 0)} Gazette item(s) and "
                f"{tribunal.get('count', 0)} tribunal decision(s) are attached to this report lens."
            ),
            severity="elevated",
            finding_type="report_regulatory_activity",
            references=(by_table.get("gazette", [])[:3] + by_table.get("tribunal", [])[:3]),
            metrics=[
                {"label": "Gazette", "value": regs.get("count", 0)},
                {"label": "Tribunal", "value": tribunal.get("count", 0)},
            ],
        ))

    if breadth.get("count", 0):
        findings.append(_finding(
            title="Operational breadth records expand the diligence picture",
            summary=f"{breadth.get('count', 0):,} operational/public-record signal(s) connect the file to places, assets, incidents, or public releases.",
            severity="watch",
            finding_type="report_operational_breadth",
            references=by_table.get("source_records", [])[:5],
            metrics=[{"label": "Breadth records", "value": breadth.get("count", 0)}],
        ))

    if contracts.get("total_value", 0):
        findings.append(_finding(
            title="Federal commercial exposure is present",
            summary=(
                f"{contracts.get('count', 0):,} federal contract record(s) total "
                f"${contracts.get('total_value', 0):,.0f}."
            ),
            severity="watch",
            finding_type="report_federal_contracting",
            references=by_table.get("contracts", [])[:5],
            metrics=[
                {"label": "Contracts", "value": contracts.get("count", 0)},
                {"label": "Spend", "value": contracts.get("total_value", 0), "format": "money"},
            ],
        ))

    findings.sort(key=lambda f: SEVERITY_RANK.get(f["severity"], 0), reverse=True)
    return findings[:8]
