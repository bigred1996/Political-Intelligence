"""Weekly political-intelligence newsletter generation.

This module is deliberately separate from company diligence reports. A weekly
issue is time-window and sector anchored: gather candidate records from the
platform, rank/de-dupe them, ask Opus for a structured cited draft, validate the
draft, then render email-ready HTML.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from html import escape
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.appointment import Appointment
from api.models.contract import Contract
from api.models.donation import Bill
from api.models.entity import LobbyingRecord
from api.models.grant import Grant
from api.models.hansard_speech import HansardSpeech
from api.models.newsletter import NewsletterIssue
from api.models.ocl_registration import OCLRegistration
from api.models.politician import HansardMention
from api.models.regulation import GazetteEntry, TribunalDecision
from api.models.source_record import SourceRecord
from pipeline.ai_provider import ProviderError, ProviderTurn, ProviderUnavailable, _ClaudeToolProvider

OPUS_MODEL = "claude-opus-4-8"
MIN_WORDS = 900
MAX_WORDS = 1200
MAX_CANDIDATES_FOR_OPUS = 48


class NewsletterGenerationError(RuntimeError):
    """Generation failed before a publishable issue could be saved."""


@dataclass(frozen=True)
class EditorialSector:
    slug: str
    name: str
    keywords: tuple[str, ...]
    app_sectors: tuple[str, ...] = ()


EDITORIAL_SECTORS: tuple[EditorialSector, ...] = (
    EditorialSector(
        "energy-natural-resources",
        "Energy and natural resources",
        ("energy", "pipeline", "oil", "gas", "lng", "emissions", "carbon", "mining", "mineral", "critical mineral", "uranium", "potash", "forestry", "natural resources", "nuclear"),
        ("energy", "mining"),
    ),
    EditorialSector(
        "technology-innovation",
        "Technology and innovation",
        ("technology", "innovation", "digital", "ai", "artificial intelligence", "cyber", "cybersecurity", "privacy", "spectrum", "telecom", "wireless", "internet", "semiconductor"),
        ("telecommunications",),
    ),
    EditorialSector(
        "finance-capital-markets",
        "Finance and capital markets",
        ("finance", "bank", "capital", "market", "securities", "osfi", "payments", "open banking", "fintrac", "money laundering", "competition"),
        ("banking",),
    ),
    EditorialSector(
        "infrastructure-construction-housing",
        "Infrastructure, construction and housing",
        ("infrastructure", "construction", "housing", "transit", "rail", "port", "airport", "bridge", "procurement", "public works", "transport"),
        ("transportation",),
    ),
    EditorialSector(
        "trade-industrial-policy",
        "Trade and industrial policy",
        ("trade", "tariff", "export", "import", "supply chain", "industrial policy", "manufacturing", "competition", "foreign investment", "investment canada"),
        (),
    ),
    EditorialSector(
        "defence-procurement",
        "Defence and procurement",
        ("defence", "defense", "military", "armed forces", "shipbuilding", "aerospace", "procurement", "national defence", "pspc", "public services and procurement"),
        ("aerospace_defence",),
    ),
    EditorialSector(
        "agriculture-food",
        "Agriculture and food",
        ("agriculture", "food", "grocery", "farm", "grain", "livestock", "dairy", "fertilizer", "cfia", "crop", "affordability"),
        ("grocery",),
    ),
    EditorialSector(
        "health-life-sciences",
        "Health and life sciences",
        ("health", "pharma", "pharmaceutical", "drug", "vaccine", "medical", "life sciences", "biotech", "pmprb", "health canada"),
        ("pharma",),
    ),
)


NEWSLETTER_TOOL: dict[str, Any] = {
    "name": "build_weekly_newsletter",
    "description": (
        "Write a cited weekly Canadian political-intelligence newsletter for "
        "strategy, investor, legal, GR, and executive readers. Use only the "
        "provided candidate records and only cite allowed record ids."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "thesis": {"type": "string"},
            "executive_summary": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 4},
            "developments": {
                "type": "array",
                "minItems": 4,
                "maxItems": 6,
                "items": {
                    "type": "object",
                    "properties": {
                        "headline": {"type": "string"},
                        "summary": {"type": "string"},
                        "why_it_matters": {"type": "string"},
                        "sectors": {"type": "array", "items": {"type": "string"}},
                        "citations": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {"table": {"type": "string"}, "pk": {"type": ["string", "integer"]}},
                                "required": ["table", "pk"],
                            },
                        },
                    },
                    "required": ["headline", "summary", "why_it_matters", "sectors", "citations"],
                },
            },
            "sector_impacts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "sector": {"type": "string"},
                        "impact": {"type": "string"},
                        "citations": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {"table": {"type": "string"}, "pk": {"type": ["string", "integer"]}},
                                "required": ["table", "pk"],
                            },
                        },
                    },
                    "required": ["sector", "impact", "citations"],
                },
            },
            "watch_next_week": {
                "type": "array",
                "minItems": 3,
                "maxItems": 5,
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "citations": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {"table": {"type": "string"}, "pk": {"type": ["string", "integer"]}},
                                "required": ["table", "pk"],
                            },
                        },
                    },
                    "required": ["text", "citations"],
                },
            },
        },
        "required": ["title", "thesis", "executive_summary", "developments", "sector_impacts", "watch_next_week"],
    },
}


class ClaudeNewsletterProvider(_ClaudeToolProvider):
    name = "claude"
    tool = NEWSLETTER_TOOL
    max_tokens = 7000

    def _default_model(self) -> str:
        return OPUS_MODEL


def prior_week_window(today: date | None = None) -> tuple[str, str]:
    """Return the prior Monday-Sunday window in America/Toronto."""
    if today is None:
        today = datetime.now(ZoneInfo("America/Toronto")).date()
    current_monday = today - timedelta(days=today.weekday())
    start = current_monday - timedelta(days=7)
    end = start + timedelta(days=6)
    return start.isoformat(), end.isoformat()


def _clean_text(value: Any, limit: int = 420) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def _candidate(
    *,
    table: str,
    pk: int,
    source: str,
    title: str,
    date_value: str | None,
    record_type: str,
    summary: str | None = None,
    url: str | None = None,
    entity: str | None = None,
    amount: float | None = None,
    source_category: str = "other",
    materiality: float = 1.0,
) -> dict[str, Any]:
    text = " ".join([title or "", summary or "", entity or "", source or "", record_type or ""])
    sectors = sectors_for_text(text)
    return {
        "table": table,
        "pk": pk,
        "id": f"{table}:{pk}",
        "source": source,
        "title": _clean_text(title, 180) or "Untitled record",
        "date": date_value,
        "record_type": record_type,
        "summary": _clean_text(summary, 420),
        "url": url,
        "entity": _clean_text(entity, 120) or None,
        "amount": amount,
        "source_category": source_category,
        "sectors": sectors or [{"slug": "cross-sector", "name": "Cross-sector"}],
        "materiality": materiality,
        "internal_url": f"/records/{table}/{pk}",
    }


def sectors_for_text(text: str) -> list[dict[str, str]]:
    haystack = text.lower()
    matches: list[dict[str, str]] = []
    for sector in EDITORIAL_SECTORS:
        if any(keyword in haystack for keyword in sector.keywords):
            matches.append({"slug": sector.slug, "name": sector.name})
    return matches[:4]


def _source_weight(category: str) -> float:
    return {
        "legislation": 8.0,
        "regulation": 7.0,
        "lobbying": 6.0,
        "procurement": 5.0,
        "parliament": 5.0,
        "news_publications": 4.0,
        "operations": 3.0,
    }.get(category, 2.0)


def rank_candidates(candidates: list[dict[str, Any]], limit: int = MAX_CANDIDATES_FOR_OPUS) -> list[dict[str, Any]]:
    seen_titles: set[str] = set()
    ranked: list[dict[str, Any]] = []
    for item in candidates:
        title_key = re.sub(r"[^a-z0-9]+", " ", item["title"].lower()).strip()[:100]
        if title_key in seen_titles:
            continue
        seen_titles.add(title_key)
        amount = float(item.get("amount") or 0)
        money_bonus = 2.0 if amount >= 10_000_000 else 1.0 if amount >= 1_000_000 else 0.0
        sector_bonus = min(len(item.get("sectors") or []), 3) * 0.6
        summary_bonus = 0.7 if item.get("summary") else 0.0
        score = float(item.get("materiality") or 1) + _source_weight(item["source_category"]) + money_bonus + sector_bonus + summary_bonus
        ranked.append({**item, "score": round(score, 3)})
    ranked.sort(key=lambda row: (row["score"], row.get("date") or ""), reverse=True)
    return ranked[:limit]


def _between(column, start: str, end: str):
    return column.isnot(None) & (column >= start) & (column <= end)


async def gather_weekly_candidates(session: AsyncSession, week_start: str, week_end: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []

    bills = (
        await session.execute(
            select(Bill)
            .where(_between(Bill.introduced_date, week_start, week_end))
            .order_by(Bill.introduced_date.desc(), Bill.id.desc())
            .limit(30)
        )
    ).scalars().all()
    for row in bills:
        candidates.append(_candidate(
            table="bills", pk=row.id, source=row.source, title=f"{row.bill_number} - {row.title_en or ''}",
            date_value=row.introduced_date, record_type="bill", summary="; ".join(filter(None, [row.status, row.latest_activity, row.sponsor])),
            source_category="legislation", materiality=4.0,
        ))

    gazette = (
        await session.execute(
            select(GazetteEntry)
            .where(_between(GazetteEntry.published_date, week_start, week_end))
            .order_by(GazetteEntry.published_date.desc(), GazetteEntry.id.desc())
            .limit(35)
        )
    ).scalars().all()
    for row in gazette:
        candidates.append(_candidate(
            table="gazette", pk=row.id, source="Canada Gazette", title=row.title,
            date_value=row.published_date, record_type=f"gazette_part_{row.gazette_part}",
            summary=row.description, url=row.url, entity=row.department,
            source_category="regulation", materiality=4.0 if row.gazette_part == "II" else 3.0,
        ))

    tribunal = (
        await session.execute(
            select(TribunalDecision)
            .where(_between(TribunalDecision.decision_date, week_start, week_end))
            .order_by(TribunalDecision.decision_date.desc(), TribunalDecision.id.desc())
            .limit(30)
        )
    ).scalars().all()
    for row in tribunal:
        candidates.append(_candidate(
            table="tribunal", pk=row.id, source=row.body, title=row.title,
            date_value=row.decision_date, record_type="tribunal_decision",
            summary="; ".join(filter(None, [row.outcome, row.summary])), url=row.url,
            entity=row.parties, source_category="regulation", materiality=4.0,
        ))

    lobbying = (
        await session.execute(
            select(LobbyingRecord)
            .where(_between(LobbyingRecord.communication_date, week_start, week_end))
            .order_by(LobbyingRecord.communication_date.desc(), LobbyingRecord.id.desc())
            .limit(45)
        )
    ).scalars().all()
    for row in lobbying:
        subjects = ", ".join((row.subject_matters or [])[:4])
        institutions = ", ".join((row.institutions or [])[:4])
        candidates.append(_candidate(
            table="lobbying", pk=row.id, source=row.source, title=f"{row.client} lobbying communication",
            date_value=row.communication_date, record_type="lobbying_communication",
            summary="; ".join(filter(None, [subjects, institutions, row.registrant])),
            entity=row.client, source_category="lobbying", materiality=3.5,
        ))

    registrations = (
        await session.execute(
            select(OCLRegistration)
            .where(_between(OCLRegistration.effective_date, week_start, week_end))
            .order_by(OCLRegistration.effective_date.desc(), OCLRegistration.id.desc())
            .limit(25)
        )
    ).scalars().all()
    for row in registrations:
        candidates.append(_candidate(
            table="ocl_registrations", pk=row.id, source=row.source, title=f"{row.client_org} lobbying registration",
            date_value=row.effective_date, record_type="lobbying_registration",
            summary=", ".join((row.subject_matters or [])[:5]), entity=row.client_org,
            source_category="lobbying", materiality=3.0,
        ))

    appointments = (
        await session.execute(
            select(Appointment)
            .where(_between(Appointment.appointment_date, week_start, week_end))
            .order_by(Appointment.appointment_date.desc(), Appointment.id.desc())
            .limit(25)
        )
    ).scalars().all()
    for row in appointments:
        candidates.append(_candidate(
            table="appointments", pk=row.id, source=row.source,
            title=f"{row.appointee_name} - {row.position_title or row.organization or 'appointment'}",
            date_value=row.appointment_date, record_type="appointment",
            summary="; ".join(filter(None, [row.organization, row.appointment_type, row.remuneration])),
            entity=row.organization or row.appointee_name, source_category="regulation", materiality=2.8,
        ))

    contracts = (
        await session.execute(
            select(Contract)
            .where(_between(Contract.contract_date, week_start, week_end))
            .order_by(Contract.contract_value.desc().nullslast(), Contract.contract_date.desc())
            .limit(35)
        )
    ).scalars().all()
    for row in contracts:
        candidates.append(_candidate(
            table="contracts", pk=row.id, source=row.source,
            title=f"{row.vendor_name} contract with {row.owner_org_title or 'the federal government'}",
            date_value=row.contract_date, record_type="contract", summary=row.description,
            entity=row.vendor_name, amount=row.contract_value, source_category="procurement", materiality=2.5,
        ))

    grants = (
        await session.execute(
            select(Grant)
            .where(_between(Grant.agreement_start, week_start, week_end))
            .order_by(Grant.agreement_value.desc().nullslast(), Grant.agreement_start.desc())
            .limit(30)
        )
    ).scalars().all()
    for row in grants:
        candidates.append(_candidate(
            table="grants", pk=row.id, source=row.source,
            title=f"{row.recipient_name} funding agreement",
            date_value=row.agreement_start, record_type="grant", summary="; ".join(filter(None, [row.program_name, row.description])),
            entity=row.recipient_name, amount=row.agreement_value, source_category="procurement", materiality=2.5,
        ))

    hansard = (
        await session.execute(
            select(HansardSpeech)
            .where(_between(HansardSpeech.sitting_date, week_start, week_end))
            .order_by(HansardSpeech.sitting_date.desc(), HansardSpeech.id.desc())
            .limit(35)
        )
    ).scalars().all()
    for row in hansard:
        candidates.append(_candidate(
            table="hansard_speeches", pk=row.id, source=row.source,
            title=f"{row.speaker or 'House intervention'} - {row.subject or 'Hansard'}",
            date_value=row.sitting_date, record_type="hansard_speech",
            summary=row.content, url=row.url, entity=row.speaker,
            source_category="parliament", materiality=2.7,
        ))

    mentions = (
        await session.execute(
            select(HansardMention)
            .where(_between(HansardMention.speech_date, week_start, week_end))
            .order_by(HansardMention.speech_date.desc(), HansardMention.id.desc())
            .limit(25)
        )
    ).scalars().all()
    for row in mentions:
        candidates.append(_candidate(
            table="hansard_mentions", pk=row.id, source=row.source,
            title=f"{row.speaker or 'House intervention'} raised {row.keyword}",
            date_value=row.speech_date, record_type="hansard_mention",
            summary=row.excerpt, url=row.speech_url, entity=row.speaker,
            source_category="parliament", materiality=2.4,
        ))

    source_records = (
        await session.execute(
            select(SourceRecord)
            .where(_between(SourceRecord.event_date, week_start, week_end))
            .order_by(SourceRecord.event_date.desc(), SourceRecord.id.desc())
            .limit(80)
        )
    ).scalars().all()
    for row in source_records:
        category = "news_publications" if row.source.endswith("_news") or row.source in {"gc_news", "conversation_ca_politics"} or "news" in (row.record_type or "") else "operations"
        if row.source == "house_votes":
            category = "parliament"
        candidates.append(_candidate(
            table="source_records", pk=row.id, source=row.source,
            title=row.title, date_value=row.event_date, record_type=row.record_type or "source_record",
            summary=row.summary, url=row.url, entity=row.entity_name or row.canonical_name,
            amount=row.amount, source_category=category, materiality=3.2 if category == "news_publications" else 2.3,
        ))

    return rank_candidates(candidates)


def chart_data(candidates: list[dict[str, Any]], draft: dict[str, Any] | None = None) -> dict[str, Any]:
    sector_counts = {sector.name: 0 for sector in EDITORIAL_SECTORS}
    source_mix: dict[str, int] = {}
    for item in candidates:
        source_mix[item["source_category"]] = source_mix.get(item["source_category"], 0) + 1
        names = {s["name"] for s in item.get("sectors") or []}
        for name in names:
            if name in sector_counts:
                sector_counts[name] += 1
    top_source = max(source_mix.items(), key=lambda row: row[1])[0] if source_mix else "none"
    developments = (draft or {}).get("developments") or []
    affected = sorted({s for dev in developments for s in (dev.get("sectors") or [])}) or [
        name for name, count in sector_counts.items() if count
    ]
    timeline = sorted(
        [
            {"date": c.get("date"), "title": c["title"], "source": c["source"], "id": c["id"]}
            for c in candidates[:10]
            if c.get("date")
        ],
        key=lambda row: row["date"],
    )
    return {
        "metrics": {
            "records_reviewed": len(candidates),
            "major_developments": len(developments),
            "sectors_affected": len(set(affected)),
            "top_source_category": top_source.replace("_", " ").title(),
        },
        "sector_heatmap": [{"sector": name, "count": count} for name, count in sector_counts.items()],
        "source_mix": [{"category": key.replace("_", " ").title(), "count": value} for key, value in sorted(source_mix.items())],
        "timeline": timeline,
    }


def _prompt(week_start: str, week_end: str, candidates: list[dict[str, Any]]) -> str:
    allowed = [{"table": c["table"], "pk": c["pk"], "title": c["title"]} for c in candidates]
    return (
        "Build the Weekly Political Intelligence newsletter for Canadian strategic readers.\n"
        f"Window: {week_start} through {week_end}.\n"
        "Audience: corporate strategy/development, PE/VC, GR/public affairs, consultants, lawyers, executives, institutional investors, and research teams.\n"
        "Voice: strategic, sober, useful, concise, evidence-led. Do not sound like a generic news digest.\n"
        "Length: 900-1,200 words across the visible newsletter prose.\n"
        "Rules:\n"
        "- Use only the provided candidate records.\n"
        "- Every development, sector impact, and watch item must cite one or more ALLOWED_RECORD_IDS.\n"
        "- Do not invent dates, names, values, source facts, or external context.\n"
        "- Prefer cross-sector implications over chronology.\n"
        "- Treat news/government publication summaries as snippet-only evidence; do not quote long text.\n"
        "- Return only the forced tool call.\n\n"
        f"ALLOWED_RECORD_IDS:\n{json.dumps(allowed, ensure_ascii=False)}\n\n"
        f"CANDIDATE_RECORDS:\n{json.dumps(candidates, ensure_ascii=False, default=str)[:60000]}"
    )


async def _call_opus(week_start: str, week_end: str, candidates: list[dict[str, Any]]) -> tuple[dict[str, Any], str]:
    provider = ClaudeNewsletterProvider(model=OPUS_MODEL)
    system = (
        "You are Nessus Intelligence's senior Canadian political-risk editor. "
        "You write cited weekly intelligence for professional decisions affected "
        "by Canadian government action. You never cite records outside the allowed list."
    )
    turn = await provider.call(system, _prompt(week_start, week_end, candidates))
    draft = turn.tool_input
    result = validate_draft(draft, candidates)
    if not result["ok"]:
        correction = (
            "Your newsletter draft failed validation:\n"
            + "\n".join(f"- {error}" for error in result["errors"])
            + "\n\nCall build_weekly_newsletter again. Fix only these issues. "
            "Keep all citations inside ALLOWED_RECORD_IDS and hit 900-1,200 words."
        )
        turn = await provider.continue_call(system, _provider_turn(turn), correction)
        draft = turn.tool_input
    return draft, provider.model


def _provider_turn(turn: ProviderTurn) -> ProviderTurn:
    return turn


def _citation_key(ref: dict[str, Any]) -> tuple[str, str]:
    return str(ref.get("table")), str(ref.get("pk"))


def _draft_citations(draft: dict[str, Any]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for dev in draft.get("developments") or []:
        out.extend(_citation_key(c) for c in dev.get("citations") or [])
    for impact in draft.get("sector_impacts") or []:
        out.extend(_citation_key(c) for c in impact.get("citations") or [])
    for item in draft.get("watch_next_week") or []:
        out.extend(_citation_key(c) for c in item.get("citations") or [])
    return out


def _draft_text(draft: dict[str, Any]) -> str:
    parts: list[str] = [draft.get("title", ""), draft.get("thesis", "")]
    parts.extend(draft.get("executive_summary") or [])
    for dev in draft.get("developments") or []:
        parts.extend([dev.get("headline", ""), dev.get("summary", ""), dev.get("why_it_matters", "")])
    for impact in draft.get("sector_impacts") or []:
        parts.append(impact.get("impact", ""))
    for item in draft.get("watch_next_week") or []:
        parts.append(item.get("text", ""))
    return " ".join(str(p or "") for p in parts)


def word_count(draft: dict[str, Any]) -> int:
    return len(re.findall(r"\b[\w'-]+\b", _draft_text(draft)))


def validate_draft(draft: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    errors: list[str] = []
    allowed = {(str(c["table"]), str(c["pk"])) for c in candidates}
    wc = word_count(draft)
    if wc < MIN_WORDS or wc > MAX_WORDS:
        errors.append(f"word_count_outside_range:{wc}")
    developments = draft.get("developments") or []
    if not (4 <= len(developments) <= 6):
        errors.append(f"development_count_invalid:{len(developments)}")
    for index, dev in enumerate(developments):
        if not dev.get("citations"):
            errors.append(f"development_{index}_missing_citations")
    for index, impact in enumerate(draft.get("sector_impacts") or []):
        if not impact.get("citations"):
            errors.append(f"sector_impact_{index}_missing_citations")
    for index, item in enumerate(draft.get("watch_next_week") or []):
        if not item.get("citations"):
            errors.append(f"watch_{index}_missing_citations")
    invalid = [key for key in _draft_citations(draft) if key not in allowed]
    if invalid:
        errors.append(f"citations_outside_candidates:{invalid[:8]}")
    return {"ok": not errors, "errors": errors, "word_count": wc}


def _ref_for_candidate(c: dict[str, Any]) -> dict[str, Any]:
    return {
        "table": c["table"], "pk": c["pk"], "id": c["pk"],
        # EvidenceReference requires non-empty source/title; some records
        # (e.g. blank-source contracts) would otherwise 500 response validation.
        "source": c.get("source") or "Public record",
        "title": c.get("title") or "Untitled record",
        "date": c.get("date"),
        "url": c.get("url"), "record_type": c.get("record_type") or "record",
        "sector": ", ".join(s["name"] for s in c.get("sectors") or [] if s.get("name")),
        "confidence": "retrieved", "amount": c.get("amount"),
    }


def _cited_source_references(draft: dict[str, Any], candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key = {(str(c["table"]), str(c["pk"])): c for c in candidates}
    refs: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for key in _draft_citations(draft):
        if key in seen or key not in by_key:
            continue
        seen.add(key)
        refs.append(_ref_for_candidate(by_key[key]))
    return refs


def _footnote_numbers(refs: list[dict[str, Any]]) -> dict[tuple[str, str], int]:
    return {(str(ref["table"]), str(ref["pk"])): i for i, ref in enumerate(refs, start=1)}


def _fn_html(citations: list[dict[str, Any]], numbers: dict[tuple[str, str], int]) -> str:
    nums = []
    for citation in citations or []:
        n = numbers.get(_citation_key(citation))
        if n and n not in nums:
            nums.append(n)
    return "".join(f'<sup style="font-size:10px;color:#B9832F">[{n}]</sup>' for n in nums)


def _bar(width_pct: float, color: str) -> str:
    width = max(3, min(100, width_pct))
    return (
        '<div style="height:8px;background:#E5DED0;border-radius:999px;overflow:hidden">'
        f'<div style="height:8px;width:{width:.1f}%;background:{color};border-radius:999px"></div></div>'
    )


def render_newsletter_html(draft: dict[str, Any], visuals: dict[str, Any], refs: list[dict[str, Any]], week_start: str, week_end: str) -> str:
    numbers = _footnote_numbers(refs)
    metrics = visuals.get("metrics") or {}
    sector_heatmap = visuals.get("sector_heatmap") or []
    source_mix = visuals.get("source_mix") or []
    timeline = visuals.get("timeline") or []
    max_sector = max([row.get("count", 0) for row in sector_heatmap] or [1]) or 1
    max_source = max([row.get("count", 0) for row in source_mix] or [1]) or 1

    metric_cells = "".join(
        f'<td style="padding:14px 16px;border-right:1px solid #E5DED0"><div style="font-size:22px;font-weight:800;color:#193C34">{escape(str(value))}</div><div style="font-size:10px;text-transform:uppercase;letter-spacing:.08em;color:#736B5F">{escape(label)}</div></td>'
        for label, value in (
            ("Records reviewed", metrics.get("records_reviewed", 0)),
            ("Major developments", metrics.get("major_developments", 0)),
            ("Sectors affected", metrics.get("sectors_affected", 0)),
            ("Top source", metrics.get("top_source_category", "None")),
        )
    )
    summary = "".join(f"<li>{escape(item)}</li>" for item in draft.get("executive_summary") or [])
    developments = "".join(
        "<section style='padding:18px 0;border-top:1px solid #E9E1D2'>"
        f"<h2 style='margin:0 0 8px;font-size:21px;color:#193C34;line-height:1.18'>{escape(dev.get('headline',''))} {_fn_html(dev.get('citations') or [], numbers)}</h2>"
        f"<p style='margin:0 0 8px;color:#2C332C'>{escape(dev.get('summary',''))}</p>"
        f"<p style='margin:0;color:#5B554C'><strong style='color:#9A5E1F'>Why it matters:</strong> {escape(dev.get('why_it_matters',''))}</p>"
        "</section>"
        for dev in draft.get("developments") or []
    )
    sector_rows = "".join(
        f"<tr><td style='padding:9px 10px;border-bottom:1px solid #ECE4D6;color:#193C34;font-weight:700'>{escape(row.get('sector',''))}</td>"
        f"<td style='padding:9px 10px;border-bottom:1px solid #ECE4D6;color:#3C4239'>{escape(row.get('impact',''))} {_fn_html(row.get('citations') or [], numbers)}</td></tr>"
        for row in draft.get("sector_impacts") or []
    )
    watch = "".join(
        f"<li>{escape(item.get('text',''))} {_fn_html(item.get('citations') or [], numbers)}</li>"
        for item in draft.get("watch_next_week") or []
    )
    heat = "".join(
        "<tr>"
        f"<td style='padding:6px 10px 6px 0;font-size:12px;color:#3C4239;width:44%'>{escape(row['sector'])}</td>"
        f"<td style='padding:6px 0'>{_bar((row.get('count', 0) / max_sector) * 100, '#1F6F55')}</td>"
        f"<td style='padding:6px 0 6px 8px;font-size:11px;color:#736B5F;text-align:right'>{row.get('count', 0)}</td>"
        "</tr>"
        for row in sector_heatmap
    )
    mix = "".join(
        "<tr>"
        f"<td style='padding:6px 10px 6px 0;font-size:12px;color:#3C4239;width:38%'>{escape(row['category'])}</td>"
        f"<td style='padding:6px 0'>{_bar((row.get('count', 0) / max_source) * 100, '#B9832F')}</td>"
        f"<td style='padding:6px 0 6px 8px;font-size:11px;color:#736B5F;text-align:right'>{row.get('count', 0)}</td>"
        "</tr>"
        for row in source_mix
    )
    timeline_html = "".join(
        f"<li style='margin-bottom:8px'><strong>{escape(str(item.get('date') or ''))}</strong> - {escape(item.get('title',''))}</li>"
        for item in timeline[:6]
    )
    footnotes = "".join(
        f"<li id='fn-{i}' style='margin-bottom:8px'><strong>[{i}]</strong> {escape(ref.get('source',''))}: "
        f"<a href='/records/{escape(str(ref['table']))}/{escape(str(ref['pk']))}' style='color:#1F6F55'>{escape(ref.get('title',''))}</a>"
        + (f" <span style='color:#8B8374'>({escape(str(ref.get('date') or 'undated'))})</span>" if ref.get("date") else "")
        + (f" - <a href='{escape(ref['url'])}' style='color:#1F6F55'>original</a>" if ref.get("url") else "")
        + "</li>"
        for i, ref in enumerate(refs, start=1)
    )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(draft.get('title') or 'Weekly Political Intelligence')}</title></head>
<body style="margin:0;background:#F5F0E7;color:#262B25;font-family:Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;line-height:1.55">
<div style="max-width:760px;margin:0 auto;background:#FFFDF8">
  <div style="background:#193C34;color:#FFF7E8;padding:30px 34px 26px">
    <div style="font-size:11px;letter-spacing:.16em;text-transform:uppercase;color:#D2B074;font-weight:700">Nessus Intelligence · Weekly Political Intelligence</div>
    <h1 style="font-size:34px;line-height:1.05;margin:12px 0 8px">{escape(draft.get('title') or 'Weekly Political Intelligence')}</h1>
    <p style="margin:0;color:#E6D8BD;font-size:14px">{escape(week_start)} to {escape(week_end)}</p>
  </div>
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-bottom:1px solid #E5DED0;background:#FBF6EC"><tr>{metric_cells}</tr></table>
  <main style="padding:28px 34px">
    <section style="margin-bottom:22px">
      <h2 style="font-size:14px;letter-spacing:.12em;text-transform:uppercase;color:#B9832F;margin:0 0 8px">This week&apos;s read</h2>
      <p style="font-size:19px;line-height:1.42;margin:0;color:#193C34;font-weight:700">{escape(draft.get('thesis') or '')}</p>
      <ul style="margin:14px 0 0;padding-left:20px;color:#3C4239">{summary}</ul>
    </section>
    <section style="display:block;border:1px solid #E5DED0;background:#FBF8F1;padding:16px;margin-bottom:24px">
      <h2 style="margin:0 0 12px;color:#193C34;font-size:16px">Signal Map</h2>
      <table width="100%" cellspacing="0" cellpadding="0" style="margin-bottom:12px">{heat}</table>
      <h3 style="font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:#736B5F;margin:14px 0 4px">Source mix</h3>
      <table width="100%" cellspacing="0" cellpadding="0">{mix}</table>
    </section>
    <section style="margin-bottom:24px">
      <h2 style="margin:0 0 10px;color:#193C34;font-size:16px">Weekly Timeline</h2>
      <ol style="margin:0;padding-left:20px;color:#3C4239">{timeline_html}</ol>
    </section>
    {developments}
    <section style="margin-top:24px">
      <h2 style="margin:0 0 10px;color:#193C34;font-size:20px">Sector Implications</h2>
      <table width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;border-top:2px solid #193C34">{sector_rows}</table>
    </section>
    <section style="margin-top:24px;background:#193C34;color:#FFF7E8;padding:18px">
      <h2 style="margin:0 0 8px;color:#FFF7E8;font-size:19px">What To Watch Next Week</h2>
      <ul style="margin:0;padding-left:20px;color:#F0E5CF">{watch}</ul>
    </section>
    <section style="margin-top:26px;border-top:1px solid #E5DED0;padding-top:18px">
      <h2 style="margin:0 0 10px;color:#193C34;font-size:16px">Sources</h2>
      <ol style="margin:0;padding-left:20px;font-size:12px;color:#4B5149">{footnotes}</ol>
    </section>
  </main>
  <footer style="padding:18px 34px;background:#F5F0E7;color:#736B5F;font-size:11px">Generated by Nessus Intelligence from cited public-record evidence. Draft for internal strategic use.</footer>
</div></body></html>"""


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


def issue_response(issue: NewsletterIssue) -> dict[str, Any]:
    return {
        **_summary(issue),
        "sections": issue.sections or {},
        "visuals": issue.visuals or {},
        "evidence": issue.evidence or {},
        "source_references": issue.source_references or [],
        "validation": issue.validation or {},
        "html": issue.html or "",
    }


async def generate_newsletter_issue(
    session: AsyncSession,
    *,
    week_start: str | None = None,
    week_end: str | None = None,
    draft_override: dict[str, Any] | None = None,
) -> NewsletterIssue:
    if not week_start or not week_end:
        week_start, week_end = prior_week_window()
    candidates = await gather_weekly_candidates(session, week_start, week_end)
    if len(candidates) < 4:
        raise NewsletterGenerationError(f"insufficient evidence for {week_start} to {week_end}: {len(candidates)} candidate records")

    try:
        if draft_override is None:
            draft, model = await _call_opus(week_start, week_end, candidates)
        else:
            draft, model = draft_override, OPUS_MODEL
    except ProviderUnavailable as exc:
        raise NewsletterGenerationError("Claude Opus API is not configured; ANTHROPIC_API_KEY is required") from exc
    except ProviderError as exc:
        raise NewsletterGenerationError(f"Claude Opus generation failed: {exc}") from exc

    validation = validate_draft(draft, candidates)
    if not validation["ok"]:
        raise NewsletterGenerationError(f"newsletter validation failed: {validation['errors']}")

    refs = _cited_source_references(draft, candidates)
    visuals = chart_data(candidates, draft)
    html = render_newsletter_html(draft, visuals, refs, week_start, week_end)
    issue = NewsletterIssue(
        week_start=week_start,
        week_end=week_end,
        title=str(draft.get("title") or "Weekly Political Intelligence")[:255],
        status="generated",
        generated_by="claude",
        model=model,
        word_count=int(validation["word_count"]),
        sections=draft,
        visuals=visuals,
        evidence={"candidate_count": len(candidates), "candidates": candidates},
        source_references=refs,
        validation=validation,
        html=html,
    )
    session.add(issue)
    await session.commit()
    return issue

