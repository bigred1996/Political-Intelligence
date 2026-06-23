"""Citation registry — the safety mechanism between retrieval and citation.

Every call to ``search.retrieval.retrieve()`` produces a *retrieval set*: the
explicit list of (table, pk) record ids actually returned for that query.
``save_retrieval_set`` persists it (query text, timestamp, planner, embedding
metadata). ``validate_citations`` is the function any downstream AI-
interpretation layer (B2+) must call before showing a cited record to a user —
it flags any cited id that is NOT in the retrieval set, so the system can never
present a citation for a record it did not actually retrieve.
"""
from __future__ import annotations

from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.retrieval_set import RetrievalSet

RecordKey = tuple[str, str]
RecordId = tuple[Any, Any]  # (table, pk) — pk may be int (tabular) or str (slug/ULID/composite)


def _key(table: Any, pk: Any) -> RecordKey:
    return (str(table), str(pk))


async def save_retrieval_set(
    session: AsyncSession,
    query: str,
    hits: list[dict[str, Any]],
    *,
    planner: str = "fallback",
    embedding_model: str = "",
) -> RetrievalSet:
    """Persist the explicit retrieval set for one query. Returns the saved row."""
    record_ids = [[h["table"], h["pk"]] for h in hits]
    row = RetrievalSet(
        query=query,
        planner=planner,
        embedding_model=embedding_model,
        record_ids=record_ids,
        result_count=len(record_ids),
    )
    session.add(row)
    await session.commit()
    return row


async def get_retrieval_set(session: AsyncSession, retrieval_set_id: str) -> RetrievalSet | None:
    return (
        await session.execute(select(RetrievalSet).where(RetrievalSet.id == retrieval_set_id))
    ).scalar_one_or_none()


def validate_citations(
    retrieval_ids: Iterable[RecordId], cited: Iterable[RecordId],
) -> dict[str, Any]:
    """Pure check: which cited (table, pk) ids actually appear in the retrieval set.

    No DB access — callers that already have the retrieval set's record ids in
    memory (e.g. right after calling ``retrieve()``) can validate without a
    round trip. ``validate_citations_for_set`` below is the DB-backed wrapper
    for validating against a previously persisted retrieval.
    """
    allowed = {_key(t, p) for t, p in retrieval_ids}
    valid: list[RecordId] = []
    invalid: list[RecordId] = []
    for t, p in cited:
        (valid if _key(t, p) in allowed else invalid).append((t, p))
    return {"valid": valid, "invalid": invalid, "all_valid": not invalid}


async def validate_citations_for_set(
    session: AsyncSession, retrieval_set_id: str, cited: Iterable[RecordId],
) -> dict[str, Any]:
    """DB-backed validation: load the persisted retrieval set, then check citations against it.

    An unknown retrieval_set_id fails closed — every citation is rejected,
    never silently treated as valid.
    """
    cited = list(cited)
    row = await get_retrieval_set(session, retrieval_set_id)
    if row is None:
        return {"valid": [], "invalid": cited, "all_valid": False, "error": "unknown_retrieval_set"}
    return validate_citations(((rid[0], rid[1]) for rid in row.record_ids), cited)
