"""Print the catalogue discovery report: what's available, downloaded, remaining.

Usage:
    .venv/bin/python scripts/catalogue_report.py
"""
from __future__ import annotations

import asyncio
import json


async def main() -> None:
    from api.database import AsyncSessionLocal, init_db
    from pipeline.catalogue_discovery import catalogue_report

    await init_db()
    async with AsyncSessionLocal() as session:
        report = await catalogue_report(session)
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
