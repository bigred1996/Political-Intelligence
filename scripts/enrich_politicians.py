"""Enrich the politicians table with photos, role labels, email and tenure
from the openparliament politician-detail API (one call per MP).

The list endpoint that seeded `politicians` doesn't carry the photo or the
role label, so we fetch each politician's detail once. Idempotent: re-running
only refills rows still missing a photo. New columns are added with ALTER TABLE
because the app uses create_all (no migrations) and won't alter an existing table.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from sqlalchemy import select, text

from api.database import AsyncSessionLocal, engine, init_db
from api.models.politician import Politician

OPENPARL = "https://openparliament.ca"
API = "https://api.openparliament.ca"
H = {"User-Agent": "Mozilla/5.0 (compatible; Polaris/1.0)", "Accept": "application/json"}

NEW_COLS = {
    "photo_url": "VARCHAR(512)", "role": "VARCHAR(256)", "email": "VARCHAR(256)",
    "since_date": "VARCHAR(32)", "commons_url": "VARCHAR(512)",
}


async def _ensure_columns() -> None:
    async with engine.begin() as conn:
        for col, typ in NEW_COLS.items():
            try:
                await conn.execute(text(f"ALTER TABLE politicians ADD COLUMN {col} {typ}"))
                print(f"  + added column {col}")
            except Exception:
                pass  # already exists


async def _detail(client: httpx.AsyncClient, slug: str) -> dict:
    r = await client.get(f"{API}/politicians/{slug}/?format=json")
    r.raise_for_status()
    return r.json()


def _extract(d: dict) -> dict:
    image = d.get("image")
    photo = f"{OPENPARL}{image}" if image and image.startswith("/") else image
    mem = (d.get("memberships") or [{}])[0]
    role = ((mem.get("label") or {}).get("en")) or None
    since = mem.get("start_date")
    commons = None
    for link in d.get("links") or []:
        if "ourcommons" in (link.get("url") or ""):
            commons = link["url"]
            break
    return {"photo_url": photo, "role": role, "email": d.get("email"),
            "since_date": since, "commons_url": commons}


async def main() -> None:
    await init_db()
    await _ensure_columns()

    async with AsyncSessionLocal() as session:
        pols = (await session.execute(select(Politician))).scalars().all()

    done = 0
    errors = 0
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=H) as client:
        for p in pols:
            try:
                info = _extract(await _detail(client, p.slug))
                async with AsyncSessionLocal() as session:
                    row = (await session.execute(
                        select(Politician).where(Politician.id == p.id))).scalar_one()
                    row.photo_url = info["photo_url"]
                    row.role = info["role"]
                    row.email = info["email"]
                    row.since_date = info["since_date"]
                    row.commons_url = info["commons_url"]
                    await session.commit()
                done += 1
                if done % 25 == 0:
                    print(f"  enriched {done}/{len(pols)} …", flush=True)
            except Exception as exc:
                errors += 1
                print(f"  ! {p.slug}: {str(exc)[:60]}", flush=True)
            await asyncio.sleep(0.25)  # polite

    print(f"DONE: enriched {done}/{len(pols)} ({errors} errors)", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
