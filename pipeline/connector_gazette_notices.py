"""Canada Gazette NOTICE-level backfill — proposed/final regs, SI/OIC-bearing
instruments, and regulator notices (Goal 8).

`connector_gazette_archive.py` (Goal 7) already walks the year-by-year issue
INDEX and proves full historical coverage (1998-2026, both parts, 2,742
issues, 0 gaps) — but it only stores one row per ISSUE (its PDF/HTML link),
not the individual instruments inside it. Goal 8 asks for those instruments
distinguished by type: proposed regulations, final regulations, regulatory
impact statements, consultation notices, Orders in Council, regulator
announcements. This connector adds that second, deeper layer, reusing
`connector_gazette_archive`'s year-index parsing to discover which issues
exist rather than re-walking years from scratch.

Each issue's own TOC page (`.../html/index-eng.html`) turns out to be a
clean, fully-structured index, confirmed live (not assumed from the RSS
feed, which only ever showed flat title+description):

  Part I  — `<h2>` section ("Commissions", "Government notices",
            "Proposed Regulations", "Miscellaneous notices", "Parliament",
            "Supplements") > `<h3>` department/agency > `<h4>` act >
            `<li><a href="...">title</a></li>`. The Commissions section is
            literally where CRTC/CITT/CBSA/CRA/PSC publish their own
            decisions, orders and "Notices of consultation" — this is
            Goal 8's "regulator announcements" and "consultation notices",
            sourced from the Gazette rather than scraped per-regulator.
  Part II — one flat list: `<li><a>title</a><br>SOR/yyyy-n or SI/yyyy-n
            <br>dd/mm/yy</li>`. SOR = final regulation. SI ("Statutory
            Instruments other than Regulations") is the broader bucket
            that includes many Orders in Council, remission orders, and
            appointments — captured here as `statutory_instrument`; a
            dedicated, much richer Orders in Council source (every P.C.
            number back to 1990, with full text) is
            `connector_orders_in_council.py`, built the same session.

Regulatory impact analysis statements are NOT a separate TOC entry — by
long-standing Treasury Board policy almost every Part I "Proposed
Regulations" item is published together with its RIAS in the same
instrument page, not as an independently indexed item. Rather than invent
a RIAS row this connector can't actually verify content for without an
extra per-instrument fetch, `proposed_regulation` rows carry
`likely_has_rias: true` as a documented modelling note, not a scraped fact.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import httpx
import structlog

from pipeline.api_paginator import BackfillSummary, PageResult, walk_cursor_pages
from pipeline.connector_gazette_archive import EARLIEST_YEAR, _HEADERS, _YEAR_URL, _parse_year_index
from pipeline.entity_resolver import normalize

log = structlog.get_logger()

CATEGORY = "canada-gazette"
SOURCE_PREFIX = "gazette_notices"

_SECTION_RE_TYPE = {
    "proposed regulations": "proposed_regulation",
    "commissions": "regulator_notice",
    "government notices": "government_notice",
    "miscellaneous notices": "miscellaneous_notice",
    "parliament": "parliament_notice",
    "supplements": "supplement",
}

_MAIN_RE = re.compile(r'<main\b.*?>(.*?)<footer\b', re.S)
# Title text may contain a <br> (long titles wrap), but must NOT cross any
# other tag boundary — a bare `.*?</a>` here will happily backtrack PAST
# an unrelated nav <li><a>...</a></li> with no <br> after it and keep
# expanding until it finds some LATER, unrelated </a> that does satisfy the
# rest of the pattern, splicing two unconnected page elements into one
# garbage row (caught live against a real Gazette issue page: the first
# "row" parsed was a multi-paragraph blob starting "Canada.ca How
# government works...").
_TITLE_RE = r'(?:[^<]|<br\s*/?>)*'
_P1_TOKEN_RE = re.compile(
    r'<h2>\s*(?:<a[^>]*>)?(?P<h2>[^<]+?)(?:</a>)?\s*</h2>'
    r'|<h3>(?P<h3>[^<]+)</h3>'
    r'|<h4>(?P<h4>[^<]+)</h4>'
    r'|<li>\s*<a href="(?P<href>[^"]+)">(?P<title>' + _TITLE_RE + r')</a>\s*</li>'
)
_P2_ITEM_RE = re.compile(
    r'<li>\s*<a href="([^"]+)">(' + _TITLE_RE + r')</a>\s*<br\s*/?>\s*'
    r'((?:SOR|SI)/\d{4}-\d+)\s*<br\s*/?>\s*(\d{2}/\d{2}/\d{2})'
)
_TAG_RE = re.compile(r"<[^>]+>")


def _main_content(html: str) -> str:
    """Scope parsing to the real TOC body — the page chrome (search-box
    widget, breadcrumb nav, footer link menus) has its own <h2>/<li><a>
    elements that otherwise get misread as real Gazette sections/items
    (caught live: a "Search" section full of nav-menu titles)."""
    m = _MAIN_RE.search(html)
    return m.group(1) if m else html


def _clean(text: str) -> str:
    text = _TAG_RE.sub(" ", text)
    text = text.replace("&ndash;", "–").replace("&mdash;", "—").replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", text).strip()


def _p2_date(dd_mm_yy: str) -> str | None:
    try:
        return datetime.strptime(dd_mm_yy, "%d/%m/%y").strftime("%Y-%m-%d")
    except ValueError:
        return None


def parse_part1_issue(content: bytes, issue_url: str) -> list[dict[str, Any]]:
    """Walk Part I's <h2>section > <h3>dept > <h4>act > <li><a> hierarchy in
    document order, tracking state — there is no nesting in the markup
    itself (h2/h3/h4/li are siblings), so the only way to know which
    section/dept/act an item belongs to is "whatever heading came last"."""
    html = _main_content(content.decode("utf-8", errors="replace"))
    section = dept = act = None
    rows: list[dict[str, Any]] = []
    for m in _P1_TOKEN_RE.finditer(html):
        if m.group("h2") is not None:
            section = _clean(m.group("h2"))
            dept = act = None
        elif m.group("h3") is not None:
            dept = _clean(m.group("h3"))
            act = None
        elif m.group("h4") is not None:
            act = _clean(m.group("h4"))
        elif m.group("href") is not None:
            title = _clean(m.group("title"))
            if not title or not section:
                continue
            record_type = _SECTION_RE_TYPE.get(section.lower(), "gazette_notice_other")
            row = {
                "part": "1", "section": section, "department": dept, "act": act,
                "title": title, "url": issue_url.rsplit("/", 1)[0] + "/" + m.group("href"),
                "record_type": record_type,
            }
            if record_type == "regulator_notice" and "consultation" in (act or title).lower():
                row["record_type"] = "consultation_notice"
            if record_type == "proposed_regulation":
                row["likely_has_rias"] = True
            rows.append(row)
    return rows


def parse_part2_issue(content: bytes, issue_url: str) -> list[dict[str, Any]]:
    html = _main_content(content.decode("utf-8", errors="replace"))
    rows: list[dict[str, Any]] = []
    base = issue_url.rsplit("/", 1)[0]
    for href, title_raw, number, date_raw in _P2_ITEM_RE.findall(html):
        title = _clean(title_raw)
        if not title:
            continue
        record_type = "final_regulation" if number.startswith("SOR/") else "statutory_instrument"
        rows.append({
            "part": "2", "title": title, "instrument_number": number,
            "registration_date": _p2_date(date_raw), "url": f"{base}/{href}",
            "record_type": record_type,
        })
    return rows


def _notices_source_id(part: str) -> str:
    return f"{SOURCE_PREFIX}_p{part}"


async def _discover_issues(client: httpx.AsyncClient, part: str, start_year: int) -> list[dict[str, Any]]:
    """Re-walk year indexes (cheap — ~1 request/year) to discover every
    issue's html_url, reusing Goal 7's already-proven parser rather than
    duplicating it. This does NOT touch connector_gazette_archive's own
    checkpoint — it is a read-only rediscovery for this connector's
    purposes."""
    issues: list[dict[str, Any]] = []
    year = start_year
    while True:
        url = _YEAR_URL.format(part=part, year=year)
        r = await client.get(url)
        if r.status_code == 404:
            break
        r.raise_for_status()
        for row in _parse_year_index(r.content, part, year):
            if row.get("html_url"):
                issues.append(row)
        year += 1
    return issues


async def backfill_gazette_notices(*, parts: list[str] | None = None, start_year: int = EARLIEST_YEAR,
                                    max_pages: int | None = None, rate_limit_s: float = 0.3) -> BackfillSummary:
    """Backfill notice-level rows for every Gazette issue that has an HTML
    edition (recent ~5 years per the directorate's own retention note in
    connector_gazette_archive — older issues are PDF-only and out of scope
    for this text-pattern parser). Each part gets its own checkpoint."""
    parts = parts or ["1", "2"]
    all_rows: list[dict[str, Any]] = []
    all_gaps: list[dict[str, Any]] = []
    total_fetched = total_skipped = 0
    cursor_start = cursor_end = None
    stopped_reason = "no_cursors"

    async with httpx.AsyncClient(timeout=45, headers=_HEADERS, follow_redirects=True) as client:
        for part in parts:
            remaining = None if max_pages is None else max(0, max_pages - total_fetched)
            if remaining == 0:
                stopped_reason = "max_pages"
                break

            issues = await _discover_issues(client, part, start_year)
            cursors = sorted({i["issue_key"]: i for i in issues}.items())  # de-dup, sort by issue_key
            by_key = {k: v for k, v in cursors}

            async def fetch_page(issue_key: str, _part=part) -> PageResult:
                # _parse_year_index already returns an absolute URL — a
                # second "https://gazette.gc.ca" prefix here produced
                # "https://gazette.gc.cahttps://..." and a DNS failure on
                # every single page (caught live: 10 consecutive gaps,
                # tripped the circuit breaker before any real row landed).
                html_url = by_key[issue_key]["html_url"]
                r = await client.get(html_url)
                r.raise_for_status()
                content = r.content
                parser = parse_part1_issue if _part == "1" else parse_part2_issue
                rows = parser(content, html_url)
                return PageResult(content=content, filename=f"notices_p{_part}_{issue_key}.html",
                                   parsed_rows=rows, is_empty=False, source_url=html_url)

            summary = await walk_cursor_pages(
                category=CATEGORY, source_id=_notices_source_id(part),
                cursors=[k for k, _ in cursors], fetch_page=fetch_page,
                stop_on_empty=False, max_pages=remaining, rate_limit_s=rate_limit_s,
            )
            if cursor_start is None:
                cursor_start = summary.cursor_start
            cursor_end = summary.cursor_end
            all_rows.extend(summary.rows)
            all_gaps.extend(summary.gaps)
            total_fetched += summary.pages_fetched
            total_skipped += summary.pages_skipped_already_done
            stopped_reason = summary.stopped_reason

    result = BackfillSummary(cursor_start=cursor_start, cursor_end=cursor_end,
                              pages_fetched=total_fetched, pages_skipped_already_done=total_skipped,
                              rows=all_rows, gaps=all_gaps, stopped_reason=stopped_reason)
    log.info("gazette_notices_backfill_done", pages=result.pages_fetched,
              skipped=result.pages_skipped_already_done, gaps=len(result.gaps),
              notices=len(result.rows), stopped=result.stopped_reason)
    return result


_ISSUE_DATE_RE = re.compile(r"/(\d{4}-\d{2}-\d{2})/html/")


def _issue_date(url: str) -> str | None:
    m = _ISSUE_DATE_RE.search(url)
    return m.group(1) if m else None


async def fetch_gazette_notice_records(max_rows: int = 0) -> list[dict[str, Any]]:
    """Registry-facing wrapper for `pipeline/connectors.py`. Full historical
    coverage (~2,742 issues at 0.3s each, ~14 minutes) is cheap enough to
    run uncapped, like the rest of this registry — `max_rows` here caps
    PAGES (issues), not output rows, same as the underlying backfill."""
    summary = await backfill_gazette_notices(max_pages=max_rows or None)
    out: list[dict[str, Any]] = []
    for row in summary.rows:
        url = row["url"]
        if row["part"] == "1":
            dept = row.get("department")
            title = row["title"]
            summary_text = f"{row.get('section')} — {row.get('act') or ''}".strip(" —")
            external_id = f"gazette-{url}"
        else:
            dept = None
            title = row["title"]
            summary_text = row.get("instrument_number")
            external_id = f"gazette-{row['instrument_number']}"
        out.append({
            "source": "gazette_notices", "record_type": row["record_type"],
            "external_id": external_id,
            "entity_name": dept, "canonical_name": normalize(dept) if dept else None,
            "title": title[:1024], "summary": summary_text[:4000] if summary_text else None,
            "full_text": title[:6000],
            "event_date": row.get("registration_date") or _issue_date(url),
            "amount": None, "province": None, "url": url, "raw": row,
        })
    return out
