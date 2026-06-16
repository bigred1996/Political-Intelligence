"""Scheduler routes — status, history, and manual job triggers."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_session
from api.models.scheduler_log import SchedulerLog
from api.scheduler import JOB_RUNNERS, SOURCE_CONFIGS, scheduler

router = APIRouter(prefix="/api/scheduler", tags=["scheduler"])


def _job_next_run(job_id: str) -> str | None:
    job = scheduler.get_job(job_id)
    if job and job.next_run_time:
        return job.next_run_time.isoformat()
    return None


@router.get("/status")
async def scheduler_status(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """All jobs with last run result and next scheduled run."""
    jobs = []
    for cfg in SOURCE_CONFIGS:
        # Get last run from log
        res = await session.execute(
            select(SchedulerLog)
            .where(SchedulerLog.job_id == cfg["id"])
            .order_by(SchedulerLog.started_at.desc())
            .limit(1)
        )
        last = res.scalar_one_or_none()
        jobs.append({
            "id": cfg["id"],
            "name": cfg["name"],
            "cadence": cfg["cadence"],
            "description": cfg["description"],
            "typical_rows": cfg["typical_rows"],
            "next_run": _job_next_run(cfg["id"]),
            "last_run": {
                "started_at": last.started_at.isoformat() if last else None,
                "finished_at": last.finished_at.isoformat() if last and last.finished_at else None,
                "status": last.status if last else "never",
                "rows_added": last.rows_added if last else 0,
                "rows_total": last.rows_total if last else 0,
                "duration_s": round(last.duration_s, 1) if last and last.duration_s else None,
                "triggered_by": last.triggered_by if last else None,
                "error": last.error if last else None,
            },
        })
    return {
        "scheduler_running": scheduler.running,
        "timezone": "America/Toronto",
        "jobs": jobs,
    }


@router.post("/trigger/{job_id}")
async def trigger_job(job_id: str, background_tasks: BackgroundTasks) -> dict[str, Any]:
    """Manually trigger an ingest job by ID. Runs in background."""
    if job_id not in JOB_RUNNERS:
        raise HTTPException(status_code=404, detail=f"Unknown job: {job_id}. Valid: {list(JOB_RUNNERS)}")
    cfg = next((c for c in SOURCE_CONFIGS if c["id"] == job_id), None)
    background_tasks.add_task(JOB_RUNNERS[job_id], "manual")
    return {
        "status": "triggered",
        "job_id": job_id,
        "name": cfg["name"] if cfg else job_id,
        "triggered_at": datetime.now(timezone.utc).isoformat(),
        "note": "Running in background. Poll /api/scheduler/status to see result.",
    }


@router.get("/history")
async def job_history(
    job_id: str | None = None,
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Recent run history across all jobs or filtered by job_id."""
    q = select(SchedulerLog).order_by(SchedulerLog.started_at.desc()).limit(limit)
    if job_id:
        q = q.where(SchedulerLog.job_id == job_id)
    res = await session.execute(q)
    rows = res.scalars().all()
    return {
        "count": len(rows),
        "records": [
            {
                "id": r.id,
                "job_id": r.job_id,
                "source_name": r.source_name,
                "started_at": r.started_at.isoformat(),
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                "status": r.status,
                "rows_added": r.rows_added,
                "rows_total": r.rows_total,
                "duration_s": round(r.duration_s, 1) if r.duration_s else None,
                "triggered_by": r.triggered_by,
                "error": r.error,
            }
            for r in rows
        ],
    }
