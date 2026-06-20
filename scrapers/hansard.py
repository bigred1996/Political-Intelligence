"""openparliament.ca API client — Hansard speeches, MP profiles, committees, votes.

openparliament.ca is a high-quality third-party API over Parliament's public data.
It covers: MPs, speeches (Hansard), bill votes, committees, ridings.

API base: https://api.openparliament.ca/
Docs:    https://api.openparliament.ca/
Rate:    polite; 1 req/s with User-Agent is accepted.
"""
from __future__ import annotations

import re
from typing import Any

import httpx
import structlog

from scrapers.base import BaseScraper

log = structlog.get_logger()

OPENPARL_BASE = "https://api.openparliament.ca"
_UA = "Nessus-Political-Intelligence/1.0 (contact@polarispolitical.ca; research use)"


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text).strip()


class OpenParliamentClient(BaseScraper):
    """Async client for the openparliament.ca JSON API."""

    def __init__(self) -> None:
        super().__init__(base_url=OPENPARL_BASE)

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """GET with openparliament.ca JSON headers and polite delay."""
        default_params = {"format": "json"}
        if params:
            default_params.update(params)
        async with httpx.AsyncClient(
            base_url=OPENPARL_BASE,
            headers={"User-Agent": _UA, "Accept": "application/json"},
            timeout=30,
            follow_redirects=True,
        ) as client:
            r = await client.get(path, params=default_params)
            r.raise_for_status()
            return r.json()

    async def get_politicians(self, limit: int = 500) -> list[dict[str, Any]]:
        """Fetch all current MPs."""
        data = await self._get("/politicians/", {"limit": limit})
        out = []
        for p in data.get("objects", []):
            slug = (p.get("url") or "").strip("/").split("/")[-1]
            party = (p.get("current_party") or {}).get("short_name", {}).get("en", "")
            riding_obj = p.get("current_riding") or {}
            out.append(
                {
                    "slug": slug,
                    "name": p.get("name", ""),
                    "party": party or None,
                    "riding": (riding_obj.get("name") or {}).get("en") or None,
                    "province": riding_obj.get("province") or None,
                    "url": p.get("url") or None,
                }
            )
        log.info("openparl_politicians_fetched", count=len(out))
        return out

    async def get_committees(self) -> list[dict[str, Any]]:
        """Fetch all standing committees."""
        data = await self._get("/committees/", {"limit": 100})
        out = []
        for c in data.get("objects", []):
            out.append(
                {
                    "slug": c.get("slug", ""),
                    "name": (c.get("name") or {}).get("en", ""),
                    "short_name": (c.get("short_name") or {}).get("en", ""),
                    "url": c.get("url") or None,
                }
            )
        return out

    async def search_speeches(
        self,
        keyword: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search Hansard speeches mentioning a keyword.

        Returns a list of speech excerpts with date, speaker, and plain-text content.
        """
        data = await self._get("/speeches/", {"q": keyword, "limit": limit})
        out = []
        for s in data.get("objects", []):
            content_html = (s.get("content") or {}).get("en", "")
            speaker = (s.get("attribution") or {}).get("en", "")
            raw_date = (s.get("time") or "")[:10]
            # Filter obviously corrupt dates (openparliament occasionally returns far-future years)
            year = int(raw_date[:4]) if raw_date and raw_date[:4].isdigit() else 0
            date = raw_date if 1990 <= year <= 2035 else None
            out.append(
                {
                    "date": date,
                    "speaker": speaker or None,
                    "excerpt": _strip_html(content_html)[:500] or None,
                    "url": s.get("url") or None,
                }
            )
        log.info("openparl_speeches_fetched", keyword=keyword, count=len(out))
        return out

    async def get_votes(self, limit: int = 50) -> list[dict[str, Any]]:
        """Fetch recent House votes."""
        data = await self._get("/votes/", {"limit": limit})
        out = []
        for v in data.get("objects", []):
            desc = (v.get("description") or {}).get("en", "")
            out.append(
                {
                    "session": v.get("session", ""),
                    "number": v.get("number"),
                    "date": v.get("date") or None,
                    "description": desc or None,
                    "bill_url": v.get("bill_url") or None,
                }
            )
        return out

    async def get_politician_speeches(
        self, politician_url: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Fetch recent speeches by a specific MP."""
        slug = politician_url.strip("/").split("/")[-1]
        data = await self._get("/speeches/", {"politician": f"/politicians/{slug}/", "limit": limit})
        out = []
        for s in data.get("objects", []):
            content_html = (s.get("content") or {}).get("en", "")
            out.append(
                {
                    "date": (s.get("time") or "")[:10] or None,
                    "excerpt": _strip_html(content_html)[:400] or None,
                    "url": s.get("url") or None,
                }
            )
        return out
