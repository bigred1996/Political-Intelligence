"""Tests for the House of Commons votes paginated backfill (Goal 7)."""
from __future__ import annotations

import pytest

import pipeline.raw_storage as rs
from pipeline.connector_house_votes import _parse_vote_summary, backfill_votes


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


def _vote_xml(parliament: int, session: int, *, yea: int = 2, nay: int = 1) -> bytes:
    participants = []
    for i in range(yea):
        participants.append(
            f"<VoteParticipant><ParliamentNumber>{parliament}</ParliamentNumber>"
            f"<SessionNumber>{session}</SessionNumber>"
            f"<DecisionEventDateTime>2022-0{(i % 9) + 1}-15T18:45:00</DecisionEventDateTime>"
            f"<IsVoteYea>true</IsVoteYea><IsVoteNay>false</IsVoteNay><IsVotePaired>false</IsVotePaired>"
            f"<DecisionResultName>Agreed To</DecisionResultName></VoteParticipant>")
    for i in range(nay):
        participants.append(
            f"<VoteParticipant><ParliamentNumber>{parliament}</ParliamentNumber>"
            f"<SessionNumber>{session}</SessionNumber>"
            f"<DecisionEventDateTime>2022-01-15T18:45:00</DecisionEventDateTime>"
            f"<IsVoteYea>false</IsVoteYea><IsVoteNay>true</IsVoteNay><IsVotePaired>false</IsVotePaired>"
            f"<DecisionResultName>Agreed To</DecisionResultName></VoteParticipant>")
    body = "".join(participants)
    return (f'<ArrayOfVoteParticipant xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            f'xmlns:xsd="http://www.w3.org/2001/XMLSchema">{body}</ArrayOfVoteParticipant>').encode()


_EMPTY_XML = (b'<ArrayOfVoteParticipant xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
              b'xmlns:xsd="http://www.w3.org/2001/XMLSchema" />')


def test_parse_vote_summary_counts_outcomes_and_handles_empty():
    row = _parse_vote_summary(_vote_xml(45, 1, yea=3, nay=1), 45, 1, 7)
    assert row == {"parliament": 45, "session": 1, "vote_number": 7, "date": "2022-01-15",
                    "result": "Agreed To", "yea": 3, "nay": 1, "paired": 0, "total": 4}
    assert _parse_vote_summary(_EMPTY_XML, 45, 1, 999) is None


@pytest.mark.asyncio
async def test_backfill_walks_two_sessions_oldest_to_newest_and_resumes(httpx_mock):
    # Session (42,1): votes 1, 2, then empty at 3.
    httpx_mock.add_response(url="https://www.ourcommons.ca/Members/en/votes/42/1/1/XML",
                             content=_vote_xml(42, 1, yea=2, nay=0))
    httpx_mock.add_response(url="https://www.ourcommons.ca/Members/en/votes/42/1/2/XML",
                             content=_vote_xml(42, 1, yea=1, nay=1))
    httpx_mock.add_response(url="https://www.ourcommons.ca/Members/en/votes/42/1/3/XML",
                             content=_EMPTY_XML)
    # Session (43,1): vote 1, then empty at 2.
    httpx_mock.add_response(url="https://www.ourcommons.ca/Members/en/votes/43/1/1/XML",
                             content=_vote_xml(43, 1, yea=5, nay=0))
    httpx_mock.add_response(url="https://www.ourcommons.ca/Members/en/votes/43/1/2/XML",
                             content=_EMPTY_XML)

    summary = await backfill_votes(sessions=[(42, 1), (43, 1)], rate_limit_s=0)

    assert summary.pages_fetched == 3  # 2 real votes in p42s1 + 1 in p43s1
    assert [r["vote_number"] for r in summary.rows] == [1, 2, 1]
    assert [r["parliament"] for r in summary.rows] == [42, 42, 43]
    assert summary.stopped_reason == "exhausted"

    saved = sorted(p.name for p in (rs.RAW_DIR / "parliament").rglob("votes_*.xml"))
    assert saved == ["votes_42_1_1.xml", "votes_42_1_2.xml", "votes_42_1_3.xml",
                      "votes_43_1_1.xml", "votes_43_1_2.xml"]

    # Resuming with the same session list must not re-request anything — each
    # session's own checkpoint immediately reports it's already complete.
    summary2 = await backfill_votes(sessions=[(42, 1), (43, 1)], rate_limit_s=0)
    assert summary2.pages_fetched == 0
    assert summary2.stopped_reason == "exhausted"
    saved_after = sorted(p.name for p in (rs.RAW_DIR / "parliament").rglob("votes_*.xml"))
    assert saved_after == saved  # no new files from the resumed (no-op) run


@pytest.mark.asyncio
async def test_backfilling_a_newer_session_first_does_not_hide_older_unwalked_ones(httpx_mock):
    # Caught live: process the CURRENT session first (as a real operator
    # naturally would — it's the most relevant one), then come back for
    # older parliaments in a separate call. The old sort-order-based
    # pre-check treated every older session as "already done" purely
    # because it sorted before the newer one's checkpoint cursor — even
    # though zero pages had ever been fetched for it.
    httpx_mock.add_response(url="https://www.ourcommons.ca/Members/en/votes/45/1/1/XML",
                             content=_vote_xml(45, 1, yea=1, nay=0))
    httpx_mock.add_response(url="https://www.ourcommons.ca/Members/en/votes/45/1/2/XML",
                             content=_EMPTY_XML)
    summary1 = await backfill_votes(sessions=[(45, 1)], rate_limit_s=0)
    assert summary1.pages_fetched == 1

    httpx_mock.add_response(url="https://www.ourcommons.ca/Members/en/votes/42/1/1/XML",
                             content=_vote_xml(42, 1, yea=1, nay=0))
    httpx_mock.add_response(url="https://www.ourcommons.ca/Members/en/votes/42/1/2/XML",
                             content=_EMPTY_XML)
    summary2 = await backfill_votes(sessions=[(42, 1)], rate_limit_s=0)
    assert summary2.pages_fetched == 1
    assert [r["parliament"] for r in summary2.rows] == [42]


@pytest.mark.asyncio
async def test_backfill_resumes_mid_session_after_a_partial_run(httpx_mock):
    httpx_mock.add_response(url="https://www.ourcommons.ca/Members/en/votes/44/1/1/XML",
                             content=_vote_xml(44, 1, yea=1, nay=0))
    summary = await backfill_votes(sessions=[(44, 1)], max_pages=1, rate_limit_s=0)
    assert summary.pages_fetched == 1
    assert summary.stopped_reason == "max_pages"

    httpx_mock.add_response(url="https://www.ourcommons.ca/Members/en/votes/44/1/2/XML",
                             content=_vote_xml(44, 1, yea=2, nay=0))
    httpx_mock.add_response(url="https://www.ourcommons.ca/Members/en/votes/44/1/3/XML",
                             content=_EMPTY_XML)
    summary2 = await backfill_votes(sessions=[(44, 1)], rate_limit_s=0)
    assert summary2.pages_fetched == 1  # only vote 2 — vote 1 was already done
    assert summary2.pages_skipped_already_done == 1
