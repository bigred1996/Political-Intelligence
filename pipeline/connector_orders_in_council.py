"""Orders in Council — full 1990-present backfill (Goal 8).

DATA_CHECKLIST.md previously concluded GIC Appointments (and, by
extension, Orders in Council) had "no working access path at all": the
hardcoded CKAN dataset 404s and there is no PCO appointments dataset in
the CKAN catalogue either. That conclusion was correct for CKAN, but
`orders-in-council.canada.ca` — the PCO's own dedicated search portal,
explicitly described on its own page as covering "Orders in Council...
made from 1990 to the present" — turns out to be a real, working,
unrestricted (no robots.txt at all — confirmed live, a 404) search engine,
not assumed reachable from memory of the earlier "HTML, no bulk CSV
evident" note, which only ever checked one bare page load.

The real mechanism (confirmed by direct probing, not documented anywhere
public): `index.php?lang=en`'s search form POSTs search criteria
(date range, etc. — a honeypot field `leaveBlank` must stay empty) to
itself, which 302-redirects to `results.php?lang=en` holding the first
page of results in the PHP session; subsequent pages are plain GETs to
`results.php?pageNum=N&lang=en` reusing that session's stored criteria.
Each result row already carries the full record inline — P.C. number,
date made, department, act, subject, and a full Précis (plain-language
summary) — plus a per-record attachment link
(`attachment.php?attach={id}&lang=en`, the scanned PDF), so no second
per-record page fetch is needed.

Walked per calendar year (1990 - current), each with its OWN search
(fresh POST) and its OWN checkpoint (`oic_{year}`) — same reasoning as
connector_house_votes/connector_gazette_archive: independent per-stream
checkpoints can't be confused by which years have or haven't been walked
yet in any given call. Within a year, `pageNum` is walked ascending and
stops naturally on the first page with zero rows.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any

import httpx
import structlog

from pipeline.api_paginator import BackfillSummary, PageResult, walk_cursor_pages

log = structlog.get_logger()

CATEGORY = "orders-in-council"
SOURCE_PREFIX = "oic"

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
_HEADERS = {"User-Agent": _UA}

BASE = "https://orders-in-council.canada.ca"
EARLIEST_YEAR = 1990

# No robots.txt at all on this host (confirmed: a literal 404, not a
# permissive empty file) — self-imposed rate limit, same order of
# magnitude as every other connector here.
RATE_LIMIT_S = 0.4

# A cell's content may carry inline formatting — <br/> (an Act cell
# listing two acts, one per line) or <strong>/<strong> (a not-yet-final
# row's Registration cell, "<strong>Registration: </strong>SOR/2026-0130
# <strong>Publication Date:</strong> 2026-07-01") — both found live, on
# DIFFERENT real rows of the same results page, each silently dropping the
# WHOLE row (not just the one field) under a naive `[^<]*` cell pattern,
# since the regex simply failed to match once it hit either embedded tag.
# Rather than allow-list every inline tag one at a time as each gets found,
# this allows ANY tag that isn't a structural td/tr/table boundary —
# narrow enough to still stop at the real cell edge, wide enough to not
# need a third bug report for the next inline tag this source happens to
# use.
_CELL = r"(?:[^<]|<(?!/?(?:td|tr|table)\b)[^>]*>)*"
_ROW_RE = re.compile(
    r"<td><a title='Link to attachment for [^']*' href='(?P<attach_href>[^']*)'>(?P<pc_number>[^<]*)</a>"
    r"<br\s*/?></td>\s*"
    r"<td>(?P<date_made>" + _CELL + r")</td>\s*"
    r"<td>(?P<chapter>" + _CELL + r")</td>\s*"
    r"<td>(?P<chapter_year>" + _CELL + r")</td>\s*"
    r"<td>(?P<bill>" + _CELL + r")</td>\s*"
    r"<td>(?P<dept>" + _CELL + r")</td>\s*"
    r"<td>(?P<act>" + _CELL + r")</td>\s*"
    r"<td>(?P<subject>" + _CELL + r")</td>\s*"
    r"<td>(?P<precis>" + _CELL + r")</td>\s*"
    r"<td[^>]*>(?P<registration>" + _CELL + r")</td>"
)


def _search_payload(from_date: str, to_date: str) -> dict[str, str]:
    return {
        "pcNumber": "", "fromDate": from_date, "toDate": to_date, "keywords": "",
        "department": "", "act": "", "chapterNumber": "", "chapterYear": "",
        "billNumber": "", "foa": "na",
        "leaveBlank": "",  # honeypot — a real browser never fills this in
        "searchList": "Search / List",
    }


def _cell_text(raw: str) -> str | None:
    text = re.sub(r"<br\s*/?>", " / ", raw)
    text = re.sub(r"<[^>]+>", " ", text)  # drop remaining inline tags (<strong>, etc.)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def parse_results_page(content: bytes) -> list[dict[str, Any]]:
    html = content.decode("utf-8", errors="replace")
    rows = []
    for m in _ROW_RE.finditer(html):
        d = m.groupdict()
        rows.append({
            "pc_number": d["pc_number"].strip(),
            "date_made": _cell_text(d["date_made"]),
            "chapter": _cell_text(d["chapter"]),
            "chapter_year": _cell_text(d["chapter_year"]),
            "bill_number": _cell_text(d["bill"]),
            "department": _cell_text(d["dept"]),
            "act": _cell_text(d["act"]),
            "subject": _cell_text(d["subject"]),
            "precis": _cell_text(d["precis"]),
            "attachment_url": f"{BASE}/{d['attach_href']}" if d["attach_href"] else None,
        })
    return rows


def _year_source_id(year: int) -> str:
    return f"{SOURCE_PREFIX}_{year}"


async def _new_session_search(client: httpx.AsyncClient, year: int) -> None:
    """POST the year's date-range search; the 302 → results.php redirect is
    followed automatically (client has follow_redirects=True), establishing
    the session's stored search criteria. The redirected body (page 1) is
    discarded here — the walk below re-fetches page 1 explicitly via GET
    for a uniform, cursor-indexed code path."""
    await client.get(f"{BASE}/index.php?lang=en")  # primes PHPSESSID
    today = datetime.now(timezone.utc).date()
    from_date = date(year, 1, 1).isoformat()
    to_date = date(year, 12, 31).isoformat() if year < today.year else today.isoformat()
    await client.post(f"{BASE}/index.php?lang=en", data=_search_payload(from_date, to_date))


async def backfill_orders_in_council(*, years: list[int] | None = None, max_pages: int | None = None,
                                      rate_limit_s: float = RATE_LIMIT_S) -> BackfillSummary:
    """Backfill every Order in Council from `years` (default: 1990 through
    the current year), oldest year first. `max_pages` is a TOTAL budget
    across every year in this one call, not per-year — see module
    docstring for why each year gets its own independent checkpoint."""
    current_year = datetime.now(timezone.utc).year
    years = years or list(range(EARLIEST_YEAR, current_year + 1))
    all_rows: list[dict[str, Any]] = []
    all_gaps: list[dict[str, Any]] = []
    total_fetched = total_skipped = 0
    cursor_start = cursor_end = None
    stopped_reason = "no_cursors"

    async with httpx.AsyncClient(timeout=45, headers=_HEADERS, follow_redirects=True) as client:
        for year in years:
            remaining = None if max_pages is None else max(0, max_pages - total_fetched)
            if remaining == 0:
                stopped_reason = "max_pages"
                break

            from pipeline import raw_storage as rs
            existing = rs.read_checkpoint(_year_source_id(year))
            if existing and existing.get("status") == "complete":
                stopped_reason = "exhausted"
                continue

            await _new_session_search(client, year)

            async def fetch_page(page_num: int, _year=year) -> PageResult:
                url = f"{BASE}/results.php?pageNum={page_num}&lang=en"
                r = await client.get(url)
                r.raise_for_status()
                content = r.content
                rows = parse_results_page(content)
                for row in rows:
                    row["year"] = _year
                return PageResult(content=content, filename=f"oic_{_year}_p{page_num}.html",
                                   parsed_rows=rows, is_empty=not rows, source_url=url)

            def _page_cursors():
                n = 1
                while True:
                    yield n
                    n += 1

            summary = await walk_cursor_pages(
                category=CATEGORY, source_id=_year_source_id(year), cursors=_page_cursors(),
                fetch_page=fetch_page, stop_on_empty=True, max_pages=remaining, rate_limit_s=rate_limit_s,
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
    log.info("oic_backfill_done", pages=result.pages_fetched, skipped=result.pages_skipped_already_done,
              gaps=len(result.gaps), orders=len(result.rows), stopped=result.stopped_reason)
    return result


async def fetch_oic_records(max_rows: int = 0) -> list[dict[str, Any]]:
    """Registry-facing wrapper for `pipeline/connectors.py`. Full
    1990-present coverage (an estimated ~3,500 pages at 0.4s, ~25 minutes)
    is cheap enough to run uncapped, like the rest of this registry —
    `max_rows` here caps PAGES, not output rows."""
    from pipeline.entity_resolver import normalize

    summary = await backfill_orders_in_council(max_pages=max_rows or None)
    out: list[dict[str, Any]] = []
    for row in summary.rows:
        dept = row.get("department")
        title = row.get("subject") or row["pc_number"]
        out.append({
            "source": "orders_in_council", "record_type": "order_in_council",
            "external_id": f"pc-{row['pc_number']}",
            "entity_name": dept, "canonical_name": normalize(dept) if dept else None,
            "title": title[:1024], "summary": (row.get("precis") or "")[:4000] or None,
            "full_text": f"{title}\n{row.get('precis') or ''}"[:6000],
            "event_date": row.get("date_made"), "amount": None, "province": None,
            "url": row.get("attachment_url"), "raw": row,
        })
    return out
