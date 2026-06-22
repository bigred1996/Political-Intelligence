"""Canadian news-publisher connector — a separate category from government
publication feeds (pipeline/feeds.py, Goal 9).

Government department feeds are blanket-reviewed once under Crown copyright /
the canada.ca Terms and Conditions. A commercial news publisher's RSS feed
carries its OWN, individually-reviewed licence, so this module keeps a
distinct registry (`NewsFeedDef`, with the licence fields baked in) and a
distinct SourceConnector category ("Canadian News") rather than reusing
`FeedDef` — mixing government press releases and actual journalism into one
"news" bucket made it impossible to tell, at a glance, which sources were
screened for COMMERCIAL reuse versus which only ever got the gov-wide
Crown-copyright review (Goal 10).

Per Tasks.md's NEWS AND RSS POLICY, a source may only be enabled here if it is
(a) publisher-provided RSS, (b) a licensed news API under an active
agreement, or (c) one whose terms explicitly permit Nessus's commercial use.
Two real reviews were done this session:

- **Global News (Corus Entertainment)**: REJECTED. corusent.com's Terms of Use
  state content may be downloaded/printed/viewed "for non-commercial use
  only", and Global News runs a separate paid "Licensing Requests" page for
  any other use — there is no syndication carve-out for RSS. Not modeled here;
  see config/data-sources.yaml `global_news_rss` for the documented finding.
- **The Conversation Canada**: APPROVED. Every Atom entry it publishes carries
  an explicit per-item `<rights>` tag reading "Licensed as Creative Commons –
  attribution, no derivatives" (CC BY-ND 4.0), and their own republishing
  guidelines confirm commercial use is permitted ("it's OK to put our articles
  on pages with ads"; you just "can't sell our material separately"). It is
  the one source enabled below.

Disabled candidates pending an actual commercial licence (CBC, CTV, Financial
Post, National Post, Globe and Mail, Toronto Star, La Presse, Le Devoir, The
Logic, The Narwhal, Canadian Press, iPolitics, The Hill Times, Policy
Options, regional/trade press, and licensed-API vendors like Factiva/
LexisNexis/Meltwater) are NOT modeled as Python objects here — they are
documentation-only rows in config/data-sources.yaml with `connector: none`,
exactly like the existing canlii/scc_official pattern. There is nothing to
schedule until one of them is actually licensed.

Even though The Conversation's licence technically permits full-article
republication, this connector still never stores full text, for two reasons
spelled out in their own guidelines:

1. "You can't systematically republish all of our articles, nor frame the
   content of our site" — a recurring connector that mirrors every item from
   the feed on every run IS systematic republication.
2. Full republication requires embedding their pageview-counter script, which
   this connector does not implement.

So `_map_item` caps to a short publisher-provided excerpt exactly like
pipeline/feeds.py, and additionally verifies each entry's own `<rights>` text
against `NewsFeedDef.required_rights_text` before accepting it — an item is
dropped rather than ingested on the assumption that the feed-level licence
review holds for every single item without checking.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import httpx
import structlog

from pipeline.entity_resolver import normalize
from pipeline.feeds import _ATOM_NS, _DC_NS, _EXTRACTORS, _HEADERS, _parse_date, _parse_feed_xml, _text

log = structlog.get_logger()


@dataclass(frozen=True)
class NewsFeedDef:
    id: str                                   # also the SourceConnector id / source_records.source value
    name: str                                 # human label
    publisher: str                            # entity_name / canonical_name — the news outlet itself
    url: str
    license_name: str                         # e.g. "Creative Commons Attribution-NoDerivatives 4.0"
    terms_url: str
    required_rights_text: str                 # exact per-item rights string every accepted entry must carry
    category: str = "Canadian News"           # UI grouping — distinct from feeds.py's "Government Publications"


NEWS_FEED_DEFS: list[NewsFeedDef] = [
    NewsFeedDef(
        id="conversation_ca_politics",
        name="The Conversation Canada — Politics",
        publisher="The Conversation Canada",
        url="https://theconversation.com/ca/politics/articles.atom",
        license_name="Creative Commons Attribution-NoDerivatives 4.0 (CC BY-ND)",
        terms_url="https://theconversation.com/ca/republishing-guidelines",
        required_rights_text="Licensed as Creative Commons – attribution, no derivatives.",
    ),
]

NEWS_FEED_DEFS_BY_ID: dict[str, NewsFeedDef] = {f.id: f for f in NEWS_FEED_DEFS}

# Publisher-supplied excerpt cap — same length policy as pipeline/feeds.py, kept
# even though this licence technically permits full text (see module docstring).
_SNIPPET_CHARS = 320


def _item_rights(item, fmt: str) -> str:
    """Per-entry rights/licence text. Atom uses <rights>; RSS2 uses <dc:rights>."""
    if fmt == "atom":
        ns = _ATOM_NS if item.tag.startswith("{") else ""
        return _text(item.find(f"{ns}rights"))
    return _text(item.find(f"{_DC_NS}rights"))


def _map_item(raw_item: dict[str, Any], rights_text: str, feed: NewsFeedDef) -> dict[str, Any] | None:
    title = raw_item["title"]
    if not title:
        return None
    if rights_text.strip() != feed.required_rights_text:
        log.warning("news_item_rights_mismatch", feed=feed.id, rights=rights_text[:120] or None)
        return None
    stripped = re.sub(r"<[^>]+>", " ", raw_item["summary_html"]).strip()
    excerpt = re.sub(r"\s+", " ", stripped)[:_SNIPPET_CHARS] or None
    return {
        "source": feed.id,
        "record_type": "news_article",
        "external_id": raw_item["guid"] or raw_item["link"] or None,
        "entity_name": feed.publisher,
        "canonical_name": normalize(feed.publisher),
        "title": title[:1024],
        "summary": excerpt,
        "full_text": None,  # never stored — see module docstring
        "event_date": _parse_date(raw_item["published"]),
        "amount": None,
        "province": None,
        "url": raw_item["link"] or None,
        "raw": {
            "publisher": feed.publisher,
            "author": raw_item["author"] or None,
            "feed_category": raw_item["categories"],
            "license": feed.license_name,
            "rights": rights_text,
            "guid": raw_item["guid"] or None,
            "item": raw_item,
        },
    }


async def fetch_news_feed_records(feed: NewsFeedDef, max_rows: int = 0) -> list[dict[str, Any]]:
    """Fetch and normalize one approved Canadian-news RSS/Atom feed.

    Reuses pipeline.feeds' format-agnostic XML parsing (same RSS2/RDF/Atom
    support) but adds a per-item licence check on top: every entry's own
    rights text must match `feed.required_rights_text` or the item is dropped,
    not just trusted because the feed-level licence page says so.
    """
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=_HEADERS) as c:
        try:
            r = await c.get(feed.url)
            r.raise_for_status()
        except Exception as exc:
            log.warning("news_feed_fetch_failed", feed=feed.id, url=feed.url[:160], error=str(exc))
            return []
        ct = r.headers.get("content-type", "").lower()
        if "html" in ct and not any(k in ct for k in ("xml", "atom", "rss")):
            log.warning("news_feed_returned_html", feed=feed.id, url=feed.url[:160], ct=ct)
            return []
        try:
            from pipeline import raw_storage as rs
            rs.save_raw("canadian-news", feed.id, f"{feed.id}.xml", r.content, source_url=feed.url)
        except Exception as exc:
            log.warning("news_feed_raw_storage_failed", feed=feed.id, error=str(exc))
        try:
            fmt, items = _parse_feed_xml(r.text)
        except Exception as exc:
            log.warning("news_feed_parse_failed", feed=feed.id, url=feed.url[:160], error=str(exc))
            return []

    extractor = _EXTRACTORS[fmt]
    out: list[dict[str, Any]] = []
    for item in items:
        mapped = _map_item(extractor(item), _item_rights(item, fmt), feed)
        if mapped:
            out.append(mapped)
        if max_rows and len(out) >= max_rows:
            break
    log.info("news_feed_parsed", feed=feed.id, format=fmt, count=len(out))
    return out
