"""Semantic vector index over Nessus's text-bearing records.

What gets embedded (and why this subset): semantic search earns its keep on
free-text records where meaning matters — bills, gazette regulations, news,
StatCan table titles, IAAC/CER/Transport/geospatial descriptions. Purely
numeric/transactional rows (donations, full contract tables, NPRI release
quantities) are served precisely by SQL filters instead — embedding millions of
near-identical rows would be slow and add no semantic value. This keeps the
vector index in the tens-of-thousands range: fast to build on CPU, brute-force
cosine is instant, no ANN infra needed yet. (Swap to FAISS/pgvector here if the
corpus outgrows in-memory cosine.)

The index is a single flat float32 matrix + a parallel metadata list, persisted
to data/index/. Rebuilt on demand via build_index().
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import structlog
from sqlalchemy import select

from search.embeddings import DIM, embed_query, embed_texts

log = structlog.get_logger()

INDEX_DIR = Path("./data/index")
VECTORS_PATH = INDEX_DIR / "vectors.npy"
META_PATH = INDEX_DIR / "meta.json"

# Breadth sources (in source_records) that carry embeddable text.
EMBED_SOURCES = ["statcan", "iaac", "cer", "transport", "geospatial", "gc_news", "social_statements",
                 "public_statements", "cer_applications", "gazette_notices", "orders_in_council",
                 # Generic RSS/Atom/RDF government-publication feeds (Goal 9).
                 "pmo_news", "boc_news", "nrcan_news", "eccc_news", "ised_news", "gac_news",
                 "transport_news", "health_news", "competition_news", "crtc_news", "cer_news",
                 # Canadian News — commercial news publishers, separate connector category,
                 # each individually licence-reviewed (pipeline/news_feeds.py, Goal 10).
                 "conversation_ca_politics"]

_cache: dict[str, Any] = {"vectors": None, "meta": None, "mtime": None}


def _doc(table: str, pk: Any, *, source: str, title: str, text: str,
         entity: str | None, date: str | None, amount: float | None,
         url: str | None, record_type: str | None) -> dict[str, Any]:
    return {
        "table": table, "pk": pk, "source": source, "record_type": record_type,
        "title": (title or "")[:300], "snippet": (text or "")[:300],
        "entity": entity, "date": date, "amount": amount, "url": url,
    }


async def _collect_documents(session) -> list[dict[str, Any]]:
    """Pull every text-bearing record into a uniform document shape for embedding."""
    from api.models.source_record import SourceRecord
    from api.models.donation import Bill
    from api.models.regulation import GazetteEntry, TribunalDecision

    docs: list[dict[str, Any]] = []

    # Breadth sources with text
    res = await session.execute(
        select(SourceRecord).where(SourceRecord.source.in_(EMBED_SOURCES))
    )
    for r in res.scalars():
        text = " ".join(filter(None, [r.title, r.summary, r.full_text]))[:1000]
        docs.append(_doc("source_records", r.id, source=r.source, record_type=r.record_type,
                         title=r.title, text=text, entity=r.entity_name,
                         date=r.event_date, amount=r.amount, url=r.url))

    # Bills
    for b in (await session.execute(select(Bill))).scalars():
        text = " ".join(filter(None, [b.title_en, b.status, b.sponsor, b.latest_activity]))
        docs.append(_doc("bills", b.id, source="bills", record_type="bill",
                         title=f"{b.bill_number} {b.title_en or ''}".strip(), text=text,
                         entity=b.sponsor, date=b.introduced_date, amount=None, url=None))

    # Gazette regulations
    for g in (await session.execute(select(GazetteEntry))).scalars():
        text = " ".join(filter(None, [g.title, g.description, g.department]))
        docs.append(_doc("gazette_entries", g.id, source="gazette", record_type=f"gazette_{g.gazette_part}",
                         title=g.title, text=text, entity=g.department,
                         date=g.published_date, amount=None, url=g.url))

    # Tribunal decisions (CRTC etc.)
    for t in (await session.execute(select(TribunalDecision))).scalars():
        text = " ".join(filter(None, [t.title, t.summary, t.parties]))
        docs.append(_doc("tribunal_decisions", t.id, source="tribunal", record_type=t.body,
                         title=t.title, text=text, entity=t.parties,
                         date=t.decision_date, amount=None, url=t.url))

    return docs


async def build_index(session, *, full: bool = False) -> dict[str, Any]:
    """(Re)build the semantic index from the DB. Returns a summary dict.

    Incremental by default: a document's embedding only depends on its
    `f"{title}. {snippet}"` text, so any (table, pk) whose text is byte-identical
    to what's already in the on-disk index gets its existing vector reused
    instead of being re-embedded. Only new or changed documents hit the model.

    This matters at this corpus's scale: a full re-embed of ~24k documents on
    CPU took 40+ minutes (see DATA_CHECKLIST.md "search-reindex performance"),
    and this function is called synchronously after every embedded-source
    ingest — including gc_news, which runs daily and typically adds only a
    handful of new rows. Pass full=True to force a complete re-embed (e.g.
    after switching embedding models, where old vectors are no longer valid).
    """
    docs = await _collect_documents(session)
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    if not docs:
        np.save(VECTORS_PATH, np.zeros((0, DIM), dtype="float32"))
        META_PATH.write_text("[]")
        _cache.update(vectors=None, meta=None, mtime=None)
        return {"documents": 0, "embedded": 0, "reused": 0}

    texts = [f"{d['title']}. {d['snippet']}" for d in docs]

    old_vectors, old_meta = (None, None) if full else _load()
    old_lookup: dict[tuple[str, Any], tuple[int, str]] = {}
    if old_meta:
        for i, d in enumerate(old_meta):
            old_lookup[(d["table"], d["pk"])] = (i, f"{d['title']}. {d['snippet']}")

    vectors = np.zeros((len(docs), DIM), dtype="float32")
    to_embed_idx: list[int] = []
    to_embed_texts: list[str] = []
    for i, (d, text) in enumerate(zip(docs, texts)):
        old = old_lookup.get((d["table"], d["pk"]))
        if old is not None and old[1] == text:
            vectors[i] = old_vectors[old[0]]
        else:
            to_embed_idx.append(i)
            to_embed_texts.append(text)

    reused = len(docs) - len(to_embed_texts)
    log.info("index_build_start", documents=len(docs), to_embed=len(to_embed_texts), reused=reused)
    if to_embed_texts:
        new_vecs = embed_texts(to_embed_texts)
        for idx, vec in zip(to_embed_idx, new_vecs):
            vectors[idx] = vec

    np.save(VECTORS_PATH, vectors)
    META_PATH.write_text(json.dumps(docs))
    _cache.update(vectors=None, meta=None, mtime=None)  # force reload
    log.info("index_build_done", documents=len(docs), embedded=len(to_embed_texts), reused=reused, dim=vectors.shape[1])
    by_source: dict[str, int] = {}
    for d in docs:
        by_source[d["source"]] = by_source.get(d["source"], 0) + 1
    return {"documents": len(docs), "embedded": len(to_embed_texts), "reused": reused, "by_source": by_source}


def _load() -> tuple[np.ndarray | None, list[dict] | None]:
    if not VECTORS_PATH.exists() or not META_PATH.exists():
        return None, None
    mtime = VECTORS_PATH.stat().st_mtime
    if _cache["mtime"] != mtime:
        _cache["vectors"] = np.load(VECTORS_PATH)
        _cache["meta"] = json.loads(META_PATH.read_text())
        _cache["mtime"] = mtime
    return _cache["vectors"], _cache["meta"]


def semantic_search(query: str, k: int = 20, sources: list[str] | None = None) -> list[dict[str, Any]]:
    """Cosine top-k over the embedded corpus. Returns docs with a `score` field."""
    vectors, meta = _load()
    if vectors is None or len(vectors) == 0:
        return []
    qv = embed_query(query)
    scores = vectors @ qv  # both normalized → cosine
    # Over-fetch then filter by source so source filtering doesn't starve results.
    top = np.argsort(-scores)[: k * 5 if sources else k]
    out: list[dict[str, Any]] = []
    for i in top:
        d = dict(meta[i])
        if sources and d["source"] not in sources:
            continue
        d["score"] = round(float(scores[i]), 4)
        out.append(d)
        if len(out) >= k:
            break
    return out


def index_status() -> dict[str, Any]:
    vectors, meta = _load()
    if vectors is None:
        return {"built": False, "documents": 0}
    by_source: dict[str, int] = {}
    for d in meta:
        by_source[d["source"]] = by_source.get(d["source"], 0) + 1
    return {"built": True, "documents": len(meta), "by_source": by_source}
