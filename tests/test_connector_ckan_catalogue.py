"""Tests for the full resumable CKAN catalogue crawl (Goal 7)."""
from __future__ import annotations

import json

import pytest

import pipeline.raw_storage as rs
from pipeline.connector_ckan_catalogue import backfill_ckan_catalogue, fetch_ckan_catalogue_records


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


def _page(datasets):
    return {"status_code": 200,
            "content": json.dumps({"result": {"results": datasets, "count": 999}}).encode()}


def _dataset(i):
    return {"id": f"ds-{i}", "title": f"Dataset {i}", "organization": {"title": "Org"},
            "metadata_created": f"2020-01-{(i % 28) + 1:02d}", "resources": [{"format": "CSV"}]}


@pytest.mark.asyncio
async def test_crawls_pages_in_order_with_metadata_created_sort(httpx_mock):
    httpx_mock.add_response(
        url="https://open.canada.ca/data/api/3/action/package_search?q=&rows=100&start=0&sort=metadata_created+asc",
        **_page([_dataset(1), _dataset(2)]))
    httpx_mock.add_response(
        url="https://open.canada.ca/data/api/3/action/package_search?q=&rows=100&start=100&sort=metadata_created+asc",
        **_page([]))

    summary = await backfill_ckan_catalogue(rate_limit_s=0)
    assert summary.pages_fetched == 1
    assert summary.stopped_reason == "exhausted"
    assert [r["id"] for r in summary.rows] == ["ds-1", "ds-2"]
    saved = sorted(p.name for p in (rs.RAW_DIR / "open-government" / "ckan_full_catalogue").rglob("page_*.json"))
    assert saved == ["page_start000000.json", "page_start000100.json"]


@pytest.mark.asyncio
async def test_resumes_from_checkpointed_offset_without_redownloading(httpx_mock):
    httpx_mock.add_response(
        url="https://open.canada.ca/data/api/3/action/package_search?q=&rows=100&start=0&sort=metadata_created+asc",
        **_page([_dataset(1)]))
    summary1 = await backfill_ckan_catalogue(max_pages=1, rate_limit_s=0)
    assert summary1.pages_fetched == 1
    assert summary1.stopped_reason == "max_pages"

    httpx_mock.add_response(
        url="https://open.canada.ca/data/api/3/action/package_search?q=&rows=100&start=100&sort=metadata_created+asc",
        **_page([_dataset(2)]))
    httpx_mock.add_response(
        url="https://open.canada.ca/data/api/3/action/package_search?q=&rows=100&start=200&sort=metadata_created+asc",
        **_page([]))
    summary2 = await backfill_ckan_catalogue(rate_limit_s=0)
    assert summary2.pages_skipped_already_done == 1  # start=0 not refetched
    assert summary2.pages_fetched == 1  # start=100 only
    assert [r["id"] for r in summary2.rows] == ["ds-2"]


@pytest.mark.asyncio
async def test_fetch_ckan_catalogue_records_maps_rows_for_source_records(httpx_mock):
    """Goal 11: registers this crawl into pipeline/connectors.py's scheduler
    registry, which needs fetch(max_rows=...) -> list[dict] shaped for
    SourceRecord, not a raw BackfillSummary."""
    httpx_mock.add_response(
        url="https://open.canada.ca/data/api/3/action/package_search?q=&rows=100&start=0&sort=metadata_created+asc",
        **_page([_dataset(1)]))
    httpx_mock.add_response(
        url="https://open.canada.ca/data/api/3/action/package_search?q=&rows=100&start=100&sort=metadata_created+asc",
        **_page([]))

    records = await fetch_ckan_catalogue_records(max_rows=5)
    assert len(records) == 1
    r = records[0]
    assert r["source"] == "ckan_catalogue"
    assert r["external_id"] == "ds-1"
    assert r["title"] == "Dataset 1"
    assert r["canonical_name"] == "org"
    assert r["url"] == "https://open.canada.ca/data/dataset/ds-1"


@pytest.mark.asyncio
async def test_org_filter_uses_a_distinct_source_id(httpx_mock):
    httpx_mock.add_response(
        url="https://open.canada.ca/data/api/3/action/package_search"
            "?q=&rows=100&start=0&sort=metadata_created+asc&fq=organization%3Anrcan-rncan",
        **_page([]))
    summary = await backfill_ckan_catalogue(org="nrcan-rncan", source_id="ckan_nrcan", rate_limit_s=0)
    assert summary.stopped_reason == "exhausted"
    assert (rs.RAW_DIR / "open-government" / "ckan_nrcan").exists()
