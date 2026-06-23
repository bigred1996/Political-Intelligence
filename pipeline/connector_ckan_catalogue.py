"""Open Government CKAN catalogue — full, resumable paginated crawl (Goal 7).

pipeline/catalogue_discovery.py's discover_ckan_catalogue() (Goal 5) already
walks CKAN's package_search start/rows pagination, but in one capped,
in-process call (max_datasets=2000 for open-government, out of ~47,446
total) with no raw-response persistence and no checkpoint — a restart
starts over from start=0 with nothing to show it already paid for the first
2000. This wraps the same CKAN endpoint with pipeline.api_paginator instead,
so the full catalogue (not just a 2000-row slice) can be crawled across
many separate runs: every page's raw JSON is saved, the `start` offset is
checkpointed after every page, and `sort=metadata_created asc` (verified
live) makes the walk genuinely oldest-to-newest and deterministic across
runs — CKAN's default relevance sort would reshuffle as new datasets are
added, breaking the "don't re-walk what's done" resume invariant.

This does not replace discover_ckan_catalogue()'s relevance classification
or catalogue_entries DB upsert — that's Goal 5's job, on whatever subset of
pages this crawl has already saved raw. This is the "fetch every page,
reliably, resumably" layer underneath it.
"""
from __future__ import annotations

from typing import Any

import httpx
import structlog

from pipeline.api_paginator import BackfillSummary, PageResult, walk_cursor_pages
from pipeline.entity_resolver import normalize

log = structlog.get_logger()

CATEGORY = "open-government"
SOURCE_ID = "ckan_full_catalogue"

# Page budget per scheduled call once Goal 11 wires this into the weekly
# "Open Government catalogue" job — the full crawl is ~475 pages (47k
# datasets / PAGE_SIZE); capping each run the same way connector_iaac.py's
# _DEFAULT_CHUNK does keeps every individual fire fast and lets the
# checkpoint carry the crawl forward across several weekly runs. Once
# caught up, the api_paginator "complete" boundary re-check (Goal 11) makes
# each later run a cheap single-page re-probe instead of a full re-walk.
_DEFAULT_CHUNK_PAGES = 50

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
_HEADERS = {"User-Agent": _UA, "Accept": "application/json"}
CKAN_PACKAGE_SEARCH = "https://open.canada.ca/data/api/3/action/package_search"
PAGE_SIZE = 100


async def _fetch_page(client: httpx.AsyncClient, start: int, *, query: str, org: str | None) -> PageResult:
    params: dict[str, Any] = {"q": query, "rows": PAGE_SIZE, "start": start, "sort": "metadata_created asc"}
    if org:
        params["fq"] = f"organization:{org}"
    r = await client.get(CKAN_PACKAGE_SEARCH, params=params)
    r.raise_for_status()
    content = r.content
    results = r.json()["result"]["results"]
    rows = [{
        "id": d.get("id"), "title": (d.get("title") or "").strip(),
        "organization": (d.get("organization") or {}).get("title"),
        "metadata_created": d.get("metadata_created"), "num_resources": len(d.get("resources") or []),
    } for d in results]
    return PageResult(content=content, filename=f"page_start{start:06d}.json", parsed_rows=rows,
                       is_empty=not results, source_url=str(r.url))


async def backfill_ckan_catalogue(*, query: str = "", org: str | None = None,
                                   source_id: str | None = None,
                                   max_pages: int | None = None, rate_limit_s: float = 0.3) -> BackfillSummary:
    """Crawl every page of open.canada.ca's CKAN catalogue (or one
    org-filtered slice of it, e.g. org="nrcan-rncan") from start=0 to the
    end, oldest-dataset-first. Safe to interrupt and re-run: resumes from
    the `start` offset checkpointed after the last completed page.
    """
    sid = source_id or SOURCE_ID

    def _cursors():
        start = 0
        while True:
            yield start
            start += PAGE_SIZE

    async with httpx.AsyncClient(timeout=45, follow_redirects=True, headers=_HEADERS) as client:
        async def fetch_page(start: int) -> PageResult:
            return await _fetch_page(client, start, query=query, org=org)

        summary = await walk_cursor_pages(
            category=CATEGORY, source_id=sid, cursors=_cursors(), fetch_page=fetch_page,
            stop_on_empty=True, max_pages=max_pages, rate_limit_s=rate_limit_s,
        )
    log.info("ckan_catalogue_backfill_done", source_id=sid, pages=summary.pages_fetched,
              skipped=summary.pages_skipped_already_done, gaps=len(summary.gaps),
              datasets=len(summary.rows), stopped=summary.stopped_reason)
    return summary


async def fetch_ckan_catalogue_records(max_rows: int = 0) -> list[dict[str, Any]]:
    """Registry-facing wrapper for pipeline/connectors.py — same
    "max_rows=0 is a bounded per-call page budget, not no cap" convention as
    connector_iaac.py's fetch_iaac_project_records (see _DEFAULT_CHUNK_PAGES
    above for why an unbounded first run isn't started here).

    Each dataset becomes one SourceRecord shaped exactly like
    breadth.py:ckan_org_catalog()'s rows, so it surfaces identically in
    search/records — this just walks the FULL catalogue instead of one
    org-filtered slice, resumably, across many scheduled runs.
    """
    cap = max_rows if max_rows else _DEFAULT_CHUNK_PAGES
    summary = await backfill_ckan_catalogue(max_pages=cap)
    out: list[dict[str, Any]] = []
    for row in summary.rows:
        org = row.get("organization") or ""
        title = row.get("title") or ""
        if not title:
            continue
        out.append({
            "source": "ckan_catalogue",
            "record_type": "dataset",
            "external_id": row.get("id"),
            "entity_name": org or None,
            "canonical_name": normalize(org) if org else None,
            "title": title[:1024],
            "summary": f"{row.get('num_resources', 0)} resource(s) published by {org or 'unknown organization'}.",
            "full_text": f"{title}\n{org}"[:6000],
            "event_date": (row.get("metadata_created") or "")[:10] or None,
            "amount": None,
            "province": None,
            "url": f"https://open.canada.ca/data/dataset/{row.get('id')}" if row.get("id") else None,
            "raw": row,
        })
    return out
