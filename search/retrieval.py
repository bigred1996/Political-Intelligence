"""Unified internal-records retrieval — the layer downstream AI interpretation
(B2+) must sit on top of, never around.

This is deliberately NOT ``search.engine.search()``. That function calls
Claude (via ``make_plan`` and ``_synthesize``) when a key is present, and
returns AI-written prose. This module never imports an AI provider: the query
plan comes from ``search.planner.fallback_plan`` (deterministic regex/keyword
parsing) and ranking comes from exact SQL predicates + the local embedding
model only. The result is a fully deterministic, citation-safe retrieval set.

``search.sql_search``/``search.index`` already cover every *tabular* record
type (contracts, donations, grants, lobbying, bills, gazette, tribunal,
appointments, hansard mentions, breadth ``source_records``). This module adds
the record types that exist in Nessus but were never wired into search:
politicians, sectors, entities, departments/regulators, committees, and prior
reports. Each of those is matched deterministically against a small, bounded
catalog (the politician roster, the sector taxonomy, curated regulator names,
the nine known House committees, generated reports) and — except for
politicians/reports/sectors, which are first-class DB rows — gated on a real
existence check against the DB so nothing is ever surfaced that has zero
internal evidence behind it.

"Findings" (``pipeline.evidence_graph.GraphFinding``) are intentionally NOT a
retrievable record type here: they are computed fresh per request and have no
persisted, stable identity, so citing one would violate the "never reference a
record you did not actually retrieve" rule. See CLAUDE.md / the B1 report for
the reasoning; B2 should either persist findings with a stable id before
citing them, or only cite the primary records a finding is built from.
"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.appointment import Appointment
from api.models.contract import Contract
from api.models.donation import Bill
from api.models.grant import Grant
from api.models.politician import HansardMention, Politician
from api.models.regulation import GazetteEntry
from api.models.report import Report
from api.routes.parliament import _COMMON_COMMITTEES as KNOWN_COMMITTEES
from api.routes.parliament import _committee_terms as committee_terms
from pipeline.entity_resolver import normalize
from pipeline.sector_mapper import SECTORS
from search.embeddings import DIM, MODEL_NAME
from search.engine import _merge
from search.index import semantic_search
from search.planner import fallback_plan
from search.sql_search import SPECS, _import_model, structured_search

EMBEDDING_MODEL_LABEL = f"{MODEL_NAME} (dim={DIM})"

# Physical table names used by the semantic indexer that differ from the short
# `source` key the SQL layer / records route uses — same aliasing as
# api/routes/records.py:_ALIASES, kept in sync so a link is never broken.
_TABLE_ALIASES = {
    "gazette_entries": "gazette",
    "tribunal_decisions": "tribunal",
    "lobbying_records": "lobbying",
}

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'\-]{2,}")


def internal_url(table: str | None, pk: Any) -> str | None:
    """The in-app Nessus page for a (table, pk) — mirrors web/lib/navigation.ts."""
    if not table or pk in (None, ""):
        return None
    if table == "politicians":
        return f"/politicians/{pk}"
    if table == "sectors":
        return f"/sectors/{pk}"
    if table == "entities":
        return f"/entities/{pk}"
    if table == "committees":
        return f"/committees/{pk}"
    if table == "reports":
        return f"/briefings/{pk}"
    if table == "organizations":
        kind, _, name = str(pk).partition(":")
        return f"/organizations/{kind}/{name}" if name else None
    canonical = _TABLE_ALIASES.get(table, table)
    return f"/records/{canonical}/{pk}"


def _to_hit(raw: dict[str, Any]) -> dict[str, Any]:
    table = raw.get("table")
    pk = raw.get("pk")
    return {
        "id": f"{table}:{pk}",
        "table": table,
        "pk": pk,
        "record_type": raw.get("record_type") or "record",
        "source": raw.get("source") or table,
        "title": raw.get("title") or "",
        "snippet": raw.get("snippet") or "",
        "score": round(float(raw.get("score") or 0.0), 4),
        "match": raw.get("match") or "deterministic",
        "date": raw.get("date"),
        "amount": raw.get("amount"),
        "internal_url": internal_url(table, pk),
        "external_url": raw.get("url"),
    }


def _openparliament_url(p: Politician) -> str | None:
    if not p.url:
        return None
    return f"https://openparliament.ca{p.url}" if p.url.startswith("/") else p.url


async def _search_politicians(session: AsyncSession, keywords: list[str], query_text: str, limit: int = 6) -> list[dict[str, Any]]:
    terms = keywords or _WORD_RE.findall(query_text)
    if not terms:
        return []
    conds = []
    for t in terms:
        like = f"%{t}%"
        conds += [Politician.name.ilike(like), Politician.party.ilike(like),
                  Politician.riding.ilike(like), Politician.role.ilike(like)]
    rows = (await session.execute(select(Politician).where(or_(*conds)).limit(limit))).scalars().all()
    hits = []
    for p in rows:
        name_hit = any(t.lower() in (p.name or "").lower() for t in terms)
        hits.append({
            "table": "politicians", "pk": p.slug, "record_type": "person",
            "source": "Politicians directory", "title": p.name,
            "snippet": " · ".join(filter(None, [p.role, p.party, p.riding])),
            "url": _openparliament_url(p), "score": 0.8 if name_hit else 0.5,
            "match": "deterministic",
        })
    return hits


def _search_sectors(keywords: list[str], query_text: str, limit: int = 5) -> list[dict[str, Any]]:
    ql = query_text.lower()
    terms = [t.lower() for t in (keywords or [])]
    scored: list[tuple[float, Any]] = []
    for sector in SECTORS.values():
        kw_hits = sum(1 for kw in sector.keywords if kw.lower() in ql)
        name_hit = sector.name.lower() in ql or sector.slug.replace("-", " ") in ql
        term_hits = sum(1 for t in terms if t in sector.name.lower() or any(t in kw.lower() for kw in sector.keywords))
        if name_hit:
            score = 0.9
        elif kw_hits or term_hits:
            score = min(0.85, 0.5 + 0.1 * (kw_hits + term_hits))
        else:
            score = 0.0
        if score:
            scored.append((score, sector))
    scored.sort(key=lambda x: (-x[0], x[1].slug))
    return [{
        "table": "sectors", "pk": sector.slug, "record_type": "sector",
        "source": "Sector taxonomy", "title": sector.name, "snippet": sector.blurb,
        "score": score, "match": "deterministic",
    } for score, sector in scored[:limit]]


async def _entity_has_rows(session: AsyncSession, canonical: str) -> bool:
    for spec in SPECS:
        if not spec.canonical_col:
            continue
        model = _import_model(spec.model_path)
        if not hasattr(model, spec.canonical_col):
            continue
        exists = (await session.execute(
            select(model.id).where(getattr(model, spec.canonical_col) == canonical).limit(1)
        )).first()
        if exists:
            return True
    return False


async def _search_entities(session: AsyncSession, query_text: str, limit: int = 3) -> list[dict[str, Any]]:
    ql = query_text.lower()
    candidates = sorted({e for sector in SECTORS.values() for e in sector.entities if e in ql})
    out: list[dict[str, Any]] = []
    for canonical in candidates:
        if await _entity_has_rows(session, canonical):
            out.append({
                "table": "entities", "pk": canonical, "record_type": "entity",
                "source": "Entity intelligence", "title": canonical.title(),
                "snippet": f"Cross-source profile for {canonical.title()}.",
                "score": 0.85, "match": "deterministic",
            })
        if len(out) >= limit:
            break
    return out


async def _organization_record_count(session: AsyncSession, name: str) -> int:
    like = f"%{name}%"
    for model, column in (
        (Contract, Contract.owner_org_title), (Grant, Grant.owner_org_title),
        (GazetteEntry, GazetteEntry.department), (Appointment, Appointment.organization),
    ):
        count = int((await session.execute(
            select(func.count()).select_from(model).where(column.ilike(like))
        )).scalar_one() or 0)
        if count:
            return count
    return 0


async def _search_organizations(session: AsyncSession, query_text: str, limit: int = 3) -> list[dict[str, Any]]:
    ql = query_text.lower()
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for sector in SECTORS.values():
        for reg in sector.regulators:
            key = reg.lower()
            if key in seen or key not in ql:
                continue
            seen.add(key)
            count = await _organization_record_count(session, reg)
            if count:
                out.append({
                    "table": "organizations", "pk": f"regulator:{reg}", "record_type": "regulator",
                    "source": "Departments & regulators", "title": reg,
                    "snippet": f"{count} internal record(s) reference {reg}.",
                    "score": 0.75, "match": "deterministic",
                })
            if len(out) >= limit:
                return out
    return out


async def _committee_has_evidence(session: AsyncSession, terms: list[str]) -> bool:
    bill_conds = [Bill.title_en.ilike(f"%{t}%") for t in terms] + [Bill.status.ilike(f"%{t}%") for t in terms]
    if (await session.execute(select(Bill.id).where(or_(*bill_conds)).limit(1))).first():
        return True
    hansard_conds = [HansardMention.keyword.ilike(f"%{t}%") for t in terms] + [HansardMention.excerpt.ilike(f"%{t}%") for t in terms]
    if (await session.execute(select(HansardMention.id).where(or_(*hansard_conds)).limit(1))).first():
        return True
    return False


async def _search_committees(session: AsyncSession, query_text: str, limit: int = 3) -> list[dict[str, Any]]:
    ql = query_text.lower()
    out: list[dict[str, Any]] = []
    for slug, name in KNOWN_COMMITTEES.items():
        if slug not in ql and name.lower() not in ql:
            continue
        terms = committee_terms(slug, name)
        if not await _committee_has_evidence(session, terms):
            continue
        out.append({
            "table": "committees", "pk": slug, "record_type": "committee",
            "source": "House committees", "title": name,
            "snippet": f"Internal evidence connected to {name}.",
            "score": 0.8, "match": "deterministic",
        })
        if len(out) >= limit:
            break
    return out


async def _search_reports(session: AsyncSession, keywords: list[str], limit: int = 5) -> list[dict[str, Any]]:
    if not keywords:
        return []
    conds = [Report.company_name.ilike(f"%{t}%") for t in keywords]
    rows = (await session.execute(
        select(Report).where(or_(*conds)).order_by(Report.created_at.desc()).limit(limit)
    )).scalars().all()
    return [{
        "table": "reports", "pk": r.id, "record_type": "report",
        "source": "Generated reports",
        "title": f"{r.company_name} — {r.report_type.replace('_', ' ')} report",
        "snippet": f"Status: {r.status} · generated by {r.generated_by}.",
        "date": r.created_at.date().isoformat() if r.created_at else None,
        "score": 0.7, "match": "deterministic",
    } for r in rows]


async def retrieve(session: AsyncSession, query: str, *, limit: int = 40) -> dict[str, Any]:
    """Run the full deterministic retrieval pipeline for a natural-language query.

    Returns a dict with the query, the (deterministic) plan used, the flat
    ranked `results` list, the same results grouped `by_type`, source counts,
    and an explicit `empty` flag — never silently returns nothing.
    """
    bounded_limit = min(max(limit, 1), 100)
    plan = fallback_plan(query)
    canonical = normalize(plan.entity_text) if plan.entity_text else None

    structured = await structured_search(
        session,
        keywords=plan.keywords or None,
        canonical=canonical,
        entity_text=plan.entity_text,
        date_from=plan.date_from,
        date_to=plan.date_to,
        min_amount=plan.min_amount,
        sources=plan.sources,
        per_table_limit=25,
    )
    semantic = semantic_search(plan.semantic_query, k=max(40, bounded_limit), sources=plan.sources)
    tabular = _merge(structured, semantic, bounded_limit * 3)

    pseudo: list[dict[str, Any]] = []
    pseudo += await _search_politicians(session, plan.keywords, plan.semantic_query)
    pseudo += _search_sectors(plan.keywords, plan.semantic_query)
    pseudo += await _search_entities(session, plan.semantic_query)
    pseudo += await _search_organizations(session, plan.semantic_query)
    pseudo += await _search_committees(session, plan.semantic_query)
    pseudo += await _search_reports(session, plan.keywords)

    hits = [_to_hit(h) for h in tabular] + [_to_hit(h) for h in pseudo]
    hits.sort(key=lambda h: (-h["score"], h["table"] or "", str(h["pk"])))
    hits = hits[:bounded_limit]

    by_type: dict[str, list[dict[str, Any]]] = {}
    for h in hits:
        by_type.setdefault(h["record_type"], []).append(h)

    return {
        "query": query,
        "plan": plan.to_dict(),
        "embedding_model": EMBEDDING_MODEL_LABEL,
        "results": hits,
        "by_type": by_type,
        "counts": {
            "returned": len(hits),
            "structured": len(structured),
            "semantic": len(semantic),
            "deterministic": len(pseudo),
            "by_type": {k: len(v) for k, v in by_type.items()},
        },
        "empty": len(hits) == 0,
    }
