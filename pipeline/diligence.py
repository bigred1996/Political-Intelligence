"""Goal B4 — the Start-Diligence service: form → ONE B3 run → persistent workspace.

This module owns the `Review` lifecycle and the workspace PROJECTION. It is a
strict consumer of B1/B2/B3:

  * `create_review` stores the form inputs, then launches exactly one B3
    `run_research` at the review's depth tier (the single source of truth that
    flowed form → B3), and links the resulting run id back to the review.
  * `build_workspace` READS a rehydrated B3 run (`get_research_run_response`,
    which itself calls no model) and arranges it into the diligence sections +
    filter facets. Every enrichment here (sector, risk level, date, entity,
    jurisdiction) is DETERMINISTIC — `pipeline.impact` + the table SPECS, never
    an AI call — so a workspace render is pure read with zero model round-trips.

Nothing here re-runs the loop; revisiting a review by id always returns the same
stored run.
"""
from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.review import Review
from pipeline.impact import industry_impact, resolve_sector
from pipeline.research import get_research_run_response, run_research
from search.retrieval import internal_url
from search.sql_search import SPECS, _g, _import_model

log = structlog.get_logger()

VALID_TIERS = {"brief", "standard", "deep"}

# Table → human source label (mirrors api/routes/records.py:_LABELS; kept local so
# this module doesn't import a routes module).
_LABELS = {
    "contracts": "Federal contracts", "donations": "Political donations",
    "grants": "Grants & contributions", "lobbying": "Lobbying communications",
    "ocl_registrations": "Lobbying registrations", "bills": "Bills & legislation",
    "gazette": "Canada Gazette", "tribunal": "Tribunal decisions",
    "appointments": "GIC appointments", "source_records": "Breadth sources",
    "hansard_mentions": "Hansard mentions",
}

# Table-name aliases between the semantic/SQL layers (mirrors records._ALIASES).
_ALIASES = {
    "gazette_entries": "gazette", "tribunal_decisions": "tribunal",
    "lobbying_records": "lobbying", "lobby": "lobbying",
    "social_statements": "source_records", "public_statements": "source_records",
    "social_posts": "source_records",
}
_BY_TABLE: dict[str, Any] = {s.source: s for s in SPECS}

# Which diligence section each evidentiary source rolls up into. A finding always
# also appears in "material findings" + the evidence library; this only governs
# the themed sections. Unmapped tables fall through to "other".
CATEGORY: dict[str, str] = {
    "bills": "legislative_regulatory",
    "gazette": "legislative_regulatory",
    "tribunal": "legislative_regulatory",
    "appointments": "legislative_regulatory",
    "lobbying": "lobbying_stakeholders",
    "ocl_registrations": "lobbying_stakeholders",
    "contracts": "govt_support",
    "grants": "govt_support",
    "donations": "political_attention",
    "hansard_mentions": "political_attention",
    "source_records": "political_attention",
}

# Pseudo/directory hits that the B3 loop records as coverage gaps — the ones that
# represent a connected person/org rather than "nothing found".
_CONNECTED_GAP_TABLES = {"politicians", "organizations", "entities", "committees"}


# --- seed-topic composition -----------------------------------------------

def compose_seed_topic(inputs: dict[str, Any]) -> str:
    """Build the B3 seed `topic` string from the structured form inputs.

    B3 uses this string VERBATIM as the deterministic seed-round query, and the
    seed round is the only round a keyless/degraded run gets — so seed retrieval
    quality is decisive. Retrieval is entity-anchored: a focused company name
    returns its evidentiary records, while piling on sector/keyword/concern
    tokens was observed to collapse the result to entity/sector pseudo-hits only
    (the deterministic query planner reads the whole string as one over-specific
    entity). So the seed is kept focused: the analyst's explicit research
    question if they gave one, otherwise the company alone. The richer framing
    (sectors, concerns, keywords) is preserved on the Review and shown in the
    workspace; gap-driven follow-up queries are the planner's job in later
    rounds, not the seed's."""
    company = (inputs.get("company") or "").strip()
    question = (inputs.get("research_question") or "").strip()
    return (question or company)[:500]


# --- review lifecycle ------------------------------------------------------

def _normalize_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    tier = str(inputs.get("depth_tier") or "standard").lower()
    if tier not in VALID_TIERS:
        tier = "standard"
    sectors = [str(s).strip() for s in (inputs.get("sectors") or []) if str(s).strip()]
    keywords = [str(k).strip() for k in (inputs.get("keywords") or []) if str(k).strip()]
    return {
        "company": (inputs.get("company") or "").strip(),
        "sectors": sectors,
        "transaction_type": (inputs.get("transaction_type") or None) or None,
        "jurisdiction": (inputs.get("jurisdiction") or None) or None,
        "date_from": (inputs.get("date_from") or None) or None,
        "date_to": (inputs.get("date_to") or None) or None,
        "key_concerns": (inputs.get("key_concerns") or None) or None,
        "keywords": keywords,
        "research_question": (inputs.get("research_question") or None) or None,
        "depth_tier": tier,
    }


async def create_review(session: AsyncSession, inputs: dict[str, Any]) -> dict[str, Any]:
    """Create one Review and launch exactly ONE B3 run at its depth tier. On any
    failure the review is persisted as `failed` with the error, never crashed —
    so the workspace always has a row to load."""
    norm = _normalize_inputs(inputs)
    if not norm["company"]:
        raise ValueError("company is required")

    review = Review(status="researching", **norm)
    session.add(review)
    await session.commit()

    topic = compose_seed_topic(norm)
    try:
        # Anchor retrieval on the company so the run only ever pulls THIS
        # entity's records — never another company's via a shared token like
        # "Resources"/"Energy" or a semantic near-miss on the name.
        run = await run_research(session, topic, norm["depth_tier"], entity=norm["company"])
        review.research_run_id = run["id"]
        review.status = "failed" if run["status"] == "error" else "ready"
    except Exception as exc:  # noqa: BLE001 — surface any run failure as a clean review state
        log.warning("review_run_failed", review_id=review.id, error=str(exc))
        review.status = "failed"
        review.error = str(exc)
    await session.commit()
    return await get_review_response(session, review.id)


async def get_review(session: AsyncSession, review_id: str) -> Review | None:
    return (
        await session.execute(select(Review).where(Review.id == review_id))
    ).scalar_one_or_none()


def _review_dict(review: Review) -> dict[str, Any]:
    return {
        "id": review.id,
        "company": review.company,
        "sectors": review.sectors or [],
        "transaction_type": review.transaction_type,
        "jurisdiction": review.jurisdiction,
        "date_from": review.date_from,
        "date_to": review.date_to,
        "key_concerns": review.key_concerns,
        "keywords": review.keywords or [],
        "research_question": review.research_question,
        "depth_tier": review.depth_tier,
        "research_run_id": review.research_run_id,
        "status": review.status,
        "error": review.error,
        "created_at": review.created_at.isoformat() if review.created_at else None,
        "updated_at": review.updated_at.isoformat() if review.updated_at else None,
    }


async def get_review_response(session: AsyncSession, review_id: str) -> dict[str, Any] | None:
    """The workspace payload: the review inputs, the rehydrated B3 run (no model
    calls), and the deterministic workspace projection over that run."""
    review = await get_review(session, review_id)
    if review is None:
        return None

    run: dict[str, Any] | None = None
    if review.research_run_id:
        run = await get_research_run_response(session, review.research_run_id)

    workspace = await build_workspace(session, run) if run else _empty_workspace()
    return {"review": _review_dict(review), "run": run, "workspace": workspace}


async def list_reviews(session: AsyncSession, limit: int = 50) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(Review).order_by(Review.created_at.desc()).limit(limit)
        )
    ).scalars().all()
    return [_review_dict(r) for r in rows]


# --- workspace projection (deterministic, no model calls) ------------------

def _empty_workspace() -> dict[str, Any]:
    return {
        "findings": [], "connected": [], "further_research": [],
        "source_coverage": [], "facets": _empty_facets(),
    }


def _empty_facets() -> dict[str, Any]:
    return {
        "sectors": [], "jurisdictions": [], "source_types": [], "risk_levels": [],
        "confidences": [], "signal_types": [], "entities": [],
        "interpretation_types": [], "date_min": None, "date_max": None,
    }


def _spec_and_key(table: str):
    key = _ALIASES.get(table, table)
    return _BY_TABLE.get(key), key


async def _finding_meta(session: AsyncSession, table: str, pk: Any, confidence: str,
                        claims: list[dict[str, Any]]) -> dict[str, Any]:
    """Derive the filterable metadata for one finding straight from its DB row +
    the deterministic impact layer. No model is called. Falls back to safe
    defaults if the row or spec can't be resolved."""
    interp_types = sorted({str(c.get("label", "")) for c in (claims or []) if c.get("label")})
    meta: dict[str, Any] = {
        "date": None, "sector_slug": None, "sector_name": None,
        "jurisdiction": "Federal", "source_type": _ALIASES.get(table, table),
        "source_label": _LABELS.get(_ALIASES.get(table, table), _ALIASES.get(table, table)),
        "risk_level": "watch", "signal_type": "record", "entity": None,
        "confidence": confidence or "low", "interpretation_types": interp_types,
    }
    spec, key = _spec_and_key(table)
    if spec is None:
        return meta
    meta["source_type"] = key
    meta["source_label"] = _LABELS.get(key, key.title())
    try:
        model = _import_model(spec.model_path)
        pk_value: Any = int(pk) if isinstance(pk, str) and pk.lstrip("-").isdigit() else pk
        row = (await session.execute(select(model).where(model.id == pk_value))).scalar_one_or_none()
    except Exception:  # noqa: BLE001 — a missing/odd row must never break the workspace
        return meta
    if row is None:
        return meta

    canonical = _g(row, spec.canonical_col) if spec.canonical_col else None
    entity = _g(row, spec.entity_col) if spec.entity_col else None
    rtype = spec.record_type
    if key == "source_records":
        rtype = _g(row, "record_type") or rtype
    province = _g(row, "province") or _g(row, "contributor_province") or ""
    title = spec.title_fn(row)
    summary_text = " ".join(filter(None, [_g(row, "summary"), _g(row, "description"), spec.snippet_fn(row)]))
    regulators_text = " ".join(filter(None, [
        _g(row, "department"), _g(row, "organization"), _g(row, "owner_org_title"), entity or ""]))

    sector, how = resolve_sector(canonical or None, title, summary_text, regulators_text=regulators_text)
    impact = industry_impact(rtype, sector, entity=entity or None,
                             amount=getattr(row, spec.amount_col, None) if spec.amount_col else None,
                             status=_g(row, "status") or None, how=how)

    meta["date"] = _g(row, spec.date_col) if spec.date_col else None
    meta["sector_slug"] = sector.slug if sector else None
    meta["sector_name"] = sector.name if sector else None
    meta["jurisdiction"] = province or "Federal"
    meta["risk_level"] = impact.get("severity") or "watch"
    meta["signal_type"] = rtype
    meta["entity"] = entity or (canonical.title() if canonical else None)
    return meta


def _collect_findings(run: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten + de-duplicate every interpreted finding across the run's rounds,
    preserving first-seen order."""
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for rd in run.get("rounds", []):
        for it in rd.get("interpretations", []):
            keyt = (str(it.get("table")), str(it.get("pk")))
            if keyt in seen:
                continue
            seen.add(keyt)
            out.append(it)
    return out


async def build_workspace(session: AsyncSession, run: dict[str, Any]) -> dict[str, Any]:
    """Project a rehydrated B3 run into the diligence workspace: enriched
    findings (with filter metadata + an internal record link), connected
    people/orgs, further-research gaps, source coverage, and the filter facets.
    Pure read — calls no model."""
    interps = _collect_findings(run)

    findings: list[dict[str, Any]] = []
    for it in interps:
        table, pk = str(it.get("table")), str(it.get("pk"))
        meta = await _finding_meta(session, table, pk, it.get("confidence", "low"), it.get("claims", []))
        findings.append({
            "interpretation_id": it.get("id"),
            "table": table,
            "pk": pk,
            "title": _title_for(it),
            "internal_url": internal_url(table, pk),
            "source_fact": it.get("source_fact", ""),
            "interpretation": it.get("interpretation", ""),
            "impact": it.get("impact", ""),
            "recommendation": it.get("recommendation", ""),
            "evidence_limitations": it.get("evidence_limitations", ""),
            "confidence": it.get("confidence", "low"),
            "claims": it.get("claims", []),
            "generated_by": it.get("generated_by", ""),
            "category": CATEGORY.get(meta["source_type"], "other"),
            "meta": meta,
        })

    connected = _connected_from_gaps(run)
    further = _further_research_from_gaps(run)
    source_coverage = _source_coverage(findings)
    facets = _build_facets(findings)

    return {
        "findings": findings,
        "connected": connected,
        "further_research": further,
        "source_coverage": source_coverage,
        "facets": facets,
    }


def _title_for(it: dict[str, Any]) -> str:
    sf = (it.get("source_fact") or "").strip()
    if sf:
        return sf[:160]
    return f"{it.get('table')}:{it.get('pk')}"


def _connected_from_gaps(run: dict[str, Any]) -> list[dict[str, Any]]:
    """Connected people/orgs = the directory hits the B3 loop recorded as
    coverage gaps (politicians, organizations, entities, committees). Deduped,
    each linked to its real in-app page."""
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for rd in run.get("rounds", []):
        for g in rd.get("coverage_gaps", []):
            tbl = str(g.get("table") or "")
            pk = str(g.get("pk") or "")
            if tbl not in _CONNECTED_GAP_TABLES or not pk:
                continue
            keyt = (tbl, pk)
            if keyt in seen:
                continue
            seen.add(keyt)
            out.append({
                "table": tbl, "pk": pk, "kind": tbl,
                "title": g.get("title") or f"{tbl}:{pk}",
                "internal_url": internal_url(tbl, pk),
            })
    return out


def _further_research_from_gaps(run: dict[str, Any]) -> list[dict[str, Any]]:
    """Leads the run did not fully pursue: records hit but not interpreted
    (interpretation cap reached) and non-evidentiary hits worth a manual look.
    These are NOT findings — they are explicit 'go look here next' pointers."""
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for rd in run.get("rounds", []):
        for g in rd.get("coverage_gaps", []):
            gtype = str(g.get("type") or "")
            tbl = str(g.get("table") or "")
            pk = str(g.get("pk") or "")
            keyt = (gtype, tbl, pk)
            if keyt in seen:
                continue
            seen.add(keyt)
            out.append({
                "type": gtype, "table": tbl or None, "pk": pk or None,
                "title": g.get("title") or "",
                "internal_url": internal_url(tbl, pk) if tbl and pk else None,
            })
    return out


def _source_coverage(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    labels: dict[str, str] = {}
    for f in findings:
        st = f["meta"]["source_type"]
        counts[st] = counts.get(st, 0) + 1
        labels[st] = f["meta"]["source_label"]
    return sorted(
        ({"source_type": st, "label": labels[st], "count": c} for st, c in counts.items()),
        key=lambda r: r["count"], reverse=True,
    )


def _build_facets(findings: list[dict[str, Any]]) -> dict[str, Any]:
    facets = _empty_facets()
    sectors: dict[str, str] = {}
    jurisdictions: set[str] = set()
    source_types: dict[str, str] = {}
    risk_levels: set[str] = set()
    confidences: set[str] = set()
    signal_types: set[str] = set()
    entities: set[str] = set()
    interp_types: set[str] = set()
    dates: list[str] = []

    for f in findings:
        m = f["meta"]
        if m.get("sector_slug"):
            sectors[m["sector_slug"]] = m.get("sector_name") or m["sector_slug"]
        if m.get("jurisdiction"):
            jurisdictions.add(m["jurisdiction"])
        if m.get("source_type"):
            source_types[m["source_type"]] = m.get("source_label") or m["source_type"]
        if m.get("risk_level"):
            risk_levels.add(m["risk_level"])
        if m.get("confidence"):
            confidences.add(m["confidence"])
        if m.get("signal_type"):
            signal_types.add(m["signal_type"])
        if m.get("entity"):
            entities.add(m["entity"])
        for t in m.get("interpretation_types", []):
            interp_types.add(t)
        if m.get("date"):
            dates.append(str(m["date"]))

    facets["sectors"] = [{"slug": s, "name": n} for s, n in sorted(sectors.items())]
    facets["jurisdictions"] = sorted(jurisdictions)
    facets["source_types"] = [{"key": k, "label": v} for k, v in sorted(source_types.items())]
    facets["risk_levels"] = sorted(risk_levels)
    facets["confidences"] = sorted(confidences)
    facets["signal_types"] = sorted(signal_types)
    facets["entities"] = sorted(entities)
    facets["interpretation_types"] = sorted(interp_types)
    if dates:
        facets["date_min"] = min(dates)
        facets["date_max"] = max(dates)
    return facets
