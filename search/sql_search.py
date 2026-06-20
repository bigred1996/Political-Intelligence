"""Unified structured search across every Nessus table.

Where semantic search finds records by *meaning*, this finds them by *exact
predicate* — keyword, entity (canonical), date range, dollar floor — across all
sources at once, and returns them in one normalized shape. This is the half of
hybrid search that lets a user pull up every individual record matching a filter,
with the precision (amounts, dates) that due-diligence needs.

Each source is described once by a TableSpec; `structured_search()` runs the same
filter logic over every spec and merges the hits. Add a table = add a spec.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy import String, and_, cast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class TableSpec:
    model_path: str                       # "api.models.contract:Contract"
    source: str                           # label shown in results
    text_cols: list[str]                  # columns matched against keywords (ILIKE)
    title_fn: Callable[[Any], str]
    entity_col: str | None = None         # raw entity name column
    canonical_col: str | None = None      # normalized entity column (exact match)
    date_col: str | None = None
    amount_col: str | None = None
    url_fn: Callable[[Any], str | None] = lambda r: None
    snippet_fn: Callable[[Any], str] = lambda r: ""
    record_type: str = "record"


def _g(r, attr, default=""):
    return getattr(r, attr, default) or default


SPECS: list[TableSpec] = [
    TableSpec(
        "api.models.contract:Contract", "contracts",
        ["vendor_name", "description", "owner_org_title"],
        title_fn=lambda r: f"{_g(r,'vendor_name')} — {_g(r,'description')[:80]}",
        entity_col="vendor_name", canonical_col="canonical_name",
        date_col="contract_date", amount_col="contract_value",
        snippet_fn=lambda r: f"${_g(r,'contract_value',0):,.0f} from {_g(r,'owner_org_title')}",
        record_type="contract",
    ),
    TableSpec(
        "api.models.donation:Donation", "donations",
        ["contributor_name", "recipient", "party"],
        title_fn=lambda r: f"{_g(r,'contributor_name')} → {_g(r,'party') or _g(r,'recipient')}",
        entity_col="contributor_name", canonical_col="canonical_name",
        date_col="received_date", amount_col="amount",
        snippet_fn=lambda r: f"${_g(r,'amount',0):,.0f} donation ({_g(r,'contributor_province')})",
        record_type="donation",
    ),
    TableSpec(
        "api.models.grant:Grant", "grants",
        ["recipient_name", "program_name", "owner_org_title", "description"],
        title_fn=lambda r: f"{_g(r,'recipient_name')} — {_g(r,'program_name')[:80]}",
        entity_col="recipient_name", canonical_col="canonical_name",
        date_col="agreement_start", amount_col="agreement_value",
        snippet_fn=lambda r: f"${_g(r,'agreement_value',0):,.0f} grant from {_g(r,'owner_org_title')}",
        record_type="grant",
    ),
    TableSpec(
        "api.models.entity:LobbyingRecord", "lobbying",
        ["client", "registrant", "company_query"],
        title_fn=lambda r: f"{_g(r,'client')} lobbied (registrant {_g(r,'registrant')})",
        entity_col="client", canonical_col="canonical_name",
        date_col="communication_date",
        snippet_fn=lambda r: ", ".join(_g(r, "institutions", []) or [])[:120],
        record_type="lobbying_communication",
    ),
    TableSpec(
        "api.models.ocl_registration:OCLRegistration", "ocl_registrations",
        ["client_org", "registrant_name", "firm_name"],
        title_fn=lambda r: f"{_g(r,'client_org')} registration ({_g(r,'firm_name')})",
        entity_col="client_org", canonical_col="canonical_name",
        date_col="effective_date", record_type="lobbying_registration",
    ),
    TableSpec(
        "api.models.donation:Bill", "bills",
        ["bill_number", "title_en", "sponsor", "status"],
        title_fn=lambda r: f"{_g(r,'bill_number')} — {_g(r,'title_en')[:90]}",
        date_col="introduced_date",
        url_fn=lambda r: (
            f"https://www.parl.ca/legisinfo/en/bill/{_g(r,'parliament')}/{_g(r,'bill_number').lower()}"
            if _g(r, "parliament") and _g(r, "bill_number") else None
        ),
        snippet_fn=lambda r: f"{_g(r,'status')} · {_g(r,'sponsor')}",
        record_type="bill",
    ),
    TableSpec(
        "api.models.regulation:GazetteEntry", "gazette",
        ["title", "description", "department", "regulation_id"],
        title_fn=lambda r: _g(r, "title")[:120],
        entity_col="department", date_col="published_date",
        url_fn=lambda r: _g(r, "url") or None,
        snippet_fn=lambda r: _g(r, "description")[:160], record_type="regulation",
    ),
    TableSpec(
        "api.models.regulation:TribunalDecision", "tribunal",
        ["title", "summary", "parties", "decision_number"],
        title_fn=lambda r: _g(r, "title")[:120],
        entity_col="parties", date_col="decision_date",
        url_fn=lambda r: _g(r, "url") or None,
        snippet_fn=lambda r: _g(r, "summary")[:160], record_type="tribunal_decision",
    ),
    TableSpec(
        "api.models.appointment:Appointment", "appointments",
        ["appointee_name", "position_title", "organization"],
        title_fn=lambda r: f"{_g(r,'appointee_name')} — {_g(r,'position_title')[:70]}",
        entity_col="appointee_name", canonical_col="canonical_name",
        date_col="appointment_date",
        snippet_fn=lambda r: _g(r, "organization"), record_type="appointment",
    ),
    TableSpec(
        "api.models.politician:HansardMention", "hansard_mentions",
        ["keyword", "speaker", "excerpt"],
        title_fn=lambda r: f"{_g(r,'speaker') or 'House intervention'} — {_g(r,'keyword')}",
        entity_col="speaker", canonical_col="canonical_name",
        date_col="speech_date",
        url_fn=lambda r: _g(r, "speech_url") or None,
        snippet_fn=lambda r: _g(r, "excerpt")[:160],
        record_type="hansard_mention",
    ),
    TableSpec(
        "api.models.source_record:SourceRecord", "source_records",
        ["title", "summary", "entity_name"],
        title_fn=lambda r: _g(r, "title")[:120],
        entity_col="entity_name", canonical_col="canonical_name",
        date_col="event_date", amount_col="amount",
        url_fn=lambda r: _g(r, "url") or None,
        snippet_fn=lambda r: _g(r, "summary")[:160],
        record_type="breadth",  # overridden below with the actual source
    ),
]

_SPEC_BY_SOURCE = {s.source: s for s in SPECS}


def _import_model(path: str):
    mod, cls = path.split(":")
    import importlib
    return getattr(importlib.import_module(mod), cls)


async def structured_search(
    session: AsyncSession,
    *,
    keywords: list[str] | None = None,
    canonical: str | None = None,
    entity_text: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    min_amount: float | None = None,
    sources: list[str] | None = None,
    per_table_limit: int = 25,
) -> list[dict[str, Any]]:
    """Run the same predicate over every (or selected) table; merge normalized hits."""
    specs = [s for s in SPECS if (not sources or s.source in sources
             or (s.source == "source_records" and sources and any(
                 src in EMBED_AND_NPRI for src in sources)))]
    # If specific breadth sources requested, always include source_records.
    if sources and any(src in BREADTH_SOURCES for src in sources):
        if _SPEC_BY_SOURCE["source_records"] not in specs:
            specs.append(_SPEC_BY_SOURCE["source_records"])

    hits: list[dict[str, Any]] = []
    for spec in specs:
        model = _import_model(spec.model_path)
        conds = []

        # Keyword match: ANY keyword in ANY text column. Precision comes from the
        # entity/date/amount/source filters below and from semantic re-ranking —
        # ANDing every keyword (incl. filler) was too strict and starved recall.
        if keywords:
            kw_conds = []
            for kw in keywords:
                like = f"%{kw}%"
                kw_conds += [getattr(model, c).ilike(like) for c in spec.text_cols
                             if hasattr(model, c)]
            if kw_conds:
                conds.append(or_(*kw_conds))

        # Entity: prefer exact canonical match, else raw ILIKE.
        if canonical and spec.canonical_col and hasattr(model, spec.canonical_col):
            ent = getattr(model, spec.canonical_col) == canonical
            if entity_text and spec.entity_col and hasattr(model, spec.entity_col):
                ent = or_(ent, getattr(model, spec.entity_col).ilike(f"%{entity_text}%"))
            conds.append(ent)
        elif entity_text and spec.entity_col and hasattr(model, spec.entity_col):
            conds.append(getattr(model, spec.entity_col).ilike(f"%{entity_text}%"))

        # Date range (string ISO compare works for YYYY-MM-DD).
        if spec.date_col and hasattr(model, spec.date_col):
            dc = getattr(model, spec.date_col)
            if date_from:
                conds.append(dc >= date_from)
            if date_to:
                conds.append(dc <= date_to)

        # Amount floor.
        if min_amount is not None and spec.amount_col and hasattr(model, spec.amount_col):
            conds.append(getattr(model, spec.amount_col) >= min_amount)

        # A source_records spec must still be scoped to requested breadth sources.
        if spec.source == "source_records" and sources:
            wanted = [s for s in sources if s in BREADTH_SOURCES]
            if wanted:
                conds.append(model.source.in_(wanted))

        if not conds:
            continue

        stmt = select(model).where(and_(*conds))
        if spec.amount_col and hasattr(model, spec.amount_col):
            stmt = stmt.order_by(getattr(model, spec.amount_col).desc())
        stmt = stmt.limit(per_table_limit)

        for r in (await session.execute(stmt)).scalars():
            rtype = spec.record_type
            src = spec.source
            if spec.source == "source_records":
                src = _g(r, "source") or "breadth"
                rtype = _g(r, "record_type") or "breadth"
            hits.append({
                "source": src, "record_type": rtype, "table": spec.source,
                "title": spec.title_fn(r), "snippet": spec.snippet_fn(r),
                "entity": _g(r, spec.entity_col) if spec.entity_col else None,
                "date": _g(r, spec.date_col) if spec.date_col else None,
                "amount": getattr(r, spec.amount_col, None) if spec.amount_col else None,
                "url": spec.url_fn(r), "pk": r.id, "match": "structured",
            })
    return hits


# Source-name sets used for routing source_records filtering.
BREADTH_SOURCES = {"statcan", "iaac", "cer", "npri", "transport", "geospatial", "gc_news", "social_statements", "public_statements"}
EMBED_AND_NPRI = BREADTH_SOURCES
