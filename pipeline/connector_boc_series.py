"""Bank of Canada Valet API — full series catalogue, paginated backfill (Goal 7).

Goal 6 already pulled full date-range CSVs for 7 hand-curated "genuine
macro" series groups. This is the different, "many API requests" angle
Goal 7 asks for: Valet's `/lists/series/json` (verified live) returns the
ENTIRE series catalogue in one call — 15,642 series as of 2026-06-22, not
just the curated 7 — and each series' actual observations are a SEPARATE
request (`/observations/{name}/json`). Backfilling "every series" is
inherently a many-requests-walk over that catalogue, one request per
series, which is exactly the api_paginator shape: cursor = series name,
walked in a fixed deterministic (alphabetical) order so resume is well
defined — Valet series names aren't date-ordered, so "oldest to newest"
is interpreted as "smallest to largest series ID", a stable total order.
"""
from __future__ import annotations


import httpx
import structlog

from pipeline import raw_storage as rs
from pipeline.api_paginator import BackfillSummary, PageResult, walk_cursor_pages

log = structlog.get_logger()

CATEGORY = "bank-of-canada"
CATALOGUE_SOURCE_ID = "boc_series_catalogue"
OBSERVATIONS_SOURCE_ID = "boc_all_series_observations"

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
_HEADERS = {"User-Agent": _UA, "Accept": "application/json"}
LIST_URL = "https://www.bankofcanada.ca/valet/lists/series/json"
OBS_URL = "https://www.bankofcanada.ca/valet/observations/{name}/json"


async def fetch_series_catalogue(client: httpx.AsyncClient) -> list[str]:
    """One-time catalogue snapshot (not a per-call walk step) — every
    series name Valet currently knows about, the universe `cursors()` below
    walks. Re-running this just re-saves (dedup'd) an up-to-date snapshot;
    it doesn't affect the observations walk's checkpoint."""
    r = await client.get(LIST_URL)
    r.raise_for_status()
    content = r.content
    rs.save_raw(CATEGORY, CATALOGUE_SOURCE_ID, "series_list.json", content, source_url=LIST_URL)
    series = r.json()["series"]
    return sorted(series.keys())


async def _fetch_observations(client: httpx.AsyncClient, name: str) -> PageResult:
    url = OBS_URL.format(name=name)
    r = await client.get(url)
    r.raise_for_status()
    content = r.content
    filename = f"obs_{name.replace('/', '_')}.json"

    # Row-building is best-effort and must never cost the raw payload: not
    # every series is date-dimensioned (most are, via dimension key "d", but
    # some — e.g. AR_2023_C1_S1, an Annual Report category breakdown — use a
    # different key like "k" for "Category"). Hardcoding "d" raised a
    # KeyError here on first real-world contact, which (before this fix)
    # propagated out of this function entirely and skipped save_raw for that
    # cursor — exactly the "a parse bug loses the underlying payload" failure
    # pipeline.api_paginator's docstring says this design prevents. Building
    # PageResult is now unconditional; only the summary row is defensive.
    try:
        payload = r.json()
        obs = payload.get("observations", [])
        detail = (payload.get("seriesDetail", {}).get(name, {}) or {})
        dim_key = (detail.get("dimension") or {}).get("key", "d")
        row = {
            "series": name, "label": detail.get("label"), "count": len(obs),
            "first_key": obs[0].get(dim_key) if obs else None,
            "last_key": obs[-1].get(dim_key) if obs else None,
        }
        rows = [row]
    except Exception as exc:
        log.warning("boc_series_row_parse_failed", series=name, error=str(exc))
        rows = [{"series": name, "label": None, "count": None, "first_key": None, "last_key": None}]

    return PageResult(content=content, filename=filename, parsed_rows=rows, is_empty=False, source_url=url)


async def backfill_all_series(*, max_pages: int | None = None, rate_limit_s: float = 0.2,
                               source_id: str = OBSERVATIONS_SOURCE_ID) -> BackfillSummary:
    """Backfill observations for every series Valet currently lists, in a
    fixed alphabetical order. Safe to interrupt/resume: the series catalogue
    is fetched fresh each call (cheap, one request) but the walk itself
    resumes from the checkpointed series name, never re-fetching one already
    saved — and a series Valet has since retired (404) becomes an open gap,
    not a false "no more series" stop.
    """
    async with httpx.AsyncClient(timeout=60, headers=_HEADERS, follow_redirects=True) as client:
        series_names = await fetch_series_catalogue(client)

        async def fetch_page(name: str) -> PageResult:
            return await _fetch_observations(client, name)

        summary = await walk_cursor_pages(
            category=CATEGORY, source_id=source_id, cursors=iter(series_names), fetch_page=fetch_page,
            stop_on_empty=False, max_pages=max_pages, rate_limit_s=rate_limit_s,
        )
    log.info("boc_series_backfill_done", pages=summary.pages_fetched,
              skipped=summary.pages_skipped_already_done, gaps=len(summary.gaps),
              stopped=summary.stopped_reason)
    return summary
