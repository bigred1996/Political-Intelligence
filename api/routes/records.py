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
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from api.schemas import RecordDetailResponse
from pipeline.impact import industry_impact, relevant_players, resolve_sector
from pipeline.sector_mapper import sector_for_entity
from search.sql_search import SPECS, _g, _import_model

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
    "hansard_mentions": "Hansard mentions",
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
        if name in _JSON_COLS:
            continue  # rendered separately as `raw`
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

    record = {
        "title": spec.title_fn(row),
        "source": src, "record_type": rtype,
        "type_label": type_label,
        "entity": entity_name or None, "canonical": canonical or None,
        "date": _g(row, spec.date_col) if spec.date_col else None,
        "amount": getattr(row, spec.amount_col, None) if spec.amount_col else None,
        "url": spec.url_fn(row),  # external source — secondary, navigation stays in-app
        "fields": _field_dump(model, row),
        "raw": getattr(row, "raw", None) if hasattr(row, "raw") else None,
    }

    # ── Industry lens: what this data point means for its sector, and who the
    # relevant political players are. The product reads everything industry-first.
    summary_text = " ".join(filter(None, [
        _g(row, "summary"), _g(row, "description"), spec.snippet_fn(row)]))
    regulators_text = " ".join(filter(None, [
        _g(row, "department"), _g(row, "organization"), _g(row, "owner_org_title"), entity_name or ""]))
    sector, how = resolve_sector(canonical or None, record["title"], summary_text,
                                 regulators_text=regulators_text)
    impact = industry_impact(
        rtype, sector, entity=entity_name or None, amount=record["amount"],
        status=_g(row, "status") or None, how=how)
    players = await relevant_players(
        session, sector=sector, canonical=canonical or None, sponsor=_g(row, "sponsor") or None)

    industry = {"name": sector.name, "slug": sector.slug, "blurb": sector.blurb,
                "matched_by": how} if sector else None

    relations: dict[str, Any] = {"by_source": [], "total": 0, "sector": None,
                                 "sector_peers": [], "timeline": []}
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

    return {"table": spec.source, "pk": pk, "record": record,
            "entity": {"canonical": canonical or None, "name": entity_name or None},
            "industry": industry, "impact": impact, "players": players,
            "relations": relations}
