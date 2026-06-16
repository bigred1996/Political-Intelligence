"""Deepen Hansard coverage by sector — fills political players + MP profiles.

For every tracked sector keyword, pull matching House speeches from openparliament
and store them as HansardMention rows (speaker, date, excerpt, url, tagged with the
sector keyword). This powers two surfaces built around the industry lens:

  * record pages → "relevant political players": MPs who raised the record's sector
  * politician profiles → "House interventions" + "industries they touch"

Idempotent: dedups on speech_url against what's already stored.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from api.database import AsyncSessionLocal, init_db
from api.models.politician import HansardMention
from pipeline.sector_mapper import SECTORS
from scrapers.hansard import OpenParliamentClient

PER_KEYWORD = 25          # speeches per keyword
KEYWORDS_PER_SECTOR = 7   # cap keywords so the run stays bounded


async def main() -> None:
    await init_db()
    client = OpenParliamentClient()

    async with AsyncSessionLocal() as session:
        seen_urls = set((await session.execute(
            select(HansardMention.speech_url).where(HansardMention.speech_url.is_not(None))
        )).scalars().all())

    added = 0
    for sector in SECTORS.values():
        for kw in sector.keywords[:KEYWORDS_PER_SECTOR]:
            try:
                speeches = await client.search_speeches(kw, limit=PER_KEYWORD)
            except Exception as exc:
                print(f"  ! {sector.slug}/{kw}: {str(exc)[:60]}", flush=True)
                continue
            batch = []
            for s in speeches:
                url = s.get("url")
                if url and url in seen_urls:
                    continue
                if url:
                    seen_urls.add(url)
                batch.append(HansardMention(
                    canonical_name=sector.slug, keyword=kw,
                    speech_date=s.get("date"), speaker=s.get("speaker"),
                    excerpt=s.get("excerpt"), speech_url=url,
                ))
            if batch:
                async with AsyncSessionLocal() as session:
                    session.add_all(batch)
                    await session.commit()
                added += len(batch)
            print(f"  {sector.slug:20} {kw:18} +{len(batch):>3}  (total {added})", flush=True)
            await asyncio.sleep(1.0)  # polite to openparliament

    print(f"DONE: added {added} Hansard mentions across {len(SECTORS)} sectors.", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
