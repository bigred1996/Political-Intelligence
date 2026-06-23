"""Tests for the resumable page-walk primitive (Goal 7).

The goal's literal done-when is: "the backfill can be interrupted and
restarted without losing progress or creating duplicate raw responses."
These tests treat that as a checkable property, not a hope — including a
true crash simulation (an exception that escapes the per-page error
handler entirely, the same way a SIGKILL or an unhandled error elsewhere
in the process would) to prove the checkpoint written before the crash is
exactly what a resumed run picks up from.
"""
from __future__ import annotations

import itertools

import pytest

import pipeline.raw_storage as rs
from pipeline.api_paginator import PageResult, read_gaps, walk_cursor_pages


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(rs, "DATA_DIR", tmp_path)
    monkeypatch.setattr(rs, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(rs, "EXTRACTED_DIR", tmp_path / "extracted")
    monkeypatch.setattr(rs, "MANIFESTS_DIR", tmp_path / "manifests")
    monkeypatch.setattr(rs, "CHECKPOINTS_DIR", tmp_path / "checkpoints")
    monkeypatch.setattr(rs, "QUARANTINE_DIR", tmp_path / "quarantine")
    monkeypatch.setattr(rs, "LOGS_DIR", tmp_path / "logs")
    yield tmp_path


class _SimulatedCrash(BaseException):
    """Stands in for a process death (SIGKILL, OOM) that no in-process
    exception handler ever sees — deliberately not Exception, so it
    propagates straight out of walk_cursor_pages's `except Exception`."""


def _make_fetcher(calls: list[int], *, crash_at: int | None = None,
                   fail_forever: set[int] = frozenset(), last_page: int = 6):
    async def fetch_page(n: int) -> PageResult:
        calls.append(n)
        if crash_at is not None and n == crash_at:
            raise _SimulatedCrash(f"simulated death at page {n}")
        if n in fail_forever:
            raise RuntimeError(f"upstream 500 on page {n}")
        if n > last_page:
            return PageResult(content=b"", filename=f"p{n}.bin", is_empty=True)
        return PageResult(content=f"page-{n}".encode(), filename=f"p{n}.bin",
                           parsed_rows=[{"n": n}])
    return fetch_page


@pytest.mark.asyncio
async def test_full_walk_stops_on_empty_page_and_saves_every_response():
    calls: list[int] = []
    fetch_page = _make_fetcher(calls, last_page=4)
    summary = await walk_cursor_pages(category="parliament", source_id="src_full",
                                       cursors=itertools.count(1), fetch_page=fetch_page,
                                       rate_limit_s=0)
    assert summary.pages_fetched == 4
    assert summary.stopped_reason == "exhausted"
    assert [r["n"] for r in summary.rows] == [1, 2, 3, 4]
    # the terminal empty page is saved too — "save every raw response"
    saved = sorted((tmp.name for tmp in (rs.RAW_DIR / "parliament" / "src_full").rglob("p*.bin")),
                   ) if (rs.RAW_DIR / "parliament" / "src_full").exists() else []
    assert len(saved) == 5  # pages 1-4 + the empty page 5


@pytest.mark.asyncio
async def test_interrupted_run_resumes_without_redownloading_or_duplicating(tmp_path):
    calls: list[int] = []
    fetch_page = _make_fetcher(calls, crash_at=4, last_page=8)

    with pytest.raises(_SimulatedCrash):
        await walk_cursor_pages(category="parliament", source_id="src_crash",
                                 cursors=itertools.count(1), fetch_page=fetch_page, rate_limit_s=0)

    # Pages 1-3 completed and checkpointed before the crash on page 4.
    checkpoint = rs.read_checkpoint("src_crash")
    assert checkpoint["last_cursor"] == 3
    assert checkpoint["status"] == "in_progress"
    saved_dir = rs.RAW_DIR / "parliament" / "src_crash"
    assert sorted(p.name for p in saved_dir.rglob("p*.bin")) == ["p1.bin", "p2.bin", "p3.bin"]

    calls.clear()
    fetch_page2 = _make_fetcher(calls, last_page=8)  # "fixed" — page 4 no longer crashes
    summary = await walk_cursor_pages(category="parliament", source_id="src_crash",
                                       cursors=itertools.count(1), fetch_page=fetch_page2, rate_limit_s=0)

    # Resume must not re-call fetch_page for already-completed cursors 1-3.
    assert calls[0] == 4
    assert not ({1, 2, 3} & set(calls))
    assert summary.pages_skipped_already_done == 3
    assert summary.stopped_reason == "exhausted"

    # No duplicate raw files: exactly one file per page 1-8 plus the empty
    # terminal page, never two for the same cursor.
    all_files = sorted(p.name for p in saved_dir.rglob("p*.bin"))
    assert all_files == [f"p{n}.bin" for n in range(1, 10)]
    manifest_lines = (rs.MANIFESTS_DIR / "parliament__src_crash.jsonl").read_text().splitlines()
    assert len(manifest_lines) == 9  # one manifest entry per page, no extras from the resume


@pytest.mark.asyncio
async def test_complete_walk_rechecks_boundary_and_discovers_new_pages():
    """Goal 11: once a walk reaches 'complete' (stop_on_empty hit), its
    terminal empty cursor is exactly where new content appears if the
    source grows later — a CKAN catalogue gaining datasets, or the current
    year of a per-year walk gaining new P.C. numbers. A scheduled
    incremental re-run must re-probe that one cursor instead of treating
    'complete' as a permanent lockout (which would make every later sync a
    silent, content-free no-op forever, not a real incremental check)."""
    calls: list[int] = []
    fetch_page = _make_fetcher(calls, last_page=4)
    summary = await walk_cursor_pages(category="parliament", source_id="src_grows",
                                       cursors=itertools.count(1), fetch_page=fetch_page, rate_limit_s=0)
    assert summary.stopped_reason == "exhausted"
    checkpoint = rs.read_checkpoint("src_grows")
    assert checkpoint["status"] == "complete"
    assert checkpoint["last_cursor"] == 5  # the empty cursor that ended the walk

    # Nothing new yet: a re-run must re-probe cursor 5 (cheap, one request)
    # rather than reporting "already done" with zero requests.
    calls.clear()
    fetch_page_same = _make_fetcher(calls, last_page=4)
    summary2 = await walk_cursor_pages(category="parliament", source_id="src_grows",
                                        cursors=itertools.count(1), fetch_page=fetch_page_same, rate_limit_s=0)
    assert calls == [5]
    assert summary2.pages_fetched == 0
    assert summary2.stopped_reason == "exhausted"

    # The source grows (3 new pages published past the old boundary). The
    # next scheduled sync must rediscover them, not skip cursor 5 forever.
    calls.clear()
    fetch_page_grown = _make_fetcher(calls, last_page=7)
    summary3 = await walk_cursor_pages(category="parliament", source_id="src_grows",
                                        cursors=itertools.count(1), fetch_page=fetch_page_grown, rate_limit_s=0)
    assert calls == [5, 6, 7, 8]
    assert [r["n"] for r in summary3.rows] == [5, 6, 7]
    assert summary3.stopped_reason == "exhausted"
    assert rs.read_checkpoint("src_grows")["last_cursor"] == 8


@pytest.mark.asyncio
async def test_failing_cursor_recorded_as_gap_and_walk_continues():
    calls: list[int] = []
    fetch_page = _make_fetcher(calls, fail_forever={3}, last_page=5)
    summary = await walk_cursor_pages(category="parliament", source_id="src_gap",
                                       cursors=itertools.count(1), fetch_page=fetch_page,
                                       rate_limit_s=0, max_retries=1, retry_base_delay=0.01)

    # Page 3 is a permanent gap, but 1,2,4,5 still made it through.
    assert [r["n"] for r in summary.rows] == [1, 2, 4, 5]
    assert len(summary.gaps) == 1
    assert summary.gaps[0]["cursor"] == 3
    assert read_gaps("src_gap")[0]["cursor"] == 3


@pytest.mark.asyncio
async def test_resolved_gap_clears_on_a_later_successful_retry():
    calls: list[int] = []
    fetch_page = _make_fetcher(calls, fail_forever={3}, last_page=5)
    await walk_cursor_pages(category="parliament", source_id="src_gap_fix",
                             cursors=itertools.count(1), fetch_page=fetch_page,
                             rate_limit_s=0, max_retries=0, retry_base_delay=0.01)
    assert [g["cursor"] for g in read_gaps("src_gap_fix")] == [3]

    # Cursor 3 is behind the checkpoint's last_cursor (which advanced to 5
    # via cursors 4 and 5 succeeding) — it must still be retried, not
    # silently skipped forever just because later cursors are "done".
    calls.clear()
    fetch_page_fixed = _make_fetcher(calls, last_page=5)
    summary = await walk_cursor_pages(category="parliament", source_id="src_gap_fix",
                                       cursors=itertools.count(1), fetch_page=fetch_page_fixed,
                                       rate_limit_s=0)
    assert 3 in calls
    assert read_gaps("src_gap_fix") == []
    assert summary.stopped_reason == "exhausted"


@pytest.mark.asyncio
async def test_max_pages_caps_a_single_invocation_then_resumes():
    calls: list[int] = []
    fetch_page = _make_fetcher(calls, last_page=10)
    summary = await walk_cursor_pages(category="parliament", source_id="src_capped",
                                       cursors=itertools.count(1), fetch_page=fetch_page,
                                       max_pages=3, rate_limit_s=0)
    assert summary.pages_fetched == 3
    assert summary.stopped_reason == "max_pages"

    summary2 = await walk_cursor_pages(category="parliament", source_id="src_capped",
                                        cursors=itertools.count(1), fetch_page=fetch_page,
                                        max_pages=3, rate_limit_s=0)
    assert summary2.pages_skipped_already_done == 3
    assert summary2.pages_fetched == 3  # pages 4,5,6


@pytest.mark.asyncio
async def test_too_many_consecutive_errors_trips_the_circuit_breaker():
    calls: list[int] = []
    fetch_page = _make_fetcher(calls, fail_forever={1, 2, 3, 4, 5}, last_page=20)
    summary = await walk_cursor_pages(category="parliament", source_id="src_breaker",
                                       cursors=itertools.count(1), fetch_page=fetch_page,
                                       rate_limit_s=0, max_retries=0, retry_base_delay=0.01,
                                       max_consecutive_errors=3)
    assert summary.stopped_reason == "too_many_errors"
    assert len(summary.gaps) == 3
