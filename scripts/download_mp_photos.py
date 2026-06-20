"""Download MP photos locally so the app serves them same-origin.

openparliament.ca blocks hotlinked images (Referer-based), so the browser can't
load them directly — but a server-side fetch works fine. We download each photo
into web/public/mp/<slug>.jpg (served statically by Next) and rewrite the DB
photo_url to the local path. Idempotent: skips files already on disk.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from sqlalchemy import select

from api.database import AsyncSessionLocal, init_db
from api.models.politician import Politician

DEST = Path(__file__).resolve().parent.parent / "web" / "public" / "mp"
H = {"User-Agent": "Mozilla/5.0 (compatible; Nessus/1.0)"}


async def main() -> None:
    await init_db()
    DEST.mkdir(parents=True, exist_ok=True)

    async with AsyncSessionLocal() as session:
        pols = (await session.execute(
            select(Politician).where(Politician.photo_url.is_not(None)))).scalars().all()

    got = 0
    skipped = 0
    errors = 0
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=H) as client:
        for p in pols:
            src = p.photo_url or ""
            if src.startswith("/mp/"):
                src_remote = f"https://openparliament.ca/media/polpics/{p.slug}.jpg"
            elif src.startswith("http"):
                src_remote = src
            else:
                continue
            out = DEST / f"{p.slug}.jpg"
            local_url = f"/mp/{p.slug}.jpg"
            if out.exists() and out.stat().st_size > 0:
                skipped += 1
            else:
                try:
                    r = await client.get(src_remote)
                    r.raise_for_status()
                    out.write_bytes(r.content)
                    got += 1
                except Exception as exc:
                    errors += 1
                    print(f"  ! {p.slug}: {str(exc)[:50]}", flush=True)
                    continue
                await asyncio.sleep(0.1)
            # Point the DB at the local copy.
            if p.photo_url != local_url:
                async with AsyncSessionLocal() as session:
                    row = (await session.execute(
                        select(Politician).where(Politician.id == p.id))).scalar_one()
                    row.photo_url = local_url
                    await session.commit()

    print(f"DONE: downloaded {got}, skipped {skipped}, errors {errors}. → {DEST}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
