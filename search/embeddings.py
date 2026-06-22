"""Local embedding model wrapper.

Architecture decision: embeddings run on a LOCAL model (fastembed / BGE-small,
ONNX, CPU), never a paid API. Government corpora are large and mostly static —
paying per-token to re-embed millions of rows would be slow and expensive, and
would couple core search to an external key. A local model embeds everything
offline, for free, and makes semantic search work with no ANTHROPIC_API_KEY set.

The model is loaded lazily and cached as a module singleton so the ~90 MB ONNX
graph is initialized once per process.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

import numpy as np
import structlog

log = structlog.get_logger()

MODEL_NAME = "BAAI/bge-small-en-v1.5"
DIM = 384

# Without an explicit cache_dir, fastembed defaults to /tmp/fastembed_cache,
# which gets wiped on reboot — defeating the "one-time download" design (see
# CLAUDE.md: "Embedding model | ~/.cache/huggingface | One-time local BGE-small
# download"). Persist it where the rest of the docs say it lives.
CACHE_DIR = Path(os.getenv("FASTEMBED_CACHE_DIR", os.path.expanduser("~/.cache/huggingface")))

_model = None
_lock = threading.Lock()


def _get_model():
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                from fastembed import TextEmbedding
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                log.info("embedding_model_loading", model=MODEL_NAME, cache_dir=str(CACHE_DIR))
                _model = TextEmbedding(MODEL_NAME, cache_dir=str(CACHE_DIR))
                log.info("embedding_model_ready", model=MODEL_NAME)
    return _model


def embed_texts(texts: list[str], batch_size: int = 256) -> np.ndarray:
    """Embed a list of texts → (n, DIM) float32 array, L2-normalized."""
    if not texts:
        return np.zeros((0, DIM), dtype="float32")
    model = _get_model()
    vecs = np.array(list(model.embed(texts, batch_size=batch_size)), dtype="float32")
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vecs / norms


def embed_query(text: str) -> np.ndarray:
    """Embed a single query string → (DIM,) normalized vector."""
    return embed_texts([text])[0]
