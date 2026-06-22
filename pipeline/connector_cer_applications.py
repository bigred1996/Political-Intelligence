"""CER applications, proceedings and decisions — row-level backfill (Goal 8).

The existing `cer` breadth connector (`pipeline/breadth.py:fetch_cer_records`)
only covers pipeline INCIDENTS. Applications/hearings/decisions are a
different CER dataset entirely, and the documents themselves live in
REGDOCS (`docs2.cer-rec.gc.ca`), whose `/robots.txt` is `Disallow: /` —
confirmed live, not assumed — matching the existing audit note ("regulatory-
DOCUMENT systems... intentionally not scraped per spec policy"). This
connector does NOT touch REGDOCS; it only stores REGDOCS filing-number
references (e.g. "C36307" linking to
`apps.cer-rec.gc.ca/REGDOCS/Item/Filing/C36307`) the same way the spec
treats CanLII: citation/link only, no mirroring.

What IS crawlable (`www.cer-rec.gc.ca`, no robots.txt disallow on this
path, confirmed live): the **Applications and projects** index —

    /en/applications-hearings/view-applications-projects/
    /en/applications-hearings/view-applications-projects/archive/

Both are static HTML, grouped under headings ("Pipelines over 40 km",
"Tolls/Tariffs applications", "Decision issued", ...) that double as the
application's category/status — "Decision issued" is literally CER's own
bucket for what Goal 8 calls "CER decisions". Many titles embed the
official hearing-order/proceeding code inline (e.g. "... – RH-002-2023",
"... – OH-001-2022", "... – XG-005-2023") — extracted here as
`proceeding_number`, covering "CER proceedings" without a separate index.
Each application's own detail page has a `<h1>` title (applicant +
project), a REGDOCS filing-number link, a project-background paragraph,
and a `dateModified`.

Two index pages, not an open-ended sequence — there is no "exhausted"
terminus to walk toward, so this discovers the full link set up front and
walks it (sorted, for the same `<=`-checkpoint resumability every other
connector here relies on) rather than pagination over an unbounded cursor.

Caveat specific to a STRING cursor space (unlike every other connector
here, whose int/date cursors are monotonic over time by construction): a
brand-new application whose slug sorts alphabetically BEFORE the
checkpoint's high-water mark would be silently skipped by the generic
`<=` resume check on a left-incomplete walk. This is only a live risk if a
run is deliberately chunked across multiple separate calls; at ~120 total
applications (one-time discovery, ~60s at this rate limit), the intended
operational pattern is a single uncapped call per trigger, which always
walks every currently-discovered path regardless of checkpoint state —
the same caveat connector_house_votes/connector_gazette_archive document
for cross-stream ordering, scoped down here because full re-walks are
cheap rather than because the underlying risk doesn't exist.
"""
from __future__ import annotations

import re
from typing import Any

import httpx
import structlog

from pipeline.api_paginator import BackfillSummary, PageResult, walk_cursor_pages
from pipeline.entity_resolver import normalize

log = structlog.get_logger()

CATEGORY = "cer"
SOURCE_ID = "cer_applications"

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
_HEADERS = {"User-Agent": _UA}

BASE = "https://www.cer-rec.gc.ca"
INDEX_URLS = [
    f"{BASE}/en/applications-hearings/view-applications-projects/",
    f"{BASE}/en/applications-hearings/view-applications-projects/archive/",
]
APPLICATION_PATH_PREFIX = "/en/applications-hearings/view-applications-projects/"

# No documented rate limit on www.cer-rec.gc.ca (confirmed via robots.txt —
# only REGDOCS, a different host, disallows crawling); self-imposed, same
# order of magnitude as the other non-rate-limited connectors here.
RATE_LIMIT_S = 0.5

_HEADING_RE = re.compile(r"<h[23][^>]*>(?:<[^>]+>)*([^<]+)", re.IGNORECASE)
_LINK_RE = re.compile(
    r'<a href="' + re.escape(APPLICATION_PATH_PREFIX) + r'([^"]+?)/(?:index\.html)?"[^>]*>([^<]+)</a>'
)
_PROCEEDING_RE = re.compile(r"\b([A-Z]{2,3}-\d{3}-\d{4})\b")
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
_REGDOCS_RE = re.compile(r'<a href="(https://apps\.cer-rec\.gc\.ca/REGDOCS/Item/Filing/[^"]+)">([^<]+)</a>')
_BACKGROUND_RE = re.compile(r'<h2 id="background">[^<]*</h2>\s*<p>(.*?)</p>', re.S)
_MODIFIED_RE = re.compile(r'<time property="dateModified">([^<]+)</time>')
_TAG_RE = re.compile(r"<[^>]+>")


def _clean(text: str) -> str:
    return _TAG_RE.sub(" ", text).replace("&ndash;", "–").replace("&nbsp;", " ").strip()


def discover_application_links(index_html: str) -> list[dict[str, str]]:
    """Pair every application link with the nearest preceding <h2>/<h3>
    heading — works for both the `<details><h3>` current-index markup and
    the plain `<h2>` archive-page markup without special-casing either."""
    headings = [(m.start(), _clean(m.group(1))) for m in _HEADING_RE.finditer(index_html)]

    def heading_for(pos: int) -> str | None:
        best = None
        for hpos, htext in headings:
            if hpos <= pos:
                best = htext
            else:
                break
        return best

    out: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    for m in _LINK_RE.finditer(index_html):
        path, title = m.group(1), _clean(m.group(2))
        if path in seen_paths:
            continue
        seen_paths.add(path)
        out.append({"path": path, "title": title, "category": heading_for(m.start()) or ""})
    return out


def _parse_application_page(content: bytes, path: str, category: str) -> dict[str, Any] | None:
    html = content.decode("utf-8", errors="replace")
    h1 = _H1_RE.search(html)
    title = _clean(h1.group(1)) if h1 else None
    if not title:
        return None
    regdocs = _REGDOCS_RE.search(html)
    background = _BACKGROUND_RE.search(html)
    modified = _MODIFIED_RE.search(html)
    proceeding = _PROCEEDING_RE.search(title)

    applicant = title.split("–")[0].split("-")[0].strip() if ("–" in title or "-" in title) else title

    return {
        "path": path,
        "title": title,
        "applicant": applicant,
        "category": category,
        "status": "decision_issued" if "decision issued" in category.lower() else "active",
        "proceeding_number": proceeding.group(1) if proceeding else None,
        "regdocs_url": regdocs.group(1) if regdocs else None,
        "regdocs_filing_number": regdocs.group(2) if regdocs else None,
        "description": _clean(background.group(1)) if background else None,
        "modified_date": modified.group(1).strip() if modified else None,
        "url": f"{BASE}{APPLICATION_PATH_PREFIX}{path}/",
    }


async def discover_all_links() -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    async with httpx.AsyncClient(timeout=30, headers=_HEADERS, follow_redirects=True) as client:
        for url in INDEX_URLS:
            r = await client.get(url)
            r.raise_for_status()
            for entry in discover_application_links(r.text):
                if entry["path"] not in seen:
                    seen.add(entry["path"])
                    out.append(entry)
    return out


async def backfill_cer_applications(*, links: list[dict[str, str]] | None = None,
                                     max_pages: int | None = None,
                                     rate_limit_s: float = RATE_LIMIT_S) -> BackfillSummary:
    """Backfill every discovered application/project detail page, sorted by
    path for resumable `<=`-checkpoint walking (see module docstring)."""
    if links is None:
        links = await discover_all_links()
    by_path = {entry["path"]: entry for entry in links}
    cursors = sorted(by_path)

    async with httpx.AsyncClient(timeout=45, headers=_HEADERS, follow_redirects=True) as client:
        async def fetch_page(path: str) -> PageResult:
            url = f"{BASE}{APPLICATION_PATH_PREFIX}{path}/"
            r = await client.get(url)
            if r.status_code == 404:
                return PageResult(content=b"", filename=f"cer_{path.replace('/', '_')}_404.html",
                                   is_empty=False, source_url=url)
            r.raise_for_status()
            content = r.content
            row = _parse_application_page(content, path, by_path[path]["category"])
            return PageResult(content=content, filename=f"cer_{path.replace('/', '_')}.html",
                               parsed_rows=[row] if row else [], is_empty=False, source_url=url)

        summary = await walk_cursor_pages(
            category=CATEGORY, source_id=SOURCE_ID, cursors=cursors, fetch_page=fetch_page,
            stop_on_empty=False, max_pages=max_pages, rate_limit_s=rate_limit_s,
        )
    log.info("cer_applications_backfill_done", pages=summary.pages_fetched,
              skipped=summary.pages_skipped_already_done, gaps=len(summary.gaps),
              applications=len(summary.rows), stopped=summary.stopped_reason)
    return summary


def _application_record_type(row: dict[str, Any]) -> str:
    if row["status"] == "decision_issued":
        return "cer_decision"
    if row.get("proceeding_number"):
        return "cer_proceeding"
    return "cer_application"


async def fetch_cer_application_records(max_rows: int = 0) -> list[dict[str, Any]]:
    """Registry-facing wrapper for `pipeline/connectors.py`. The full set
    (~120 applications, one HTTP request each at 0.5s) completes in about a
    minute, so unlike `fetch_iaac_project_records`, `max_rows=0` here means
    genuinely uncapped — consistent with the rest of this registry."""
    summary = await backfill_cer_applications(max_pages=max_rows or None)
    out: list[dict[str, Any]] = []
    for row in summary.rows:
        applicant = row.get("applicant")
        out.append({
            "source": "cer_applications", "record_type": _application_record_type(row),
            "external_id": f"cer-{row['path']}",
            "entity_name": applicant, "canonical_name": normalize(applicant) if applicant else None,
            "title": row["title"], "summary": (row.get("description") or "")[:4000] or None,
            "full_text": f"{row['title']}\n{row.get('description') or ''}"[:6000],
            "event_date": row.get("modified_date"), "amount": None, "province": None,
            "url": row["url"], "raw": row,
        })
    return out
