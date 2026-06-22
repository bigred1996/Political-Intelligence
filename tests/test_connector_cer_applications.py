"""Tests for the CER applications/proceedings/decisions backfill (Goal 8)."""
from __future__ import annotations

import pytest

import pipeline.raw_storage as rs
from pipeline.connector_cer_applications import (
    _application_record_type,
    _parse_application_page,
    backfill_cer_applications,
    discover_application_links,
)


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


_CURRENT_INDEX = """
<details>
<summary><h3>Tolls/Tariffs applications</h3></summary>
<ul>
<li><a href="/en/applications-hearings/view-applications-projects/trans-mountain-interim-tolls/">Trans Mountain Pipeline ULC Application for Interim Tolls &ndash; RH-002-2023</a></li>
</ul>
</details>
<details>
<summary><h3>Decision issued</h3></summary>
<ul>
<li><a href="/en/applications-hearings/view-applications-projects/enbridge-line-1/index.html">Enbridge Pipelines Inc. &ndash; Line 1 Optimization Project</a></li>
</ul>
</details>
"""

# The archive page uses plain <h2> headings, no <details> wrapper.
_ARCHIVE_INDEX = """
<h2>Facilities Applications</h2>
<ul class="lst-spcd">
<li><a href="/en/applications-hearings/view-applications-projects/keystone-xl/index.html">South Bow GP (Canada) Ltd. Keystone XL Pipeline Project</a></li>
</ul>
"""

_APPLICATION_PAGE = b"""
<html><body>
<h1>Enbridge Pipelines Inc. \xe2\x80\x93 Line 1 Optimization Project</h1>
<h2 id="regdocs">REGDOCS Link</h2>
<p><a href="https://apps.cer-rec.gc.ca/REGDOCS/Item/Filing/C36307">C36307</a></p>
<h2 id="background">Project Background</h2>
<p>Enbridge has filed an application for the Line 1 Optimization Project.</p>
<dl id="wb-dtmd"><dt>Date modified:</dt><dd><time property="dateModified">2025-10-23</time></dd></dl>
</body></html>
"""


def test_discovers_links_from_details_wrapped_current_index():
    links = discover_application_links(_CURRENT_INDEX)
    paths = {entry["path"]: entry["category"] for entry in links}
    assert paths["trans-mountain-interim-tolls"] == "Tolls/Tariffs applications"
    assert paths["enbridge-line-1"] == "Decision issued"


def test_discovers_links_from_plain_h2_archive_index():
    links = discover_application_links(_ARCHIVE_INDEX)
    assert links[0]["path"] == "keystone-xl"
    assert links[0]["category"] == "Facilities Applications"


def test_parses_application_detail_page():
    row = _parse_application_page(_APPLICATION_PAGE, "enbridge-line-1", "Decision issued")
    assert row["applicant"] == "Enbridge Pipelines Inc."
    assert row["regdocs_filing_number"] == "C36307"
    assert row["modified_date"] == "2025-10-23"
    assert "Line 1 Optimization" in row["description"]


def test_proceeding_number_extracted_from_title():
    row = _parse_application_page(
        b"<html><body><h1>Trans Mountain Pipeline ULC \xe2\x80\x93 Interim Tolls \xe2\x80\x93 RH-002-2023</h1></body></html>",
        "trans-mountain-interim-tolls", "Tolls/Tariffs applications",
    )
    assert row["proceeding_number"] == "RH-002-2023"


def test_decision_issued_bucket_classifies_as_decision_not_application():
    row = {"status": "decision_issued", "proceeding_number": None}
    assert _application_record_type(row) == "cer_decision"
    row2 = {"status": "active", "proceeding_number": "RH-002-2023"}
    assert _application_record_type(row2) == "cer_proceeding"
    row3 = {"status": "active", "proceeding_number": None}
    assert _application_record_type(row3) == "cer_application"


@pytest.mark.asyncio
async def test_backfill_walks_discovered_links_and_resumes(httpx_mock):
    httpx_mock.add_response(
        url="https://www.cer-rec.gc.ca/en/applications-hearings/view-applications-projects/enbridge-line-1/",
        content=_APPLICATION_PAGE)
    httpx_mock.add_response(
        url="https://www.cer-rec.gc.ca/en/applications-hearings/view-applications-projects/keystone-xl/",
        content=_APPLICATION_PAGE)

    links = [
        {"path": "enbridge-line-1", "title": "x", "category": "Decision issued"},
        {"path": "keystone-xl", "title": "y", "category": "Facilities Applications"},
    ]
    summary = await backfill_cer_applications(links=links, rate_limit_s=0)
    assert summary.pages_fetched == 2
    assert len(summary.rows) == 2

    summary2 = await backfill_cer_applications(links=links, rate_limit_s=0)
    assert summary2.pages_fetched == 0


@pytest.mark.asyncio
async def test_fetch_wrapper_tags_rows_with_the_registry_source_id(httpx_mock, monkeypatch):
    # Regression: the wrapper originally tagged every row "source": "cer" —
    # the SAME source id the pre-existing pipeline-incidents connector uses
    # — silently co-mingling 110 real application/decision rows into the
    # incidents bucket and breaking this connector's own upsert/checkpoint
    # tracking (which is keyed by the REGISTRY id, "cer_applications").
    from pipeline.connector_cer_applications import fetch_cer_application_records

    async def fake_discover():
        return [{"path": "enbridge-line-1", "title": "x", "category": "Decision issued"}]
    monkeypatch.setattr("pipeline.connector_cer_applications.discover_all_links", fake_discover)
    httpx_mock.add_response(
        url="https://www.cer-rec.gc.ca/en/applications-hearings/view-applications-projects/enbridge-line-1/",
        content=_APPLICATION_PAGE)

    records = await fetch_cer_application_records()
    assert len(records) == 1
    assert records[0]["source"] == "cer_applications"
