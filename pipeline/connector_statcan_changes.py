"""StatCan WDS daily changed-cube tracker — paginated backfill (Goal 7).

The goal text calls out that "the StatCan WDS provides data and metadata
updates released each business day" — the real, documented mechanism for
that is `getChangedCubeList/{date}` (verified live 2026-06-22, not assumed):

    GET https://www150.statcan.gc.ca/t1/wds/rest/getChangedCubeList/{YYYY-MM-DD}

returns every cube (table) that had a data or metadata release on that
calendar date. Three response shapes, all confirmed by direct probing:
  - 200 {"status":"SUCCESS","object":[...]}  — resolved, possibly empty
    (most days have zero releases; StatCan mostly releases Tue-Thu 8:30am).
  - 409 {"message":"The product is not released yet"} — a date within the
    last ~1-2 days whose snapshot hasn't finished processing server-side.
  - 404 {"message":"The input date is a future release date."} — a date
    that hasn't happened yet.

409/404 are NOT "end of data" — they're "not computed yet," which is a
TRANSIENT condition: re-running tomorrow can resolve a date that 409'd
today. So this connector deliberately does NOT use PageResult.is_empty for
them; both are left to raise via httpx's raise_for_status(), which makes
pipeline.api_paginator treat them as ordinary retryable errors → an open
gap if they outlast the retry budget, automatically retried (not
permanently skipped) on a later run once last_cursor has moved past them —
exactly the open-gap behaviour the primitive already provides.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import httpx
import structlog

from pipeline.api_paginator import BackfillSummary, PageResult, walk_cursor_pages

log = structlog.get_logger()

CATEGORY = "statcan"
SOURCE_ID = "statcan_changed_cubes"

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
_HEADERS = {"User-Agent": _UA, "Accept": "application/json"}
_CHANGED_URL = "https://www150.statcan.gc.ca/t1/wds/rest/getChangedCubeList/{date}"

# A FIXED anchor, not "N days before today". The resume check is `cursor <=
# last_cursor` — it has no idea what range a PRIOR run actually walked, it
# only knows chronological order. A rolling "today - 180 days" start date
# silently breaks that invariant: a later call computes a new, earlier
# start_date than the one before it, and every one of those never-before-seen
# earlier dates satisfies `cursor <= last_cursor` purely by being
# chronologically before it — so they get skipped as "already done" despite
# never having been fetched (caught live: a second run with the same rolling
# default reported skipped=178/pages_fetched=0 for a window that had only
# ever been walked 10 days deep). A fixed anchor keeps every call's cursor
# sequence starting from the same point, which is what the skip-check assumes.
DEFAULT_START_DATE = date(2025, 1, 1)


async def _fetch_day(client: httpx.AsyncClient, day: str) -> PageResult:
    url = _CHANGED_URL.format(date=day)
    r = await client.get(url)
    r.raise_for_status()  # 409/404 raise here -> retried, then an open gap, not a false "done"
    content = r.content
    payload = r.json()
    rows = [{"date": day, "product_id": c.get("productId"), "release_time": c.get("releaseTime")}
            for c in payload.get("object", [])]
    return PageResult(content=content, filename=f"changed_{day}.json", parsed_rows=rows,
                       is_empty=False, source_url=url)


def _date_range(start: date, end: date):
    d = start
    while d <= end:
        yield d.isoformat()
        d += timedelta(days=1)


async def backfill_changed_cubes(*, start_date: date | None = None, end_date: date | None = None,
                                  max_pages: int | None = None, rate_limit_s: float = 0.2,
                                  max_retries: int = 2, retry_base_delay: float = 1.0) -> BackfillSummary:
    """Walk every calendar day from `start_date` to `end_date` (default:
    DEFAULT_START_DATE -> today) oldest-first, recording which cubes changed
    each day. Safe to interrupt/resume: see module docstring for why 409/404
    become retriable gaps instead of a false "no more data" stop — and see
    DEFAULT_START_DATE's comment for why this is a fixed date, not a rolling
    "N days ago" one. A caller-supplied `start_date` carries the same
    constraint: don't pass an earlier one across runs than a prior run used,
    or already-checkpointed-past dates in between will be wrongly skipped.
    """
    end = end_date or datetime.now(timezone.utc).date()
    start = start_date or DEFAULT_START_DATE

    async with httpx.AsyncClient(timeout=30, headers=_HEADERS, follow_redirects=True) as client:
        async def fetch_page(day: str) -> PageResult:
            return await _fetch_day(client, day)

        summary = await walk_cursor_pages(
            category=CATEGORY, source_id=SOURCE_ID,
            cursors=_date_range(start, end),
            fetch_page=fetch_page,
            stop_on_empty=False, max_pages=max_pages, rate_limit_s=rate_limit_s,
            max_retries=max_retries, retry_base_delay=retry_base_delay,
        )
    log.info("statcan_changes_backfill_done", pages=summary.pages_fetched,
              skipped=summary.pages_skipped_already_done, gaps=len(summary.gaps),
              stopped=summary.stopped_reason)
    return summary
