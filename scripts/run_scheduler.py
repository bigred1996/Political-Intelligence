"""Standalone data-refresh scheduler — runs the APScheduler outside the web server.

Why standalone: big streaming ingests must NOT run inside uvicorn (they can block
the event loop and a dropped stream at the tail can crash the API / preview server
— see CLAUDE.md). This process runs ONLY the scheduler, so a long contracts or
donations load is isolated; if it dies, launchd restarts it and the API is unaffected.

It reuses the exact same cadence definitions and job runners as the in-server
scheduler (api/scheduler.py:start_scheduler) — single source of truth. The DB target
is whatever DATABASE_URL points at in .env (SQLite locally, Supabase Postgres in prod).

Run manually:
    .venv/bin/python scripts/run_scheduler.py

Run under launchd (recommended — keeps it alive across reboots/sleep):
    see deploy/com.polaris.scheduler.plist and deploy/README.md
"""
from __future__ import annotations

import asyncio
import signal

import structlog

log = structlog.get_logger()


async def main() -> None:
    from api.config import settings
    from api.database import init_db
    from api.scheduler import scheduler, start_scheduler, stop_scheduler

    await init_db()
    start_scheduler()
    log.info("standalone_scheduler_up", db=settings.database_url.split("@")[-1], jobs=len(scheduler.get_jobs()))

    # Print the next run time per job so the log shows the cadence at a glance.
    for job in scheduler.get_jobs():
        print(f"  {job.id:24} next run: {job.next_run_time}", flush=True)

    stop = asyncio.Event()

    def _shutdown(*_):
        log.info("standalone_scheduler_shutdown")
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _shutdown)

    try:
        await stop.wait()
    finally:
        stop_scheduler()


if __name__ == "__main__":
    asyncio.run(main())
