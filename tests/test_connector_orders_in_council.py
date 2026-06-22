"""Tests for the Orders in Council backfill (Goal 8)."""
from __future__ import annotations

import pytest

import pipeline.raw_storage as rs
from pipeline.connector_orders_in_council import backfill_orders_in_council, parse_results_page


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


_SIMPLE_ROW = (
    "<td><a title='Link to attachment for 2026-0616' href='attachment.php?attach=1&lang=en'>"
    "2026-0616</a><br /></td><td>2026-06-12</td><td></td><td></td><td></td>"
    "<td>GAC</td><td>Other Than Statutory Authority</td>"
    "<td>Test subject</td><td>Test precis text.</td><td aria-label='not applicable'>N/A</td>"
)

# Real shape found live: an Act cell spanning two acts with an embedded
# <br />, which a naive `[^<]*` cell pattern fails to match — dropping the
# WHOLE row, not just that field.
_MULTI_ACT_ROW = (
    "<td><a title='Link to attachment for 2026-0612' href='attachment.php?attach=2&lang=en'>"
    "2026-0612</a><br /></td><td>2026-06-12</td><td></td><td></td><td></td>"
    "<td>INFC</td><td>Canada Mortgage and Housing Corporation Act<br />Financial Administration Act</td>"
    "<td>Order Appointing Joint Auditors</td><td>Order appointing joint auditors.</td>"
    "<td aria-label='not applicable'>N/A</td>"
)

# Real shape found live: a Registration cell with <strong> formatting
# (a not-yet-final regulation showing its forecast SOR number/date).
_STRONG_TAG_ROW = (
    "<td><a title='Link to attachment for 2026-0610' href='attachment.php?attach=3&lang=en'>"
    "2026-0610</a><br /></td><td>2026-06-12</td><td></td><td></td><td></td>"
    "<td>FIN</td><td>Excise Tax Act</td>"
    "<td>Regulations Amending the HST Regulations</td><td>Some precis.</td>"
    "<td><strong>Registration: </strong>SOR/2026-0130  <strong>Publication Date:</strong> 2026-07-01</td>"
)


def _page(*rows: str) -> bytes:
    body = "<table><tbody><tr>" + "<tr>".join(rows) + "</tr></tbody></table>"
    return body.encode("utf-8")


def test_parses_a_simple_row():
    rows = parse_results_page(_page(_SIMPLE_ROW))
    assert len(rows) == 1
    assert rows[0]["pc_number"] == "2026-0616"
    assert rows[0]["department"] == "GAC"
    assert rows[0]["attachment_url"].endswith("attachment.php?attach=1&lang=en")


def test_multi_act_row_with_embedded_br_is_not_dropped():
    rows = parse_results_page(_page(_SIMPLE_ROW, _MULTI_ACT_ROW))
    assert len(rows) == 2
    assert rows[1]["act"] == "Canada Mortgage and Housing Corporation Act / Financial Administration Act"


def test_row_with_strong_tags_in_registration_cell_is_not_dropped():
    rows = parse_results_page(_page(_SIMPLE_ROW, _STRONG_TAG_ROW))
    assert len(rows) == 2
    assert rows[1]["pc_number"] == "2026-0610"
    assert rows[1]["subject"] == "Regulations Amending the HST Regulations"


@pytest.mark.asyncio
async def test_backfill_walks_pages_within_a_year_until_empty_and_resumes(httpx_mock):
    httpx_mock.add_response(url="https://orders-in-council.canada.ca/index.php?lang=en")
    httpx_mock.add_response(url="https://orders-in-council.canada.ca/index.php?lang=en", method="POST")
    httpx_mock.add_response(url="https://orders-in-council.canada.ca/results.php?pageNum=1&lang=en",
                             content=_page(_SIMPLE_ROW))
    httpx_mock.add_response(url="https://orders-in-council.canada.ca/results.php?pageNum=2&lang=en",
                             content=_page(""))

    summary = await backfill_orders_in_council(years=[2026], rate_limit_s=0)
    assert summary.pages_fetched == 1
    assert len(summary.rows) == 1
    assert summary.rows[0]["year"] == 2026
    assert summary.stopped_reason == "exhausted"

    # Resuming the same year must not re-search or re-walk it.
    summary2 = await backfill_orders_in_council(years=[2026], rate_limit_s=0)
    assert summary2.pages_fetched == 0
