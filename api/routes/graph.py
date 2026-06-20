"""Evidence graph routes.

These endpoints expose deterministic "connected findings" that can power the
home dashboard, sector pages, reports, and record-detail side panels without a
new graph database.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_session
from api.routes.records import get_record
from api.schemas import EvidenceGraphResponse, FindingsResponse
from pipeline.evidence_graph import (
    build_actor_findings,
    build_global_findings,
    build_politician_graph,
    build_sector_graph,
)

router = APIRouter(prefix="/api/graph", tags=["graph"])


@router.get("/findings", response_model=FindingsResponse)
async def findings(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    rows = await build_global_findings(session)
    return {"count": len(rows), "findings": rows}


@router.get("/actors", response_model=FindingsResponse)
async def actors(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    rows = await build_actor_findings(session)
    return {"count": len(rows), "findings": rows}


@router.get("/actor/{slug}", response_model=EvidenceGraphResponse)
async def actor_graph(slug: str, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    graph = await build_politician_graph(session, slug)
    if not graph.get("actor"):
        raise HTTPException(status_code=404, detail=f"Unknown actor '{slug}'")
    return graph


@router.get("/sector/{slug}", response_model=EvidenceGraphResponse)
async def sector_graph(slug: str, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    graph = await build_sector_graph(session, slug)
    if not graph.get("sector"):
        raise HTTPException(status_code=404, detail=f"Unknown sector '{slug}'")
    return graph


@router.get("/record/{table}/{pk}", response_model=EvidenceGraphResponse)
async def record_graph(table: str, pk: int, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    detail = await get_record(table, pk, session)
    record = detail["record"]
    nodes = [{
        "id": f"record:{detail['table']}:{pk}",
        "type": "record",
        "label": record["title"],
        "meta": {"table": detail["table"], "pk": pk, "source": record["source"], "date": record["date"]},
    }]
    edges: list[dict[str, Any]] = []
    seen = {nodes[0]["id"]}

    industry = detail.get("industry")
    if industry:
        sector_id = f"sector:{industry['slug']}"
        nodes.append({"id": sector_id, "type": "sector", "label": industry["name"], "meta": industry})
        edges.append({"from": nodes[0]["id"], "to": sector_id, "type": "sector_match"})
        seen.add(sector_id)

    entity = detail.get("entity") or {}
    if entity.get("canonical"):
        entity_id = f"entity:{entity['canonical']}"
        nodes.append({"id": entity_id, "type": "entity", "label": entity.get("name") or entity["canonical"], "meta": entity})
        edges.append({"from": nodes[0]["id"], "to": entity_id, "type": "entity_match"})
        seen.add(entity_id)

    for group in (detail.get("relations") or {}).get("by_source", []):
        for related in group.get("records", [])[:4]:
            node_id = f"record:{related['table']}:{related['pk']}"
            if node_id not in seen:
                nodes.append({"id": node_id, "type": "record", "label": related["title"], "meta": related})
                seen.add(node_id)
            edges.append({"from": node_id, "to": nodes[0]["id"], "type": "shared_entity"})

    findings: list[dict[str, Any]] = []
    if industry:
        sector_graph_data = await build_sector_graph(session, industry["slug"])
        sector_findings = sector_graph_data.get("findings") or []
        direct: list[dict[str, Any]] = []
        contextual: list[dict[str, Any]] = []
        current_table = detail["table"]
        current_pk = str(pk)
        for finding in sector_findings:
            refs = finding.get("references") or []
            is_direct = any(
                ref.get("table") == current_table and str(ref.get("pk", ref.get("id"))) == current_pk
                for ref in refs
            )
            enriched = {**finding, "relationship_strength": "supported" if is_direct else "inferred"}
            if is_direct:
                direct.append(enriched)
            else:
                contextual.append(enriched)
        findings = (direct + contextual)[:5]

        for finding in findings:
            node_id = f"finding:{finding['title']}"
            if node_id not in seen:
                nodes.append({"id": node_id, "type": "finding", "label": finding["title"], "meta": finding})
                seen.add(node_id)
            edges.append({
                "from": nodes[0]["id"],
                "to": node_id,
                "type": "supports_finding" if finding.get("relationship_strength") == "supported" else "sector_context",
                "strength": finding.get("relationship_strength", "inferred"),
            })

    return {
        "record": {"table": detail["table"], "pk": pk, "title": record["title"]},
        "industry": industry,
        "entity": entity,
        "findings": findings,
        "nodes": nodes[:40],
        "edges": edges[:80],
        "relations": detail.get("relations") or {},
    }
