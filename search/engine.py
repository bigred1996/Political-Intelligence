"""Hybrid search engine — plan → (SQL ∪ semantic) → merge/rank → optional answer.

Flow:
  1. make_plan(q)            NL → structured plan (Claude or fallback)
  2. structured_search(...)  exact predicates across every table  (precision)
  3. semantic_search(...)    cosine over embedded text records     (meaning)
  4. merge + rank            dedup, blend scores, sort
  5. synthesize (optional)   Claude writes a cited answer from the top hits

Steps 1 and 5 use Claude when a key is present and degrade gracefully without it,
so the whole engine runs offline; the semantic half always runs (local model).
"""
from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import settings
from pipeline.entity_resolver import normalize
from search.index import semantic_search
from search.planner import make_plan
from search.sql_search import structured_search

log = structlog.get_logger()


def _key(hit: dict[str, Any]) -> tuple:
    return (hit.get("table") or hit.get("source"), hit.get("pk"))


def _merge(structured: list[dict], semantic: list[dict], limit: int) -> list[dict[str, Any]]:
    """Blend the two result sets. A record found by BOTH ranks highest."""
    by_key: dict[tuple, dict] = {}

    for h in structured:
        h = dict(h)
        h["score"] = 0.5  # base relevance for an exact predicate match
        by_key[_key(h)] = h

    for h in semantic:
        # semantic hits carry table=source_records/bills/... + pk
        k = (h.get("table"), h.get("pk"))
        if k in by_key:
            by_key[k]["score"] = round(0.5 + float(h.get("score", 0)), 4)
            by_key[k]["match"] = "both"
        else:
            hit = dict(h)
            hit["match"] = "semantic"
            hit["amount"] = h.get("amount")
            by_key[k] = hit

    merged = sorted(by_key.values(), key=lambda x: x.get("score", 0), reverse=True)
    return merged[:limit]


_ANSWER_SYSTEM = (
    "You are a Canadian political due-diligence analyst. Using ONLY the provided search "
    "results, answer the user's question concisely. Cite specific records inline as "
    "[source:title]. If the results are insufficient, say so plainly. Never invent data."
)


async def _synthesize(q: str, hits: list[dict]) -> str | None:
    if not settings.anthropic_api_key or not hits:
        return None
    try:
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        evidence = "\n".join(
            f"- [{h['source']}] {h['title']} | {h.get('snippet','')} | "
            f"date={h.get('date')} amount={h.get('amount')}"
            for h in hits[:25]
        )
        resp = await client.messages.create(
            model=settings.claude_model,
            max_tokens=700,
            system=_ANSWER_SYSTEM,
            messages=[{"role": "user", "content": f"Question: {q}\n\nSearch results:\n{evidence}"}],
        )
        return "".join(b.text for b in resp.content if b.type == "text").strip()
    except Exception as exc:
        log.warning("synthesis_failed", error=str(exc))
        return None


async def search(
    session: AsyncSession, q: str, *, limit: int = 40, answer: bool = True,
) -> dict[str, Any]:
    """Run the full hybrid pipeline for a natural-language query."""
    plan = await make_plan(q)
    canonical = normalize(plan.entity_text) if plan.entity_text else None

    structured = await structured_search(
        session,
        keywords=plan.keywords or None,
        canonical=canonical,
        entity_text=plan.entity_text,
        date_from=plan.date_from,
        date_to=plan.date_to,
        min_amount=plan.min_amount,
        sources=plan.sources,
        per_table_limit=25,
    )
    semantic = semantic_search(plan.semantic_query, k=40, sources=plan.sources)

    hits = _merge(structured, semantic, limit)
    answer_text = await _synthesize(q, hits) if answer else None

    by_source: dict[str, int] = {}
    for h in hits:
        by_source[h["source"]] = by_source.get(h["source"], 0) + 1

    return {
        "query": q,
        "plan": plan.to_dict(),
        "counts": {"structured": len(structured), "semantic": len(semantic),
                   "returned": len(hits), "by_source": by_source},
        "answer": answer_text,
        "results": hits,
    }
