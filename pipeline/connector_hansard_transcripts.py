"""Full House of Commons Hansard transcripts — every spoken word, first-party.

This is NOT `pipeline/connector_house_votes.py`'s sibling source (recorded
votes) and NOT the existing `hansard_search` job (a thin, third-party
openparliament.ca keyword sweep — ~500-char excerpts around sector keywords,
landing in `HansardMention`). This connector pulls ourcommons.ca's own
per-sitting Hansard XML directly and parses every Intervention into its own
row in the new `hansard_speeches` table — the full text of everything said,
not a keyword-matched excerpt.

URL pattern (confirmed live 2026-06-26, not assumed):

    GET https://www.ourcommons.ca/Content/House/{parliament}{session}/Debates/{NNN}/HAN{NNN}-E.XML

`{parliament}{session}` is the two numbers concatenated with no separator
(e.g. parliament 45 session 1 -> "451"); `{NNN}` is the zero-padded 3-digit
sitting number. A sitting that doesn't exist returns **HTTP 302** (redirecting
to `/ErrorPage/...`), never a 404 — confirmed by probing sitting 999 of every
session below. That's the exact "unbounded cursor walked oldest->newest,
stop on first empty page" shape `pipeline/api_paginator.py` was built for,
same as `connector_house_votes.py`'s vote-number walk.

robots.txt (checked live) disallows `/Embed/`, `/ErrorPage/`,
`/ParlDataWidgets/`, `/PublicationSearch/`, `/Search/` (and lowercase
variants) — `/Content/` and `/documentviewer/` are both unrestricted, so
this connector's direct content fetches and the citation URLs it builds
(documentviewer, used for the `url` column) are both compliant.

Structured Hansard XML only exists from the 38th Parliament (2004) onward —
parliaments 35-37 only published PDF Hansard, confirmed by probing sitting 1
of (37,1): HTTP 302 (doesn't exist), vs. (38,1): HTTP 200. Pre-2004 transcripts
are out of scope for this connector; a PDF-text-extraction pipeline would be
a separate, much heavier effort.

Sessions with confirmed real sitting-XML data as of 2026-06-26 (probed live,
sitting 1 of every (parliament, session) pair from 37 through 45): (38,1),
(39,1), (39,2), (40,1), (40,2), (40,3), (41,1), (41,2), (42,1), (43,1),
(43,2), (44,1), (45,1) returned HTTP 200. (37,1), (42,2), (44,2), (45,2)
returned HTTP 302 at sitting 1 — those parliament/session combinations never
sat (consistent with connector_house_votes.py's independent finding that
(42,2), (44,2), (45,2) have no recorded votes either).

Each session gets its own checkpoint (source_id="hansard_transcripts_p{P}s{S}"),
exactly per connector_house_votes.py's documented reasoning: a shared
checkpoint silently breaks when sessions are walked out of chronological
order or as a subset.

Crash-resilience departs from connector_house_votes.py's pattern on purpose:
house_votes is small enough (a few thousand rows total) to buffer entirely in
memory and let the caller write it to the DB once, at the end. Hansard at
full scale is not — a process crash partway through a multi-hour, many-
hundred-thousand-row backfill must not lose everything already fetched. So
the DB insert + commit for a sitting's parsed rows happens *inside*
`_fetch_sitting_page`, before it returns to `walk_cursor_pages` — which only
advances (and persists) that sitting's checkpoint cursor after `fetch_page`
returns successfully. That ordering guarantees the checkpoint can never claim
a sitting is done unless its rows already reached the DB. `PageResult.
parsed_rows` is deliberately left empty (rows are already committed) so
`BackfillSummary.rows` never buffers the full corpus in memory — row/sitting
counts are tracked via a closure-scoped counter instead, mirroring
api/scheduler.py's `_stream_load` batch-and-discard memory discipline.

A second, sitting-granularity dedup check covers the one gap that ordering
doesn't: if a crash happens *after* a sitting's rows commit but *before* its
checkpoint write lands on disk, the next run will legitimately re-fetch that
one sitting. `_fetch_sitting_page` checks for existing rows for that
(parliament, session, sitting_number) before inserting and skips re-insert if
found — one query per sitting (cheap; there are only ~5-15k sittings total
across all 13 sessions), not per row.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

import httpx
import structlog

from pipeline import raw_storage as rs
from pipeline.api_paginator import BackfillSummary, PageResult, walk_cursor_pages

log = structlog.get_logger()

CATEGORY = "parliament"
SOURCE_PREFIX = "hansard_transcripts"

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
_HEADERS = {"User-Agent": _UA, "Accept": "application/xml,text/xml"}
_SITTING_URL = "https://www.ourcommons.ca/Content/House/{parl}{sess}/Debates/{n:03d}/HAN{n:03d}-E.XML"
_DOC_VIEWER_URL = "https://www.ourcommons.ca/documentviewer/en/{parliament}-{session}/house/sitting-{sitting}/hansard"

# Confirmed live 2026-06-26 by probing sitting 1 of every (parliament, session)
# pair from 37 through 45 — see module docstring.
SESSIONS: list[tuple[int, int]] = [
    (38, 1), (39, 1), (39, 2), (40, 1), (40, 2), (40, 3), (41, 1), (41, 2),
    (42, 1), (43, 1), (43, 2), (44, 1), (45, 1),
]


def session_source_id(parliament: int, session: int) -> str:
    return f"{SOURCE_PREFIX}_p{parliament}s{session}"


def _collapse_ws(text: str) -> str:
    return " ".join(text.split())


def _text(el: ET.Element | None) -> str:
    if el is None:
        return ""
    return _collapse_ws("".join(el.itertext()))


def parse_sitting_xml(content: bytes, parliament: int, session: int, sitting_number: int) -> list[dict[str, Any]]:
    """Parse one sitting's Hansard XML into a flat, document-ordered list of
    speech rows shaped for `HansardSpeech`. Captures every `Intervention`
    (Debate/Question/Answer/Interjection) plus standalone `ProceduralText`
    notes (bill stage announcements etc. that have no PersonSpeaking) — but
    NOT the copies of `ProceduralText` nested inside an Intervention's own
    `Content` (those are already captured as part of that intervention's
    text; double-counting them would duplicate content). The discriminator,
    confirmed by direct structural inspection of real sitting XML: a
    standalone `ProceduralText` is a direct child of `SubjectOfBusiness`; a
    nested one's parent chain runs through `Content`.

    Document order matters here, not nesting depth: a `Timestamp` or
    `SubjectOfBusinessTitle`/`OrderOfBusinessTitle` heading always precedes
    the interventions it applies to in `root.iter()`'s traversal order, even
    though structurally those interventions are several levels deeper (under
    `SubjectOfBusinessContent`) — confirmed live, not assumed. So a single
    linear `root.iter()` pass with "most recently seen heading/timestamp"
    state is sufficient; no parent-tracking is needed for headings.
    """
    root = ET.fromstring(content)
    items = {it.attrib.get("Name"): (it.text or "").strip() for it in root.findall(".//ExtractedItem")}
    y, m, d = items.get("MetaDateNumYear"), items.get("MetaDateNumMonth"), items.get("MetaDateNumDay")
    sitting_date = f"{y}-{m}-{d}" if y and m and d else None
    doc_url = _DOC_VIEWER_URL.format(parliament=parliament, session=session, sitting=sitting_number)

    # Single pass to know each element's parent — the only way to tell a
    # standalone ProceduralText from one nested inside an Intervention's
    # Content without re-walking from the root for every candidate.
    parent_map: dict[ET.Element, ET.Element] = {c: p for p in root.iter() for c in p}

    rows: list[dict[str, Any]] = []
    current_order: str | None = None
    current_subject: str | None = None
    current_time: str | None = None
    seq = 0

    for el in root.iter():
        if el.tag == "OrderOfBusinessTitle":
            current_order = _text(el) or current_order
        elif el.tag == "SubjectOfBusinessTitle":
            current_subject = _text(el) or current_subject
        elif el.tag == "Timestamp":
            hr, mn = el.attrib.get("Hr"), el.attrib.get("Mn")
            if hr is not None and mn is not None:
                try:
                    current_time = f"{int(hr):02d}:{int(mn):02d}"
                except ValueError:
                    pass
        elif el.tag == "Intervention":
            person = el.find("PersonSpeaking")
            aff = person.find("Affiliation") if person is not None else None
            text = _text(el.find("Content"))
            if not text:
                continue
            seq += 1
            rows.append({
                "parliament": parliament, "session": session, "sitting_number": sitting_number,
                "sitting_date": sitting_date, "sequence": seq,
                "external_id": f"{parliament}-{session}-{sitting_number}-{seq}",
                "intervention_type": el.attrib.get("Type"),
                "subject": current_subject or current_order,
                "speaker": _text(aff) or None,
                "speaker_role": aff.attrib.get("Type") if aff is not None else None,
                "speaker_db_id": aff.attrib.get("DbId") if aff is not None else None,
                "time_of_day": current_time,
                "content": text,
                "url": doc_url,
            })
        elif el.tag == "ProceduralText":
            parent = parent_map.get(el)
            if parent is None or parent.tag != "SubjectOfBusiness":
                continue  # nested inside an Intervention's Content — already captured above
            text = _text(el)
            if not text:
                continue
            seq += 1
            rows.append({
                "parliament": parliament, "session": session, "sitting_number": sitting_number,
                "sitting_date": sitting_date, "sequence": seq,
                "external_id": f"{parliament}-{session}-{sitting_number}-{seq}",
                "intervention_type": "Procedural",
                "subject": current_subject or current_order,
                "speaker": None, "speaker_role": None, "speaker_db_id": None,
                "time_of_day": current_time,
                "content": text,
                "url": doc_url,
            })
    return rows


async def _sitting_already_loaded(parliament: int, session: int, sitting_number: int) -> bool:
    from sqlalchemy import select

    from api.database import AsyncSessionLocal
    from api.models.hansard_speech import HansardSpeech

    async with AsyncSessionLocal() as db:
        exists = (await db.execute(
            select(HansardSpeech.id).where(
                HansardSpeech.parliament == parliament,
                HansardSpeech.session == session,
                HansardSpeech.sitting_number == sitting_number,
            ).limit(1)
        )).scalar_one_or_none()
        return exists is not None


async def _insert_sitting_rows(rows: list[dict[str, Any]]) -> int:
    from api.database import AsyncSessionLocal
    from api.models.hansard_speech import HansardSpeech

    if not rows:
        return 0
    async with AsyncSessionLocal() as db:
        db.add_all(HansardSpeech(**r) for r in rows)
        await db.commit()
    return len(rows)


async def _fetch_sitting_page(client: httpx.AsyncClient, parliament: int, session: int,
                               sitting_number: int, counters: dict[str, int]) -> PageResult:
    url = _SITTING_URL.format(parl=parliament, sess=session, n=sitting_number)
    filename = f"hansard_{parliament}_{session}_{sitting_number:03d}.xml"
    r = await client.get(url)
    if r.status_code in (302, 404):
        return PageResult(content=b"", filename=filename, parsed_rows=[], is_empty=True,
                           source_url=url, already_saved=True)
    r.raise_for_status()
    content = r.content
    # Real Hansard files are served with a leading UTF-8 BOM before the XML
    # declaration (confirmed on live fixtures) — the BOM bytes aren't
    # whitespace, so the guard must tolerate them explicitly or it rejects
    # every genuine file.
    if not re.match(rb"^(\xef\xbb\xbf)?\s*<\?xml", content):
        raise ValueError(f"unexpected non-XML response for {url} (got {content[:40]!r})")

    if await _sitting_already_loaded(parliament, session, sitting_number):
        counters["sittings_skipped"] = counters.get("sittings_skipped", 0) + 1
        return PageResult(content=content, filename=filename, parsed_rows=[], is_empty=False, source_url=url)

    rows = parse_sitting_xml(content, parliament, session, sitting_number)
    inserted = await _insert_sitting_rows(rows)
    counters["rows"] = counters.get("rows", 0) + inserted
    counters["sittings"] = counters.get("sittings", 0) + 1
    return PageResult(content=content, filename=filename, parsed_rows=[], is_empty=False, source_url=url)


async def backfill_hansard(*, sessions: list[tuple[int, int]] | None = None,
                            max_pages: int | None = None,
                            rate_limit_s: float = 0.2) -> dict[str, Any]:
    """Backfill full Hansard transcripts across every session in `sessions`
    (default SESSIONS). Each session gets its own independent checkpoint
    (see module docstring). `max_pages` is a TOTAL sitting budget across
    every session in this one call, not per-session — pass None for an
    unbounded run (the standalone `scripts/run_ingest.py` path); the
    scheduled incremental job passes a bounded budget so a routine cron tick
    can't block the event loop for hours.

    Returns a summary dict (not a BackfillSummary with `.rows` populated —
    rows are committed to the DB inside `_fetch_sitting_page` as they're
    fetched, never buffered for the whole run, so the full-corpus backfill
    stays memory-flat).
    """
    sessions = sessions or SESSIONS
    counters: dict[str, int] = {}
    total_pages_fetched = 0
    total_pages_skipped = 0
    all_gaps: list[dict[str, Any]] = []
    stopped_reason = "no_cursors"

    async with httpx.AsyncClient(timeout=60, headers=_HEADERS, follow_redirects=False) as client:
        for parliament, session in sessions:
            remaining = None if max_pages is None else max(0, max_pages - total_pages_fetched)
            if remaining == 0:
                stopped_reason = "max_pages"
                break

            existing = rs.read_checkpoint(session_source_id(parliament, session))
            if existing and existing.get("status") == "complete":
                stopped_reason = "exhausted"
                continue

            async def fetch_page(sitting_number: int, _p=parliament, _s=session) -> PageResult:
                return await _fetch_sitting_page(client, _p, _s, sitting_number, counters)

            def _cursors():
                n = 1
                while True:
                    yield n
                    n += 1

            summary: BackfillSummary = await walk_cursor_pages(
                category=CATEGORY, source_id=session_source_id(parliament, session),
                cursors=_cursors(), fetch_page=fetch_page,
                stop_on_empty=True, max_pages=remaining, rate_limit_s=rate_limit_s,
            )
            total_pages_fetched += summary.pages_fetched
            total_pages_skipped += summary.pages_skipped_already_done
            all_gaps.extend(summary.gaps)
            stopped_reason = summary.stopped_reason

    result = {
        "sittings_fetched": total_pages_fetched, "sittings_skipped_already_done": total_pages_skipped,
        "rows_inserted": counters.get("rows", 0), "sittings_already_loaded": counters.get("sittings_skipped", 0),
        "gaps": all_gaps, "stopped_reason": stopped_reason,
    }
    log.info("hansard_transcripts_backfill_done", **result)
    return result
