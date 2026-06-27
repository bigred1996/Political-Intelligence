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
from pathlib import Path
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
MAX_LABELS_PER_STORY = 2
MAX_SENTENCE_WORDS = 35
PROMPTS = Path("prompts")
# Em dash (U+2014) and horizontal bar (U+2015), optionally spaced; plus a spaced
# en dash (U+2013), spaced "--", or a spaced single hyphen used as a dash. The
# spaced forms require surrounding whitespace so ranges like "2026-27" are safe.
_EM_DASH_RE = re.compile(r"\s*[—―]\s*|\s+(?:--|[–-])\s+")


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
        "headline": {"type": "string", "description": "Sentence-case news headline, 6-12 words, active verb, leads with the concrete development. No colon, no Title Case, not a slide title."},
        "standfirst": {"type": "string", "description": "One or two sentence summary under the headline."},
        "sections": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string", "description": "Optional. Use at most two labels per story; most supporting stories should read as plain paragraphs with no label."},
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
            "title": {"type": "string", "description": "Sentence-case issue headline, 6-12 words, leads with the week's main news, active verb, no colon. Never Title Case, never 'Weekly Political Update'."},
            "preheader": {"type": "string", "description": "Hidden inbox preview line, <=140 chars, no greeting."},
            "opening_note": {"type": "string", "description": "50-90 words. One tension: what happened, what is still unresolved, why the distinction matters. Do not list every story or address 'executives, investors and counsel'."},
            "key_points": {
                "type": "array",
                "minItems": 2,
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Two or three short sentences: the fact, its consequence, and the open question. Never a 'fact - consequence' dash format."},
                    },
                    "required": ["text"],
                },
            },
            "lead_story": _STORY,
            "supporting_stories": {"type": "array", "minItems": 2, "maxItems": 3, "items": _STORY},
            "statistics_heading": {"type": "string", "description": "'By the numbers' for real quantities, or 'Key dates and milestones' if the items are dates."},
            "statistics": {
                "type": "array",
                "minItems": 0,
                "maxItems": 5,
                "description": "Optional. Only real quantities (dollars, totals, counts, timelines, vote totals, percentages) or, retitled, key dates. Never procedural stages like 'third reading'. Omit entirely if there is nothing meaningful.",
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
                    "body": {"type": "string", "description": "80-140 words. One editorial argument: connect the main developments, name the unresolved test, point to one or two concrete indicators to watch. Do NOT repeat the opening note. No 'strengthen vs weaken' framing."},
                },
                "required": ["title", "body"],
            },
        },
        "required": [
            "title", "preheader", "opening_note", "key_points",
            "lead_story", "supporting_stories", "radar_items", "closing_analysis",
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


# Same output shape as the generator — the editor only rewrites prose, so it
# returns the identical schema with the same field names and citations.
NEWSLETTER_EDIT_TOOL: dict[str, Any] = {
    "name": "rewrite_weekly_newsletter",
    "description": (
        "Return the SAME weekly newsletter with rewritten prose only. Preserve "
        "every fact, date, name, bill number, dollar figure, source citation, "
        "and level of certainty. Same field names, same citations. No em dashes."
    ),
    "input_schema": NEWSLETTER_TOOL["input_schema"],
}


class ClaudeNewsletterEditor(_ClaudeToolProvider):
    name = "claude"
    tool = NEWSLETTER_EDIT_TOOL
    max_tokens = 8000

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


def _as_list(value: Any) -> list[Any]:
    # A model turn can return a string where a list is expected; iterating it
    # directly would walk characters. Coerce anything non-list to [].
    return value if isinstance(value, list) else []


def _norm_story(value: Any) -> dict[str, Any]:
    story = value if isinstance(value, dict) else {}
    sections = []
    for section in _as_list(story.get("sections")):
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
    for point in _as_list(d.get("key_points")):
        if isinstance(point, dict):
            # Tolerate the legacy {development, significance} shape.
            text = point.get("text") or " ".join(filter(None, [point.get("development"), point.get("significance")]))
            text = str(text or "").strip()
        else:
            text = str(point or "").strip()
        if text:
            key_points.append({"text": text})
    d["key_points"] = key_points
    d["lead_story"] = _norm_story(d.get("lead_story"))
    d["supporting_stories"] = [_norm_story(s) for s in _as_list(d.get("supporting_stories"))]

    stats = []
    for stat in _as_list(d.get("statistics")):
        if isinstance(stat, dict):
            stats.append({
                "value": str(stat.get("value") or ""), "label": str(stat.get("label") or ""),
                "significance": str(stat.get("significance") or ""), "citation": _norm_single_citation(stat.get("citation")),
            })
    d["statistics"] = stats
    heading = str(d.get("statistics_heading") or "").strip()
    d["statistics_heading"] = heading or "By the numbers"

    radar = []
    for item in _as_list(d.get("radar_items")):
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
        parts.append(point.get("text", ""))
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
    # "By the numbers" is optional now (omit when there is nothing meaningful),
    # so only an over-full statistics block is an error.
    if len(draft.get("statistics") or []) > 5:
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
        "Write the Weekly Political Intelligence issue as an experienced Canadian political and business journalist would: reported and edited, not assembled from a template. Be selective, not exhaustive.\n"
        f"Window: {week_start} through {week_end}.\n\n"
        "SELECTION:\n"
        "- Rank by consequence, novelty, political/regulatory momentum, evidence strength, and whether a decision/deadline/vote/hearing/consultation is coming.\n"
        "- One lead story, two or three supporting stories, three to five 'on the radar' items. Do not give every record equal space.\n\n"
        "CONNECTIONS — do not force them. Connect two developments only when one genuinely alters, enables, constrains, accelerates, funds, delays, or explains the other (use CONNECTION_HINTS as candidates, not mandates). Do NOT link records merely because they share a week, a minister, the label 'federal bill', or broad reliance on parliamentary spending. If no strong link exists, treat records separately. Not every story needs a connection.\n\n"
        "STRUCTURE — vary it. Lead with the strongest concrete development. The lead story may use one or two short labels; supporting stories should normally be plain paragraphs with NO labels. Do not open consecutive stories the same way. One point per paragraph.\n\n"
        "VOICE:\n"
        "- Named actors and active verbs ('Parliament approved the bill', 'Ottawa authorized the funding'), not abstract-noun stacks ('implementation-capacity risk', 'financial-crime architecture', 'regulatory momentum').\n"
        "- Show who is affected through the concrete consequence. Do NOT write 'for executives/investors/counsel/stakeholders'. Do not use 'investors' as a generic audience word.\n"
        "- State conclusions directly. Do not announce that you are analysing ('the key signal is', 'Nessus reads this as', 'this is significant because').\n"
        "- Do not treat a minister sponsoring several bills as a strategic insight unless the records show a real shift in responsibility, mandate, or authority.\n"
        "- Vary sentence length; most sentences well under 35 words. No em dashes and no spaced hyphen used as a dash: use a period, comma, colon, or two sentences. Canadian English. Explain acronyms in plain language on first use.\n\n"
        "LEGISLATIVE PRECISION: distinguish received royal assent / became law / in force now / comes into force on a set date / requires an order in council or regulations / remains at committee / passed one chamber. Do not call provisions operative unless the records confirm they are in force. If two records conflict, use the most authoritative and recent, or leave it for an analyst.\n\n"
        "SECTIONS:\n"
        "- opening_note: one tension (what happened, what is unresolved, why the distinction matters). Do not list every story.\n"
        "- key_points: two or three items, each the fact, its consequence, and the open question. Never a 'fact - consequence' dash.\n"
        "- statistics: OPTIONAL. Include only real quantities (dollars, totals, counts, timelines, vote totals, percentages). Never use procedural stages ('third reading') as statistics. If the useful content is dates, set statistics_heading to 'Key dates and milestones'. If nothing meaningful exists, omit statistics entirely.\n"
        "- headlines: 6-12 words, sentence case, active verb, no colon.\n"
        "- closing_analysis: 80-140 words, one editorial argument naming one or two concrete indicators to watch. Do NOT repeat the opening and do NOT use 'strengthen vs weaken' framing.\n\n"
        f"LENGTH: visible editorial prose {MIN_WORDS}-{MAX_WORDS} words.\n\n"
        "RULES:\n"
        "- Use only the provided candidate records. Every story, statistic, and radar item must cite ALLOWED_RECORD_IDS.\n"
        "- Do not invent dates, names, values, URLs, motivations, or causal relationships.\n"
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
    # Up to two structured-repair turns: the model occasionally returns a
    # malformed shape (a string where a list is expected, missing modules); one
    # retry is often not enough to fully recover.
    for _ in range(2):
        result = validate_draft(draft, candidates)
        if result["ok"]:
            break
        correction = (
            "Your newsletter draft failed validation:\n"
            + "\n".join(f"- {error}" for error in result["errors"])
            + "\n\nCall build_weekly_newsletter again with the FULL object: title, preheader, "
            "opening_note, key_points (a list of 2-3 objects), lead_story, supporting_stories (a "
            "list of 2-3 story objects), radar_items (3-5), closing_analysis, and optional "
            f"statistics. Keep every citation inside ALLOWED_RECORD_IDS and the prose at "
            f"{MIN_WORDS}-{MAX_WORDS} words."
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


# --- Editorial voice rewrite + deterministic style guards ---------------------
def _read_prompt(name: str) -> str:
    p = PROMPTS / name
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _strip_em_dashes(text: str) -> str:
    """Guaranteed em-dash removal (the model is asked to avoid them; this is the
    safety net). Split on the dash and rejoin with a period, capitalising the
    following word so the result reads as two sentences."""
    if not text or not _EM_DASH_RE.search(text):
        return text
    parts = _EM_DASH_RE.split(text)
    result = parts[0].rstrip()
    for part in parts[1:]:
        part = part.lstrip()
        if part:
            part = part[0].upper() + part[1:]
        result = f"{result.rstrip()}. {part}" if result else part
    return result


def _guard_story(story: dict[str, Any]) -> None:
    story["headline"] = _strip_em_dashes(story.get("headline", ""))
    if story.get("standfirst"):
        story["standfirst"] = _strip_em_dashes(story["standfirst"])
    if story.get("eyebrow"):
        story["eyebrow"] = _strip_em_dashes(story["eyebrow"])
    labels_kept = 0
    for section in story.get("sections") or []:
        section["body"] = _strip_em_dashes(section.get("body", ""))
        if section.get("label"):
            if labels_kept < MAX_LABELS_PER_STORY:
                labels_kept += 1
            else:
                section["label"] = None  # cap analytical labels per story


def _apply_style_guards(draft: Any) -> dict[str, Any]:
    """Deterministic post-rewrite enforcement: strip every em dash and cap the
    number of analytical labels per story. Always runs, even when the editorial
    pass is off or the model output is used verbatim."""
    d = _normalize_draft(draft)
    s = _strip_em_dashes
    d["title"] = s(d.get("title", ""))
    d["preheader"] = s(d.get("preheader", ""))
    d["opening_note"] = s(d.get("opening_note", ""))
    for point in d["key_points"]:
        point["text"] = s(point["text"])
    for story in [d["lead_story"], *d["supporting_stories"]]:
        _guard_story(story)
    for stat in d["statistics"]:
        stat["value"] = s(stat.get("value", ""))
        stat["label"] = s(stat.get("label", ""))
        stat["significance"] = s(stat.get("significance", ""))
    for item in d["radar_items"]:
        item["headline"] = s(item.get("headline", ""))
        item["summary"] = s(item.get("summary", ""))
        if item.get("next_milestone"):
            item["next_milestone"] = s(item["next_milestone"])
    closing = d["closing_analysis"]
    closing["title"] = s(closing.get("title", ""))
    closing["body"] = s(closing.get("body", ""))
    return d


# Generic consulting / self-conscious-analysis phrasing to flag (not technical
# terms — these are flagged only as generic usage). Audience callouts are listed
# separately so the warning can name the pattern.
_BANNED_PHRASES = (
    "nessus reads", "the key signal", "the read here", "this is significant",
    "materially raises", "execution risk", "implementation-capacity",
    "implementation capacity", "necessary but not sufficient", "strategic implication",
    "what this means for readers",
)
_AUDIENCE_CALLOUTS = (
    "for executives", "for investors", "for counsel", "for stakeholders",
    "for readers", "for clients", "for business leaders", "readers should watch",
    "compliance teams should",
)
# Over-claims that royal assent rarely supports — flag for a coming-into-force check.
_FORCE_CLAIMS = ("came into force", "now in force", "immediately operative", "takes effect immediately", "now operative")
_STOPWORDS = frozenset({"that", "this", "with", "from", "have", "will", "their", "which", "about", "into", "they", "than", "then", "them", "been", "were", "would", "could", "after", "before", "over", "more", "most", "some", "such", "only", "also", "both"})


def _content_tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z'-]{3,}", (text or "").lower()) if w not in _STOPWORDS}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _headline_warnings(draft: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    named = [("issue title", draft.get("title", "")), ("lead headline", (draft.get("lead_story") or {}).get("headline", ""))]
    named += [(f"supporting headline {i + 1}", st.get("headline", "")) for i, st in enumerate(draft.get("supporting_stories") or [])]
    for label, head in named:
        words = len(re.findall(r"\b[\w'-]+\b", head))
        if words > 12:
            warnings.append(f"{label} is {words} words (aim for 6–12)")
        if ":" in head:
            warnings.append(f"{label} uses a colon — prefer a single clause")
    return warnings


def _duplicate_section_warnings(draft: dict[str, Any]) -> list[str]:
    """Token-overlap (Jaccard) repetition check across modules."""
    warnings: list[str] = []
    opening = _content_tokens(draft.get("opening_note", ""))
    closing = _content_tokens((draft.get("closing_analysis") or {}).get("body", ""))
    if _jaccard(opening, closing) > 0.5:
        warnings.append("closing repeats the opening — give it a distinct argument")
    stories = [draft.get("lead_story") or {}, *(draft.get("supporting_stories") or [])]
    story_tokens = [_content_tokens(" ".join(_story_text(s))) for s in stories]
    for i, item in enumerate(draft.get("radar_items") or []):
        radar_tokens = _content_tokens(f"{item.get('headline', '')} {item.get('summary', '')}")
        if any(_jaccard(radar_tokens, st) > 0.45 for st in story_tokens):
            warnings.append(f"radar item {i + 1} repeats a main story — replace it or rebuild around a new milestone")
    return warnings


def _editorial_lint(draft: dict[str, Any]) -> list[str]:
    lower = " ".join(str(p or "") for p in _visible_parts(draft)).lower()
    warnings: list[str] = []
    hits = [p for p in _BANNED_PHRASES if p in lower]
    if hits:
        warnings.append("consulting/self-conscious phrasing: " + ", ".join(f"“{h}”" for h in hits[:6]))
    callouts = [p for p in _AUDIENCE_CALLOUTS if p in lower]
    if callouts:
        warnings.append("audience callouts (show relevance through consequence): " + ", ".join(f"“{c}”" for c in callouts[:6]))
    if "architecture" in lower:
        warnings.append("“architecture” reads as a policy metaphor — prefer a concrete noun")
    if any(c in lower for c in _FORCE_CLAIMS):
        warnings.append("verify coming-into-force: royal assent does not always mean provisions are in force")
    return warnings


def _style_report(draft: dict[str, Any]) -> dict[str, Any]:
    """Non-blocking voice metrics + editorial lint surfaced in the preview."""
    parts = [str(p or "") for p in _visible_parts(draft)]
    text = " ".join(parts)
    lower = text.lower()
    em = sum(part.count("—") + part.count("―") for part in parts)
    spaced_hyphen = len(re.findall(r"\S\s+[-–]\s+\S", text))
    signal = len(re.findall(r"\bsignals?\b", lower))
    why_it_matters = lower.count("why it matters")
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    lengths = [len(re.findall(r"\b[\w'-]+\b", s)) for s in sentences]
    long_sentences = sum(1 for n in lengths if n > MAX_SENTENCE_WORDS)
    avg = round(sum(lengths) / len(lengths), 1) if lengths else 0.0

    warnings: list[str] = []
    if em:
        warnings.append(f"{em} em dash(es) remain in the copy")
    if spaced_hyphen:
        warnings.append(f"{spaced_hyphen} spaced hyphen(s) used as a dash")
    if signal > 2:
        warnings.append(f"“signal” used {signal} times (style limit is 2)")
    if why_it_matters > 1:
        warnings.append(f"“why it matters” used {why_it_matters} times (style limit is 1)")
    if long_sentences:
        warnings.append(f"{long_sentences} sentence(s) over {MAX_SENTENCE_WORDS} words")
    if avg and not (14 <= avg <= 24):
        warnings.append(f"average sentence length {avg} words (target 14–24)")
    warnings.extend(_headline_warnings(draft))
    warnings.extend(_duplicate_section_warnings(draft))
    warnings.extend(_editorial_lint(draft))
    return {
        "warnings": warnings,
        "metrics": {
            "em_dashes": em, "spaced_hyphens": spaced_hyphen, "signal": signal,
            "why_it_matters": why_it_matters, "long_sentences": long_sentences,
            "avg_sentence_words": avg,
        },
    }


def _bill_numbers(draft: dict[str, Any]) -> set[str]:
    text = " ".join(str(p or "") for p in _visible_parts(draft))
    return {m.upper() for m in re.findall(r"\b[CS]-\d{1,4}\b", text)}


def _preserved(original: dict[str, Any], rewritten: dict[str, Any]) -> bool:
    """The rewrite is prose-only. Reject it if citations, statistic values, bill
    numbers, or module counts changed — those carry the facts."""
    if set(_draft_citations(original)) != set(_draft_citations(rewritten)):
        return False
    orig_values = sorted(str(s.get("value", "")) for s in original.get("statistics") or [])
    new_values = sorted(str(s.get("value", "")) for s in rewritten.get("statistics") or [])
    if orig_values != new_values:
        return False
    # Bill numbers (C-26, S-7) are stable tokens a faithful rewrite never drops.
    if not _bill_numbers(original) <= _bill_numbers(rewritten):
        return False
    for field in ("supporting_stories", "key_points", "radar_items", "statistics"):
        if len(original.get(field) or []) != len(rewritten.get(field) or []):
            return False
    return bool((rewritten.get("lead_story") or {}).get("headline"))


async def _editorial_rewrite(original: dict[str, Any], candidates: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Second Opus pass: reported journalistic prose per the voice guide, facts
    held constant. Any drift in facts/citations/validation falls back to the
    factual draft, so the rewrite can only improve voice, never corrupt data."""
    guide = _read_prompt("newsletter_editorial_voice.md")
    if not guide:
        return original, {"ran": False, "reason": "guide_missing"}
    editor = ClaudeNewsletterEditor(model=OPUS_MODEL)
    user = (
        "Rewrite the prose of this weekly newsletter draft to follow the editorial voice guide. "
        "Preserve every fact, date, name, bill number, dollar figure, source citation, and level "
        "of certainty. Do not add facts or interpretations. Keep the visible prose between "
        f"{MIN_WORDS} and {MAX_WORDS} words. Return the rewrite_weekly_newsletter tool call with "
        "the same field names and the same citations.\n\n"
        f"DRAFT:\n{json.dumps(original, ensure_ascii=False, default=str)[:55000]}"
    )
    try:
        rewritten = _normalize_draft((await editor.call(guide, user)).tool_input)
    except (ProviderError, ProviderUnavailable) as exc:
        return original, {"ran": True, "applied": False, "reason": f"provider_error:{exc}"}
    if not _preserved(original, rewritten):
        return original, {"ran": True, "applied": False, "reason": "facts_or_citations_changed"}
    # Accept the rewrite on facts + structure; a slightly out-of-range word count
    # is acceptable for better prose (it is surfaced as a warning either way).
    blocking = [e for e in validate_draft(rewritten, candidates)["errors"] if not e.startswith("word_count_outside_range")]
    if blocking:
        return original, {"ran": True, "applied": False, "reason": f"rewrite_failed_validation:{blocking[:3]}"}
    return rewritten, {"ran": True, "applied": True}


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
        f'<tr><td style="padding:0 0 14px;border-left:3px solid {GOLD};padding-left:12px">'
        f'<span style="font-family:{SANS};font-size:16px;line-height:1.55;color:{INK}">{escape(point.get("text",""))}</span></td></tr>'
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

    # "By the numbers" is optional — render nothing when there are no statistics.
    stats_section = (
        f'<tr><td style="padding:22px 28px 6px;border-top:1px solid {BORDER}" class="pad">'
        f'<div style="font-family:{SANS};font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:{GOLD};margin-bottom:8px">{escape(draft.get("statistics_heading") or "By the numbers")}</div>'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-top:1px solid {BORDER}">{stats}</table>'
        '</td></tr>'
    ) if stats else ""

    closing = draft.get("closing_analysis") or {}
    sources = "".join(
        f'<li style="margin-bottom:8px"><a href="{_asset("/records/" + escape(str(ref["table"])) + "/" + escape(str(ref["pk"])))}" '
        f'style="color:{NAVY_SURFACE};text-decoration:underline">{escape(ref.get("title",""))}</a> '
        f'<span style="color:{MUTED}">· {escape(ref.get("source",""))}'
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
    <!-- by the numbers / key dates (optional) -->
    {stats_section}
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
    editorial_meta: dict[str, Any] = {"ran": False}
    try:
        if draft_override is None:
            draft, model, provider, turn = await _call_opus(week_start, week_end, candidates, clusters)
            if settings.newsletter_quality_review and validate_draft(draft, candidates)["ok"]:
                draft, review_meta = await _review_and_revise(provider, turn, draft, candidates)
            if settings.newsletter_editorial_pass:
                draft, editorial_meta = await _editorial_rewrite(draft, candidates)
        else:
            draft, model = _normalize_draft(draft_override), OPUS_MODEL
    except ProviderUnavailable as exc:
        raise NewsletterGenerationError("Claude Opus API is not configured; ANTHROPIC_API_KEY is required") from exc
    except ProviderError as exc:
        raise NewsletterGenerationError(f"Claude Opus generation failed: {exc}") from exc

    # Deterministic voice guards always run (em dashes, label cap), even on the
    # override path or when the editorial pass is disabled.
    draft = _apply_style_guards(draft)

    validation = validate_draft(draft, candidates)
    # Word count is a "normally 900-1,200" target, not a factual-integrity rule —
    # the editorial rewrite can legitimately push a touch past it. Block only on
    # integrity/structure errors (citations, missing lead, bad counts); record
    # an out-of-range word count as a non-blocking warning shown in the preview.
    blocking = [e for e in validation["errors"] if not e.startswith("word_count_outside_range")]
    if blocking:
        raise NewsletterGenerationError(f"newsletter validation failed: {blocking}")
    validation["review"] = review_meta
    validation["editorial"] = editorial_meta
    validation["style"] = _style_report(draft)

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
