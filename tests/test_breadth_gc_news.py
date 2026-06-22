"""Regression test for the gc_news full-text cap (found auditing Goal 10).

fetch_gc_news_records used to store up to 4000 chars of summary and a
separate 6000-char full_text field per item, even though this connector's own
config/data-sources.yaml entry already claimed `full_text_storage_allowed:
false` — a real documentation/code mismatch under the same canada.ca
non-commercial-reproduction finding pipeline/feeds.py enforces everywhere
else. Fixed to a 320-char snippet with full_text always None.
"""
from __future__ import annotations

import pytest

from pipeline.breadth import fetch_gc_news_records

_LONG_SUMMARY = "Lorem ipsum dolor sit amet. " * 50  # ~1,400 chars, well past the 320-char cap

_ATOM_FEED = f"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Canada News Centre</title>
  <entry>
    <title>A government announcement</title>
    <id>https://www.canada.ca/en/news/123.html</id>
    <link rel="alternate" href="https://www.canada.ca/en/news/123.html"/>
    <published>2026-06-20T12:00:00Z</published>
    <summary type="html">&lt;p&gt;{_LONG_SUMMARY}&lt;/p&gt;</summary>
    <author><name>Department of Example</name></author>
  </entry>
</feed>
"""


@pytest.mark.asyncio
async def test_full_text_is_never_stored_and_summary_is_capped(httpx_mock):
    httpx_mock.add_response(content=_ATOM_FEED.encode(), headers={"content-type": "application/atom+xml"})

    rows = await fetch_gc_news_records(max_rows=5)
    assert len(rows) == 1
    row = rows[0]
    assert row["full_text"] is None
    assert len(row["summary"]) <= 320
    assert row["summary"] in _LONG_SUMMARY  # a true prefix/snippet, not a different transformation
