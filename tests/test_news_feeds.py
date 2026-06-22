"""Tests for the Canadian-news connector (Goal 10).

Distinct from tests/test_*feed*.py-style coverage of pipeline/feeds.py
(government department feeds): these exercise the licence-aware behaviour
specific to pipeline/news_feeds.py — never storing full text, and dropping
any item whose per-entry <rights> tag doesn't match the reviewed licence.
"""
from __future__ import annotations

import pytest

import pipeline.raw_storage as rs
from pipeline.news_feeds import NewsFeedDef, fetch_news_feed_records


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


_FEED = NewsFeedDef(
    id="test_news_feed",
    name="Test News Feed",
    publisher="Test Publisher",
    url="https://example.test/news/articles.atom",
    license_name="Creative Commons Attribution-NoDerivatives 4.0 (CC BY-ND)",
    terms_url="https://example.test/republishing-guidelines",
    required_rights_text="Licensed as Creative Commons – attribution, no derivatives.",
)

_ATOM_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Test News Feed</title>
  <entry>
    <title>{title}</title>
    <id>https://example.test/articles/{slug}</id>
    <link rel="alternate" href="https://example.test/articles/{slug}"/>
    <published>2026-06-20T12:00:00Z</published>
    <updated>2026-06-20T12:00:00Z</updated>
    <summary type="html">&lt;p&gt;{summary}&lt;/p&gt;</summary>
    <rights>{rights}</rights>
    <author><name>{author}</name></author>
  </entry>
</feed>
"""

_RIGHTS_OK = "Licensed as Creative Commons – attribution, no derivatives."


@pytest.mark.asyncio
async def test_accepted_item_never_carries_full_text(httpx_mock):
    body = _ATOM_TEMPLATE.format(
        title="A real headline", slug="a-real-headline",
        summary="A short publisher-supplied excerpt about the headline topic.",
        rights=_RIGHTS_OK, author="Jane Doe, Professor of Something",
    ).encode()
    httpx_mock.add_response(url=_FEED.url, content=body, headers={"content-type": "application/atom+xml"})

    rows = await fetch_news_feed_records(_FEED)
    assert len(rows) == 1
    row = rows[0]
    assert row["title"] == "A real headline"
    assert row["full_text"] is None
    assert row["summary"] == "A short publisher-supplied excerpt about the headline topic."
    assert row["entity_name"] == "Test Publisher"
    assert row["url"] == "https://example.test/articles/a-real-headline"
    assert row["raw"]["author"] == "Jane Doe, Professor of Something"
    assert row["raw"]["rights"] == _RIGHTS_OK


@pytest.mark.asyncio
async def test_item_with_mismatched_rights_is_dropped(httpx_mock):
    body = _ATOM_TEMPLATE.format(
        title="Syndicated wire content", slug="syndicated-wire-content",
        summary="This entry is not actually covered by the reviewed licence.",
        rights="All rights reserved.", author="Wire Service",
    ).encode()
    httpx_mock.add_response(url=_FEED.url, content=body, headers={"content-type": "application/atom+xml"})

    rows = await fetch_news_feed_records(_FEED)
    assert rows == []


@pytest.mark.asyncio
async def test_html_response_is_rejected_not_parsed_as_garbage(httpx_mock):
    httpx_mock.add_response(url=_FEED.url, content=b"<html><body>not a feed</body></html>",
                             headers={"content-type": "text/html"})
    rows = await fetch_news_feed_records(_FEED)
    assert rows == []


@pytest.mark.asyncio
async def test_raw_feed_is_archived_for_provenance(httpx_mock):
    body = _ATOM_TEMPLATE.format(
        title="A real headline", slug="a-real-headline",
        summary="excerpt", rights=_RIGHTS_OK, author="Jane Doe",
    ).encode()
    httpx_mock.add_response(url=_FEED.url, content=body, headers={"content-type": "application/atom+xml"})

    await fetch_news_feed_records(_FEED)
    saved = list((rs.RAW_DIR / "canadian-news" / _FEED.id).rglob("*.xml"))
    assert len(saved) == 1
