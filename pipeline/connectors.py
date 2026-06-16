"""Declarative connector registry for the breadth sources.

A SourceConnector binds together everything the rest of the system needs to know
about a source in ONE place: how to fetch it, how often, how to upsert it, and
how it should surface in unified search. The scheduler builds its jobs from this
registry and the search indexer reads `embed` to decide what to vectorise — so
adding a source is a single entry here plus its fetcher, not edits in four files.

Core sources (contracts, donations, lobbying, bills, grants, appointments,
gazette, parliament) keep their existing typed tables and hand-written jobs in
api/scheduler.py. Everything new flows through this registry into the unified
`source_records` table.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import structlog
from apscheduler.triggers.cron import CronTrigger

from pipeline import breadth

log = structlog.get_logger()


@dataclass(frozen=True)
class SourceConnector:
    id: str                                   # job id, e.g. "npri"
    name: str                                 # human label
    category: str                             # UI grouping
    fetch: Callable[..., Awaitable[list[dict[str, Any]]]]
    trigger: CronTrigger
    cadence: str                              # human cadence label
    upsert: str = "replace"                   # "replace" | "upsert" (by source+external_id)
    embed: bool = True                        # build semantic vectors for this source?
    typical_rows: int = 0
    description: str = ""


# Stagger ingests across the week so the dev box never runs two big pulls at once.
CONNECTORS: list[SourceConnector] = [
    SourceConnector(
        id="gc_news", name="Government of Canada News", category="News & Publications",
        fetch=breadth.fetch_gc_news_records,
        trigger=CronTrigger(hour=5, minute=30, timezone="America/Toronto"),
        cadence="daily", upsert="upsert", embed=True, typical_rows=100,
        description="GC news releases (all departments) via the IO news API.",
    ),
    SourceConnector(
        id="statcan", name="Statistics Canada (catalogue)", category="Economic Context",
        fetch=breadth.fetch_statcan_records,
        trigger=CronTrigger(day_of_week="sun", hour=4, minute=0, timezone="America/Toronto"),
        cadence="weekly", upsert="replace", embed=True, typical_rows=6000,
        description="StatCan WDS cube catalogue — every economic/social table available.",
    ),
    SourceConnector(
        id="iaac", name="Impact Assessment Agency (IAAC)", category="Major Projects",
        fetch=breadth.fetch_iaac_records,
        trigger=CronTrigger(day_of_week="mon", hour=4, minute=0, timezone="America/Toronto"),
        cadence="weekly", upsert="replace", embed=True, typical_rows=2000,
        description="Federal impact-assessment project registry — project-level political risk.",
    ),
    SourceConnector(
        id="cer", name="Canada Energy Regulator (CER)", category="Major Projects",
        fetch=breadth.fetch_cer_records,
        trigger=CronTrigger(day_of_week="tue", hour=4, minute=0, timezone="America/Toronto"),
        cadence="weekly", upsert="replace", embed=True, typical_rows=2500,
        description="CER-regulated pipeline incidents by company, substance and location.",
    ),
    SourceConnector(
        id="npri", name="National Pollutant Release Inventory (NPRI)", category="Environment",
        fetch=breadth.fetch_npri_records,
        trigger=CronTrigger(day_of_week="wed", hour=3, minute=0, timezone="America/Toronto"),
        cadence="weekly", upsert="replace", embed=False, typical_rows=200000,
        description="Facility-level pollutant releases (structured/numeric — SQL-served).",
    ),
    SourceConnector(
        id="transport", name="Transport Canada Open Data", category="Transport",
        fetch=breadth.fetch_transport_records,
        trigger=CronTrigger(day_of_week="thu", hour=4, minute=0, timezone="America/Toronto"),
        cadence="weekly", upsert="replace", embed=True, typical_rows=300,
        description="Transport Canada dataset catalogue + safety investigations.",
    ),
    SourceConnector(
        id="geospatial", name="Federal Geospatial (NRCan / GeoGratis)", category="Geospatial",
        fetch=breadth.fetch_geospatial_records,
        trigger=CronTrigger(day_of_week="fri", hour=4, minute=0, timezone="America/Toronto"),
        cadence="weekly", upsert="replace", embed=True, typical_rows=300,
        description="Federal geospatial data catalogue (NRCan / GeoGratis / CGDI).",
    ),
]

CONNECTORS_BY_ID: dict[str, SourceConnector] = {c.id: c for c in CONNECTORS}


async def run_connector(conn: SourceConnector, *, max_rows: int = 0,
                        triggered_by: str = "manual") -> dict[str, Any]:
    """Fetch a connector and load its rows into source_records.

    `replace` wipes the source's existing rows first (idempotent full refresh).
    `upsert` inserts only rows whose (source, external_id) is new (append feeds).
    Logs to scheduler_log so runs show up on the dashboard alongside core sources.
    """
    from sqlalchemy import delete, select
    from api.database import AsyncSessionLocal
    from api.models.source_record import SourceRecord
    from api.models.scheduler_log import SchedulerLog

    async with AsyncSessionLocal() as session:
        entry = SchedulerLog(job_id=conn.id, source_name=conn.name, triggered_by=triggered_by)
        session.add(entry)
        await session.commit()
        await session.refresh(entry)
        log_id = entry.id

    t0 = time.monotonic()
    try:
        rows = await conn.fetch(max_rows=max_rows)
        added = 0
        async with AsyncSessionLocal() as session:
            if conn.upsert == "replace":
                await session.execute(delete(SourceRecord).where(SourceRecord.source == conn.id))
                await session.commit()
                seen: set[str] = set()
            else:  # upsert by external_id
                existing = (await session.execute(
                    select(SourceRecord.external_id).where(SourceRecord.source == conn.id)
                )).scalars().all()
                seen = {e for e in existing if e}

            batch = []
            for r in rows:
                ext = r.get("external_id")
                if ext and ext in seen:
                    continue
                if ext:
                    seen.add(ext)
                batch.append(SourceRecord(**r))
                if len(batch) >= 2000:
                    session.add_all(batch)
                    await session.commit()
                    added += len(batch)
                    batch = []
            if batch:
                session.add_all(batch)
                await session.commit()
                added += len(batch)

        dur = time.monotonic() - t0
        async with AsyncSessionLocal() as session:
            e = (await session.execute(
                select(SchedulerLog).where(SchedulerLog.id == log_id))).scalar_one_or_none()
            if e:
                from datetime import datetime, timezone
                e.finished_at = datetime.now(timezone.utc)
                e.status = "ok"
                e.rows_added = added
                e.rows_total = len(rows)
                e.duration_s = dur
                await session.commit()
        log.info("connector_done", id=conn.id, added=added, total=len(rows), dur=round(dur, 1))
        return {"source": conn.id, "fetched": len(rows), "added": added, "duration_s": round(dur, 1)}
    except Exception as exc:
        dur = time.monotonic() - t0
        async with AsyncSessionLocal() as session:
            from sqlalchemy import select as _sel
            e = (await session.execute(
                _sel(SchedulerLog).where(SchedulerLog.id == log_id))).scalar_one_or_none()
            if e:
                from datetime import datetime, timezone
                e.finished_at = datetime.now(timezone.utc)
                e.status = "error"
                e.error = str(exc)
                e.duration_s = dur
                await session.commit()
        log.error("connector_failed", id=conn.id, error=str(exc))
        raise
