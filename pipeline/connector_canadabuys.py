"""CanadaBuys tender notices — paginated bulk-file backfill (Goal 7).

CanadaBuys is NOT a paginated REST API — verified live via its CKAN dataset
record (id 6abd20d4-7a1c-4b38-baa2-9525d0bb2fd2): the real access mechanism
is a fixed, small set of flat CSV files (one per fiscal year, plus rolling
"complete since 2022-08-08" / "open" / "new" snapshots), the same shape as
several Goal 6 sources (Transport Canada, NRCan). The historical archive
alone is 558MB, large enough to need raw_storage.save_raw_streamed (never
buffer the whole file in memory) rather than a normal save_raw call — that's
why PageResult.already_saved exists in pipeline.api_paginator.

Still genuinely a "walk" in the sense Goal 7 asks for: each file is one
page, fetched and checkpointed in a fixed oldest-to-newest order, resumable
across runs — it's just that the "many requests" here is "the ~9 files this
dataset is published as", not date pages or row offsets.
"""
from __future__ import annotations

from typing import Any

import structlog

from pipeline import raw_storage as rs
from pipeline.api_paginator import BackfillSummary, PageResult, walk_cursor_pages

log = structlog.get_logger()

CATEGORY = "canadabuys"
SOURCE_ID = "canadabuys_tender_notices"

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
_HEADERS = {"User-Agent": _UA}
_BASE = "https://canadabuys.canada.ca/opendata/pub"

# Fixed oldest-to-newest order, confirmed live against the CKAN dataset
# record 2026-06-22 — append new fiscal years here as CanadaBuys publishes
# them; never reorder or remove existing entries (their cursor index is
# the resume key every prior run's checkpoint was written against).
FILES: list[tuple[str, str]] = [
    ("2009-2022-historical", f"{_BASE}/2009-2022-tenderNoticeHistorical-AvisAppelOffresHistorique.csv"),
    ("2022-2023", f"{_BASE}/2022-2023-TenderNotice-AvisAppelOffres.csv"),
    ("2023-2024", f"{_BASE}/2023-2024-TenderNotice-AvisAppelOffres.csv"),
    ("2024-2025", f"{_BASE}/2024-2025-TenderNotice-AvisAppelOffres.csv"),
    ("2025-2026", f"{_BASE}/2025-2026-TenderNotice-AvisAppelOffres.csv"),
    ("2026-2027", f"{_BASE}/2026-2027-TenderNotice-AvisAppelOffres.csv"),
    ("complete-since-2022-08-08", f"{_BASE}/tenderNoticeComplete-avisAppelOffresComplet.csv"),
    ("open", f"{_BASE}/openTenderNotice-ouvertAvisAppelOffres.csv"),
    ("new", f"{_BASE}/newTenderNotice-nouvelAvisAppelOffres.csv"),
]


async def _fetch_file(index: int) -> PageResult:
    label, url = FILES[index]
    result = await rs.save_raw_streamed(CATEGORY, SOURCE_ID, f"{label}.csv", url, headers=_HEADERS)
    row = {"label": label, "url": url, "size": result["size"], "checksum": result["checksum"],
           "duplicate": result["duplicate"]}
    return PageResult(content=None, filename=f"{label}.csv", parsed_rows=[row],
                       is_empty=False, source_url=url, already_saved=True)


def _cursors():
    for i in range(len(FILES)):
        yield i


async def backfill_tender_notices(*, max_pages: int | None = None, rate_limit_s: float = 0.5) -> BackfillSummary:
    """Download every CanadaBuys tender-notice file in FILES, oldest first.
    Safe to interrupt/resume: resumes from the checkpointed file index, and
    save_raw_streamed's own content-hash dedup means even a re-run of a
    file that's already current just confirms it rather than duplicating it.

    One-time/manual historical pull, not the recurring sync — once every
    FILES index has succeeded once, walk_cursor_pages's `cursor <= last_done`
    skip rule (correct for the historical fixed-year files, which never
    change once published) ALSO locks out the 3 rolling snapshot files
    (open/new/complete-since), which mutate in place under the same fixed
    index rather than growing the cursor space — this walker's checkpoint
    model has no way to tell "done forever" apart from "due for a recheck"
    for an in-place-mutating cursor. See sync_rolling_tender_notices() for
    the recurring job that actually keeps those three current.
    """
    async def fetch_page(index: int) -> PageResult:
        return await _fetch_file(index)

    summary = await walk_cursor_pages(
        category=CATEGORY, source_id=SOURCE_ID, cursors=_cursors(), fetch_page=fetch_page,
        stop_on_empty=False, max_pages=max_pages, rate_limit_s=rate_limit_s,
        max_retries=1, retry_base_delay=2.0,
    )
    log.info("canadabuys_backfill_done", pages=summary.pages_fetched,
              skipped=summary.pages_skipped_already_done, gaps=len(summary.gaps),
              stopped=summary.stopped_reason)
    return summary


# The 3 rolling snapshots (not the fixed historical fiscal-year files) —
# these are what "active procurement opportunities" (Goal 11) actually
# means: tenders open right now, not 2009-2022 history.
_ROLLING_LABELS = {"complete-since-2022-08-08", "open", "new"}
_ROLLING_INDICES = [i for i, (label, _) in enumerate(FILES) if label in _ROLLING_LABELS]


async def sync_rolling_tender_notices() -> dict[str, Any]:
    """Re-fetch just the 3 rolling tender-notice snapshots, every call —
    deliberately bypassing walk_cursor_pages's checkpoint skip (see
    backfill_tender_notices's docstring for why that would lock these out
    after the first successful fetch). save_raw_streamed's own content-hash
    dedup still makes an unchanged file a cheap no-new-file no-op; CanadaBuys
    exposes no documented ETag/Last-Modified to skip the download itself."""
    results = []
    for index in _ROLLING_INDICES:
        page = await _fetch_file(index)
        results.append(page.parsed_rows[0])
    changed = sum(1 for r in results if not r["duplicate"])
    log.info("canadabuys_rolling_sync_done", files=len(results), changed=changed)
    return {"files": results, "changed": changed}
