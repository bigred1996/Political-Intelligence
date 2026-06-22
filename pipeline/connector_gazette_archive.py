"""Canada Gazette historical issue archive — paginated backfill (Goal 7).

`pipeline/ingest.py:fetch_gazette_entries()` already covers the RSS feeds
(recent issues only — RSS is not an archive). This connector walks the
REAL historical structure instead, confirmed live by probing, not assumed:

    GET https://gazette.gc.ca/rp-pr/p{part}/{year}/index-eng.html

is a per-year index that lists every issue for that year. Two formats
coexist on the SAME url pattern depending on age — straight from the page's
own text: "The Canada Gazette Directorate provides both the HTML and PDF
versions of the Canada Gazette for the last 5 years. Earlier editions... are
only available in the PDF version." So recent years' rows have an
`.../html/index-eng.html` link AND a `.../pdf/....pdf` link per issue; older
years have only the PDF link. The connector extracts both link kinds and
merges by date so either format yields a complete row.

The archive's earliest available year (probed, both parts): 1998 — 1997
404s, 1998 returns real content. Current year is open-ended (walks until a
year 404s, e.g. next January for the year after "now").

Each part gets its OWN checkpoint (source_id="gazette_archive_p{part}"),
not one shared across both. See pipeline.connector_house_votes's module
docstring for the full story: a single shared checkpoint compared by
`(part, year) <` against ANOTHER part's progress only stays correct if
every call walks both parts together in the same fixed order — call this
with parts=["2"] alone and then parts=["1"] afterward (a perfectly
reasonable thing to do) and the old design would have silently treated
Part I as "already done" purely because "1" < "2", never having fetched
a single Part I page. Independent per-part checkpoints make that
ordering/subset question not exist in the first place.
"""
from __future__ import annotations

import re
from typing import Any

import httpx
import structlog

from pipeline import raw_storage as rs
from pipeline.api_paginator import BackfillSummary, PageResult, walk_cursor_pages

log = structlog.get_logger()

CATEGORY = "canada-gazette"
SOURCE_PREFIX = "gazette_archive"

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
_HEADERS = {"User-Agent": _UA}
_YEAR_URL = "https://gazette.gc.ca/rp-pr/p{part}/{year}/index-eng.html"

EARLIEST_YEAR = 1998
PARTS = ["1", "2"]

_PDF_RE = re.compile(r'href="(/rp-pr/p\d/(\d{4})/([\w-]+)/pdf/[^"]+\.pdf)"', re.IGNORECASE)
_HTML_RE = re.compile(r'href="(/rp-pr/p\d/(\d{4})/([\w-]+)/html/index-eng\.html)"', re.IGNORECASE)


def part_source_id(part: str) -> str:
    return f"{SOURCE_PREFIX}_p{part}"


def _parse_year_index(content: bytes, part: str, year: int) -> list[dict[str, Any]]:
    text = content.decode("utf-8", errors="replace")
    by_date: dict[str, dict[str, Any]] = {}
    for path, _y, issue_key in _PDF_RE.findall(text):
        by_date.setdefault(issue_key, {"part": part, "year": year, "issue_key": issue_key,
                                        "pdf_url": None, "html_url": None})
        by_date[issue_key]["pdf_url"] = f"https://gazette.gc.ca{path}"
    for path, _y, issue_key in _HTML_RE.findall(text):
        by_date.setdefault(issue_key, {"part": part, "year": year, "issue_key": issue_key,
                                        "pdf_url": None, "html_url": None})
        by_date[issue_key]["html_url"] = f"https://gazette.gc.ca{path}"
    return [by_date[k] for k in sorted(by_date)]


async def _fetch_year(client: httpx.AsyncClient, part: str, year: int) -> PageResult:
    url = _YEAR_URL.format(part=part, year=year)
    r = await client.get(url)
    if r.status_code == 404:
        return PageResult(content=b"", filename=f"p{part}_{year}_404.html", is_empty=True, source_url=url)
    r.raise_for_status()
    content = r.content
    rows = _parse_year_index(content, part, year)
    return PageResult(content=content, filename=f"p{part}_{year}_index.html", parsed_rows=rows,
                       is_empty=False, source_url=url)


async def backfill_gazette_archive(*, parts: list[str] | None = None, start_year: int = EARLIEST_YEAR,
                                    max_pages: int | None = None, rate_limit_s: float = 0.3) -> BackfillSummary:
    """Backfill the Canada Gazette year-by-year issue index for each part in
    `parts` (default both I and II), oldest year first, stopping naturally at
    a 404 (a year that hasn't happened yet). Safe to interrupt/resume with
    any subset or order of `parts` across separate calls (see module
    docstring) — each part's own checkpoint is independent.
    """
    parts = parts or PARTS
    all_rows: list[dict[str, Any]] = []
    all_gaps: list[dict[str, Any]] = []
    total_fetched = 0
    total_skipped = 0
    cursor_start = None
    cursor_end = None
    stopped_reason = "no_cursors"

    async with httpx.AsyncClient(timeout=45, headers=_HEADERS, follow_redirects=True) as client:
        for part in parts:
            remaining = None if max_pages is None else max(0, max_pages - total_fetched)
            if remaining == 0:
                stopped_reason = "max_pages"
                break

            source_id = part_source_id(part)
            # Same narrow, per-part-scoped optimization as house_votes: once
            # this part's own checkpoint says "complete", don't even start a
            # walk that would otherwise re-probe one year past the 404 that
            # already proved it's done.
            existing = rs.read_checkpoint(source_id)
            if existing and existing.get("status") == "complete":
                stopped_reason = "exhausted"
                continue

            async def fetch_page(year: int, _part=part) -> PageResult:
                return await _fetch_year(client, _part, year)

            def _cursors(_start=start_year):
                year = _start
                while True:
                    yield year
                    year += 1

            summary = await walk_cursor_pages(
                category=CATEGORY, source_id=source_id, cursors=_cursors(),
                fetch_page=fetch_page, stop_on_empty=True, max_pages=remaining, rate_limit_s=rate_limit_s,
            )
            if cursor_start is None:
                cursor_start = summary.cursor_start
            cursor_end = summary.cursor_end
            all_rows.extend(summary.rows)
            all_gaps.extend(summary.gaps)
            total_fetched += summary.pages_fetched
            total_skipped += summary.pages_skipped_already_done
            stopped_reason = summary.stopped_reason

    result = BackfillSummary(cursor_start=cursor_start, cursor_end=cursor_end,
                              pages_fetched=total_fetched, pages_skipped_already_done=total_skipped,
                              rows=all_rows, gaps=all_gaps, stopped_reason=stopped_reason)
    log.info("gazette_archive_backfill_done", pages=result.pages_fetched,
              skipped=result.pages_skipped_already_done, gaps=len(result.gaps),
              issues=len(result.rows), stopped=result.stopped_reason)
    return result
