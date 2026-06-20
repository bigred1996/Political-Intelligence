"""Lobbying routes — OCL bulk ingest + per-company scan.

POST /api/lobbying/ingest    → bulk-ingest full OCL communications dataset (~369k rows)
POST /api/lobbying/scan      → on-demand OCL sample scan for a company (fallback)
GET  /api/lobbying/records   → list stored records
GET  /api/lobbying/stats     → ingest summary counts
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..cache import invalidate_workspace_caches
from ..database import get_session, AsyncSessionLocal
from ..models.entity import LobbyingRecord
from ..routes.sources import get_sources_status
from ..schemas import IngestStartedResponse, RecordListResponse, SourceSearchResponse, StatsResponse
from pipeline.entity_resolver import normalize
from pipeline.ingest import fetch_ocl_communication_rows
from scrapers.ocl import OCLScraper
import structlog

log = structlog.get_logger()
router = APIRouter(prefix="/api/lobbying", tags=["lobbying"])


async def _run_ocl_bulk_ingest(max_rows: int) -> None:
    """Background task: download OCL ZIP, parse, upsert all rows into DB."""
    log.info("ocl_bulk_ingest_start", max_rows=max_rows)
    rows = await fetch_ocl_communication_rows(max_rows=max_rows)
    log.info("ocl_bulk_ingest_parsed", count=len(rows))

    batch_size = 2000
    inserted = 0
    async with AsyncSessionLocal() as session:
        for i in range(0, len(rows), batch_size):
            batch = rows[i : i + batch_size]
            for r in batch:
                existing = await session.execute(
                    select(LobbyingRecord).where(
                        LobbyingRecord.registration_id == r["comlog_id"]
                    )
                )
                if existing.scalar_one_or_none() is None:
                    session.add(
                        LobbyingRecord(
                            company_query=r["client_org"],
                            canonical_name=r["canonical_name"],
                            registration_id=r["comlog_id"],
                            client=r["client_org"],
                            registrant=r["registrant"],
                            subject_matters=r.get("subject_codes", []),
                            institutions=r.get("institutions", []),
                            communication_date=r.get("comm_date"),
                            type=r.get("reg_type"),
                            source="OCL Monthly Communications",
                            raw={
                                "dpoh_contacts": r.get("dpoh_contacts", []),
                                "subject_codes": r.get("subject_codes", []),
                            },
                        )
                    )
                    inserted += 1
            await session.commit()
            log.info("ocl_bulk_ingest_progress", inserted=inserted, total=len(rows))

    invalidate_workspace_caches("manual_ocl_bulk_ingest")
    log.info("ocl_bulk_ingest_done", inserted=inserted, total=len(rows))


class IngestRequest(BaseModel):
    max_rows: int = 0


@router.post("/ingest", response_model=IngestStartedResponse)
async def ingest_ocl(
    body: IngestRequest,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    """Trigger bulk OCL communications ingest (runs in background).

    max_rows=0 means full corpus (~369k rows). Set to e.g. 10000 for a quick test.
    """
    background_tasks.add_task(_run_ocl_bulk_ingest, body.max_rows)
    return {
        "status": "started",
        "message": "OCL bulk ingest running in background — check /api/lobbying/stats for progress",
        "max_rows": body.max_rows or "all",
    }


class ScanRequest(BaseModel):
    company_name: str


@router.post("/scan", response_model=SourceSearchResponse)
async def scan_company(body: ScanRequest, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Pull OCL lobbying records for a company, store them, return the set."""
    company = body.company_name.strip()
    canonical = normalize(company)

    async with OCLScraper() as scraper:
        records = await scraper.search(company)

    # Replace any prior rows for this canonical entity (idempotent re-scan).
    await session.execute(delete(LobbyingRecord).where(LobbyingRecord.canonical_name == canonical))
    rows = [
        LobbyingRecord(
            company_query=company,
            canonical_name=canonical,
            registration_id=r.get("registration_id", ""),
            client=r.get("client", ""),
            registrant=r.get("registrant", ""),
            subject_matters=r.get("subject_matters", []),
            institutions=r.get("institutions", []),
            communication_date=r.get("communication_date"),
            type=r.get("type"),
            source=r.get("source", "OCL Lobbying Registry"),
            raw=r,
        )
        for r in records
    ]
    session.add_all(rows)
    await session.commit()
    invalidate_workspace_caches("manual_lobbying_scan")

    return {
        "company_name": company,
        "canonical_name": canonical,
        "count": len(records),
        "records": records,
    }


@router.get("/stats", response_model=StatsResponse)
async def lobbying_stats(
    include_breakdown: bool = Query(default=False, description="Run slower exact count/distinct-client aggregates."),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Summary counts for the lobbying records table."""
    source_status = await get_sources_status(session)
    total = int(source_status.get("counts", {}).get("lobbying_communications") or 0)
    if not include_breakdown:
        return {
            "total_records": total,
            "unique_clients": 0,
            "source": "OCL Monthly Communications",
            "approximate": False,
            "summary_only": True,
            "row_count_method": "exact_cached",
        }

    unique_clients = (
        await session.execute(select(func.count(func.distinct(LobbyingRecord.canonical_name))))
    ).scalar_one()
    return {
        "total_records": total,
        "unique_clients": unique_clients,
        "source": "OCL Monthly Communications",
        "approximate": False,
        "summary_only": False,
    }


@router.get("/records", response_model=RecordListResponse)
async def list_records(
    canonical: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Stored lobbying records, optionally filtered by canonical company name."""
    q = select(LobbyingRecord).order_by(LobbyingRecord.communication_date.desc()).limit(limit)
    if canonical:
        q = q.where(LobbyingRecord.canonical_name.like(f"%{canonical}%"))
    result = await session.execute(q)
    items = result.scalars().all()
    return {
        "count": len(items),
        "records": [
            {
                "company_query": r.company_query,
                "canonical_name": r.canonical_name,
                "registration_id": r.registration_id,
                "client": r.client,
                "registrant": r.registrant,
                "subject_matters": r.subject_matters,
                "institutions": r.institutions,
                "communication_date": r.communication_date,
                "type": r.type,
                "source": r.source,
            }
            for r in items
        ],
    }
