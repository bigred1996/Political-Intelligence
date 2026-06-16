"""Natural-language → structured search plan.

A user asks "who lobbied on telecom while donating to the governing party since
2023?". The planner turns that into a machine-executable plan: entity, keywords,
source filters, date range, dollar floor, and a clean semantic query string.

Two paths, same output schema:
  * Claude path  — when ANTHROPIC_API_KEY is set, Claude fills the plan via a
    forced tool call (reliable structured output).
  * Fallback path — a deterministic heuristic parser (amounts, years, keywords)
    so search works fully offline with no key. Drop the key in later to upgrade
    plan quality; nothing else changes.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

import structlog

from api.config import settings

log = structlog.get_logger()

KNOWN_SOURCES = [
    "contracts", "donations", "grants", "lobbying", "ocl_registrations",
    "bills", "gazette", "tribunal", "appointments",
    "statcan", "iaac", "cer", "npri", "transport", "geospatial", "gc_news",
]

_STOPWORDS = {
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "with", "by",
    "who", "what", "which", "show", "me", "all", "find", "list", "every", "any",
    "that", "this", "from", "since", "between", "over", "under", "than", "more",
    "give", "pull", "up", "about", "did", "do", "does", "has", "have", "had",
    "is", "are", "was", "were", "been", "while", "their", "they", "them",
}


@dataclass
class SearchPlan:
    semantic_query: str
    keywords: list[str] = field(default_factory=list)
    entity_text: str | None = None
    sources: list[str] | None = None
    date_from: str | None = None
    date_to: str | None = None
    min_amount: float | None = None
    planner: str = "fallback"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Deterministic fallback parser ─────────────────────────────────────────────
_AMOUNT_RE = re.compile(r"\$?\s?([\d,]+(?:\.\d+)?)\s*(million|billion|m|b|k)?", re.I)
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_MULT = {"k": 1e3, "m": 1e6, "million": 1e6, "b": 1e9, "billion": 1e9}


def _parse_amount(q: str) -> float | None:
    m = re.search(r"(?:over|above|more than|>|at least|minimum|min)\s*" + _AMOUNT_RE.pattern, q, re.I)
    if not m:
        return None
    num = float(m.group(1).replace(",", ""))
    mult = _MULT.get((m.group(2) or "").lower(), 1)
    return num * mult


def fallback_plan(q: str) -> SearchPlan:
    ql = q.lower()
    # Source hints by keyword
    src_hints = {
        "contract": "contracts", "donat": "donations", "contribut": "donations",
        "grant": "grants", "lobby": "lobbying", "bill": "bills",
        "regulation": "gazette", "gazette": "gazette", "pipeline": "cer",
        "energy": "cer", "pollut": "npri", "emission": "npri", "npri": "npri",
        "impact assessment": "iaac", "project": "iaac", "transport": "transport",
        "geospatial": "geospatial", "map": "geospatial", "news": "gc_news",
        "statcan": "statcan", "statistic": "statcan", "appoint": "appointments",
        "crtc": "tribunal", "tribunal": "tribunal",
    }
    sources = sorted({v for k, v in src_hints.items() if k in ql}) or None

    min_amount = _parse_amount(q)
    years = [int(y) for y in re.findall(r"\b(?:19|20)\d{2}\b", q)]
    date_from = date_to = None
    if "since" in ql and years:
        date_from = f"{min(years)}-01-01"
    elif len(years) >= 2:
        date_from, date_to = f"{min(years)}-01-01", f"{max(years)}-12-31"
    elif years:
        date_from, date_to = f"{years[0]}-01-01", f"{years[0]}-12-31"

    # Keywords: significant topic tokens only. Strip stopwords, the source-hint
    # words (they become `sources`, not keywords), and amount/unit filler so a
    # query like "contracts over $1M for IT services" keys on "IT"/"services".
    _NOISE = _STOPWORDS | set(src_hints) | {
        "federal", "government", "canada", "canadian", "million", "billion",
        "dollar", "dollars", "data", "record", "records", "amount", "total",
    }
    words = re.findall(r"[a-zA-Z][a-zA-Z&\-]{2,}", q)
    keywords = [w for w in words if w.lower() not in _NOISE][:8]

    return SearchPlan(
        semantic_query=q.strip(), keywords=keywords, sources=sources,
        date_from=date_from, date_to=date_to, min_amount=min_amount, planner="fallback",
    )


# ── Claude path ───────────────────────────────────────────────────────────────
_PLAN_TOOL = {
    "name": "build_search_plan",
    "description": "Produce a structured search plan over Canadian federal data sources.",
    "input_schema": {
        "type": "object",
        "properties": {
            "semantic_query": {"type": "string", "description": "Clean restatement of the information need for semantic retrieval."},
            "keywords": {"type": "array", "items": {"type": "string"}, "description": "Specific terms to match (sectors, topics, programs)."},
            "entity_text": {"type": ["string", "null"], "description": "A company/person/org name if the query is about a specific entity, else null."},
            "sources": {"type": ["array", "null"], "items": {"type": "string", "enum": KNOWN_SOURCES}, "description": "Restrict to these sources, or null for all."},
            "date_from": {"type": ["string", "null"], "description": "ISO YYYY-MM-DD lower bound or null."},
            "date_to": {"type": ["string", "null"], "description": "ISO YYYY-MM-DD upper bound or null."},
            "min_amount": {"type": ["number", "null"], "description": "Minimum dollar amount or null."},
        },
        "required": ["semantic_query", "keywords"],
    },
}

_SYSTEM = (
    "You are the query planner for Polaris, a Canadian political due-diligence platform. "
    "Translate the user's natural-language question into a search plan over these federal "
    "data sources: " + ", ".join(KNOWN_SOURCES) + ". "
    "Pick source filters only when the question clearly targets specific sources; otherwise "
    "leave sources null to search everything. Extract entities, date bounds, and dollar floors "
    "when present. Always call build_search_plan."
)


async def claude_plan(q: str) -> SearchPlan | None:
    if not settings.anthropic_api_key:
        return None
    try:
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        resp = await client.messages.create(
            model=settings.claude_model,
            max_tokens=600,
            system=_SYSTEM,
            tools=[_PLAN_TOOL],
            tool_choice={"type": "tool", "name": "build_search_plan"},
            messages=[{"role": "user", "content": q}],
        )
        for block in resp.content:
            if block.type == "tool_use":
                data = block.input
                return SearchPlan(
                    semantic_query=data.get("semantic_query") or q,
                    keywords=data.get("keywords") or [],
                    entity_text=data.get("entity_text"),
                    sources=data.get("sources"),
                    date_from=data.get("date_from"),
                    date_to=data.get("date_to"),
                    min_amount=data.get("min_amount"),
                    planner="claude",
                )
    except Exception as exc:
        log.warning("claude_plan_failed", error=str(exc))
    return None


async def make_plan(q: str) -> SearchPlan:
    """Claude plan if a key is set and the call succeeds, else deterministic fallback."""
    plan = await claude_plan(q)
    if plan is None:
        plan = fallback_plan(q)
    # Always merge a fallback amount/year pass so deterministic signals aren't lost.
    fb = fallback_plan(q)
    if plan.min_amount is None:
        plan.min_amount = fb.min_amount
    if plan.date_from is None:
        plan.date_from = fb.date_from
    if plan.date_to is None:
        plan.date_to = fb.date_to
    return plan
