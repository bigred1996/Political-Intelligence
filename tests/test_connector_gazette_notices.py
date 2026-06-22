"""Tests for the Canada Gazette per-instrument notice backfill (Goal 8)."""
from __future__ import annotations

import pytest

import pipeline.raw_storage as rs
from pipeline.connector_gazette_notices import backfill_gazette_notices, parse_part1_issue, parse_part2_issue


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


_ISSUE_URL = "https://gazette.gc.ca/rp-pr/p1/2026/2026-06-20/html/index-eng.html"

# Mirrors a real issue page: page chrome (a "Search" <h2> full of nav
# links) BEFORE <main>, real content INSIDE <main>...<footer> — the exact
# shape that, unscoped, fed nav-menu garbage into the parsed rows on a
# real run.
_PART1_PAGE = b"""
<html><body>
<section id="wb-srch"><h2>Search</h2>
<ul><li><a href="https://www.canada.ca/en.html">Canada.ca</a></li></ul>
</section>
<main role="main">
<h2> <a href="./commis-eng.html">Commissions</a></h2>
<h3>Canada Border Services Agency</h3>
<h4>Special Import Measures Act</h4>
<ul><li> <a href="./commis-eng.html#cs1">Unarmoured building cables&nbsp;&mdash;&nbsp;Decisions</a></li></ul>
<h3>Canadian Radio-television and Telecommunications Commission</h3>
<h4>Notices of consultation</h4>
<ul><li> <a href="./commis-eng.html#cs9">Administrative procedures</a></li></ul>
<h2>Proposed Regulations</h2>
<h3>Natural Resources, Dept. of</h3>
<h4>Energy Efficiency Act</h4>
<ul><li> <a href="./reg1-eng.html">Regulations Amending the Energy Efficiency Regulations</a></li></ul>
</main>
<footer id="wb-info"><h2 class="wb-inv">About government</h2>
<ul><li><a href="https://www.canada.ca/en/contact.html">Contact us</a></li></ul>
</footer>
</body></html>
"""

_PART2_PAGE = b"""
<html><body>
<section id="wb-srch"><h2>Search</h2>
<ul><li><a href="https://www.canada.ca/en.html">Canada.ca</a></li></ul>
</section>
<main role="main">
<ul class="lst-spcd list-unstyled">
<li> <a href="sor-dors114-eng.html"> Amnesty Period&nbsp;&mdash;&nbsp;Order Amending Certain Orders <br>
    Criminal Code </a> <br>
    SOR/2026-114 <br>
    05/06/26 </li>
<li> <a href="si-tr27-eng.html"> Bovine Tuberculosis Outbreaks <br>
    Financial Administration Act </a> <br>
    SI/2026-27 <br>
    17/06/26 <br>
    new </li>
</ul>
</main>
<footer id="wb-info"></footer>
</body></html>
"""


def test_part1_excludes_page_chrome_outside_main():
    rows = parse_part1_issue(_PART1_PAGE, _ISSUE_URL)
    titles = [r["title"] for r in rows]
    assert "Canada.ca" not in titles
    assert "Contact us" not in titles
    assert len(rows) == 3


def test_part1_section_to_record_type_mapping():
    rows = parse_part1_issue(_PART1_PAGE, _ISSUE_URL)
    by_title = {r["title"]: r for r in rows}
    assert by_title["Unarmoured building cables — Decisions"]["record_type"] == "regulator_notice"
    assert by_title["Regulations Amending the Energy Efficiency Regulations"]["record_type"] == "proposed_regulation"
    assert by_title["Regulations Amending the Energy Efficiency Regulations"]["likely_has_rias"] is True


def test_part1_commissions_consultation_reclassified():
    rows = parse_part1_issue(_PART1_PAGE, _ISSUE_URL)
    by_title = {r["title"]: r for r in rows}
    assert by_title["Administrative procedures"]["record_type"] == "consultation_notice"
    assert by_title["Administrative procedures"]["department"] == \
        "Canadian Radio-television and Telecommunications Commission"


def test_part1_title_does_not_run_away_across_unrelated_anchors():
    # Regression: a bare `.*?</a>` title group, scanning the WHOLE page
    # (not scoped to <main>), backtracked past an unrelated nav <li><a>
    # with no trailing context and spliced two page elements into one
    # garbage row. Scoping to <main> plus a tag-safe title group fixes it.
    rows = parse_part1_issue(_PART1_PAGE, _ISSUE_URL)
    for row in rows:
        assert "Canada.ca" not in row["title"]
        assert len(row["title"]) < 200


def test_part2_final_regulation_vs_statutory_instrument():
    rows = parse_part2_issue(_PART2_PAGE, "https://gazette.gc.ca/rp-pr/p2/2026/2026-06-17/html/index-eng.html")
    assert len(rows) == 2
    assert rows[0]["record_type"] == "final_regulation"
    assert rows[0]["instrument_number"] == "SOR/2026-114"
    assert rows[0]["registration_date"] == "2026-06-05"
    assert rows[1]["record_type"] == "statutory_instrument"
    assert rows[1]["instrument_number"] == "SI/2026-27"


def test_part2_title_with_br_does_not_run_away_into_nav():
    rows = parse_part2_issue(_PART2_PAGE, "https://gazette.gc.ca/rp-pr/p2/2026/2026-06-17/html/index-eng.html")
    assert "Canada.ca" not in rows[0]["title"]
    assert "Amnesty Period" in rows[0]["title"]
    assert "Criminal Code" in rows[0]["title"]


@pytest.mark.asyncio
async def test_backfill_fetches_the_year_indexs_own_absolute_html_url(httpx_mock):
    # Regression: _parse_year_index already returns an ABSOLUTE html_url
    # ("https://gazette.gc.ca/..."); re-prefixing it with the host again
    # produced "https://gazette.gc.cahttps://..." — a DNS failure on every
    # single page, caught live as 10 consecutive gaps tripping the circuit
    # breaker before a single real row landed.
    year_index = (
        b'<a href="/rp-pr/p1/2026/2026-01-03/html/index-eng.html">HTML</a>'
    )
    httpx_mock.add_response(url="https://gazette.gc.ca/rp-pr/p1/2026/index-eng.html", content=year_index)
    httpx_mock.add_response(url="https://gazette.gc.ca/rp-pr/p1/2027/index-eng.html", status_code=404)
    httpx_mock.add_response(url="https://gazette.gc.ca/rp-pr/p1/2026/2026-01-03/html/index-eng.html",
                             content=_PART1_PAGE)

    summary = await backfill_gazette_notices(parts=["1"], start_year=2026, rate_limit_s=0)
    assert summary.gaps == []
    assert summary.pages_fetched == 1
    assert len(summary.rows) == 3
