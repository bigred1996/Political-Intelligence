"""Tests for the Canada Gazette historical year-index backfill (Goal 7)."""
from __future__ import annotations

import pytest

import pipeline.raw_storage as rs
from pipeline.connector_gazette_archive import _parse_year_index, backfill_gazette_archive


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


_OLD_FORMAT_PAGE = b"""
<html><body>
<a href="/rp-pr/p1/2003/2003-01-04/pdf/g1-13701.pdf">Dec 27, 2003 (222KB)</a>
<a href="/rp-pr/p1/2003/2003-01-11/pdf/g1-13702.pdf">Jan 11, 2003</a>
</body></html>
"""

_RECENT_FORMAT_PAGE = b"""
<html><body>
<a href="/rp-pr/p1/2025/2025-01-04/html/index-eng.html">HTML</a>
<a href="/rp-pr/p1/2025/2025-01-04/pdf/g1-15901.pdf">PDF</a>
<a href="/rp-pr/p1/2025/2025-01-11/html/index-eng.html">HTML</a>
<a href="/rp-pr/p1/2025/2025-01-11/pdf/g1-15902.pdf">PDF</a>
</body></html>
"""


def test_parses_old_pdf_only_format():
    rows = _parse_year_index(_OLD_FORMAT_PAGE, "1", 2003)
    assert len(rows) == 2
    assert rows[0]["issue_key"] == "2003-01-04"
    assert rows[0]["pdf_url"].endswith("g1-13701.pdf")
    assert rows[0]["html_url"] is None


def test_parses_recent_html_plus_pdf_format_merged_by_date():
    rows = _parse_year_index(_RECENT_FORMAT_PAGE, "1", 2025)
    assert len(rows) == 2
    assert rows[0]["html_url"].endswith("html/index-eng.html")
    assert rows[0]["pdf_url"].endswith("g1-15901.pdf")


@pytest.mark.asyncio
async def test_walks_years_oldest_to_newest_until_a_404_and_resumes(httpx_mock):
    httpx_mock.add_response(url="https://gazette.gc.ca/rp-pr/p1/1998/index-eng.html", content=_OLD_FORMAT_PAGE)
    httpx_mock.add_response(url="https://gazette.gc.ca/rp-pr/p1/1999/index-eng.html", status_code=404)

    summary = await backfill_gazette_archive(parts=["1"], start_year=1998, rate_limit_s=0)
    assert summary.pages_fetched == 1
    assert summary.stopped_reason == "exhausted"
    assert len(summary.rows) == 2

    # Resuming with the same part must not re-request 1998 — it's complete.
    summary2 = await backfill_gazette_archive(parts=["1"], start_year=1998, rate_limit_s=0)
    assert summary2.pages_fetched == 0


@pytest.mark.asyncio
async def test_backfilling_part_two_first_does_not_hide_part_one(httpx_mock):
    # Same bug class caught live in connector_house_votes: walk Part II
    # alone first, then Part I alone in a SEPARATE call — "1" sorting
    # before "2" must not make Part I look "already done".
    httpx_mock.add_response(url="https://gazette.gc.ca/rp-pr/p2/1998/index-eng.html", content=_OLD_FORMAT_PAGE)
    httpx_mock.add_response(url="https://gazette.gc.ca/rp-pr/p2/1999/index-eng.html", status_code=404)
    summary1 = await backfill_gazette_archive(parts=["2"], start_year=1998, rate_limit_s=0)
    assert summary1.pages_fetched == 1

    httpx_mock.add_response(url="https://gazette.gc.ca/rp-pr/p1/1998/index-eng.html", content=_OLD_FORMAT_PAGE)
    httpx_mock.add_response(url="https://gazette.gc.ca/rp-pr/p1/1999/index-eng.html", status_code=404)
    summary2 = await backfill_gazette_archive(parts=["1"], start_year=1998, rate_limit_s=0)
    assert summary2.pages_fetched == 1
    assert summary2.rows[0]["part"] == "1"


@pytest.mark.asyncio
async def test_two_parts_walked_independently_without_infinite_skip(httpx_mock):
    httpx_mock.add_response(url="https://gazette.gc.ca/rp-pr/p1/1998/index-eng.html", content=_OLD_FORMAT_PAGE)
    httpx_mock.add_response(url="https://gazette.gc.ca/rp-pr/p1/1999/index-eng.html", status_code=404)
    httpx_mock.add_response(url="https://gazette.gc.ca/rp-pr/p2/1998/index-eng.html", content=_OLD_FORMAT_PAGE)
    httpx_mock.add_response(url="https://gazette.gc.ca/rp-pr/p2/1999/index-eng.html", status_code=404)

    summary = await backfill_gazette_archive(parts=["1", "2"], start_year=1998, rate_limit_s=0)
    assert summary.pages_fetched == 2  # one real year-page per part
    assert summary.stopped_reason == "exhausted"

    # Resuming both parts again must not spin or re-request anything.
    summary2 = await backfill_gazette_archive(parts=["1", "2"], start_year=1998, rate_limit_s=0)
    assert summary2.pages_fetched == 0
