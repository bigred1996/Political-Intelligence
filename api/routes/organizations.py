"""Department, regulator, and public-organization detail surfaces.

This route turns text-only government bodies already present in records into
clickable Nessus investigation objects without adding new tables.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import String, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_session
from api.models.appointment import Appointment
from api.models.contract import Contract
from api.models.entity import LobbyingRecord
from api.models.grant import Grant
from api.models.regulation import GazetteEntry, TribunalDecision
from api.schemas import EvidenceReference, OrganizationProfileResponse
from pipeline.evidence_graph import build_global_findings, sectors_for_text

router = APIRouter(prefix="/api/organizations", tags=["organizations"])

_KIND_LABELS = {
    "department": "Department",
    "regulator": "Regulator",
    "organization": "Organization",
}


def _clean(name: str) -> str:
    return unquote(name).replace("-", " ").strip()


def _like(name: str) -> str:
    return f"%{name}%"


def _ref(table: str, pk: int, source: str, title: str, date: str | None = None, url: str | None = None, record_type: str = "record") -> dict[str, Any]:
    return EvidenceReference.model_validate({
        "table": table,
        "pk": pk,
        "id": pk,
        "source": source,
        "title": title,
        "date": date,
        "url": url,
        "record_type": record_type,
    }).model_dump()


def _sort_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(refs, key=lambda item: str(item.get("date") or ""), reverse=True)


async def _scalar_group(session: AsyncSession, *, model, column, table: str, source: str, record_type: str, name: str, title_fn, date_attr: str | None = None, url_attr: str | None = None, limit: int = 8) -> dict[str, Any]:
    cond = column.ilike(_like(name))
    count = int((await session.execute(select(func.count()).select_from(model).where(cond))).scalar_one() or 0)
    stmt = select(model).where(cond)
    if date_attr and hasattr(model, date_attr):
        stmt = stmt.order_by(getattr(model, date_attr).desc())
    rows = (await session.execute(stmt.limit(limit))).scalars().all()
    records = [
        _ref(
            table,
            row.id,
            source,
            title_fn(row),
            getattr(row, date_attr, None) if date_attr else None,
            getattr(row, url_attr, None) if url_attr else None,
            record_type,
        )
        for row in rows
    ]
    return {"table": table, "source": source, "label": source, "count": count, "records": records, "partial": count > len(records)}


async def _lobbying_group(session: AsyncSession, name: str, limit: int = 8) -> dict[str, Any]:
    cond = cast(LobbyingRecord.institutions, String).ilike(_like(name))
    count = int((await session.execute(select(func.count()).select_from(LobbyingRecord).where(cond))).scalar_one() or 0)
    rows = (await session.execute(
        select(LobbyingRecord).where(cond).order_by(LobbyingRecord.communication_date.desc()).limit(limit)
    )).scalars().all()
    records = [
        _ref(
            "lobbying",
            row.id,
            "OCL Lobbying Registry",
            f"{row.client} lobbied {name}",
            row.communication_date,
            None,
            "lobbying_communication",
        )
        for row in rows
    ]
    return {"table": "lobbying", "source": "OCL Lobbying Registry", "label": "Lobbying communications", "count": count, "records": records, "partial": count > len(records)}


@router.get("/{kind}/{name}", response_model=OrganizationProfileResponse)
async def organization_profile(kind: str, name: str, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    if kind not in _KIND_LABELS:
        raise HTTPException(status_code=404, detail=f"Unsupported organization type '{kind}'")
    display_name = _clean(name)
    if not display_name:
        raise HTTPException(status_code=404, detail="Organization name is required")

    groups = [
        await _scalar_group(
            session,
            model=Contract,
            column=Contract.owner_org_title,
            table="contracts",
            source="Federal contracts",
            record_type="contract",
            name=display_name,
            title_fn=lambda row: f"{row.owner_org_title or display_name} awarded contract to {row.vendor_name}",
            date_attr="contract_date",
        ),
        await _scalar_group(
            session,
            model=Grant,
            column=Grant.owner_org_title,
            table="grants",
            source="Grants & contributions",
            record_type="grant",
            name=display_name,
            title_fn=lambda row: f"{row.owner_org_title or display_name} funded {row.recipient_name}",
            date_attr="agreement_start",
        ),
        await _scalar_group(
            session,
            model=GazetteEntry,
            column=GazetteEntry.department,
            table="gazette",
            source="Canada Gazette",
            record_type="regulation",
            name=display_name,
            title_fn=lambda row: row.title,
            date_attr="published_date",
            url_attr="url",
        ),
        await _scalar_group(
            session,
            model=TribunalDecision,
            column=TribunalDecision.body,
            table="tribunal",
            source="Tribunal decisions",
            record_type="tribunal_decision",
            name=display_name,
            title_fn=lambda row: row.title,
            date_attr="decision_date",
            url_attr="url",
        ),
        await _scalar_group(
            session,
            model=Appointment,
            column=Appointment.organization,
            table="appointments",
            source="GIC appointments",
            record_type="appointment",
            name=display_name,
            title_fn=lambda row: f"{row.appointee_name} appointed to {row.organization or display_name}",
            date_attr="appointment_date",
        ),
        await _lobbying_group(session, display_name),
    ]
    groups = [group for group in groups if group["count"] > 0]
    connected_records = _sort_refs([record for group in groups for record in group["records"]])
    if not connected_records:
        raise HTTPException(status_code=404, detail=f"No internal records found for '{display_name}'")

    evidence_text = " ".join(record["title"] for record in connected_records[:12])
    affected_sectors = sectors_for_text(f"{display_name} {evidence_text}", limit=4)
    findings = []
    for finding in await build_global_findings(session):
        haystack = f"{finding.get('title', '')} {finding.get('summary', '')}"
        if display_name.lower() in haystack.lower():
            findings.append({**finding, "relationship_strength": "supported"})
        if len(findings) >= 4:
            break

    metrics = [
        {"label": "Linked records", "value": sum(group["count"] for group in groups)},
        {"label": "Evidence sources", "value": len(groups)},
        {"label": "Related findings", "value": len(findings)},
    ]
    return {
        "kind": kind,
        "name": display_name,
        "title": f"{display_name} {_KIND_LABELS[kind].lower()} profile",
        "summary": f"Nessus found {metrics[0]['value']} internal records naming {display_name} across {len(groups)} source bucket(s).",
        "why_it_matters": "Departments and regulators define the mandate, funding, consultations, decisions, appointments, and lobbying touchpoints that shape sector risk.",
        "metrics": metrics,
        "affected_sectors": affected_sectors,
        "related_findings": findings,
        "connected_people": [],
        "connected_organizations": [],
        "connected_records": connected_records[:24],
        "groups": groups,
        "timeline": connected_records[:12],
    }
