"""Entity normalization (Step 5 — minimal slice).

The full resolver (graph across all sources, 175k+ variant mapping) is the
technical moat and arrives later. For now `normalize()` gives a canonical form
so cross-referencing has a stable key. Always run names through this before
storing, per CLAUDE.md conventions.
"""
from __future__ import annotations

import re

# Common corporate suffixes/noise to strip for canonicalization.
_SUFFIXES = [
    "communications", "company", "companies", "corporation", "corp", "incorporated",
    "inc", "ltd", "limited", "limitee", "ltee", "llp", "lp", "co", "canada", "canadian",
    "holdings", "group", "the",
]
_SUFFIX_RE = re.compile(r"\b(" + "|".join(_SUFFIXES) + r")\b", re.IGNORECASE)
_NONWORD_RE = re.compile(r"[^a-z0-9 ]+")
_WS_RE = re.compile(r"\s+")


def normalize(name: str) -> str:
    """Return a canonical lowercase key for a company/entity name."""
    s = name.lower()
    s = _NONWORD_RE.sub(" ", s)
    s = _SUFFIX_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    return s or name.lower().strip()
