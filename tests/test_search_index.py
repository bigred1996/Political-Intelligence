"""Tests for the incremental semantic-index rebuild.

Regression coverage for a real performance bug found 2026-06-21: build_index
used to re-embed the entire text corpus from scratch on every call (40+ minutes
on this host for ~24k documents), even when run after a daily ingest that only
added a handful of new rows. These tests prove the fix actually discriminates
between unchanged / new / changed / removed documents rather than e.g. always
reusing everything (which would look identical to "fast" from the outside).

No real DB or model: `_collect_documents` and `embed_texts` are monkeypatched
so this runs in milliseconds and never touches the network or ONNX.
"""
from __future__ import annotations

import asyncio
import json

import numpy as np
import search.index as index_mod


def _doc(table: str, pk: int, title: str, snippet: str = "") -> dict:
    return {
        "table": table, "pk": pk, "source": "bills", "record_type": "bill",
        "title": title, "snippet": snippet, "entity": None, "date": None,
        "amount": None, "url": None,
    }


def _fake_embed_texts(texts, batch_size=256):
    # Deterministic, distinct-per-text vectors — enough to tell embeddings apart
    # in assertions without needing the real model.
    return np.array([[float(len(t)), float(hash(t) % 97)] + [0.0] * (index_mod.DIM - 2) for t in texts], dtype="float32")


def test_build_index_embeds_new_reuses_unchanged_drops_removed(tmp_path, monkeypatch):
    asyncio.run(_scenario(tmp_path, monkeypatch))


async def _scenario(tmp_path, monkeypatch):
    monkeypatch.setattr(index_mod, "INDEX_DIR", tmp_path)
    monkeypatch.setattr(index_mod, "VECTORS_PATH", tmp_path / "vectors.npy")
    monkeypatch.setattr(index_mod, "META_PATH", tmp_path / "meta.json")
    monkeypatch.setattr(index_mod, "embed_texts", _fake_embed_texts)
    index_mod._cache.update(vectors=None, meta=None, mtime=None)

    embed_calls: list[list[str]] = []
    real_embed = index_mod.embed_texts

    def counting_embed(texts, batch_size=256):
        embed_calls.append(list(texts))
        return real_embed(texts, batch_size=batch_size)

    monkeypatch.setattr(index_mod, "embed_texts", counting_embed)

    # --- First build: 3 fresh documents, nothing on disk yet. ---
    docs_v1 = [
        _doc("bills", 1, "Bill C-1", "first reading"),
        _doc("bills", 2, "Bill C-2", "second reading"),
        _doc("bills", 3, "Bill C-3", "royal assent"),
    ]

    async def fake_collect_v1(session):
        return docs_v1

    monkeypatch.setattr(index_mod, "_collect_documents", fake_collect_v1)

    result1 = await index_mod.build_index(session=None)
    assert result1["documents"] == 3
    assert result1["embedded"] == 3  # all new, nothing to reuse yet
    assert result1["reused"] == 0
    assert len(embed_calls) == 1 and len(embed_calls[0]) == 3

    # --- Second build: bill 1 unchanged, bill 2's text changed (new reading
    # stage), bill 3 removed entirely (e.g. dropped from the source), bill 4 is
    # new. Only 2 and 4 should hit the model; 1 should be reused; 3 should be
    # gone from the rebuilt index. ---
    docs_v2 = [
        _doc("bills", 1, "Bill C-1", "first reading"),          # unchanged
        _doc("bills", 2, "Bill C-2", "third reading"),          # changed
        _doc("bills", 4, "Bill C-4", "introduced"),             # new
    ]

    async def fake_collect_v2(session):
        return docs_v2

    monkeypatch.setattr(index_mod, "_collect_documents", fake_collect_v2)
    embed_calls.clear()

    result2 = await index_mod.build_index(session=None)
    assert result2["documents"] == 3
    assert result2["embedded"] == 2  # bill 2 (changed) + bill 4 (new)
    assert result2["reused"] == 1    # bill 1 (unchanged)
    assert len(embed_calls) == 1
    assert set(embed_calls[0]) == {"Bill C-2. third reading", "Bill C-4. introduced"}

    # Bill 3 must not appear anywhere in the rebuilt index.
    meta = json.loads((tmp_path / "meta.json").read_text())
    pks = {d["pk"] for d in meta}
    assert pks == {1, 2, 4}

    # Bill 1's vector must be byte-identical to what was embedded the first
    # time (proof it was REUSED, not recomputed from the same deterministic
    # function landing on the same value by coincidence).
    vectors = np.load(tmp_path / "vectors.npy")
    bill1_idx_v2 = next(i for i, d in enumerate(meta) if d["pk"] == 1)
    expected = _fake_embed_texts(["Bill C-1. first reading"])[0]
    assert np.array_equal(vectors[bill1_idx_v2], expected)


def test_build_index_full_forces_complete_reembed(tmp_path, monkeypatch):
    asyncio.run(_full_rebuild_scenario(tmp_path, monkeypatch))


async def _full_rebuild_scenario(tmp_path, monkeypatch):
    monkeypatch.setattr(index_mod, "INDEX_DIR", tmp_path)
    monkeypatch.setattr(index_mod, "VECTORS_PATH", tmp_path / "vectors.npy")
    monkeypatch.setattr(index_mod, "META_PATH", tmp_path / "meta.json")
    index_mod._cache.update(vectors=None, meta=None, mtime=None)

    embed_calls: list[list[str]] = []

    def counting_embed(texts, batch_size=256):
        embed_calls.append(list(texts))
        return _fake_embed_texts(texts, batch_size=batch_size)

    monkeypatch.setattr(index_mod, "embed_texts", counting_embed)

    docs = [_doc("bills", 1, "Bill C-1", "first reading")]

    async def fake_collect(session):
        return docs

    monkeypatch.setattr(index_mod, "_collect_documents", fake_collect)

    await index_mod.build_index(session=None)
    embed_calls.clear()

    # Same exact documents, but full=True must re-embed anyway (e.g. after an
    # embedding-model change, where stale-but-identical-looking text is no
    # longer safe to reuse).
    result = await index_mod.build_index(session=None, full=True)
    assert result["embedded"] == 1
    assert result["reused"] == 0
    assert len(embed_calls) == 1
