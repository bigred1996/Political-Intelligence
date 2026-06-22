"""Tests for the IAAC project registry backfill (Goal 8)."""
from __future__ import annotations

import pytest

import pipeline.raw_storage as rs
from pipeline.connector_iaac import (
    _parse_project_page,
    _project_refs_from_sitemap,
    backfill_iaac_projects,
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


# A trimmed-down real project page (the meta block + key-documents +
# comment-periods panels — the parts the parser actually reads).
_PROJECT_PAGE = b"""
<html><head>
<meta name="Project Name" content="Test Supply Road Project" />
<meta name="description" content="A test project description." />
<meta name="Assessment Type" content="Impact Assessment by the Agency" />
<meta name="Assessment Start Date" content="2019-08-28 12:00:00 AM" />
<meta name="Modified Date" content="2026-06-19" />
<meta name="Status" content="In progress" />
<meta name="Proponent" content="Test First Nation" />
<meta name="Responsible Authority" content="Impact Assessment Agency of Canada" />
<meta name="Location" content="Test Lake area" />
<meta name="Province" content="Ontario" />
</head><body>
<h3>Key documents</h3>
<ul class="row dashboard-list">
<li class="dashboard-key-document col-md-12">
<a href=/050/evaluations/document/1001>Notice of commencement</a>
<span class="label label-default">April 20, 2026</span>
</li>
</ul>
<h3>Comment periods</h3>
<ul class="row comment-period-list">
<li class="col-md-12 comment-period">
<a href="/050/evaluations/document/1002">Public Notice - comments invited</a>
<span class="label label-danger">December 19, 2019  to  January 28, 2020 - Closed</span>
</li>
</ul>
</body></html>
"""


def test_parses_meta_block_documents_and_comment_periods():
    row = _parse_project_page(_PROJECT_PAGE, 80183)
    assert row["reference_number"] == 80183
    assert row["title"] == "Test Supply Road Project"
    assert row["proponent"] == "Test First Nation"
    assert row["province"] == "Ontario"
    assert row["status"] == "In progress"
    assert row["start_date"] == "2019-08-28"

    assert len(row["documents"]) == 1
    assert row["documents"][0]["document_id"] == "1001"
    assert row["documents"][0]["title"] == "Notice of commencement"

    assert len(row["comment_periods"]) == 1
    assert row["comment_periods"][0]["document_id"] == "1002"
    assert "Closed" in row["comment_periods"][0]["label"]


def test_unquoted_and_quoted_document_hrefs_both_classified_correctly():
    # Key documents use href=/050/... (unquoted); comment periods use
    # href="/050/..." (quoted) — both real, both seen live.
    row = _parse_project_page(_PROJECT_PAGE, 80183)
    doc_ids = {d["document_id"] for d in row["documents"]}
    cp_ids = {d["document_id"] for d in row["comment_periods"]}
    assert doc_ids == {"1001"}
    assert cp_ids == {"1002"}


def test_page_with_no_title_returns_none():
    assert _parse_project_page(b"<html><body>nothing here</body></html>", 1) is None


def test_project_refs_extracted_and_deduplicated_from_sitemap():
    urls = [
        "https://iaac-aeic.gc.ca/050/evaluations/proj/90567",
        "https://iaac-aeic.gc.ca/050/evaluations/proj/15620",
        "https://iaac-aeic.gc.ca/050/evaluations/proj/90567",  # duplicate
    ]
    assert _project_refs_from_sitemap(urls) == [15620, 90567]


@pytest.mark.asyncio
async def test_backfill_walks_refs_ascending_and_resumes_without_refetching(httpx_mock):
    httpx_mock.add_response(url="https://iaac-aeic.gc.ca/050/evaluations/proj/100",
                             content=_PROJECT_PAGE)
    httpx_mock.add_response(url="https://iaac-aeic.gc.ca/050/evaluations/proj/200",
                             content=_PROJECT_PAGE)

    summary = await backfill_iaac_projects(refs=[200, 100], rate_limit_s=0)
    assert summary.pages_fetched == 2
    assert len(summary.rows) == 2

    # Resuming with the same ref set must not re-request either page.
    summary2 = await backfill_iaac_projects(refs=[200, 100], rate_limit_s=0)
    assert summary2.pages_fetched == 0
    assert summary2.pages_skipped_already_done == 2


@pytest.mark.asyncio
async def test_a_404_project_does_not_abort_or_terminate_the_walk(httpx_mock):
    httpx_mock.add_response(url="https://iaac-aeic.gc.ca/050/evaluations/proj/100",
                             status_code=404)
    httpx_mock.add_response(url="https://iaac-aeic.gc.ca/050/evaluations/proj/200",
                             content=_PROJECT_PAGE)

    summary = await backfill_iaac_projects(refs=[100, 200], rate_limit_s=0)
    # Both refs are real, finite, discovered work — a withdrawn project
    # isn't "no more data ahead" the way an empty page is for an
    # open-ended sequence (years, vote numbers).
    assert summary.pages_fetched == 2
    assert len(summary.rows) == 1
    assert summary.rows[0]["reference_number"] == 200


def test_comment_period_label_parsed_into_start_end_status():
    from pipeline.connector_iaac import _parse_comment_period_label
    start, end, status = _parse_comment_period_label(
        "December 19, 2019  to  January 28, 2020 - Closed"
    )
    assert start == "2019-12-19"
    assert end == "2020-01-28"
    assert status == "Closed"


def test_comment_periods_surfaced_as_their_own_records():
    # Regression: comment periods were parsed into the project row but only
    # ever lived inside the project's `raw` blob — never their own
    # searchable/linkable record, unlike documents.
    from pipeline.connector_iaac import _project_row_to_source_records

    row = _parse_project_page(_PROJECT_PAGE, 80183)
    records = _project_row_to_source_records(row)
    cp_records = [r for r in records if r["record_type"] == "iaac_comment_period"]
    assert len(cp_records) == 1
    assert cp_records[0]["external_id"] == "cp-1002"
    assert cp_records[0]["raw"]["status"] == "Closed"
    assert cp_records[0]["raw"]["start_date"] == "2019-12-19"
