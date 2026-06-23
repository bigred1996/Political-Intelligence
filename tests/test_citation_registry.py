"""Citation integrity tests — the core safety mechanism for Goal B1.

The rule under test: a citation that names a record id NOT present in the
retrieval set it claims to come from must always be rejected, whether checked
in-memory right after a retrieval, or against a retrieval set persisted
earlier and looked up by id (including an unknown/garbage id, which must fail
closed rather than silently validating).
"""
from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.database import Base
from pipeline.citation_registry import (
    save_retrieval_set,
    validate_citations,
    validate_citations_for_set,
)

# Register all model tables on Base.metadata (mirrors tests/test_api_smoke.py).
from api.models import (  # noqa: F401
    appointment, contract, donation, entity, grant, ocl_registration,
    politician, regulation, report, request, retrieval_set, scheduler_log, source_record,
)


def test_validate_citations_pure_rejects_id_outside_set():
    retrieval_ids = [("bills", 1), ("contracts", 7), ("politicians", "jane-doe")]
    cited = [("bills", 1), ("contracts", 999), ("politicians", "jane-doe")]

    result = validate_citations(retrieval_ids, cited)

    assert result["all_valid"] is False
    assert ("bills", 1) in result["valid"]
    assert ("politicians", "jane-doe") in result["valid"]
    assert ("contracts", 999) in result["invalid"]
    assert len(result["invalid"]) == 1


def test_validate_citations_pure_accepts_when_every_citation_is_in_set():
    retrieval_ids = [("gazette", 5), ("sectors", "energy")]
    cited = [("sectors", "energy"), ("gazette", 5)]

    result = validate_citations(retrieval_ids, cited)

    assert result["all_valid"] is True
    assert result["invalid"] == []


def test_validate_citations_for_set_rejects_id_outside_persisted_set(tmp_path):
    asyncio.run(_persisted_set_scenario(tmp_path))


async def _persisted_set_scenario(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'citations.db'}", future=True)
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_maker() as session:
        hits = [
            {"table": "bills", "pk": 1},
            {"table": "contracts", "pk": 42},
        ]
        saved = await save_retrieval_set(session, "telecom bills", hits, planner="fallback", embedding_model="test-model")
        retrieval_set_id = saved.id

    async with session_maker() as session:
        result = await validate_citations_for_set(
            session, retrieval_set_id, [("bills", 1), ("contracts", 9999)],
        )

    assert result["all_valid"] is False
    assert ("bills", 1) in result["valid"]
    assert ("contracts", 9999) in result["invalid"]
    await engine.dispose()


def test_validate_citations_for_set_unknown_id_fails_closed(tmp_path):
    asyncio.run(_unknown_set_scenario(tmp_path))


async def _unknown_set_scenario(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'citations_unknown.db'}", future=True)
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_maker() as session:
        result = await validate_citations_for_set(
            session, "does-not-exist", [("bills", 1), ("contracts", 2)],
        )

    # Fail closed: an unknown retrieval set rejects every citation, never
    # treats an unverifiable claim as valid by default.
    assert result["all_valid"] is False
    assert result["valid"] == []
    assert len(result["invalid"]) == 2
    assert result["error"] == "unknown_retrieval_set"
    await engine.dispose()
