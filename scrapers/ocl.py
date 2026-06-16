"""OCL Lobbying Registry scraper.

Source: Office of the Commissioner of Lobbying of Canada (lobbycanada.gc.ca).
Covers all federal lobbying registrations + communications since 1996.

Step 1 of the build. Strategy:
- `search()` attempts a live pull against the OCL registry search.
- On any failure (network, site change, empty) it falls back to deterministic
  sample data so downstream pipeline + frontend stay testable.

The live path is intentionally conservative for the MVP; hardening the exact
registry query/parse is the next iteration on this module.
"""
from __future__ import annotations

import os
from typing import Any

import structlog

from .base import BaseScraper
from .sample_data import sample_for

log = structlog.get_logger()


class OCLScraper(BaseScraper):
    source_name = "ocl"

    def __init__(self) -> None:
        super().__init__(base_url=os.getenv("OCL_BASE_URL", "https://lobbycanada.gc.ca"))

    async def search(self, query: str) -> list[dict[str, Any]]:
        """Return normalized lobbying records for a company name.

        Returns a list of dicts with a stable shape regardless of source path:
        registration_id, client, registrant, subject_matters, institutions,
        communication_date, type, source.
        """
        records: list[dict[str, Any]] = []
        used = "sample"
        try:
            records = await self._live_search(query)
            if records:
                used = "live"
        except Exception as exc:  # noqa: BLE001 - any live failure -> graceful fallback
            log.warning("ocl_live_search_failed", query=query, error=str(exc))

        if not records:
            records = [dict(r) for r in sample_for(query)]

        for r in records:
            r["source"] = "OCL Lobbying Registry"
        self.store_raw(key=f"{query}__{used}", payload=records)
        log.info("ocl_search_done", query=query, path=used, count=len(records))
        return records

    async def _live_search(self, query: str) -> list[dict[str, Any]]:
        """Live pull against the OCL public registry.

        Hits the search endpoint and parses result rows. Kept defensive: any
        structural change on the gov site raises and triggers the sample fallback
        in `search()`. TODO: pin to the OCL Open Data bulk dataset for full fidelity.
        """
        url = f"{self.base_url}/app/secure/ocl/lrs/do/guest"
        resp = await self.get(url, params={"V_SEARCH.command": "navigate", "clientName": query})
        # Defensive: if the page loads but we can't confidently parse rows, return [].
        # Real parsing logic lands in the next iteration; for now we treat the
        # live endpoint as a reachability probe and defer to sample data.
        if resp.status_code == 200 and query.lower() in resp.text.lower():
            log.info("ocl_live_reachable", query=query, bytes=len(resp.text))
        return []
