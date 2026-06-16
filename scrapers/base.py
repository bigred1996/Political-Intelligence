"""Base scraper class. All source scrapers inherit from this.

Conventions (see CLAUDE.md):
- async httpx.AsyncClient for all HTTP
- rate limiting + retry with exponential backoff
- store raw scraped data before processing
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

log = structlog.get_logger()

RAW_DIR = Path(os.getenv("RAW_STORAGE_PATH", "./data/raw"))
SCRAPER_DELAY = float(os.getenv("SCRAPER_DELAY_SECONDS", "1.0"))
SCRAPER_MAX_RETRIES = int(os.getenv("SCRAPER_MAX_RETRIES", "3"))


class BaseScraper:
    """Shared HTTP + persistence behaviour for every data-source scraper."""

    source_name: str = "base"

    def __init__(self, base_url: str | None = None, timeout: float = 30.0) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "BaseScraper":
        self._client = httpx.AsyncClient(
            timeout=self._timeout,
            headers={"User-Agent": "PolarisIntelligence/0.1 (+political-risk-research)"},
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("Use the scraper as an async context manager: `async with Scraper() as s:`")
        return self._client

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
        wait=wait_exponential(multiplier=1, min=1, max=20),
        stop=stop_after_attempt(SCRAPER_MAX_RETRIES),
        reraise=True,
    )
    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        """GET with exponential-backoff retry. Raises on 4xx/5xx."""
        resp = await self.client.get(url, **kwargs)
        resp.raise_for_status()
        return resp

    def store_raw(self, key: str, payload: Any) -> Path:
        """Persist raw source data before any processing. Never throw away source data."""
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_dir = RAW_DIR / self.source_name
        out_dir.mkdir(parents=True, exist_ok=True)
        safe_key = "".join(c if c.isalnum() or c in "-_" else "_" for c in key)[:80]
        path = out_dir / f"{safe_key}__{ts}.json"
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        log.info("stored_raw", source=self.source_name, path=str(path))
        return path

    async def search(self, query: str) -> list[dict[str, Any]]:  # pragma: no cover - interface
        raise NotImplementedError
