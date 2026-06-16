"""Run a data-ingest job in a standalone process (no web server).

Big one-time full-corpus loads (contracts ~1M, donations multi-million) are more
robust run outside uvicorn: no HTTP timeout, no risk of blocking the event loop
or the preview server, and SQLite has a single writer.

Usage:
    .venv/bin/python scripts/run_ingest.py donations_quarterly
    .venv/bin/python scripts/run_ingest.py contracts_monthly

Any job id from api.scheduler.JOB_RUNNERS is valid.
"""
from __future__ import annotations

import asyncio
import sys
import time


async def main(job_id: str) -> None:
    from api.database import init_db
    from api.scheduler import JOB_RUNNERS

    if job_id not in JOB_RUNNERS:
        print(f"Unknown job: {job_id}\nValid: {', '.join(JOB_RUNNERS)}")
        raise SystemExit(2)

    await init_db()
    print(f"[run_ingest] starting {job_id} …", flush=True)
    t0 = time.monotonic()
    await JOB_RUNNERS[job_id]("manual")
    print(f"[run_ingest] {job_id} finished in {time.monotonic() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: run_ingest.py <job_id>")
        raise SystemExit(2)
    asyncio.run(main(sys.argv[1]))
