"""One-time load of the 15 recovered StatCan cubes into statcan_observations.

See pipeline/connector_statcan_cubes.py for parsing and DATA.md for the
statcan_36100608 (61.4M rows, 14G) deferral rationale. Run standalone, not
through the web server, per CLAUDE.md's big-ingest rule — this is a one-time
backfill from already-downloaded local files, not a recurring scheduled job,
so it isn't in pipeline/connectors.py.

Usage: .venv/bin/python scripts/ingest_statcan_cubes.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import structlog

from api.database import AsyncSessionLocal, init_db
from api.models.statcan_observation import StatcanObservation
from pipeline.connector_statcan_cubes import iter_cube_dirs, parse_cube

log = structlog.get_logger()


async def main() -> None:
    await init_db()
    dirs = iter_cube_dirs()
    log.info("statcan_ingest_start", cubes=len(dirs))
    total = 0
    for cube_dir in dirs:
        rows = parse_cube(cube_dir)
        async with AsyncSessionLocal() as session:
            batch = []
            for r in rows:
                batch.append(StatcanObservation(**r))
                if len(batch) >= 5000:
                    session.add_all(batch)
                    await session.commit()
                    batch = []
            if batch:
                session.add_all(batch)
                await session.commit()
        total += len(rows)
        log.info("statcan_cube_loaded", cube_id=cube_dir.name, rows=len(rows), running_total=total)
    log.info("statcan_ingest_done", total=total, cubes=len(dirs))


if __name__ == "__main__":
    asyncio.run(main())
