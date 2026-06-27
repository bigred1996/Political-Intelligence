"""Weekly political-intelligence newsletter generation.

This module is deliberately separate from company diligence reports. A weekly
issue is time-window and sector anchored: gather candidate records from the
platform, rank/de-dupe them, hand the model deterministic connection hints,
ask Opus for a *structured edited issue* (not a block of HTML), validate the
draft, optionally run one editor-review revision, then render email-safe HTML
with a deterministic renderer so the in-app preview can never drift from what
is exported.

Editorial shape (one coherent issue, not a list of DB rows):
  masthead → opening note → what matters today → lead story → by the numbers
  → supporting stories → on the radar → closing analysis → sources → footer

All model-supplied text is HTML-escaped at render time — the renderer never
emits model-authored markup, which is the sanitisation guarantee (there is no
trusted-HTML path from the model to a reader).
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

from api.config import settings
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
MIN_CANDIDATES = 6
MAX_SUPPORTING_STORIES = 3


class NewsletterGenerationError(RuntimeError):
    """Generation failed before a publishable issue could be saved."""


# --- Brand tokens (Nessus logo package + intelligence_grade DESIGN.md) --------
NAVY = "#041632"          # Parliament Navy
NAVY_SURFACE = "#1B2B48"  # Navy Surface
GOLD = "#C6A15B"          # Nessus Gold
DOC_WHITE = "#F7F9FB"     # Document White
INK = "#191C1E"
MUTED = "#44474D"
BORDER = "#D9DADD"
PAGE_BG = "#E6E8EA"
POSITIVE = "#3FA37D"
WARNING = "#C9953B"

SERIF = "'Source Serif 4', Georgia, 'Times New Roman', serif"
SANS = "'Public Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"


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


# --- Structured generation tool ------------------------------------------------
_CITATION = {
    "type": "object",
    "properties": {"table": {"type": "string"}, "pk": {"type": ["string", "integer"]}},
    "required": ["table", "pk"],
}
_CITATIONS = {"type": "array", "items": _CITATION}
_STORY = {
    "type": "object",
    "properties": {
        "eyebrow": {"type": "string", "description": "Short uppercase kicker, e.g. 'REGULATORY' or 'PROCUREMENT'."},
        "headline": {"type": "string", "description": "Specific analytical headline — never generic."},
        "standfirst": {"type": "string", "description": "One or two sentence summary under the headline."},
        "sections": {
            "type": "array",
            "minItems": 2,
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string", "description": "Optional analytical label, e.g. 'The fine print', 'The political dynamic', 'What comes next'."},
                    "body": {"type": "string"},
                },
                "required": ["body"],
            },
        },
        "citations": _CITATIONS,
    },
    "required": ["headline", "sections", "citations"],
}

NEWSLETTER_TOOL: dict[str, Any] = {
    "name": "build_weekly_newsletter",
    "description": (
        "Compose ONE coherent, edited weekly Canadian political-intelligence "
        "issue for strategy, investor, legal, GR, and executive readers. "
        "Prioritise — do not give every record equal space. Synthesise related "
        "records into single stories and explain the mechanism connecting them. "
        "Cite only ALLOWED_RECORD_IDS. Never invent dates, names, values, URLs, "
        "or causal claims."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Specific issue title. Never 'Weekly Political Update'."},
            "preheader": {"type": "string", "description": "Hidden inbox preview line, <=140 chars, no greeting."},
            "opening_note": {"type": "string", "description": "50-90 words establishing the issue's theme and the single most important implication."},
            "key_points": {
                "type": "array",
                "minItems": 2,
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "properties": {
                        "development": {"type": "string"},
                        "significance": {"type": "string", "description": "The immediate so-what, not a restatement."},
                    },
                    "required": ["development", "significance"],
                },
            },
            "lead_story": _STORY,
            "supporting_stories": {"type": "array", "minItems": 2, "maxItems": 3, "items": _STORY},
            "statistics": {
                "type": "array",
                "minItems": 3,
                "maxItems": 5,
                "items": {
                    "type": "object",
                    "properties": {
                        "value": {"type": "string", "description": "The figure as a display string, e.g. '$3.4B' or '12 days'."},
                        "label": {"type": "string"},
                        "significance": {"type": "string", "description": "One sentence on why the figure matters."},
                        "citation": _CITATION,
                    },
                    "required": ["value", "label", "significance"],
                },
            },
            "radar_items": {
                "type": "array",
                "minItems": 3,
                "maxItems": 5,
                "items": {
                    "type": "object",
                    "properties": {
                        "headline": {"type": "string"},
                        "summary": {"type": "string"},
                        "next_milestone": {"type": "string", "description": "The next decision/deadline/hearing/vote/report."},
                        "citation": _CITATION,
                    },
                    "required": ["headline", "summary"],
                },
            },
            "closing_analysis": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "e.g. 'The bottom line', 'The Nessus view', 'What to watch'."},
                    "body": {"type": "string", "description": "The broader pattern + what evidence would change the read. Must NOT repeat the opening note."},
                },
                "required": ["title", "body"],
            },
        },
        "required": [
            "title", "preheader", "opening_note", "key_points",
            "lead_story", "supporting_stories", "statistics", "radar_items", "closing_analysis",
        ],
    },
}


class ClaudeNewsletterProvider(_ClaudeToolProvider):
    name = "claude"
    tool = NEWSLETTER_TOOL
    max_tokens = 8000

    def _default_model(self) -> str:
        return OPUS_MODEL


# --- Optional editor-review pass ----------------------------------------------
REVIEW_TOOL: dict[str, Any] = {
    "name": "review_weekly_newsletter",
    "description": "Score a drafted weekly intelligence issue 1-10 on each dimension and flag whether a single targeted revision is warranted.",
    "input_schema": {
        "type": "object",
        "properties": {
            "scores": {
                "type": "object",
                "properties": {dim: {"type": "integer"} for dim in (
                    "evidence_grounding", "editorial_hierarchy", "content_flow",
                    "analytical_value", "readability", "visual_balance",
                    "repetition", "source_attribution", "audience_relevance", "mobile_suitability",
                )},
            },
            "revision_instruction": {"type": "string", "description": "Specific, actionable fixes for the lowest-scoring dimensions only."},
        },
        "required": ["scores", "revision_instruction"],
    },
}


class ClaudeNewsletterReviewer(_ClaudeToolProvider):
    name = "claude"
    tool = REVIEW_TOOL
    max_tokens = 1200

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
    canonical: str | None = None,
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
        "canonical": (canonical or "").strip().lower() or None,
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


def connection_clusters(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deterministic cross-record links handed to the model so it synthesises
    rather than infers from raw text. Groups records that share a canonical
    entity, then (separately) records that share an editorial sector."""
    by_entity: dict[str, list[dict[str, Any]]] = {}
    for c in candidates:
        key = c.get("canonical") or (c.get("entity") or "").lower()
        if key:
            by_entity.setdefault(key, []).append(c)
    clusters: list[dict[str, Any]] = []
    for key, group in by_entity.items():
        if len(group) >= 2:
            clusters.append({
                "type": "same_entity",
                "entity": group[0].get("entity") or key,
                "ids": [{"table": g["table"], "pk": g["pk"]} for g in group[:6]],
                "sources": sorted({g["source_category"] for g in group}),
            })

    by_sector: dict[str, list[dict[str, Any]]] = {}
    for c in candidates:
        for sec in c.get("sectors") or []:
            by_sector.setdefault(sec["name"], []).append(c)
    for name, group in by_sector.items():
        cats = {g["source_category"] for g in group}
        # Only worth flagging when the sector is touched from >=2 record types
        # (e.g. legislation AND lobbying) — that is a real "mechanism" to explain.
        if len(group) >= 3 and len(cats) >= 2 and name != "Cross-sector":
            clusters.append({
                "type": "same_sector",
                "sector": name,
                "ids": [{"table": g["table"], "pk": g["pk"]} for g in group[:6]],
                "sources": sorted(cats),
            })
    return clusters[:10]


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
            entity=row.sponsor, source_category="legislation", materiality=4.0,
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
            entity=row.client, canonical=row.canonical_name, source_category="lobbying", materiality=3.5,
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
            canonical=row.canonical_name, source_category="lobbying", materiality=3.0,
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
            entity=row.vendor_name, canonical=row.canonical_name, amount=row.contract_value,
            source_category="procurement", materiality=2.5,
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
            entity=row.recipient_name, canonical=row.canonical_name, amount=row.agreement_value,
            source_category="procurement", materiality=2.5,
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
            canonical=row.canonical_name, amount=row.amount, source_category=category,
            materiality=3.2 if category == "news_publications" else 2.3,
        ))

    return rank_candidates(candidates)


# --- Draft normalisation ------------------------------------------------------
# The Anthropic tool API does not hard-enforce input_schema, so a model turn can
# return loose shapes (a string where an object is expected, a missing list).
# Normalise once after every turn so validation and rendering operate on a
# predictable structure and can never crash on a malformed draft.
def _norm_citations(value: Any) -> list[dict[str, Any]]:
    items = value if isinstance(value, list) else [value] if value else []
    return [c for c in items if isinstance(c, dict) and c.get("table") is not None and c.get("pk") is not None]


def _norm_story(value: Any) -> dict[str, Any]:
    story = value if isinstance(value, dict) else {}
    sections = []
    for section in story.get("sections") or []:
        if isinstance(section, dict):
            sections.append({"label": section.get("label"), "body": str(section.get("body") or "")})
        elif section:
            sections.append({"label": None, "body": str(section)})
    return {
        "eyebrow": story.get("eyebrow"),
        "headline": str(story.get("headline") or ""),
        "standfirst": story.get("standfirst"),
        "sections": sections,
        "citations": _norm_citations(story.get("citations")),
    }


def _norm_single_citation(value: Any) -> dict[str, Any] | None:
    cites = _norm_citations(value)
    return cites[0] if cites else None


def _normalize_draft(draft: Any) -> dict[str, Any]:
    d = dict(draft or {})
    key_points = []
    for point in d.get("key_points") or []:
        if isinstance(point, dict):
            key_points.append({"development": str(point.get("development") or ""), "significance": str(point.get("significance") or "")})
        elif point:
            key_points.append({"development": str(point), "significance": ""})
    d["key_points"] = key_points
    d["lead_story"] = _norm_story(d.get("lead_story"))
    d["supporting_stories"] = [_norm_story(s) for s in d.get("supporting_stories") or []]

    stats = []
    for stat in d.get("statistics") or []:
        if isinstance(stat, dict):
            stats.append({
                "value": str(stat.get("value") or ""), "label": str(stat.get("label") or ""),
                "significance": str(stat.get("significance") or ""), "citation": _norm_single_citation(stat.get("citation")),
            })
    d["statistics"] = stats

    radar = []
    for item in d.get("radar_items") or []:
        if isinstance(item, dict):
            radar.append({
                "headline": str(item.get("headline") or ""), "summary": str(item.get("summary") or ""),
                "next_milestone": item.get("next_milestone"), "citation": _norm_single_citation(item.get("citation")),
            })
    d["radar_items"] = radar

    closing = d.get("closing_analysis")
    d["closing_analysis"] = closing if isinstance(closing, dict) else {"title": "", "body": str(closing or "")}
    return d


# --- Draft text + citation helpers --------------------------------------------
def _story_text(story: dict[str, Any]) -> list[str]:
    parts = [story.get("headline", ""), story.get("standfirst", "")]
    parts.extend(section.get("body", "") for section in story.get("sections") or [])
    return parts


def _visible_parts(draft: dict[str, Any]) -> list[str]:
    parts: list[str] = [draft.get("opening_note", "")]
    for point in draft.get("key_points") or []:
        parts.extend([point.get("development", ""), point.get("significance", "")])
    parts.extend(_story_text(draft.get("lead_story") or {}))
    for story in draft.get("supporting_stories") or []:
        parts.extend(_story_text(story))
    for stat in draft.get("statistics") or []:
        parts.append(stat.get("significance", ""))
    for item in draft.get("radar_items") or []:
        parts.extend([item.get("summary", ""), item.get("next_milestone", "")])
    parts.append((draft.get("closing_analysis") or {}).get("body", ""))
    return parts


def word_count(draft: dict[str, Any]) -> int:
    return len(re.findall(r"\b[\w'-]+\b", " ".join(str(p or "") for p in _visible_parts(draft))))


def _citation_key(ref: dict[str, Any]) -> tuple[str, str]:
    return str(ref.get("table")), str(ref.get("pk"))


def _draft_citations(draft: dict[str, Any]) -> list[tuple[str, str]]:
    """All citation keys, in render order, so footnote numbering is stable."""
    out: list[tuple[str, str]] = []
    out.extend(_citation_key(c) for c in (draft.get("lead_story") or {}).get("citations") or [])
    for story in draft.get("supporting_stories") or []:
        out.extend(_citation_key(c) for c in story.get("citations") or [])
    for stat in draft.get("statistics") or []:
        if stat.get("citation"):
            out.append(_citation_key(stat["citation"]))
    for item in draft.get("radar_items") or []:
        if item.get("citation"):
            out.append(_citation_key(item["citation"]))
    return out


def _headlines(draft: dict[str, Any]) -> list[str]:
    heads = [(draft.get("lead_story") or {}).get("headline", "")]
    heads.extend(story.get("headline", "") for story in draft.get("supporting_stories") or [])
    return [h.strip().lower() for h in heads if h.strip()]


def validate_draft(draft: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    errors: list[str] = []
    allowed = {(str(c["table"]), str(c["pk"])) for c in candidates}

    wc = word_count(draft)
    if wc < MIN_WORDS or wc > MAX_WORDS:
        errors.append(f"word_count_outside_range:{wc}")

    lead = draft.get("lead_story") or {}
    if not lead.get("headline"):
        errors.append("lead_story_missing")
    if not lead.get("citations"):
        errors.append("lead_story_missing_citations")

    supporting = draft.get("supporting_stories") or []
    if not (2 <= len(supporting) <= MAX_SUPPORTING_STORIES):
        errors.append(f"supporting_story_count_invalid:{len(supporting)}")
    for index, story in enumerate(supporting):
        if not story.get("citations"):
            errors.append(f"supporting_{index}_missing_citations")

    if not (2 <= len(draft.get("key_points") or []) <= 3):
        errors.append(f"key_points_count_invalid:{len(draft.get('key_points') or [])}")
    if not (3 <= len(draft.get("statistics") or []) <= 5):
        errors.append(f"statistics_count_invalid:{len(draft.get('statistics') or [])}")
    if not (3 <= len(draft.get("radar_items") or []) <= 5):
        errors.append(f"radar_count_invalid:{len(draft.get('radar_items') or [])}")

    heads = _headlines(draft)
    if len(heads) != len(set(heads)):
        errors.append("duplicate_headlines")

    opening = re.sub(r"\s+", " ", (draft.get("opening_note") or "")).strip().lower()
    closing = re.sub(r"\s+", " ", (draft.get("closing_analysis") or {}).get("body", "")).strip().lower()
    if opening and closing and opening == closing:
        errors.append("closing_duplicates_opening")

    invalid = [key for key in _draft_citations(draft) if key not in allowed]
    if invalid:
        errors.append(f"citations_outside_candidates:{invalid[:8]}")

    return {"ok": not errors, "errors": errors, "word_count": wc}


def _prompt(week_start: str, week_end: str, candidates: list[dict[str, Any]], clusters: list[dict[str, Any]]) -> str:
    allowed = [{"table": c["table"], "pk": c["pk"], "title": c["title"]} for c in candidates]
    return (
        "Compose the Weekly Political Intelligence issue for Canadian strategic readers.\n"
        f"Window: {week_start} through {week_end}.\n"
        "Audience: corporate strategy/development, PE/VC, GR/public affairs, consultants, lawyers, executives, institutional investors, and research teams.\n\n"
        "EDITORIAL DECISIONS YOU MUST MAKE:\n"
        "- Rank stories by consequence, novelty, political/regulatory momentum, audience relevance, evidence strength, and whether a decision/deadline/vote/hearing/consultation is coming.\n"
        "- Select ONE lead story, two or three supporting stories, three to five 'on the radar' items, and three to five statistics. Do not give every record equal space.\n"
        "- When multiple records describe the same underlying event, COMBINE them into one story and explain the mechanism connecting them (e.g. lobbying → legislation, announcement → funding, economic data → sector exposure). Use CONNECTION_HINTS below.\n\n"
        "FOR EACH STORY ANSWER: what changed, why it matters, who is affected, how developments connect, what could happen next, what to monitor. Use short analytical section labels where useful (The development, The fine print, The political dynamic, The business impact, The constraint, The signal, What comes next) — but do not force every label into every story.\n\n"
        "ANALYTICAL STANDARDS:\n"
        "- Distinguish confirmed facts from statements by political actors, reported expectations, Nessus analysis, and forward-looking scenarios. Never present an inference as confirmed fact.\n"
        "- Use calibrated language (suggests, indicates, could, is likely to, raises the possibility, would depend on). Reason: government action → regulatory/institutional change → sector exposure → possible consequence.\n"
        "- Account for jurisdictional limits, regulatory independence, Indigenous rights and consultation, funding uncertainty, legal challenges, political opposition, implementation capacity, timing risk, and the gap between an announcement and a binding decision.\n\n"
        "WRITING: Canadian English. Authoritative, analytical, concise, politically neutral, accessible, confident without overstating. Short paragraphs (1-3 sentences), strong verbs, concrete nouns, specific dates and amounts. Explain acronyms on first use. Avoid jargon, generic AI phrasing, repeated sentence structures, filler greetings, and clickbait.\n\n"
        f"LENGTH: the visible editorial prose MUST be {MIN_WORDS}-{MAX_WORDS} words.\n\n"
        "RULES:\n"
        "- Use only the provided candidate records. Every story, statistic, and radar item must cite ALLOWED_RECORD_IDS.\n"
        "- Do not invent dates, names, values, URLs, motivations, or causal relationships.\n"
        "- The closing analysis must NOT repeat the opening note; it should name what evidence would strengthen, weaken, or change the read.\n"
        "- Return only the forced tool call.\n\n"
        f"CONNECTION_HINTS (deterministic cross-record links — explain the mechanism, do not just assert relatedness):\n{json.dumps(clusters, ensure_ascii=False, default=str)}\n\n"
        f"ALLOWED_RECORD_IDS:\n{json.dumps(allowed, ensure_ascii=False)}\n\n"
        f"CANDIDATE_RECORDS:\n{json.dumps(candidates, ensure_ascii=False, default=str)[:60000]}"
    )


_SYSTEM = (
    "You are Nessus Intelligence's senior Canadian political-risk editor. You "
    "write cited weekly intelligence for professional decisions affected by "
    "Canadian government action. You synthesise across government, regulatory, "
    "political, economic, news, and proprietary records into a single edited "
    "issue. You never cite records outside the allowed list and never invent "
    "facts, figures, quotations, or URLs."
)


async def _call_opus(
    week_start: str, week_end: str, candidates: list[dict[str, Any]], clusters: list[dict[str, Any]],
) -> tuple[dict[str, Any], str, ClaudeNewsletterProvider, ProviderTurn]:
    provider = ClaudeNewsletterProvider(model=OPUS_MODEL)
    turn = await provider.call(_SYSTEM, _prompt(week_start, week_end, candidates, clusters))
    draft = _normalize_draft(turn.tool_input)
    result = validate_draft(draft, candidates)
    if not result["ok"]:
        correction = (
            "Your newsletter draft failed validation:\n"
            + "\n".join(f"- {error}" for error in result["errors"])
            + f"\n\nCall build_weekly_newsletter again. Fix only these issues. Keep all citations "
            f"inside ALLOWED_RECORD_IDS and the visible prose at {MIN_WORDS}-{MAX_WORDS} words."
        )
        turn = await provider.continue_call(_SYSTEM, turn, correction)
        draft = _normalize_draft(turn.tool_input)
    return draft, provider.model, provider, turn


async def _review_and_revise(
    provider: ClaudeNewsletterProvider, turn: ProviderTurn, draft: dict[str, Any], candidates: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """One optional editor pass: score the draft and, if any dimension is below
    8, run a single targeted revision. Bounded to exactly one revision."""
    reviewer = ClaudeNewsletterReviewer(model=OPUS_MODEL)
    review_prompt = (
        "Score this drafted weekly intelligence issue 1-10 on each dimension and give one "
        "specific revision instruction for the weakest dimensions only.\n\n"
        f"DRAFT:\n{json.dumps(draft, ensure_ascii=False, default=str)[:50000]}"
    )
    try:
        review = (await reviewer.call(_SYSTEM, review_prompt)).tool_input
    except (ProviderError, ProviderUnavailable):
        return draft, {"ran": False}
    scores = review.get("scores") or {}
    low = [k for k, v in scores.items() if isinstance(v, int) and v < 8]
    if not low or not review.get("revision_instruction"):
        return draft, {"ran": True, "revised": False, "scores": scores}
    instruction = (
        "Editor review flagged weaknesses in: " + ", ".join(low) + ".\n"
        + review["revision_instruction"]
        + f"\n\nCall build_weekly_newsletter again with a single improved version. Keep citations "
        f"inside ALLOWED_RECORD_IDS and the visible prose at {MIN_WORDS}-{MAX_WORDS} words."
    )
    try:
        revised = _normalize_draft((await provider.continue_call(_SYSTEM, turn, instruction)).tool_input)
    except (ProviderError, ProviderUnavailable):
        return draft, {"ran": True, "revised": False, "scores": scores}
    if validate_draft(revised, candidates)["ok"]:
        return revised, {"ran": True, "revised": True, "scores": scores}
    return draft, {"ran": True, "revised": False, "scores": scores}


# --- Source references + visuals ----------------------------------------------
def _ref_for_candidate(c: dict[str, Any]) -> dict[str, Any]:
    return {
        "table": c["table"], "pk": c["pk"], "id": c["pk"],
        # EvidenceReference requires non-empty source/title; some records
        # (e.g. blank-source contracts) would otherwise fail response validation.
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


def chart_data(candidates: list[dict[str, Any]], draft: dict[str, Any] | None = None) -> dict[str, Any]:
    sector_counts = {sector.name: 0 for sector in EDITORIAL_SECTORS}
    source_mix: dict[str, int] = {}
    for item in candidates:
        source_mix[item["source_category"]] = source_mix.get(item["source_category"], 0) + 1
        for name in {s["name"] for s in item.get("sectors") or []}:
            if name in sector_counts:
                sector_counts[name] += 1
    top_source = max(source_mix.items(), key=lambda row: row[1])[0] if source_mix else "none"

    draft = draft or {}
    story_count = (1 if (draft.get("lead_story") or {}).get("headline") else 0) + len(draft.get("supporting_stories") or [])
    cited_keys = set(_draft_citations(draft))
    by_key = {(str(c["table"]), str(c["pk"])): c for c in candidates}
    cited_sectors = {
        s["name"]
        for key in cited_keys
        for s in (by_key.get(key) or {}).get("sectors") or []
        if s.get("name") and s["name"] != "Cross-sector"
    }
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
            "major_developments": story_count,
            "sectors_affected": len(cited_sectors) or len([n for n, c in sector_counts.items() if c]),
            "top_source_category": top_source.replace("_", " ").title(),
        },
        "sector_heatmap": [{"sector": name, "count": count} for name, count in sector_counts.items()],
        "source_mix": [{"category": key.replace("_", " ").title(), "count": value} for key, value in sorted(source_mix.items())],
        "timeline": timeline,
    }


# --- Email-safe HTML renderer (deterministic; escapes all model text) ---------
def _asset(path: str) -> str:
    base = settings.public_base_url.rstrip("/")
    return f"{base}{path}" if base else path


def _fn_html(citations: list[dict[str, Any]] | dict[str, Any] | None, numbers: dict[tuple[str, str], int]) -> str:
    if not citations:
        return ""
    items = citations if isinstance(citations, list) else [citations]
    nums: list[int] = []
    for citation in items:
        n = numbers.get(_citation_key(citation))
        if n and n not in nums:
            nums.append(n)
    return "".join(f'<sup style="font-size:11px;color:{GOLD};font-weight:700">[{n}]</sup>' for n in nums)


def _eyebrow(text: str) -> str:
    return (
        f'<div style="font-family:{SANS};font-size:11px;font-weight:700;letter-spacing:.09em;'
        f'text-transform:uppercase;color:{GOLD};margin:0 0 6px">{escape(text)}</div>'
    )


def _story_html(story: dict[str, Any], numbers: dict[tuple[str, str], int], *, lead: bool) -> str:
    eyebrow = _eyebrow(story["eyebrow"]) if story.get("eyebrow") else ""
    head_size = "26px" if lead else "21px"
    headline = (
        f'<h2 style="font-family:{SERIF};font-size:{head_size};line-height:1.2;font-weight:600;'
        f'color:{NAVY};margin:0 0 8px">{escape(story.get("headline",""))} {_fn_html(story.get("citations"), numbers)}</h2>'
    )
    standfirst = (
        f'<p style="font-family:{SANS};font-size:16px;line-height:1.55;color:{MUTED};margin:0 0 14px">{escape(story["standfirst"])}</p>'
        if story.get("standfirst") else ""
    )
    blocks = []
    for section in story.get("sections") or []:
        label = (
            f'<span style="font-family:{SANS};font-size:12px;font-weight:700;letter-spacing:.04em;'
            f'text-transform:uppercase;color:{NAVY_SURFACE}">{escape(section["label"])}: </span>'
            if section.get("label") else ""
        )
        blocks.append(
            f'<p style="font-family:{SANS};font-size:16px;line-height:1.6;color:{INK};margin:0 0 12px">{label}{escape(section.get("body",""))}</p>'
        )
    divider = f'border-top:3px solid {GOLD}' if lead else f'border-top:1px solid {BORDER}'
    return (
        f'<tr><td style="padding:22px 28px;{divider}">{eyebrow}{headline}{standfirst}{"".join(blocks)}</td></tr>'
    )


def render_newsletter_html(draft: dict[str, Any], visuals: dict[str, Any], refs: list[dict[str, Any]], week_start: str, week_end: str) -> str:
    numbers = {(str(ref["table"]), str(ref["pk"])): i for i, ref in enumerate(refs, start=1)}
    title = escape(draft.get("title") or "Weekly Political Intelligence")
    preheader = escape(draft.get("preheader") or "")
    logo = _asset("/brand/nessus-horizontal-on-dark.png")

    key_points = "".join(
        f'<tr><td style="padding:0 0 14px"><span style="font-family:{SANS};font-size:16px;font-weight:700;color:{NAVY}">{escape(point.get("development",""))}</span>'
        f'<span style="font-family:{SANS};font-size:16px;color:{INK}"> — {escape(point.get("significance",""))}</span></td></tr>'
        for point in draft.get("key_points") or []
    )

    stats = "".join(
        '<tr>'
        f'<td style="padding:14px 16px;border-bottom:1px solid {BORDER};white-space:nowrap;vertical-align:top">'
        f'<span style="font-family:{SERIF};font-size:24px;font-weight:600;color:{GOLD}">{escape(stat.get("value",""))}</span></td>'
        f'<td style="padding:14px 16px;border-bottom:1px solid {BORDER}">'
        f'<div style="font-family:{SANS};font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:{NAVY_SURFACE}">{escape(stat.get("label",""))}</div>'
        f'<div style="font-family:{SANS};font-size:15px;line-height:1.5;color:{INK};margin-top:3px">{escape(stat.get("significance",""))} {_fn_html(stat.get("citation"), numbers)}</div></td></tr>'
        for stat in draft.get("statistics") or []
    )

    radar = "".join(
        f'<tr><td style="padding:0 0 16px">'
        f'<div style="font-family:{SANS};font-size:16px;font-weight:700;color:{NAVY}">{escape(item.get("headline",""))} {_fn_html(item.get("citation"), numbers)}</div>'
        f'<div style="font-family:{SANS};font-size:15px;line-height:1.55;color:{INK};margin-top:3px">{escape(item.get("summary",""))}</div>'
        + (f'<div style="font-family:{SANS};font-size:13px;color:{MUTED};margin-top:5px"><strong style="color:{NAVY_SURFACE}">Next:</strong> {escape(item["next_milestone"])}</div>' if item.get("next_milestone") else "")
        + '</td></tr>'
        for item in draft.get("radar_items") or []
    )

    stories = _story_html(draft.get("lead_story") or {}, numbers, lead=True)
    stories += "".join(_story_html(story, numbers, lead=False) for story in draft.get("supporting_stories") or [])

    closing = draft.get("closing_analysis") or {}
    sources = "".join(
        f'<li style="margin-bottom:8px"><a href="{_asset("/records/" + escape(str(ref["table"])) + "/" + escape(str(ref["pk"])))}" '
        f'style="color:{NAVY_SURFACE};text-decoration:underline">{escape(ref.get("title",""))}</a> '
        f'<span style="color:{MUTED}">— {escape(ref.get("source",""))}'
        + (f', {escape(str(ref.get("date")))}' if ref.get("date") else "")
        + '</span>'
        + (f' · <a href="{escape(ref["url"])}" style="color:{NAVY_SURFACE}">original source</a>' if ref.get("url") else "")
        + '</li>'
        for ref in refs
    )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><title>{title}</title>
<style>
  body {{ margin:0; padding:0; background:{PAGE_BG}; -webkit-text-size-adjust:100%; }}
  a {{ color:{NAVY_SURFACE}; }}
  @media only screen and (max-width:620px) {{
    .container {{ width:100% !important; }}
    .pad {{ padding-left:18px !important; padding-right:18px !important; }}
    .lead-h {{ font-size:23px !important; }}
  }}
</style></head>
<body style="margin:0;background:{PAGE_BG};">
<span style="display:none!important;visibility:hidden;opacity:0;height:0;width:0;overflow:hidden;mso-hide:all">{preheader}</span>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{PAGE_BG}"><tr><td align="center" style="padding:24px 12px">
  <table role="presentation" class="container" width="640" cellpadding="0" cellspacing="0" style="width:640px;max-width:640px;background:#FFFFFF;border:1px solid {BORDER}">
    <!-- masthead -->
    <tr><td style="background:{NAVY};padding:24px 28px" class="pad">
      <img src="{logo}" width="220" alt="Nessus Intelligence" style="display:block;width:220px;max-width:60%;height:auto;border:0">
      <div style="font-family:{SANS};font-size:11px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:{GOLD};margin-top:16px">Weekly Intelligence Briefing</div>
      <div style="font-family:{SANS};font-size:13px;color:#C7CEDA;margin-top:4px">{escape(week_start)} – {escape(week_end)}</div>
    </td></tr>
    <!-- issue title + opening note -->
    <tr><td style="padding:26px 28px 8px" class="pad">
      <h1 class="lead-h" style="font-family:{SERIF};font-size:30px;line-height:1.15;font-weight:600;color:{NAVY};margin:0 0 14px">{title}</h1>
      <p style="font-family:{SANS};font-size:17px;line-height:1.6;color:{INK};margin:0">{escape(draft.get("opening_note",""))}</p>
    </td></tr>
    <!-- what matters today -->
    <tr><td style="padding:18px 28px 4px" class="pad">
      <div style="font-family:{SANS};font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:{GOLD};margin-bottom:12px">What matters today</div>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0">{key_points}</table>
    </td></tr>
    <!-- stories (lead + supporting) -->
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0">{stories}</table>
    <!-- by the numbers -->
    <tr><td style="padding:22px 28px 6px;border-top:1px solid {BORDER}" class="pad">
      <div style="font-family:{SANS};font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:{GOLD};margin-bottom:8px">By the numbers</div>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-top:1px solid {BORDER}">{stats}</table>
    </td></tr>
    <!-- on the radar -->
    <tr><td style="padding:22px 28px 6px" class="pad">
      <div style="font-family:{SANS};font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:{GOLD};margin-bottom:12px">On the radar</div>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0">{radar}</table>
    </td></tr>
    <!-- closing analysis -->
    <tr><td style="padding:0 28px 26px" class="pad">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{NAVY};border-radius:4px"><tr><td style="padding:20px 22px">
        <div style="font-family:{SANS};font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:{GOLD};margin-bottom:8px">{escape(closing.get("title") or "The bottom line")}</div>
        <p style="font-family:{SERIF};font-size:17px;line-height:1.6;color:{DOC_WHITE};margin:0">{escape(closing.get("body",""))}</p>
      </td></tr></table>
    </td></tr>
    <!-- sources -->
    <tr><td style="padding:20px 28px;border-top:1px solid {BORDER};background:{DOC_WHITE}" class="pad">
      <div style="font-family:{SANS};font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:{NAVY_SURFACE};margin-bottom:10px">Sources &amp; Nessus records</div>
      <ol style="font-family:{SANS};font-size:13px;line-height:1.5;color:{INK};margin:0;padding-left:20px">{sources}</ol>
    </td></tr>
    <!-- footer -->
    <tr><td style="padding:20px 28px;background:{NAVY}" class="pad">
      <div style="font-family:{SANS};font-size:12px;line-height:1.6;color:#AEB8C9">
        Generated by Nessus Intelligence from cited public-record evidence. Analysis is for internal strategic use and is not legal, investment, or lobbying advice.
      </div>
      <div style="font-family:{SANS};font-size:12px;color:#8893A8;margin-top:10px">
        <a href="{_asset("/newsletters")}" style="color:{GOLD};text-decoration:none">Newsletter preferences</a>
        &nbsp;·&nbsp; <a href="{_asset("/newsletters")}" style="color:{GOLD};text-decoration:none">Unsubscribe</a>
      </div>
    </td></tr>
  </table>
</td></tr></table>
</body></html>"""


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
    if len(candidates) < MIN_CANDIDATES:
        raise NewsletterGenerationError(
            f"insufficient evidence for {week_start} to {week_end}: {len(candidates)} candidate records (need {MIN_CANDIDATES})"
        )
    clusters = connection_clusters(candidates)

    review_meta: dict[str, Any] = {"ran": False}
    try:
        if draft_override is None:
            draft, model, provider, turn = await _call_opus(week_start, week_end, candidates, clusters)
            if settings.newsletter_quality_review and validate_draft(draft, candidates)["ok"]:
                draft, review_meta = await _review_and_revise(provider, turn, draft, candidates)
        else:
            draft, model = _normalize_draft(draft_override), OPUS_MODEL
    except ProviderUnavailable as exc:
        raise NewsletterGenerationError("Claude Opus API is not configured; ANTHROPIC_API_KEY is required") from exc
    except ProviderError as exc:
        raise NewsletterGenerationError(f"Claude Opus generation failed: {exc}") from exc

    validation = validate_draft(draft, candidates)
    if not validation["ok"]:
        raise NewsletterGenerationError(f"newsletter validation failed: {validation['errors']}")
    validation["review"] = review_meta

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
        evidence={"candidate_count": len(candidates), "candidates": candidates, "clusters": clusters},
        source_references=refs,
        validation=validation,
        html=html,
    )
    session.add(issue)
    await session.commit()
    return issue
