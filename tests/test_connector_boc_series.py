"""Tests for the full Bank of Canada series-catalogue backfill (Goal 7)."""
from __future__ import annotations

import json

import pytest

import pipeline.raw_storage as rs
from pipeline.connector_boc_series import backfill_all_series


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


_LIST_RESPONSE = json.dumps({"series": {
    "B.SERIES": {"label": "B series"},
    "A.SERIES": {"label": "A series"},
    "C.SERIES": {"label": "C series"},
}}).encode()


def _obs(name, dates):
    return json.dumps({
        "seriesDetail": {name: {"label": f"{name} label"}},
        "observations": [{"d": d, name: {"v": "1.0"}} for d in dates],
    }).encode()


@pytest.mark.asyncio
async def test_walks_series_in_alphabetical_order_and_saves_catalogue_snapshot(httpx_mock):
    httpx_mock.add_response(url="https://www.bankofcanada.ca/valet/lists/series/json", content=_LIST_RESPONSE)
    httpx_mock.add_response(url="https://www.bankofcanada.ca/valet/observations/A.SERIES/json",
                             content=_obs("A.SERIES", ["2020-01-01", "2021-01-01"]))
    httpx_mock.add_response(url="https://www.bankofcanada.ca/valet/observations/B.SERIES/json",
                             content=_obs("B.SERIES", ["2020-01-01"]))
    httpx_mock.add_response(url="https://www.bankofcanada.ca/valet/observations/C.SERIES/json",
                             content=_obs("C.SERIES", []))

    summary = await backfill_all_series(rate_limit_s=0)
    assert summary.pages_fetched == 3
    assert [r["series"] for r in summary.rows] == ["A.SERIES", "B.SERIES", "C.SERIES"]
    assert summary.rows[0]["count"] == 2
    assert summary.rows[2]["count"] == 0
    assert list((rs.RAW_DIR / "bank-of-canada" / "boc_series_catalogue").rglob("series_list.json"))


@pytest.mark.asyncio
async def test_resumes_alphabetically_without_redownloading(httpx_mock):
    httpx_mock.add_response(url="https://www.bankofcanada.ca/valet/lists/series/json", content=_LIST_RESPONSE)
    httpx_mock.add_response(url="https://www.bankofcanada.ca/valet/observations/A.SERIES/json",
                             content=_obs("A.SERIES", ["2020-01-01"]))
    summary1 = await backfill_all_series(max_pages=1, rate_limit_s=0)
    assert summary1.pages_fetched == 1

    httpx_mock.add_response(url="https://www.bankofcanada.ca/valet/lists/series/json", content=_LIST_RESPONSE)
    httpx_mock.add_response(url="https://www.bankofcanada.ca/valet/observations/B.SERIES/json",
                             content=_obs("B.SERIES", ["2020-01-01"]))
    httpx_mock.add_response(url="https://www.bankofcanada.ca/valet/observations/C.SERIES/json",
                             content=_obs("C.SERIES", []))
    summary2 = await backfill_all_series(rate_limit_s=0)
    assert summary2.pages_skipped_already_done == 1  # A.SERIES not refetched
    assert [r["series"] for r in summary2.rows] == ["B.SERIES", "C.SERIES"]
