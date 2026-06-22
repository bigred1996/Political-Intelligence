"""IAAC project registry — row-level project + document backfill (Goal 8).

Closes the gap documented in config/data-sources.yaml's `iaac` entry and
DATA_CHECKLIST.md ("CATALOGUE ONLY — no actual project registry... needs a
dedicated connector against the IAAC project registry"): `breadth.py`'s
existing `fetch_iaac_records` only ever pulled a dead screenings CSV or, on
failure, 200 rows of open.canada.ca dataset *metadata* — never an actual
project.

The real registry (iaac-aeic.gc.ca/050/evaluations) has no API and its
search-results pagination (`?SrchPg=`) is explicitly listed in
`/robots.txt` under `Disallow: /050/*SrchPg=1*` / `*SrchPg=3*` — so it is
not crawled here. Instead this connector uses what robots.txt itself
*offers* for crawling:

    Sitemap: https://iaac-aeic.gc.ca/050/evaluations/sitemaps/projects
    Sitemap: https://iaac-aeic.gc.ca/050/evaluations/sitemaps/documents

Both are flat newline-separated URL lists (not XML `<urlset>` despite the
"sitemap" name — confirmed live, not assumed). The projects sitemap is the
complete project index: 6,389 project URLs as of 2026-06-22. Each project
page (`/proj/{ref}`) carries a clean `<meta name="..." content="...">`
block (Proponent, Responsible Authority, Status, Assessment Type, Location,
Province, Modified Date) — far more reliable than scraping the visible
dashboard markup — plus a "Key documents" list and a "Comment periods"
list, each `<a href=.../document/{id}>title</a><span class="label...">
date or date-range</span>`, which together ARE this project's document
inventory (per Goal 8's done-when: "a local raw record and a document
inventory").

robots.txt sets `Crawl-delay: 5` for general bots (the well-behaved-bot
allowlist with a 2s delay is Google/Bing/OpenAI/Anthropic-style crawlers
specifically, which this connector does not claim to be) — `RATE_LIMIT_S`
honours that. At 5s/request, all 6,389 projects is ~9 hours, too long for
one call; `backfill_iaac_projects()` is checkpointed exactly like
connector_house_votes/connector_gazette_archive so repeated calls (manual
or the weekly cron) make monotonic progress without ever re-fetching a
done ref. Cursors walk the sitemap's project refs OLDEST-FIRST (ascending)
— per the cross-stream skip bug documented in connector_house_votes, a
resumable `<=`-checkpoint walk must always traverse the same fixed
direction, so this does not bias toward "most recent projects first" even
though that would be the more politically-relevant default; correctness of
resume took priority over recency bias.

The documents sitemap (50,000+ URLs, likely truncated at the standard
50k-per-sitemap-file convention) is discovered but not deep-crawled here —
visiting every document page individually at the same 5s delay would be
multiple days. Each project's own "Key documents" panel (already fetched
for free as part of its project page) is the practical per-project
document inventory; the full document sitemap is stored as a lightweight
discovery list (URL only) so it is at least locally known and resumable by
a future deeper pass, not silently ignored.
"""
from __future__ import annotations

import re
from typing import Any

import httpx
import structlog

from pipeline import raw_storage as rs
from pipeline.api_paginator import BackfillSummary, PageResult, walk_cursor_pages
from pipeline.entity_resolver import normalize

log = structlog.get_logger()

CATEGORY = "iaac"
PROJECTS_SOURCE_ID = "iaac_projects"
DOCUMENTS_SOURCE_ID = "iaac_documents_sitemap"

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
_HEADERS = {"User-Agent": _UA}

PROJECT_SITEMAP_URL = "https://iaac-aeic.gc.ca/050/evaluations/sitemaps/projects"
DOCUMENT_SITEMAP_URL = "https://iaac-aeic.gc.ca/050/evaluations/sitemaps/documents"
PROJECT_URL = "https://iaac-aeic.gc.ca/050/evaluations/proj/{ref}"

# robots.txt: "User-agent: *  Crawl-delay: 5" — this connector is a general
# bot, not one of the specifically-allowlisted 2s-delay crawlers.
RATE_LIMIT_S = 5.0

_PROJ_REF_RE = re.compile(r"/proj/(\d+)")
_DOC_ID_RE = re.compile(r"/document/(\d+)")
_META_RE = re.compile(r'<meta name="([^"]+)" content="([^"]*)"\s*/?>')
# Key documents use an unquoted href; comment periods use a quoted one —
# both real, both seen live — so the quote is optional in the pattern.
_DOC_ENTRY_RE = re.compile(
    r'<a href=["\']?/050/evaluations/document/(\d+)["\']?>([^<]+)</a>\s*'
    r'<span class="label[^"]*">([^<]+)</span>'
)
# A comment-period's label is a date RANGE ("... to ... - Open/Closed");
# a key document's label is a single date. That distinction, not which
# list it physically sits in, is what classifies each match below.
_DATE_RANGE_RE = re.compile(r"\bto\b.*-\s*(Open|Closed)", re.IGNORECASE)


async def fetch_sitemap_urls(url: str) -> list[str]:
    """Fetch one of IAAC's flat-text sitemaps. Saves the raw response."""
    async with httpx.AsyncClient(timeout=60, headers=_HEADERS, follow_redirects=True) as c:
        r = await c.get(url)
        r.raise_for_status()
        content = r.content
    rs.save_raw(CATEGORY, "iaac_sitemaps", url.rsplit("/", 1)[-1] + ".txt", content, source_url=url)
    return [line.strip() for line in content.decode("utf-8", errors="replace").splitlines() if line.strip()]


def _project_refs_from_sitemap(urls: list[str]) -> list[int]:
    refs: list[int] = []
    for u in urls:
        m = _PROJ_REF_RE.search(u)
        if m:
            refs.append(int(m.group(1)))
    return sorted(set(refs))


def _parse_project_page(content: bytes, ref: int) -> dict[str, Any] | None:
    html = content.decode("utf-8", errors="replace")
    meta: dict[str, str] = {}
    for key, val in _META_RE.findall(html):
        meta.setdefault(key, val)  # first occurrence wins (e.g. first Location/Province pair)
    title = meta.get("Project Name") or meta.get("dcterms.title")
    if not title:
        return None

    documents: list[dict[str, str]] = []
    comment_periods: list[dict[str, str]] = []
    for doc_id, doc_title, label in _DOC_ENTRY_RE.findall(html):
        label = label.strip()
        entry = {"document_id": doc_id, "title": doc_title.strip(), "label": label,
                  "url": f"https://iaac-aeic.gc.ca/050/evaluations/document/{doc_id}"}
        if _DATE_RANGE_RE.search(label):
            comment_periods.append(entry)
        else:
            documents.append(entry)

    return {
        "reference_number": ref,
        "title": title.strip(),
        "description": (meta.get("description") or "").strip() or None,
        "proponent": meta.get("Proponent"),
        "responsible_authority": meta.get("Responsible Authority"),
        "location": meta.get("Location"),
        "province": meta.get("Province"),
        "project_type": meta.get("Project Type"),
        "assessment_type": meta.get("Assessment Type"),
        "status": meta.get("Status"),
        "start_date": (meta.get("Assessment Start Date") or "")[:10] or None,
        "modified_date": meta.get("Modified Date"),
        "documents": documents,
        "comment_periods": comment_periods,
        "url": PROJECT_URL.format(ref=ref),
    }


async def _fetch_project(client: httpx.AsyncClient, ref: int) -> PageResult:
    url = PROJECT_URL.format(ref=ref)
    r = await client.get(url)
    if r.status_code == 404:
        # A withdrawn/renumbered project, not "no more data" — refs are a
        # fixed finite set from the sitemap, not an open-ended sequence, so
        # this must not be treated as a walk terminator (see stop_on_empty
        # below).
        return PageResult(content=b"", filename=f"proj_{ref}_404.html", is_empty=False, source_url=url)
    r.raise_for_status()
    content = r.content
    row = _parse_project_page(content, ref)
    return PageResult(content=content, filename=f"proj_{ref}.html", parsed_rows=[row] if row else [],
                       is_empty=False, source_url=url)


async def backfill_iaac_projects(*, refs: list[int] | None = None, max_pages: int | None = None,
                                  rate_limit_s: float = RATE_LIMIT_S) -> BackfillSummary:
    """Backfill IAAC project detail pages, oldest reference number first.

    `refs` defaults to the full live sitemap (one cheap extra request). Pass
    an explicit list to test or to bound a single call's scope; the shared
    checkpoint (`iaac_projects`) makes repeated calls cumulative regardless
    of how `max_pages` chunks them.
    """
    if refs is None:
        urls = await fetch_sitemap_urls(PROJECT_SITEMAP_URL)
        refs = _project_refs_from_sitemap(urls)
    cursors = sorted(refs)

    async with httpx.AsyncClient(timeout=45, headers=_HEADERS, follow_redirects=True) as client:
        async def fetch_page(ref: int) -> PageResult:
            return await _fetch_project(client, ref)

        summary = await walk_cursor_pages(
            category=CATEGORY, source_id=PROJECTS_SOURCE_ID, cursors=cursors,
            fetch_page=fetch_page, stop_on_empty=False, max_pages=max_pages,
            rate_limit_s=rate_limit_s,
        )
    log.info("iaac_projects_backfill_done", pages=summary.pages_fetched,
              skipped=summary.pages_skipped_already_done, gaps=len(summary.gaps),
              projects=len(summary.rows), stopped=summary.stopped_reason)
    return summary


async def discover_document_sitemap() -> list[dict[str, Any]]:
    """Lightweight discovery pass over the documents sitemap — URL + id only,
    no per-document page fetch (see module docstring on why a full
    document-level deep crawl is out of scope for this connector). Recorded
    via raw_storage as a backfill record so its coverage is visible without
    pretending it's the same as a deep per-document crawl.
    """
    urls = await fetch_sitemap_urls(DOCUMENT_SITEMAP_URL)
    doc_ids = sorted({int(m.group(1)) for u in urls if (m := _DOC_ID_RE.search(u))})
    rs.record_backfill(CATEGORY, DOCUMENTS_SOURCE_ID, row_count=len(doc_ids),
                        extraction_validated=True,
                        notes="URL-level discovery only (sitemap), no per-document page fetch")
    return [{"document_id": d, "url": f"https://iaac-aeic.gc.ca/050/evaluations/document/{d}"} for d in doc_ids]


# Full sitemap coverage is 6,389 projects at a mandatory 5s/request
# (~9 hours) — too long for one scheduled/triggered call. `max_rows=0`
# therefore does NOT mean "uncapped" here, unlike every other breadth
# connector in this registry (cer/npri/etc.) — it means "one safe chunk",
# explicitly smaller than full so a weekly cron run finishes in minutes,
# not hours; the checkpoint makes repeated calls cumulative regardless.
# Pass an explicit max_rows to control a single call's size directly.
_DEFAULT_CHUNK = 300


def _project_row_to_source_records(row: dict[str, Any]) -> list[dict[str, Any]]:
    proponent = row.get("proponent")
    out = [{
        "source": "iaac", "record_type": "iaac_project",
        "external_id": f"proj-{row['reference_number']}",
        "entity_name": proponent, "canonical_name": normalize(proponent) if proponent else None,
        "title": row["title"], "summary": (row.get("description") or "")[:4000] or None,
        "full_text": f"{row['title']}\n{row.get('description') or ''}"[:6000],
        "event_date": row.get("modified_date") or row.get("start_date"),
        "amount": None, "province": row.get("province"), "url": row["url"],
        "raw": row,
    }]
    for doc in row.get("documents", []):
        out.append({
            "source": "iaac", "record_type": "iaac_document",
            "external_id": f"doc-{doc['document_id']}",
            "entity_name": proponent, "canonical_name": normalize(proponent) if proponent else None,
            "title": doc["title"], "summary": None, "full_text": doc["title"],
            "event_date": None, "amount": None, "province": row.get("province"),
            "url": doc["url"],
            "raw": {"project_reference_number": row["reference_number"], "project_title": row["title"],
                    "label": doc["label"]},
        })
    # Comment periods were parsed into the project row (see _parse_project_page)
    # but, until now, only ever surfaced inside the project's own `raw` blob —
    # not as their own searchable/linkable records, unlike documents above.
    for cp in row.get("comment_periods", []):
        start, end, status = _parse_comment_period_label(cp["label"])
        out.append({
            "source": "iaac", "record_type": "iaac_comment_period",
            "external_id": f"cp-{cp['document_id']}",
            "entity_name": proponent, "canonical_name": normalize(proponent) if proponent else None,
            "title": cp["title"], "summary": cp["label"], "full_text": cp["title"],
            "event_date": start, "amount": None, "province": row.get("province"),
            "url": cp["url"],
            "raw": {"project_reference_number": row["reference_number"], "project_title": row["title"],
                    "label": cp["label"], "start_date": start, "end_date": end, "status": status},
        })
    return out


_COMMENT_PERIOD_DATES_RE = re.compile(
    r"([A-Za-z]+ \d{1,2},\s*\d{4})\s*to\s*([A-Za-z]+ \d{1,2},\s*\d{4})\s*-\s*(Open|Closed)",
    re.IGNORECASE,
)


def _parse_comment_period_label(label: str) -> tuple[str | None, str | None, str | None]:
    """'December 19, 2019  to  January 28, 2020 - Closed' -> ISO start/end + status."""
    m = _COMMENT_PERIOD_DATES_RE.search(re.sub(r"\s+", " ", label))
    if not m:
        return None, None, None
    start_raw, end_raw, status = m.groups()
    try:
        from datetime import datetime
        start = datetime.strptime(start_raw, "%B %d, %Y").strftime("%Y-%m-%d")
        end = datetime.strptime(end_raw, "%B %d, %Y").strftime("%Y-%m-%d")
    except ValueError:
        start = end = None
    return start, end, status.capitalize()


async def fetch_iaac_project_records(max_rows: int = 0) -> list[dict[str, Any]]:
    """Registry-facing wrapper for `pipeline/connectors.py` — see
    `_DEFAULT_CHUNK` docstring above for why `max_rows=0` is a bounded
    default here rather than "no cap"."""
    cap = max_rows if max_rows else _DEFAULT_CHUNK
    summary = await backfill_iaac_projects(max_pages=cap)
    out: list[dict[str, Any]] = []
    for row in summary.rows:
        out.extend(_project_row_to_source_records(row))
    return out
