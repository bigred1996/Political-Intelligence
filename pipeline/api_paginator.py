"""Generic resumable page-walk primitive for API-paginated sources (Goal 7).

Every source in this goal (House of Commons votes, StatCan WDS daily change
checks, the full Open Government CKAN catalogue, Bank of Canada series,
government news, Canada Gazette issues, CanadaBuys, Elections Canada
per-item endpoints) needs the same three guarantees, so they're built once
here instead of seven times:

  1. Every raw page response is persisted via raw_storage.save_raw()
     BEFORE being parsed — a parse bug never loses the underlying payload.
     (A fetch_page that streamed a large file straight to disk itself, via
     raw_storage.save_raw_streamed, sets PageResult.already_saved=True and
     this step is skipped — the guarantee already holds, just earlier.)
  2. A checkpoint is written after EVERY page, not batched at the end, so
     a crash mid-walk loses at most the one in-flight page. Restarting
     resumes from the checkpoint's cursor and never re-fetches a cursor
     already marked done — raw_storage.save_raw's content-hash dedup is
     a backstop, not the primary defence (skipping the request entirely
     also respects the source's rate limit instead of wasting a call on
     a page already known-good).
  3. A page that fails after retries is recorded as a gap in the
     checkpoint (not silently dropped, not a fatal abort) — "record
     missing date ranges" from the goal's done-when list.

This sits below pipeline/connector_base.py: a connector's backfill()
implementation calls walk_cursor_pages() for the actual paged loop.
"""
from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Iterable

import structlog

from pipeline import raw_storage as rs

log = structlog.get_logger()


@dataclass
class PageResult:
    """What one page-fetch call hands back to the walker."""
    content: bytes | None
    filename: str
    parsed_rows: list[dict[str, Any]] = field(default_factory=list)
    is_empty: bool = False          # True → this cursor signals "no more data"
    source_url: str | None = None
    already_saved: bool = False     # True → fetch_page already called raw_storage itself
                                     # (e.g. save_raw_streamed for a large file); content may be None.


@dataclass
class BackfillSummary:
    cursor_start: Any
    cursor_end: Any
    pages_fetched: int
    pages_skipped_already_done: int
    rows: list[dict[str, Any]]
    gaps: list[dict[str, Any]]
    stopped_reason: str   # "exhausted" | "max_pages" | "too_many_errors" | "no_cursors"


def _to_jsonable(cursor: Any) -> Any:
    return list(cursor) if isinstance(cursor, tuple) else cursor


async def _fetch_with_retry(fetch_page: Callable[[Any], Awaitable[PageResult]], cursor: Any,
                             *, max_retries: int, base_delay: float) -> PageResult:
    """Exponential backoff + jitter, per the ingestion spec's retry policy.
    Raises the last exception if every attempt fails — the caller turns
    that into a recorded gap rather than aborting the whole walk.
    """
    attempt = 0
    while True:
        try:
            return await fetch_page(cursor)
        except Exception:
            attempt += 1
            if attempt > max_retries:
                raise
            delay = base_delay * (2 ** (attempt - 1)) + random.uniform(0, base_delay)
            await asyncio.sleep(delay)


async def walk_cursor_pages(
    *, category: str, source_id: str,
    cursors: Iterable[Any],
    fetch_page: Callable[[Any], Awaitable[PageResult]],
    stop_on_empty: bool = True,
    max_pages: int | None = None,
    max_consecutive_errors: int = 5,
    rate_limit_s: float = 0.0,
    max_retries: int = 2,
    retry_base_delay: float = 0.5,
    resume: bool = True,
) -> BackfillSummary:
    """Walk `cursors` in the order given (caller sorts oldest→newest) and
    fetch+save+checkpoint each one. `cursors` may be a generator (e.g. an
    unbounded count()) — the walker stops itself on emptiness/max_pages/
    error budget, it doesn't require a finite list up front.

    Cursors must support `<=` (int, str, or tuple of those) — that's all
    that's needed to skip everything already completed on resume.
    """
    def _normalize(c: Any) -> Any:
        # Checkpoints round-trip through JSON, which has no tuple type — a
        # tuple cursor comes back as a list and `(1, 2) <= [1, 2]` raises
        # TypeError. Normalize both sides to tuples before any comparison.
        return tuple(c) if isinstance(c, list) else c

    checkpoint = rs.read_checkpoint(source_id) if resume else None
    last_done = _normalize(checkpoint.get("last_cursor")) if checkpoint else None
    prior_gaps: list[dict[str, Any]] = list(checkpoint.get("gaps", [])) if checkpoint else []
    # A "complete" checkpoint's last_cursor IS the empty/terminal cursor that
    # ended the previous walk — skipping it forever (the in-progress `<=`
    # rule below) would permanently lock out rediscovering new content that
    # the source later publishes at exactly that boundary (e.g. a growing
    # offset-paginated catalogue, or the current year of a per-year walk).
    # An "in_progress" resume must still skip its last completed cursor
    # (proven by test_interrupted_run_resumes_without_redownloading), so only
    # a prior "complete" status re-opens the boundary cursor for one cheap
    # re-check per sync call — this is the actual "incremental check" Goal 11
    # asks for: free 29 days out of 30, real work the one day content grows.
    reopen_boundary = bool(checkpoint) and checkpoint.get("status") == "complete"

    # A gap is an open retry, not a permanent skip — without this, a cursor
    # that fails and is later passed by a successful higher cursor (which
    # advances last_cursor) would become unreachable forever: the `cursor <=
    # last_done` skip below would hide it from every future resume.
    gap_cursors: set[Any] = {_normalize(g["cursor"]) for g in prior_gaps}

    rows: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = list(prior_gaps)
    pages_fetched = 0
    pages_skipped = 0
    consecutive_errors = 0
    cursor_start: Any = None
    cursor_end: Any = last_done
    stopped_reason = "no_cursors"
    ran_any = False

    for cursor in cursors:
        if cursor_start is None:
            cursor_start = cursor

        already_done = (
            cursor < last_done if reopen_boundary else cursor <= last_done
        ) if last_done is not None else False
        if already_done and _normalize(cursor) not in gap_cursors:
            pages_skipped += 1
            continue

        if max_pages is not None and pages_fetched >= max_pages:
            stopped_reason = "max_pages"
            break

        ran_any = True
        try:
            page = await _fetch_with_retry(fetch_page, cursor, max_retries=max_retries,
                                            base_delay=retry_base_delay)
        except Exception as exc:
            if _normalize(cursor) not in gap_cursors:
                gaps.append({"cursor": _to_jsonable(cursor), "error": str(exc)})
                gap_cursors.add(_normalize(cursor))
            consecutive_errors += 1
            rs.write_checkpoint(source_id, {"last_cursor": _to_jsonable(cursor_end),
                                             "status": "in_progress", "gaps": gaps})
            log.warning("api_paginator_gap", source_id=source_id, cursor=cursor, error=str(exc))
            if consecutive_errors >= max_consecutive_errors:
                stopped_reason = "too_many_errors"
                break
            continue

        consecutive_errors = 0
        if not page.already_saved:
            rs.save_raw(category, source_id, page.filename, page.content, source_url=page.source_url)
        # A retried gap that now succeeds is resolved — drop it from the
        # open-gaps list rather than leaving a stale failure on record.
        if _normalize(cursor) in gap_cursors:
            gap_cursors.discard(_normalize(cursor))
            gaps = [g for g in gaps if _normalize(g["cursor"]) != _normalize(cursor)]

        if page.is_empty and stop_on_empty:
            cursor_end = cursor
            stopped_reason = "exhausted"
            rs.write_checkpoint(source_id, {"last_cursor": _to_jsonable(cursor_end),
                                             "status": "complete", "gaps": gaps})
            break

        cursor_end = max(cursor_end, cursor) if cursor_end is not None else cursor
        rows.extend(page.parsed_rows)
        pages_fetched += 1
        rs.write_checkpoint(source_id, {"last_cursor": _to_jsonable(cursor_end),
                                         "status": "in_progress", "gaps": gaps})
        if rate_limit_s:
            await asyncio.sleep(rate_limit_s)
    else:
        stopped_reason = "cursors_exhausted" if ran_any else stopped_reason

    return BackfillSummary(cursor_start=cursor_start, cursor_end=cursor_end,
                            pages_fetched=pages_fetched, pages_skipped_already_done=pages_skipped,
                            rows=rows, gaps=gaps, stopped_reason=stopped_reason)


def read_gaps(source_id: str) -> list[dict[str, Any]]:
    """Every cursor that's failed every retry so far for this source —
    the "record missing date ranges" report, read independent of a run."""
    checkpoint = rs.read_checkpoint(source_id)
    return list(checkpoint.get("gaps", [])) if checkpoint else []
