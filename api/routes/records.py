"""Universal record detail — view any individual record in-app, plus its
inferred-graph relations to every other record in the system.

This is the "pull up any data point, see how it connects" surface. It is
deliberately generic: one route resolves a record in ANY table by (table, pk),
dumps its full fields, and computes its connections without per-source code.

Relations are a layered inferred graph, strongest signal first:
  1. by_source  — the SAME canonical entity across every other table (the moat:
                  this company/person's contracts, donations, lobbying, incidents…)
  2. sector     — the industry roster this entity belongs to, plus peer entities
  3. timeline   — the entity's cross-source activity in chronological order
                  (surfaces temporal co-occurrence — lobbying then a contract, etc.)

Everything returned carries (table, pk) so the front-end can link every related
item to its own detail page. No external links are required to navigate.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from api.schemas import RecordDetailResponse
from pipeline.impact import resolve_sector
from pipeline.record_lens import assessment, cross_source_signature, signal_strength
from pipeline.sector_mapper import sector_for_entity
from search.sql_search import SPECS, _g, _import_model
from ..models.record_link import RecordLink

router = APIRouter(prefix="/api/records", tags=["records"])

# Map every table name (and its aliases from the semantic indexer) to its spec.
# The semantic index labels gazette/tribunal rows with the physical table name,
# while the SQL layer uses the short source name — accept both so any (table, pk)
# coming from search resolves.
_BY_TABLE: dict[str, Any] = {s.source: s for s in SPECS}
_ALIASES = {
    "gazette_entries": "gazette",
    "tribunal_decisions": "tribunal",
    "lobbying_records": "lobbying",
    "lobby": "lobbying",
    "social_statements": "source_records",
    "public_statements": "source_records",
    "social_posts": "source_records",
}

# Human labels for the source/table keys.
_LABELS = {
    "contracts": "Federal contracts", "donations": "Political donations",
    "grants": "Grants & contributions", "lobbying": "Lobbying communications",
    "ocl_registrations": "Lobbying registrations", "bills": "Bills & legislation",
    "gazette": "Canada Gazette", "tribunal": "Tribunal decisions",
    "appointments": "GIC appointments", "source_records": "Breadth sources",
    "hansard_mentions": "Hansard mentions", "hansard_speeches": "Hansard transcripts",
}

_SOURCE_RECORD_LABELS = {
    "social_statements": "Public statement",
    "public_statements": "Public statement",
    "gc_news": "Government news release",
    "cer": "CER operations record",
    "npri": "NPRI release record",
    "iaac": "Impact assessment record",
    "statcan": "StatCan dataset",
    "transport": "Transport catalogue record",
    "geospatial": "Geospatial catalogue record",
}

# Column names that hold a verbose blob we render compactly, not as a plain field.
_JSON_COLS = {"raw", "institutions", "subject_matters", "federal_benefits"}

# Internal/ops columns that aren't meaningful to an analyst reading the record
# (the id and source/table are already shown in the page header; ingested_at is
# a pipeline timestamp, not a fact about the record itself).
_HIDDEN_COLS = {"id", "ingested_at", "canonical_name"}

# Tables with a genuine body of text worth rendering in full on the record page,
# rather than truncated to 600 chars inside the generic field dump — this is what
# lets the page "fully live in the platform" instead of sending the reader to the
# external source just to read the actual content.
_BODY_COL = {
    "hansard_speeches": "content",
    "gazette": "description",
    "tribunal": "summary",
    "source_records": "summary",
    "hansard_mentions": "excerpt",
}


def _spec_for(table: str):
    key = _ALIASES.get(table, table)
    return _BY_TABLE.get(key), key


def _fmt(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, (list, dict)):
        if not value:
            return None
        if isinstance(value, list):
            return ", ".join(str(v) for v in value[:20])
        return ", ".join(f"{k}: {v}" for k, v in list(value.items())[:20])
    return str(value)


def _field_dump(model, row) -> list[dict[str, str]]:
    """Every column of the record as label/value pairs — the full data point."""
    out: list[dict[str, str]] = []
    for col in model.__table__.columns:
        name = col.name
        if name in _JSON_COLS or name in _HIDDEN_COLS:
            continue  # rendered separately as `raw`, or not analyst-relevant
        val = _fmt(getattr(row, name, None))
        if val is None:
            continue
        label = name.replace("_", " ").strip().capitalize()
        out.append({"key": name, "label": label, "value": val[:600]})
    return out


def _short(spec, row) -> dict[str, Any]:
    """A compact, linkable reference to a record (for relation lists)."""
    table = spec.source
    src = table
    rtype = spec.record_type
    if table == "source_records":
        src = _g(row, "source") or "breadth"
        rtype = _g(row, "record_type") or "breadth"
    return {
        "table": table, "pk": row.id, "source": src, "record_type": rtype,
        "type_label": _SOURCE_RECORD_LABELS.get(src) if table == "source_records" else _LABELS.get(table, table.title()),
        "title": spec.title_fn(row)[:160],
        "date": _g(row, spec.date_col) if spec.date_col else None,
        "amount": getattr(row, spec.amount_col, None) if spec.amount_col else None,
        "entity": _g(row, spec.entity_col) if spec.entity_col else None,
    }



async def _explicit_links(
    session: AsyncSession, this_table: str, this_pk: int, limit: int = 60,
) -> dict[str, Any]:
    """Materialized record_links touching this record, resolved to compact refs."""
    links = (await session.execute(
        select(RecordLink)
        .where(or_(
            and_(RecordLink.source_table == this_table, RecordLink.source_pk == this_pk),
            and_(RecordLink.target_table == this_table, RecordLink.target_pk == this_pk),
        ))
        .order_by(RecordLink.confidence.desc(), RecordLink.id.desc())
        .limit(limit)
    )).scalars().all()

    refs: list[dict[str, Any]] = []
    for link in links:
        outgoing = link.source_table == this_table and link.source_pk == this_pk
        table = link.target_table if outgoing else link.source_table
        pk = link.target_pk if outgoing else link.source_pk
        spec, key = _spec_for(table)
        if not spec:
            continue
        model = _import_model(spec.model_path)
        row = (await session.execute(select(model).where(model.id == pk))).scalar_one_or_none()
        if row is None:
            continue
        ref = _short(spec, row)
        ref["relationship"] = link.relationship
        ref["confidence"] = link.confidence
        ref["direction"] = "out" if outgoing else "in"
        if link.evidence:
            ref["evidence"] = link.evidence
        refs.append(ref)

    groups: dict[str, dict[str, Any]] = {}
    for ref in refs:
        rel = ref["relationship"]
        group = groups.setdefault(rel, {"relationship": rel, "count": 0, "records": []})
        group["count"] += 1
        group["records"].append(ref)
    return {"total": len(refs), "groups": list(groups.values()), "records": refs}


async def _related_by_entity(
    session: AsyncSession, canonical: str, this_table: str, this_pk: int,
    per_source: int = 6,
) -> tuple[list[dict[str, Any]], int]:
    """Every record sharing this canonical entity, grouped by source. Indexed → fast."""
    groups: list[dict[str, Any]] = []
    total = 0
    for spec in SPECS:
        if not (spec.canonical_col and canonical):
            continue
        model = _import_model(spec.model_path)
        if not hasattr(model, spec.canonical_col):
            continue
        cond = getattr(model, spec.canonical_col) == canonical
        # Exclude the record itself.
        if spec.source == this_table:
            cond = and_(cond, model.id != this_pk)

        count = (await session.execute(
            select(func.count()).select_from(model).where(cond))).scalar_one()
        if not count:
            continue
        total += count

        stmt = select(model).where(cond)
        if spec.amount_col and hasattr(model, spec.amount_col):
            stmt = stmt.order_by(getattr(model, spec.amount_col).desc())
        elif spec.date_col and hasattr(model, spec.date_col):
            stmt = stmt.order_by(getattr(model, spec.date_col).desc())
        stmt = stmt.limit(per_source)
        rows = (await session.execute(stmt)).scalars().all()

        # source_records can mix several breadth sources under one spec — split label.
        if spec.source == "source_records":
            buckets: dict[str, list] = {}
            for r in rows:
                buckets.setdefault(_g(r, "source") or "breadth", []).append(r)
            for src, rs in buckets.items():
                groups.append({
                    "table": "source_records", "source": src,
                    "label": src.replace("_", " ").title(),
                    "count": len(rs), "records": [_short(spec, r) for r in rs],
                    "partial": count > per_source,
                })
        else:
            groups.append({
                "table": spec.source, "source": spec.source,
                "label": _LABELS.get(spec.source, spec.source.title()),
                "count": count, "records": [_short(spec, r) for r in rows],
                "partial": count > per_source,
            })
    groups.sort(key=lambda g: g["count"], reverse=True)
    return groups, total


def _timeline(groups: list[dict[str, Any]], this: dict[str, Any]) -> list[dict[str, Any]]:
    """Chronological union of the entity's records (incl. the current one).

    Surfaces temporal co-occurrence: a lobbying communication and a contract for
    the same firm landing weeks apart is exactly the kind of connection a
    due-diligence analyst is looking for.
    """
    items = [r for g in groups for r in g["records"] if r.get("date")]
    cur = dict(this)
    cur["current"] = True
    if cur.get("date"):
        items.append(cur)
    # ISO dates sort lexically; M/D/YYYY won't, but most core sources are ISO.
    items.sort(key=lambda r: str(r.get("date") or ""), reverse=True)
    return items[:24]


# Why a politician is genuinely tied to THIS record (from materialized links).
_PERSON_LINK_WHY = {
    "spoken_by": "Delivered this intervention",
    "mp_voted": "Recorded a vote on this motion",
}


async def _genuine_people(
    session: AsyncSession, key: str, row: Any, explicit_links: dict[str, Any],
    sponsor: str | None,
) -> list[dict[str, Any]]:
    """People with a REAL, explainable tie to this record — never keyword noise.

    Sources of a genuine tie: the bill's sponsor, the MP who delivered a Hansard
    speech (`spoken_by`), MPs recorded voting on a motion (`mp_voted`), and the
    appointee named on a GIC appointment. Regulators are handled separately as
    institutional context, not as "people on this record".
    """
    from api.models.politician import Politician

    people: list[dict[str, Any]] = []
    seen: set[str] = set()

    # 1. Politicians materialized as explicit links to this record.
    why_by_pid: dict[int, str] = {}
    for ref in explicit_links.get("records", []):
        if ref.get("table") == "politicians" and ref.get("pk") is not None:
            why_by_pid.setdefault(int(ref["pk"]), _PERSON_LINK_WHY.get(ref.get("relationship"), "Linked to this record"))
    if why_by_pid:
        rows = (await session.execute(
            select(Politician).where(Politician.id.in_(list(why_by_pid)))
        )).scalars().all()
        for p in rows:
            name_key = (p.name or "").lower().strip()
            if not name_key or name_key in seen:
                continue
            seen.add(name_key)
            people.append({
                "type": "politician", "name": p.name, "slug": p.slug,
                "party": p.party, "role": p.role,
                "photo_url": getattr(p, "photo_url", None),
                "why": why_by_pid.get(p.id, "Linked to this record"),
            })

    # 2. Bill sponsor (resolve to an MP profile where possible).
    if sponsor:
        name_key = sponsor.lower().strip()
        if name_key not in seen:
            seen.add(name_key)
            p = (await session.execute(
                select(Politician).where(Politician.name.ilike(f"%{sponsor.strip()}%")).limit(1)
            )).scalar_one_or_none()
            people.append({
                "type": "politician", "name": p.name if p else sponsor,
                "slug": p.slug if p else None, "party": p.party if p else None,
                "role": p.role if p else "Bill sponsor",
                "photo_url": getattr(p, "photo_url", None) if p else None,
                "why": "Sponsored this legislation",
            })

    # 3. The appointee named on a GIC appointment is the record's subject.
    if key == "appointments":
        name = _g(row, "appointee_name")
        if name and name.lower().strip() not in seen:
            seen.add(name.lower().strip())
            org = _g(row, "organization")
            people.append({
                "type": "appointee", "name": name, "slug": None, "party": None,
                "role": _g(row, "position_title") or "Appointee", "photo_url": None,
                "why": f"Appointed to {org}" if org else "Subject of this appointment",
            })

    return people[:12]


# Per-type lateral lookups for one-off records — "records like this" via an indexed
# column, so a connection-less record still offers somewhere to go. Each maps a
# physical table key → (filter column, order column, label template, basis).
_LATERAL: dict[str, tuple[str, str | None, str, str]] = {
    "contracts": ("owner_org_title", "contract_value", "Other contracts from {v}", "same contracting department"),
    "grants": ("owner_org_title", "agreement_value", "Other grants from {v}", "same department"),
    "appointments": ("organization", "appointment_date", "Other appointments to {v}", "same body"),
    "bills": ("sponsor", "introduced_date", "Other bills sponsored by {v}", "same sponsor"),
    "tribunal": ("body", "decision_date", "Other {v} decisions", "same tribunal"),
}


async def _lateral_records(
    session: AsyncSession, model: Any, spec: Any, key: str, row: Any, pk: int,
) -> list[dict[str, Any]]:
    """Indexed 'records like this one' for records with no entity graph to lean on."""
    cfg = _LATERAL.get(key)
    if not cfg:
        return []
    col, order_col, label_tmpl, basis = cfg
    value = _g(row, col)
    if not value or not hasattr(model, col):
        return []
    stmt = select(model).where(getattr(model, col) == value, model.id != pk)
    if order_col and hasattr(model, order_col):
        stmt = stmt.order_by(getattr(model, order_col).desc())
    rows = (await session.execute(stmt.limit(5))).scalars().all()
    if not rows:
        return []
    return [{
        "label": label_tmpl.format(v=value), "basis": basis,
        "records": [_short(spec, r) for r in rows],
    }]


@router.get("/{table}/{pk}", response_model=RecordDetailResponse)
async def get_record(table: str, pk: int, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    spec, key = _spec_for(table)
    if not spec:
        raise HTTPException(404, f"Unknown record table: {table}")
    model = _import_model(spec.model_path)
    row = (await session.execute(select(model).where(model.id == pk))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, f"No {key} record #{pk}")

    canonical = _g(row, spec.canonical_col) if spec.canonical_col else None
    entity_name = _g(row, spec.entity_col) if spec.entity_col else None

    src = key
    rtype = spec.record_type
    if spec.source == "source_records":
        src = _g(row, "source") or "breadth"
        rtype = _g(row, "record_type") or "breadth"
    type_label = _SOURCE_RECORD_LABELS.get(src) if spec.source == "source_records" else None

    # Full, untruncated body text for sources that have one (Hansard speeches,
    # gazette notices, tribunal decisions, breadth summaries) — rendered inline
    # so reading the record never requires leaving the platform. Dropped from
    # the generic field dump below to avoid showing it twice, once truncated.
    body_col = _BODY_COL.get(key)
    body = (_g(row, body_col) or None) if body_col else None

    fields = _field_dump(model, row)
    if body and body_col:
        fields = [f for f in fields if f["key"] != body_col]

    record = {
        "title": spec.title_fn(row),
        "source": src, "record_type": rtype,
        "type_label": type_label,
        "entity": entity_name or None, "canonical": canonical or None,
        "date": _g(row, spec.date_col) if spec.date_col else None,
        "amount": getattr(row, spec.amount_col, None) if spec.amount_col else None,
        "url": spec.url_fn(row),  # external source — secondary, navigation stays in-app
        "fields": fields,
        "body": body,
        "raw": getattr(row, "raw", None) if hasattr(row, "raw") else None,
    }

    # ── Industry lens (confidence-tiered): entity-roster matches are confirmed,
    # keyword matches need corroboration before being asserted — so a PSPC road
    # contract no longer mis-reads as "Aerospace & Defence".
    summary_text = " ".join(filter(None, [
        _g(row, "summary"), _g(row, "description"), spec.snippet_fn(row)]))
    # Only genuine regulator/department signals feed the regulator fallback — NOT a
    # contract's generic buyer (owner_org_title="…Procurement Canada" would otherwise
    # match every contract to Aerospace & Defence) and not the vendor name.
    regulators_text = " ".join(filter(None, [_g(row, "department"), _g(row, "organization")]))
    sector, how, confidence = resolve_sector(
        canonical or None, record["title"], summary_text, regulators_text=regulators_text)
    industry = {"name": sector.name, "slug": sector.slug, "blurb": sector.blurb,
                "matched_by": how, "confidence": confidence} if sector else None
    governing_regulators = list(sector.regulators) if sector else []

    # ── Connections (the moat): the same canonical entity across every source,
    # plus the materialized explicit links (Hansard speakers, bill mentions, votes).
    explicit = await _explicit_links(session, spec.source, pk)
    relations: dict[str, Any] = {
        "by_source": [], "total": 0, "sector": None, "sector_peers": [],
        "timeline": [], "explicit_links": explicit, "lateral": [],
        "cross_source_signature": {"sources": [], "distinct": 0, "insight": None},
    }
    if canonical:
        groups, total = await _related_by_entity(session, canonical, spec.source, pk)
        relations["by_source"] = groups
        relations["total"] = total
        relations["timeline"] = _timeline(groups, {
            "table": spec.source, "pk": pk, "source": src, "record_type": rtype,
            "title": record["title"][:160], "date": record["date"], "amount": record["amount"],
        })
        sec = sector_for_entity(canonical)
        if sec:
            relations["sector"] = {"slug": sec.slug, "name": sec.name, "blurb": sec.blurb}
            relations["sector_peers"] = [
                {"canonical": e, "name": e.title()} for e in sec.entities if e != canonical
            ][:12]

    distinct_sources = len(relations["by_source"])
    total_conn = relations["total"]
    signature = cross_source_signature(relations["by_source"], _LABELS.get(key, key))
    relations["cross_source_signature"] = signature

    # Lateral "records like this" only for connection-poor records — rich records
    # already fill the rail with real cross-source ties, so skip the extra queries.
    if total_conn <= 3:
        relations["lateral"] = await _lateral_records(session, model, spec, key, row, pk)

    # ── The deterministic reading: signal strength + the five narrative beats.
    signal = signal_strength(
        record_type=rtype, amount=record["amount"],
        total_connections=total_conn + explicit["total"],
        distinct_sources=distinct_sources, sector_confidence=confidence,
        status=_g(row, "status") or None)
    assess = assessment(
        record_type=rtype, entity=entity_name or None,
        sector_name=sector.name if sector else None, sector_confidence=confidence,
        amount=record["amount"], status=_g(row, "status") or None,
        signature=signature, total_connections=total_conn,
        distinct_sources=distinct_sources, signal_level=signal["level"])

    people = await _genuine_people(session, key, row, explicit, _g(row, "sponsor") or None)

    return {
        "table": spec.source, "pk": pk, "record": record,
        "entity": {"canonical": canonical or None, "name": entity_name or None},
        "industry": industry,
        "signal": signal,
        "assessment": assess,
        "governing_regulators": governing_regulators,
        "people": people,
        # Back-compat keys for any older consumer; the page now reads the rich
        # fields above (signal/assessment/people) instead.
        "impact": {"severity": signal["level"], "meaning": assess["strategic_read"],
                   "industry": sector.name if sector else None, "regulators": governing_regulators},
        "players": people,
        "relations": relations,
    }
