"""Tests for the CanadaBuys tender-notice bulk-file backfill (Goal 7)."""
from __future__ import annotations

import pytest

import pipeline.raw_storage as rs
from pipeline.connector_canadabuys import FILES, backfill_tender_notices, sync_rolling_tender_notices


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


@pytest.mark.asyncio
async def test_downloads_every_file_oldest_to_newest_via_streamed_save(httpx_mock):
    # Distinct content per file: save_raw_streamed dedups by content hash,
    # not filename — identical bytes across different files would (rightly)
    # collapse them into "the same save", which isn't what's under test here.
    for label, url in FILES:
        httpx_mock.add_response(url=url, content=f"a,b,c\n{label},2,3\n".encode())

    summary = await backfill_tender_notices(rate_limit_s=0)
    assert summary.pages_fetched == len(FILES)
    assert summary.stopped_reason == "cursors_exhausted"
    assert [r["label"] for r in summary.rows] == [label for label, _ in FILES]
    saved = sorted(p.name for p in (rs.RAW_DIR / "canadabuys" / "canadabuys_tender_notices").rglob("*.csv"))
    assert saved == sorted(f"{label}.csv" for label, _ in FILES)


@pytest.mark.asyncio
async def test_resumes_from_checkpointed_file_index(httpx_mock):
    httpx_mock.add_response(url=FILES[0][1], content=b"x,y\n1,2\n")
    summary1 = await backfill_tender_notices(max_pages=1, rate_limit_s=0)
    assert summary1.pages_fetched == 1
    assert summary1.stopped_reason == "max_pages"

    for label, url in FILES[1:]:
        httpx_mock.add_response(url=url, content=f"x,y\n{label},2\n".encode())
    summary2 = await backfill_tender_notices(rate_limit_s=0)
    assert summary2.pages_skipped_already_done == 1
    assert summary2.pages_fetched == len(FILES) - 1
    assert [r["label"] for r in summary2.rows] == [label for label, _ in FILES[1:]]


_ROLLING = {"complete-since-2022-08-08", "open", "new"}


@pytest.mark.asyncio
async def test_sync_rolling_only_touches_the_three_rolling_files(httpx_mock):
    for label, url in FILES:
        if label in _ROLLING:
            httpx_mock.add_response(url=url, content=f"a,b\n{label},1\n".encode())

    result = await sync_rolling_tender_notices()
    assert {r["label"] for r in result["files"]} == _ROLLING
    requested = {str(r.url) for r in httpx_mock.get_requests()}
    assert requested == {url for label, url in FILES if label in _ROLLING}


@pytest.mark.asyncio
async def test_sync_rolling_rechecks_files_the_backfill_walker_would_lock_out(httpx_mock):
    """Goal 11's actual bug: once backfill_tender_notices has walked every
    file once, its checkpoint locks the rolling snapshots out forever (see
    backfill_tender_notices's docstring) — sync_rolling_tender_notices must
    still re-fetch them on every call regardless."""
    for label, url in FILES:
        httpx_mock.add_response(url=url, content=f"a,b\n{label},1\n".encode())
    summary = await backfill_tender_notices(rate_limit_s=0)
    assert summary.pages_fetched == len(FILES)

    # The walker itself is now permanently a no-op for every file.
    summary2 = await backfill_tender_notices(rate_limit_s=0)
    assert summary2.pages_fetched == 0
    assert summary2.pages_skipped_already_done == len(FILES)

    # The rolling sync bypasses that lockout and re-checks anyway.
    for label, url in FILES:
        if label in _ROLLING:
            httpx_mock.add_response(url=url, content=f"a,b\n{label},2\n".encode())
    result = await sync_rolling_tender_notices()
    assert {r["label"] for r in result["files"]} == _ROLLING
