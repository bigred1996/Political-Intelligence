"""Discover (not download) what's available in the source catalogues.

Goal 5 of the 2026-06-21 ingestion work: before downloading large datasets,
discover what exists. Writes metadata only into catalogue_entries — no
dataset content is fetched here.

Usage:
    .venv/bin/python scripts/catalogue_discover.py              # all sources
    .venv/bin/python scripts/catalogue_discover.py open-government
    .venv/bin/python scripts/catalogue_discover.py statcan

Valid source ids: open-government, nrcan-geospatial, transport-canada, cer,
iaac, statcan, canada-gazette, government-news.

open-government defaults to a 2000-dataset cap (the full catalogue is
~47,000 datasets as of 2026-06-21 — see DATA_CHECKLIST.md for why this is
capped rather than uncapped on a first pass).
"""
from __future__ import annotations

import asyncio
import sys
import time


async def _run_source(source_id: str) -> None:
    from api.database import AsyncSessionLocal
    from pipeline.catalogue_discovery import (
        discover_canada_gazette_index, discover_ckan_catalogue,
        discover_government_news_departments, discover_statcan_catalogue,
        persist_catalogue_entries,
    )

    ckan_sources = {
        "open-government": {"max_datasets": 2000},
        "nrcan-geospatial": {"org": "nrcan-rncan", "max_datasets": 300},
        "transport-canada": {"org": "tc", "max_datasets": 300},
        "cer": {"org": "cer-rec", "max_datasets": 200},
        "iaac": {"org": "iaac-aeic", "max_datasets": 200},
    }

    t0 = time.monotonic()
    if source_id in ckan_sources:
        entries = await discover_ckan_catalogue(source_id, **ckan_sources[source_id])
    elif source_id == "statcan":
        entries = await discover_statcan_catalogue()
    elif source_id == "canada-gazette":
        from datetime import datetime, timezone
        year = datetime.now(timezone.utc).year
        entries = await discover_canada_gazette_index(years=[year - 2, year - 1, year])
    elif source_id == "government-news":
        async with AsyncSessionLocal() as session:
            entries = await discover_government_news_departments(session)
    else:
        print(f"Unknown catalogue source: {source_id}")
        print(f"Valid: open-government, {', '.join(ckan_sources)}, statcan, canada-gazette, government-news")
        raise SystemExit(2)

    async with AsyncSessionLocal() as session:
        result = await persist_catalogue_entries(session, entries)
    print(f"[catalogue_discover] {source_id}: discovered={len(entries)} {result} "
          f"({time.monotonic() - t0:.1f}s)", flush=True)


async def main(source_id: str | None) -> None:
    from api.database import init_db
    await init_db()

    all_sources = ["statcan", "canada-gazette", "nrcan-geospatial", "transport-canada",
                   "cer", "iaac", "open-government", "government-news"]
    targets = [source_id] if source_id else all_sources
    for s in targets:
        await _run_source(s)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else None))
