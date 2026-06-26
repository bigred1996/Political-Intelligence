"""House of Commons recorded votes — paginated backfill (Goal 7).

ourcommons.ca's public open-data page documents OData v4 as the underlying
protocol adopted in 2015, but the actual exposed feeds for votes are XML
"export" endpoints, not a queryable $skip/$top OData service — confirmed by
direct probing (see DATA_CHECKLIST.md "Goal 7"), not assumed from the
glossary's framing. The real, verified pagination mechanism:

    GET /Members/en/votes/{parliament}/{session}/{vote_number}/XML

returns every MP's individual vote for that division (party, riding,
yea/nay/paired, decision outcome). An out-of-range vote_number returns
HTTP 200 with an empty `<ArrayOfVoteParticipant/>` — never a 404 — so
"end of session" is detected by emptiness, not status code. That's exactly
the page-walk shape pipeline/api_paginator.py was built for: an unbounded
cursor (vote_number) walked oldest→newest, stopping on the first empty page.

Sessions with confirmed real data as of 2026-06-22 (probed live, not
hardcoded from memory): (42,1), (43,1), (43,2), (44,1), (45,1) — sessions
(42,2), (44,2), (45,2) returned empty even at vote 1 and are skipped.

Each session gets its OWN checkpoint (source_id="house_votes_p{P}s{S}"),
not one shared across all of them. An earlier version shared a single
checkpoint keyed by a (parliament, session, vote_number) tuple and skipped
any cursor `<= last_cursor` — which silently assumes every call walks
sessions in one fixed, consistent order from the same starting point. That
broke live: backfilling the CURRENT session (45,1) first — the natural
thing an operator would do, it's the most relevant one — then asking for
older parliaments (42-44) afterward made every one of those sort before
(45,1)'s checkpoint cursor and get skipped as "already done", despite zero
pages ever having been fetched for them. Giving each session its own
independent checkpoint removes the cross-session comparison entirely:
there's nothing to get confused by call order or subset, and a session
already walked to its end is rediscovered as "done" in O(1) by its own
per-cursor `<=` check the moment its walk starts, however many other
sessions have or haven't been touched in between.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

import httpx
import structlog

from pipeline import raw_storage as rs
from pipeline.api_paginator import BackfillSummary, PageResult, walk_cursor_pages

log = structlog.get_logger()

CATEGORY = "parliament"
SOURCE_PREFIX = "house_votes"

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
_HEADERS = {"User-Agent": _UA, "Accept": "application/xml"}
_VOTE_URL = "https://www.ourcommons.ca/Members/en/votes/{parliament}/{session}/{vote_number}/XML"

# Confirmed live 2026-06-22 by probing vote 1 of session=1 and session=2 for
# parliaments 42-45 — sessions not listed here returned an empty array even
# at vote 1 (not yet sitting, or this parliament only ran one session).
SESSIONS: list[tuple[int, int]] = [(42, 1), (43, 1), (43, 2), (44, 1), (45, 1)]


def session_source_id(parliament: int, session: int) -> str:
    return f"{SOURCE_PREFIX}_p{parliament}s{session}"


def _parse_vote_summary(content: bytes, parliament: int, session: int, vote_number: int) -> dict[str, Any] | None:
    """One summary row per division from the per-MP XML array — counts and
    outcome, not a row per MP (the raw XML keeps that full granularity)."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return None
    participants = root.findall("VoteParticipant")
    if not participants:
        return None
    yea = sum(1 for p in participants if (p.findtext("IsVoteYea") or "").lower() == "true")
    nay = sum(1 for p in participants if (p.findtext("IsVoteNay") or "").lower() == "true")
    paired = sum(1 for p in participants if (p.findtext("IsVotePaired") or "").lower() == "true")
    first = participants[0]
    return {
        "parliament": parliament, "session": session, "vote_number": vote_number,
        "date": (first.findtext("DecisionEventDateTime") or "")[:10],
        "result": first.findtext("DecisionResultName"),
        "yea": yea, "nay": nay, "paired": paired, "total": len(participants),
    }


async def _fetch_vote_page(client: httpx.AsyncClient, parliament: int, session: int,
                            vote_number: int) -> PageResult:
    url = _VOTE_URL.format(parliament=parliament, session=session, vote_number=vote_number)
    r = await client.get(url)
    r.raise_for_status()
    content = r.content
    row = _parse_vote_summary(content, parliament, session, vote_number)
    filename = f"votes_{parliament}_{session}_{vote_number}.xml"
    return PageResult(content=content, filename=filename, parsed_rows=[row] if row else [],
                       is_empty=row is None, source_url=url)


async def backfill_votes(*, sessions: list[tuple[int, int]] | None = None,
                          max_pages: int | None = None, rate_limit_s: float = 0.05) -> BackfillSummary:
    """Backfill House of Commons recorded votes across every session in
    `sessions` (default SESSIONS). Each session is walked with its own
    independent checkpoint (see module docstring) — safe to call with any
    subset or order of sessions, in any sequence of separate invocations,
    without one session's progress hiding another's.

    `max_pages` is a TOTAL budget across every session in this one call,
    not per-session.
    """
    sessions = sessions or SESSIONS
    all_rows: list[dict[str, Any]] = []
    all_gaps: list[dict[str, Any]] = []
    total_fetched = 0
    total_skipped = 0
    cursor_start: int | None = None
    cursor_end: int | None = None
    stopped_reason = "no_cursors"

    async with httpx.AsyncClient(timeout=60, headers=_HEADERS, follow_redirects=True) as client:
        for parliament, session in sessions:
            remaining = None if max_pages is None else max(0, max_pages - total_fetched)
            if remaining == 0:
                stopped_reason = "max_pages"
                break

            # A session's own checkpoint says "complete" once it's hit its
            # natural empty terminus — skip the walk entirely rather than
            # re-fetching vote_number = (last completed) + 1 every time:
            # the per-cursor `<=` skip only covers UP TO the checkpointed
            # cursor (which IS that empty page), so without this, a resumed
            # walk would always re-probe one cursor past it live. Safe to
            # check here (unlike the old shared-checkpoint version) because
            # it only ever reads THIS session's own dedicated checkpoint.
            existing = rs.read_checkpoint(session_source_id(parliament, session))
            if existing and existing.get("status") == "complete":
                stopped_reason = "exhausted"
                continue

            async def fetch_page(vote_number: int, _p=parliament, _s=session) -> PageResult:
                return await _fetch_vote_page(client, _p, _s, vote_number)

            def _cursors():
                n = 1
                while True:
                    yield n
                    n += 1

            summary = await walk_cursor_pages(
                category=CATEGORY, source_id=session_source_id(parliament, session),
                cursors=_cursors(), fetch_page=fetch_page,
                stop_on_empty=True, max_pages=remaining, rate_limit_s=rate_limit_s,
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
    log.info("house_votes_backfill_done", pages=result.pages_fetched,
              skipped=result.pages_skipped_already_done, gaps=len(result.gaps),
              stopped=result.stopped_reason)
    return result


async def fetch_house_vote_records(max_rows: int = 0) -> list[dict[str, Any]]:
    """SourceConnector adapter — wraps backfill_votes() into source_records
    shape so this connector (built and tested, never wired) joins the
    standard Tier-2 registry instead of needing a bespoke scheduler job."""
    summary = await backfill_votes(max_pages=max_rows or None)
    out: list[dict[str, Any]] = []
    for row in summary.rows:
        parliament, session, vote_number = row["parliament"], row["session"], row["vote_number"]
        result = row.get("result") or "Unknown"
        out.append({
            "source": "house_votes",
            "record_type": "division_vote",
            "external_id": f"p{parliament}s{session}v{vote_number}",
            "entity_name": None,
            "canonical_name": None,
            "title": f"Vote #{vote_number} — Parliament {parliament}, Session {session} — {result}"[:1024],
            "summary": (f"Result: {result}. Yea: {row.get('yea', 0)}, Nay: {row.get('nay', 0)}, "
                        f"Paired: {row.get('paired', 0)}, Total: {row.get('total', 0)}."),
            "full_text": None,
            "event_date": row.get("date") or None,
            "amount": None,
            "province": None,
            "url": f"https://www.ourcommons.ca/Members/en/votes/{parliament}/{session}/{vote_number}",
            "raw": row,
        })
    log.info("house_votes_fetch_records_done", count=len(out))
    return out
