"""CRTC Decisions — replaces the dead BroadcastDecisions/TelecomDecisions RSS
feeds `pipeline.ingest.fetch_crtc_decisions` used to depend on
(config/data-sources.yaml documented both as returning an HTML 404 page
with HTTP 200 — confirmed again live 2026-06-25, unchanged). This is the
Tier-1 typed-table source (`api/models/regulation.py:TribunalDecision`,
job id `tribunal_decisions`), not a Tier-2 breadth connector — the
replacement plugs into the SAME existing job/table, not a new
`source_records` entry; see `api/scheduler.py:_run_tribunal_decisions`.

crtc.gc.ca has since restructured its decisions index; the real, working
source is the per-year decisions index `/eng/8045/d{year}.htm`, confirmed
live — each links every decision/order issued that year
(`/eng/archive/{year}/{id}.htm`) with its title inline, grouped under
category headings (Broadcasting, Telecommunications, Compliance and
Enforcement).

No per-decision date is exposed on the index page — only on each decision's
own page, via `<time property="dateModified">` — and fetching ~1,700+
individual pages just for that date is out of scope for this pass.
`decision_date` is left null, the same MVP tradeoff already accepted for
the IAAC/StatCan/Transport catalogue-level sources elsewhere in this
registry. `outcome` is recovered for free though: many titles embed their
own result inline ("... APPROVED - Request for authority to broadcast...",
"... DENIED.") — confirmed live (185 APPROVED / 33 DENIED / 7 RENEWED in a
single sampled year) — so a plain keyword scan gets a real signal other
tribunal sources have to fetch a second page for.

The index template itself changed more than once over 30 years: years
through ~2013 wrap the `<a>` across a multi-line `<p>` with an extra
`title="..."` attribute; 2014+ is a flatter single-line `<p>`. The regex
below tolerates both — it only requires "<p> <a href=...>ID</a> -" to open
the entry and the next "</p>" to close it, nothing rigid in between (same
"any non-structural tag" trick used for the Orders in Council table cells
in connector_orders_in_council.py). Years before ~1995 use a wholly
different numbering/template (e.g. "DB96-1" with no matching entries at
all under this pattern) — confirmed live that 1996 still 200s but the
regex finds zero rows; that's treated as "nothing usable", logged, and
skipped, not retried differently, since /eng/dno.htm's own index only
claims coverage back to 1995 anyway.
"""
from __future__ import annotations

import asyncio
import html
import re
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

log = structlog.get_logger()

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
_HEADERS = {"User-Agent": _UA}

BASE = "https://crtc.gc.ca"
EARLIEST_YEAR = 1995
RATE_LIMIT_S = 0.3

_SECTION_RE = re.compile(r'<h2[^>]*id="sec-[^"]*"[^>]*>(?P<label>.*?)</h2>', re.I | re.S)
_ENTRY_RE = re.compile(
    r'<p>\s*<a href="(?P<href>/eng/archive/\d{4}/[^"]+\.htm)"[^>]*>(?P<id>[^<]*)</a>\s*-\s*'
    r'(?P<title>(?:[^<]|<(?!/p\b)[^>]*>)*)</p>',
    re.I,
)
# Split a title on its first ". " or " - "/" – " — whichever comes first —
# to pull off a leading party name (e.g. "Quebecor Media Inc. – Application
# to..." or "Gowling WLG (Canada) LLP - Across Canada - Application to...").
# Best-effort only: multi-party titles ("Bell Canada Inc. and Telus... - Joint
# application") still just yield the first party, and policy-style titles
# with no leading party ("Making broadband Internet... available") yield None.
_ENTITY_SPLIT_RE = re.compile(r"\.\s+|\s+[-–]\s+")


def _clean(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _record_type(label: str) -> str:
    low = label.lower()
    if "broadcast" in low:
        return "broadcasting_decision"
    if "telecom" in low:
        return "telecom_decision"
    if "compliance" in low:
        return "compliance_enforcement"
    return "decision"


def _extract_entity(title: str) -> str | None:
    m = _ENTITY_SPLIT_RE.search(title)
    if not m:
        return None
    candidate = title[: m.start()].strip().rstrip(". ")
    if 2 <= len(candidate) <= 80 and candidate[0].isupper():
        return candidate
    return None


def _extract_outcome(title: str) -> str | None:
    up = title.upper()
    if "DENIED" in up:
        return "Denied"
    if "APPROVED" in up:
        return "Approved"
    if "RENEWED" in up:
        return "Renewed"
    return None


def parse_year_page(content: bytes, year: int) -> list[dict[str, Any]]:
    text = content.decode("utf-8", errors="replace")
    sections = [(m.start(), _record_type(_clean(m.group("label")))) for m in _SECTION_RE.finditer(text)]
    out: list[dict[str, Any]] = []
    for m in _ENTRY_RE.finditer(text):
        pos = m.start()
        record_type = "decision"
        for sec_pos, sec_type in sections:
            if sec_pos > pos:
                break
            record_type = sec_type
        out.append({
            "decision_id": m.group("id").strip(),
            "year": year,
            "record_type": record_type,
            "title": _clean(m.group("title")),
            "url": f"{BASE}{m.group('href')}",
        })
    return out


async def fetch_crtc_decisions(max_entries: int = 0, *, max_years: int = 0) -> list[dict[str, Any]]:
    """Drop-in replacement for the dead RSS-based `pipeline.ingest.fetch_crtc_decisions`
    — same output shape (`body, decision_number, title, decision_date, outcome,
    parties, summary, url`), consumed unchanged by
    `api/scheduler.py:_run_tribunal_decisions`.

    One GET per year, current year back to EARLIEST_YEAR — cheap enough
    (~32 small HTML pages) to fully re-walk every run; `_run_tribunal_decisions`
    already dedupes by (decision_number, body) before inserting, so repeated
    full walks are idempotent. `max_years` caps how many years back to walk
    (most recent first; 0 = all); `max_entries` caps total rows returned (0 = no cap).
    """
    current_year = datetime.now(timezone.utc).year
    years = list(range(current_year, EARLIEST_YEAR - 1, -1))
    if max_years:
        years = years[:max_years]

    out: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=30, headers=_HEADERS, follow_redirects=True) as client:
        for year in years:
            url = f"{BASE}/eng/8045/d{year}.htm"
            try:
                r = await client.get(url)
                r.raise_for_status()
            except httpx.HTTPError as exc:
                log.warning("crtc_year_page_failed", year=year, error=str(exc))
                await asyncio.sleep(RATE_LIMIT_S)
                continue
            rows = parse_year_page(r.content, year)
            if not rows:
                log.debug("crtc_year_page_empty", year=year)
            for row in rows:
                title = row["title"]
                out.append({
                    "body": "CRTC",
                    "decision_number": row["decision_id"],
                    "title": title[:1024],
                    "decision_date": None,
                    "outcome": _extract_outcome(title),
                    "parties": _extract_entity(title),
                    "summary": title[:1000],
                    "url": row["url"],
                })
                if max_entries and len(out) >= max_entries:
                    log.info("crtc_decisions_fetch_done", years_walked=years.index(year) + 1, count=len(out))
                    return out
            await asyncio.sleep(RATE_LIMIT_S)
    log.info("crtc_decisions_fetch_done", years_walked=len(years), count=len(out))
    return out
