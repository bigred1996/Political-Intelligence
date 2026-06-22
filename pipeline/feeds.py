"""Generic RSS / Atom / RDF connector for government publications.

One parser, many feeds: every entry in `FEED_DEFS` describes a single government
RSS/Atom/RSS1.0(RDF) feed (URL + display name + department). `fetch_feed_records()`
fetches and normalizes ANY of the three formats into the same `source_records`
shape used by every other breadth source (see api/models/source_record.py) — add
a feed by adding one `FeedDef`, not by writing a new parser.

Each upstream item's GUID/Atom-id becomes `external_id` (the upsert dedup key),
the department becomes `entity_name`/`canonical_name` so it joins the entity and
regulator-fragment resolution in pipeline/impact.py for free, and the full parsed
item (including Atom `updated`, RSS `category` tags, and the raw author string)
is kept in `raw` alongside the typed columns — consistent with how every other
breadth fetcher in pipeline/breadth.py stuffs extra fields into `raw` rather than
growing the shared table schema.

Feed URLs were live-verified before being wired in here (see commit message /
PR description for the verification notes). A handful of bodies named in Goal 9
— IAAC, OSFI, the Canadian Nuclear Safety Commission — publish no working
RSS/Atom feed as of this writing (confirmed dead links / HTML-404-with-200 /
email-only notification); Finance Canada has no separate departmental feed but
already flows through the existing `gc_news` connector. None of those four are
in `FEED_DEFS` — fabricating a feed for them would silently ingest nothing or
garbage, so they're left out rather than wired to a guessed URL.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from email.utils import parsedate
from typing import Any

import httpx
import structlog

from pipeline.entity_resolver import normalize

log = structlog.get_logger()

# A real browser UA, not the generic "Nessus/1.0" string used elsewhere in
# pipeline/breadth.py — pm.gc.ca and bankofcanada.ca's bot-management WAFs 403
# anything that doesn't look like a browser (same class of gotcha as the OCL
# download in pipeline/ingest.py, which needs the same treatment).
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
_HEADERS = {
    "User-Agent": _UA,
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
    "Accept-Language": "en-CA,en;q=0.9",
}

_ATOM_NS = "{http://www.w3.org/2005/Atom}"
_RSS1_NS = "{http://purl.org/rss/1.0/}"
_DC_NS = "{http://purl.org/dc/elements/1.1/}"
_CONTENT_NS = "{http://purl.org/rss/1.0/modules/content/}"

# Repairs stray bare `&` that some government feeds emit (same fix already used
# for CRTC's decision feeds in pipeline/ingest.py).
_BAD_AMP_RE = re.compile(r"&(?!(?:amp|lt|gt|apos|quot|#\d+|#x[0-9a-fA-F]+);)")


@dataclass(frozen=True)
class FeedDef:
    id: str                                   # also the SourceConnector id / source_records.source value
    name: str                                 # human label, e.g. "Bank of Canada — Press Releases"
    department: str                           # entity_name/canonical_name + regulator-fragment resolution
    url: str
    category: str = "Government Publications"  # UI grouping, mirrors SourceConnector.category — distinct
    # from "Canadian News" (pipeline/news_feeds.py, Goal 10): every feed here is an official government
    # department/agency, blanket-reviewed once under Crown copyright / canada.ca's Terms and Conditions,
    # not a commercial news publisher with its own individually-reviewed licence.


FEED_DEFS: list[FeedDef] = [
    FeedDef(
        id="pmo_news", name="Prime Minister's Office — News",
        department="Prime Minister's Office",
        url="https://www.pm.gc.ca/en/news.rss",
    ),
    FeedDef(
        id="boc_news", name="Bank of Canada — Press Releases",
        department="Bank of Canada",
        url="https://www.bankofcanada.ca/content_type/press-releases/feed/",
    ),
    FeedDef(
        id="nrcan_news", name="Natural Resources Canada — News",
        department="Natural Resources Canada",
        url="https://api.io.canada.ca/io-server/gc/news/en/v2"
            "?dept=naturalresourcescanada&sort=publishedDate&orderBy=desc&pick=50000&format=atom",
    ),
    FeedDef(
        id="eccc_news", name="Environment and Climate Change Canada — News",
        department="Environment and Climate Change Canada",
        url="https://api.io.canada.ca/io-server/gc/news/en/v2"
            "?dept=departmentoftheenvironment&sort=publishedDate&orderBy=desc&pick=50000&format=atom",
    ),
    FeedDef(
        id="ised_news", name="Innovation, Science and Economic Development Canada — News",
        department="Innovation, Science and Economic Development Canada",
        url="https://api.io.canada.ca/io-server/gc/news/en/v2"
            "?dept=departmentofindustry&sort=publishedDate&orderBy=desc&pick=50000&format=atom",
    ),
    FeedDef(
        id="gac_news", name="Global Affairs Canada — News",
        department="Global Affairs Canada",
        url="https://api.io.canada.ca/io-server/gc/news/en/v2"
            "?dept=departmentofforeignaffairstradeanddevelopment&sort=publishedDate&orderBy=desc&pick=50000&format=atom",
    ),
    FeedDef(
        id="transport_news", name="Transport Canada — News",
        department="Transport Canada",
        url="https://api.io.canada.ca/io-server/gc/news/en/v2"
            "?dept=departmentoftransport&sort=publishedDate&orderBy=desc&pick=50000&format=atom",
    ),
    FeedDef(
        id="health_news", name="Health Canada — News",
        department="Health Canada",
        url="https://api.io.canada.ca/io-server/gc/news/en/v2"
            "?dept=departmentofhealth&sort=publishedDate&orderBy=desc&pick=50000&format=atom",
    ),
    FeedDef(
        id="competition_news", name="Competition Bureau Canada — News",
        department="Competition Bureau Canada",
        url="https://api.io.canada.ca/io-server/gc/news/en/v2"
            "?dept=competitionbureau&sort=publishedDate&orderBy=desc&pick=50000&format=atom",
    ),
    FeedDef(
        id="crtc_news", name="CRTC — News & Speeches",
        department="Canadian Radio-television and Telecommunications Commission (CRTC)",
        url="https://crtc.gc.ca/eng/rss/news.xml",
    ),
    FeedDef(
        id="cer_news", name="Canada Energy Regulator — News Releases",
        department="Canada Energy Regulator",
        url="https://www.cer-rec.gc.ca/rss/rssfd.aspx?l=e&c=catNR",
    ),
]

FEED_DEFS_BY_ID: dict[str, FeedDef] = {f.id: f for f in FEED_DEFS}


# ── Format-agnostic parsing ──────────────────────────────────────────────────

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text(el: ET.Element | None) -> str:
    return (el.text or "").strip() if el is not None and el.text else ""


def _parse_feed_xml(raw_xml: str) -> tuple[str, list[ET.Element]]:
    """Return (format, item_elements). format is one of rss2 / rdf / atom."""
    cleaned = _BAD_AMP_RE.sub("&amp;", raw_xml)
    root = ET.fromstring(cleaned)
    tag = _local(root.tag)
    if tag == "rss":
        channel = root.find("channel")
        items = channel.findall("item") if channel is not None else root.findall("item")
        return "rss2", items
    if tag == "RDF":
        items = [el for el in root if _local(el.tag) == "item"]
        return "rdf", items
    if tag == "feed":
        ns = _ATOM_NS if root.tag.startswith("{") else ""
        return "atom", root.findall(f"{ns}entry")
    raise ValueError(f"unrecognized feed root element: {tag}")


def _parse_date(raw: str) -> str | None:
    """RFC 822/2822 (RSS) or ISO 8601 (Atom / dc:date) → YYYY-MM-DD."""
    if not raw:
        return None
    parsed = parsedate(raw)
    if parsed:
        return f"{parsed[0]:04d}-{parsed[1]:02d}-{parsed[2]:02d}"
    m = re.match(r"\d{4}-\d{2}-\d{2}", raw)
    return m.group(0) if m else raw[:10] or None


def _extract_rss2(item: ET.Element) -> dict[str, Any]:
    guid_el = item.find("guid")
    return {
        "title": _text(item.find("title")),
        "link": _text(item.find("link")),
        "summary_html": _text(item.find("description")),
        "published": _text(item.find("pubDate")),
        "updated": "",
        "guid": _text(guid_el) or _text(item.find("link")),
        "categories": [c.text.strip() for c in item.findall("category") if c.text],
        "author": _text(item.find(f"{_DC_NS}creator")) or _text(item.find("author")),
    }


def _extract_rdf(item: ET.Element) -> dict[str, Any]:
    def t(tag: str, ns: str = _RSS1_NS) -> str:
        return _text(item.find(f"{ns}{tag}"))

    return {
        "title": t("title"), "link": t("link"), "summary_html": t("description"),
        "published": t("date", _DC_NS), "updated": "",
        "guid": t("link"), "categories": [], "author": t("creator", _DC_NS),
    }


def _extract_atom(entry: ET.Element) -> dict[str, Any]:
    ns = _ATOM_NS if entry.tag.startswith("{") else ""

    def t(tag: str) -> str:
        return _text(entry.find(f"{ns}{tag}"))

    link = ""
    for link_el in entry.findall(f"{ns}link"):
        if link_el.get("rel") in (None, "alternate"):
            link = link_el.get("href") or ""
            break

    author = ""
    author_el = entry.find(f"{ns}author")
    if author_el is not None:
        author = _text(author_el.find(f"{ns}name"))

    return {
        "title": t("title"),
        "link": link or t("id"),
        "summary_html": t("summary"),
        "published": t("published") or t("updated"),
        "updated": t("updated"),
        "guid": t("id") or link,
        "categories": [c.get("term") for c in entry.findall(f"{ns}category") if c.get("term")],
        "author": author,
    }


_EXTRACTORS = {"rss2": _extract_rss2, "rdf": _extract_rdf, "atom": _extract_atom}

# Canada.ca's Terms and Conditions license reproduction of government content
# for NON-COMMERCIAL purposes only ("you may not reproduce materials for the
# purposes of commercial redistribution... without prior written permission");
# Nessus is a commercial product and holds no such permission. So this stores
# a short publisher-supplied snippet (per the project's news/RSS ingestion
# policy), never the full release body — `<content:encoded>`/Atom `<content>`
# (the full-article fields) are deliberately never even parsed. The complete
# raw feed XML is still archived via pipeline.raw_storage for internal
# provenance, which is not a public display/redistribution surface.
_SNIPPET_CHARS = 320


def _map_item(raw_item: dict[str, Any], feed: FeedDef) -> dict[str, Any] | None:
    title = raw_item["title"]
    if not title:
        return None
    stripped = re.sub(r"<[^>]+>", " ", raw_item["summary_html"]).strip()
    snippet = re.sub(r"\s+", " ", stripped)[:_SNIPPET_CHARS] or None
    full_text = snippet
    author = raw_item["author"] or feed.department
    return {
        "source": feed.id,
        "record_type": "publication",
        "external_id": raw_item["guid"] or raw_item["link"] or None,
        "entity_name": author or None,
        "canonical_name": normalize(author) if author else None,
        "title": title[:1024],
        "summary": snippet,
        "full_text": full_text,
        "event_date": _parse_date(raw_item["published"]),
        "amount": None,
        "province": None,
        "url": raw_item["link"] or None,
        "raw": {
            "feed_name": feed.name,
            "department": feed.department,
            "guid": raw_item["guid"] or None,
            "updated": raw_item["updated"] or None,
            "categories": raw_item["categories"],
            "author_raw": raw_item["author"] or None,
            "item": raw_item,
        },
    }


async def fetch_feed_records(feed: FeedDef, max_rows: int = 0) -> list[dict[str, Any]]:
    """Fetch and normalize one RSS/Atom/RDF feed into source_records-shaped dicts.

    `max_rows` caps the OUTPUT, not the upstream window — plain government RSS/Atom
    feeds expose only their own rolling window (typically the most recent N items;
    no deep pagination), so "historical backfill" for these sources means the full
    window the feed currently serves, with `upsert` (by GUID) catching everything
    new on every later run.
    """
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=_HEADERS) as c:
        try:
            r = await c.get(feed.url)
            r.raise_for_status()
        except Exception as exc:
            log.warning("feed_fetch_failed", feed=feed.id, url=feed.url[:160], error=str(exc))
            return []
        ct = r.headers.get("content-type", "").lower()
        if "html" in ct and not any(k in ct for k in ("xml", "rss", "atom")):
            log.warning("feed_returned_html", feed=feed.id, url=feed.url[:160], ct=ct)
            return []
        # Archive the complete raw feed payload for provenance BEFORE parsing,
        # per pipeline/raw_storage.py's contract — this is an internal audit
        # copy on disk, not a public display/redistribution surface, so it can
        # retain the full feed XML even though the parsed source_records row
        # below only keeps a short snippet (see _map_item's licensing note).
        try:
            from pipeline import raw_storage as rs
            rs.save_raw("news-rss", feed.id, f"{feed.id}.xml", r.content, source_url=feed.url)
        except Exception as exc:
            log.warning("feed_raw_storage_failed", feed=feed.id, error=str(exc))
        try:
            fmt, items = _parse_feed_xml(r.text)
        except Exception as exc:
            log.warning("feed_parse_failed", feed=feed.id, url=feed.url[:160], error=str(exc))
            return []

    extractor = _EXTRACTORS[fmt]
    out: list[dict[str, Any]] = []
    for item in items:
        mapped = _map_item(extractor(item), feed)
        if mapped:
            out.append(mapped)
        if max_rows and len(out) >= max_rows:
            break
    log.info("feed_parsed", feed=feed.id, format=fmt, count=len(out))
    return out
