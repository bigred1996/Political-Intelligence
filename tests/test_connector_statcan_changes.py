"""Tests for the StatCan WDS daily changed-cube backfill (Goal 7)."""
from __future__ import annotations

from datetime import date

import pytest

import pipeline.raw_storage as rs
from pipeline.connector_statcan_changes import backfill_changed_cubes


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


def _success(object_list):
    import json
    return {"status_code": 200, "content": json.dumps({"status": "SUCCESS", "object": object_list}).encode()}


@pytest.mark.asyncio
async def test_walks_date_range_oldest_to_newest_and_parses_changed_cubes(httpx_mock):
    httpx_mock.add_response(url="https://www150.statcan.gc.ca/t1/wds/rest/getChangedCubeList/2026-01-01",
                             **_success([{"productId": 10100023, "releaseTime": "2026-01-01T08:30"}]))
    httpx_mock.add_response(url="https://www150.statcan.gc.ca/t1/wds/rest/getChangedCubeList/2026-01-02",
                             **_success([]))
    httpx_mock.add_response(url="https://www150.statcan.gc.ca/t1/wds/rest/getChangedCubeList/2026-01-03",
                             **_success([{"productId": 36100213, "releaseTime": "2026-01-03T08:30"}]))

    summary = await backfill_changed_cubes(start_date=date(2026, 1, 1), end_date=date(2026, 1, 3),
                                            rate_limit_s=0)
    assert summary.pages_fetched == 3
    assert summary.stopped_reason == "cursors_exhausted"
    assert [r["product_id"] for r in summary.rows] == [10100023, 36100213]
    saved = sorted(p.name for p in (rs.RAW_DIR / "statcan" / "statcan_changed_cubes").rglob("changed_*.json"))
    assert saved == ["changed_2026-01-01.json", "changed_2026-01-02.json", "changed_2026-01-03.json"]


@pytest.mark.asyncio
async def test_a_not_yet_released_date_becomes_an_open_gap_not_a_false_stop(httpx_mock):
    httpx_mock.add_response(url="https://www150.statcan.gc.ca/t1/wds/rest/getChangedCubeList/2026-01-01",
                             **_success([{"productId": 1, "releaseTime": "2026-01-01T08:30"}]))
    # 2026-01-02 "not released yet" — every retry attempt also 409s.
    for _ in range(3):
        httpx_mock.add_response(
            url="https://www150.statcan.gc.ca/t1/wds/rest/getChangedCubeList/2026-01-02",
            status_code=409, content=b'{"message":"The product is not released yet"}')
    httpx_mock.add_response(url="https://www150.statcan.gc.ca/t1/wds/rest/getChangedCubeList/2026-01-03",
                             **_success([{"productId": 2, "releaseTime": "2026-01-03T08:30"}]))

    summary = await backfill_changed_cubes(start_date=date(2026, 1, 1), end_date=date(2026, 1, 3),
                                            rate_limit_s=0, max_retries=1, retry_base_delay=0.01)
    # Day 2 is a gap, but day 3 still gets processed — the walk doesn't stop.
    assert [r["product_id"] for r in summary.rows] == [1, 2]
    assert len(summary.gaps) == 1
    assert summary.gaps[0]["cursor"] == "2026-01-02"

    # Once StatCan finishes processing it, a later run resolves the gap —
    # even though cursor_end has already moved past it to 2026-01-03.
    httpx_mock.add_response(url="https://www150.statcan.gc.ca/t1/wds/rest/getChangedCubeList/2026-01-02",
                             **_success([{"productId": 99, "releaseTime": "2026-01-02T08:30"}]))
    summary2 = await backfill_changed_cubes(start_date=date(2026, 1, 1), end_date=date(2026, 1, 3),
                                             rate_limit_s=0)
    assert summary2.pages_fetched == 1
    assert [r["product_id"] for r in summary2.rows] == [99]
    from pipeline.api_paginator import read_gaps
    assert read_gaps("statcan_changed_cubes") == []
