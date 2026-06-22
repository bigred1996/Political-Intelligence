"""Tests for Goal 5: catalogue/metadata discovery before downloading anything.

No live network — httpx calls are mocked via pytest-httpx with response shapes
copied from real CKAN/Gazette responses observed 2026-06-21 (see
DATA_CHECKLIST.md for the live verification numbers this is modeled on).
"""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import api.database as db
from pipeline.catalogue_discovery import (
    catalogue_report, classify_download_status, classify_relevance,
    discover_canada_gazette_index, discover_ckan_catalogue, persist_catalogue_entries,
)

from api.models import catalogue_entry  # noqa: F401


# ── classify_relevance() / classify_download_status() ───────────────────────

def test_classify_relevance_high_on_multiple_topic_matches():
    tier, topics = classify_relevance("Federal energy and mining regulation dataset")
    assert tier == "high"
    assert "energy" in topics and "mining" in topics and "regulation" in topics


def test_classify_relevance_medium_on_one_topic_match():
    tier, topics = classify_relevance("Annual housing report")
    assert tier == "medium"
    assert topics == ["housing"]


def test_classify_relevance_low_on_no_topic_match():
    tier, topics = classify_relevance("Cafeteria menu options for the week")
    assert tier == "low"
    assert topics == []


def test_classify_relevance_handles_none_parts():
    tier, topics = classify_relevance("Trade statistics", None, None)
    assert tier == "medium"
    assert topics == ["trade"]


def test_classify_download_status_known_downloaded():
    assert classify_download_status("d8f85d91-7dec-4fd1-8055-483b77225d8b") == "downloaded"


def test_classify_download_status_known_blocked():
    assert classify_download_status("58b10b98-acab-458a-9e7a-fc1a1c2b1a58") == "blocked"


def test_classify_download_status_unknown_defaults_not_downloaded():
    assert classify_download_status("some-dataset-never-seen-before") == "not_downloaded"


# ── discover_ckan_catalogue() ─────────────────────────────────────────────────

CKAN_RESPONSE = {
    "help": "...", "success": True,
    "result": {
        "count": 1,
        "results": [
            {
                "id": "abc-123",
                "title": "Federal Grants and Contributions Energy Sector",
                "notes": "Annual energy grant disbursements by department.",
                "organization": {"title": "Natural Resources Canada"},
                "metadata_modified": "2026-05-01T00:00:00",
                "license_title": "Open Government Licence - Canada",
                "keywords": {"en": ["energy", "grants"]},
                "resources": [
                    {"id": "res-1", "format": "CSV", "url": "https://example.ca/data.csv",
                     "size": "123456", "last_modified": "2026-05-01"},
                    {"id": "res-2", "format": "XLSX", "url": "https://example.ca/data.xlsx",
                     "size": None},
                ],
            },
        ],
    },
}

EMPTY_RESPONSE = {"help": "...", "success": True, "result": {"count": 0, "results": []}}


@pytest.mark.asyncio
async def test_discover_ckan_catalogue_extracts_one_row_per_resource(httpx_mock):
    httpx_mock.add_response(json=CKAN_RESPONSE)
    httpx_mock.add_response(json=EMPTY_RESPONSE)  # second page, ends pagination

    entries = await discover_ckan_catalogue("open-government", max_datasets=200)

    assert len(entries) == 2  # one dataset, two resources -> two rows
    csv_row = next(e for e in entries if e["format"] == "CSV")
    assert csv_row["dataset_external_id"] == "abc-123"
    assert csv_row["resource_external_id"] == "res-1"
    assert csv_row["download_url"] == "https://example.ca/data.csv"
    assert csv_row["estimated_size_bytes"] == 123456
    assert csv_row["publisher"] == "Natural Resources Canada"
    assert csv_row["license"] == "Open Government Licence - Canada"
    assert csv_row["relevance"] == "high"  # "energy" + "grant" both match topics
    assert csv_row["download_status"] == "not_downloaded"

    xlsx_row = next(e for e in entries if e["format"] == "XLSX")
    assert xlsx_row["estimated_size_bytes"] is None  # size=None handled, not crashed


@pytest.mark.asyncio
async def test_discover_ckan_catalogue_respects_max_datasets(httpx_mock):
    many = {"help": "...", "success": True, "result": {
        "count": 5,
        "results": [dict(CKAN_RESPONSE["result"]["results"][0], id=f"id-{i}") for i in range(5)],
    }}
    httpx_mock.add_response(json=many)

    entries = await discover_ckan_catalogue("open-government", max_datasets=2)
    dataset_ids = {e["dataset_external_id"] for e in entries}
    assert len(dataset_ids) <= 2


@pytest.mark.asyncio
async def test_discover_ckan_catalogue_keeps_dataset_with_no_resources(httpx_mock):
    no_resources = {"help": "...", "success": True, "result": {"count": 1, "results": [
        {**CKAN_RESPONSE["result"]["results"][0], "resources": []},
    ]}}
    httpx_mock.add_response(json=no_resources)
    httpx_mock.add_response(json=EMPTY_RESPONSE)

    entries = await discover_ckan_catalogue("open-government", max_datasets=200)
    assert len(entries) == 1
    assert entries[0]["resource_external_id"] is None
    assert entries[0]["format"] is None


# ── discover_canada_gazette_index() ──────────────────────────────────────────

GAZETTE_HTML = """
<html><body>
<a href="/rp-pr/p1/2026/2026-06-20/html/index-eng.html">Part&nbsp;I, volume 160, number 25</a>
<a href="/rp-pr/p1/2026/2026-06-13/html/index-eng.html">Part&nbsp;I, volume 160, number 24</a>
</body></html>
"""


@pytest.mark.asyncio
async def test_discover_canada_gazette_index_parses_issue_links(httpx_mock):
    httpx_mock.add_response(text=GAZETTE_HTML, url="https://gazette.gc.ca/rp-pr/p1/2026/index-eng.html")
    httpx_mock.add_response(status_code=404, url="https://gazette.gc.ca/rp-pr/p2/2026/index-eng.html")

    entries = await discover_canada_gazette_index(years=[2026])
    assert len(entries) == 2
    titles = {e["title"] for e in entries}
    assert "Part I, volume 160, number 25" in titles
    first = next(e for e in entries if "number 25" in e["title"])
    assert first["download_url"] == "https://gazette.gc.ca/rp-pr/p1/2026/2026-06-20/html/index-eng.html"
    assert first["date_coverage"] == "2026-06-20"
    assert first["download_status"] == "not_downloaded"


# ── persist_catalogue_entries() + catalogue_report() ─────────────────────────

async def _make_session_maker(tmp_path, name):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / name}", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(db.Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def _entry(**overrides):
    base = {
        "catalogue_source": "open-government", "dataset_external_id": "ds-1",
        "resource_external_id": "res-1", "title": "Test dataset", "description": None,
        "publisher": "Test Publisher", "format": "CSV", "download_url": "https://x/data.csv",
        "dataset_url": "https://x/dataset/ds-1", "subject": [], "geographic_coverage": None,
        "date_coverage": None, "last_modified": None, "license": None,
        "estimated_size_bytes": 1000, "relevance": "high", "relevance_topics": ["energy"],
        "download_status": "not_downloaded",
    }
    base.update(overrides)
    return base


def test_persist_then_report_end_to_end(tmp_path, monkeypatch):
    asyncio.run(_persist_report_scenario(tmp_path, monkeypatch))


async def _persist_report_scenario(tmp_path, monkeypatch):
    session_maker = await _make_session_maker(tmp_path, "catalogue.db")
    monkeypatch.setattr(db, "AsyncSessionLocal", session_maker)

    entries = [
        _entry(dataset_external_id="ds-1", resource_external_id="res-1",
               relevance="high", download_status="not_downloaded", estimated_size_bytes=1000),
        _entry(dataset_external_id="ds-2", resource_external_id="res-2",
               relevance="low", download_status="downloaded", estimated_size_bytes=2000),
    ]
    async with session_maker() as session:
        result = await persist_catalogue_entries(session, entries)
    assert result == {"added": 2, "updated": 0, "total": 2}

    # Re-running with one unchanged + one new entry: 1 update, 1 add.
    entries2 = [
        _entry(dataset_external_id="ds-1", resource_external_id="res-1", title="Updated title"),
        _entry(dataset_external_id="ds-3", resource_external_id="res-3"),
    ]
    async with session_maker() as session:
        result2 = await persist_catalogue_entries(session, entries2)
    assert result2 == {"added": 1, "updated": 1, "total": 2}

    async with session_maker() as session:
        report = await catalogue_report(session)

    assert report["total_discovered"] == 3
    assert report["by_download_status"]["downloaded"] == 1
    assert report["by_download_status"]["not_downloaded"] == 2
    assert report["by_relevance"]["high"] == 2  # ds-1 (updated) + ds-3 both default high
    assert report["estimated_bytes_remaining"] == 1000 + 1000  # ds-1 + ds-3, not ds-2 (downloaded)
    assert "catalogues_not_yet_implemented" in report
