"""Orchestrator tests for the Goal B2 interpretation layer
(`pipeline/interpretation.py`). The Claude provider is monkeypatched with a
fake that returns scripted `ProviderTurn`s — these tests are hermetic and
never make a network call, the same approach `tests/test_retrieval.py` uses
for `semantic_search`.

Covers: citation integrity end-to-end, caching (no second "model call" for an
identical finding + retrieval set), provider-failure degradation (no crash,
no fabrication), and reproducibility (stored prompt/model/output fully
reconstructs the response).
"""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import pipeline.interpretation as interp_mod
from api.database import Base
from api.models.donation import Bill
from api.models.contract import Contract
from pipeline.ai_provider import ProviderError, ProviderTurn, ProviderUnavailable
from pipeline.citation_registry import save_retrieval_set
from pipeline.interpretation import (
    FindingNotRetrievedError,
    UnknownRetrievalSetError,
    interpret_finding,
)

# Register all model tables on Base.metadata (mirrors tests/test_retrieval.py).
from api.models import (  # noqa: F401
    appointment, donation, entity, grant, interpretation, ocl_registration,
    politician, regulation, report, request, retrieval_set, scheduler_log, source_record,
)


def _good_tool_input(table: str, pk: str) -> dict:
    return {
        "source_fact": f"Bill {pk} was introduced and is at second reading.",
        "interpretation": "This may reflect increased legislative attention to the sector.",
        "impact": "Could affect timing of related regulatory approvals.",
        "recommendation": "Ask whether the target tracks this bill in its compliance program.",
        "confidence": "medium",
        "evidence_limitations": "Only a single bill record was retrieved for this query.",
        "cited_record_ids": [{"table": table, "pk": pk}],
        "claims": [{"text": f"Bill {pk} was introduced.", "label": "observed", "cited_record_ids": [{"table": table, "pk": pk}]}],
    }


def _bad_citation_tool_input(table: str, pk: str) -> dict:
    data = _good_tool_input(table, pk)
    data["cited_record_ids"].append({"table": "contracts", "pk": "999999"})
    return data


class FakeProvider:
    """Scripted provider — each `call`/`continue_call` pops the next response
    (a dict tool_input, or an Exception instance to raise) off the queue."""

    name = "fake"
    model = "fake-model-v1"
    calls = 0

    def __init__(self, script: list):
        self.script = list(script)
        self.calls = 0

    async def call(self, system: str, user_content: str) -> ProviderTurn:
        return await self._next()

    async def continue_call(self, system: str, prior, correction: str) -> ProviderTurn:
        return await self._next()

    async def _next(self) -> ProviderTurn:
        self.calls += 1
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return ProviderTurn(tool_input=item, tool_use_id=f"tool_{self.calls}", messages=[], model=self.model)


async def _make_db(tmp_path, name: str):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / name}", future=True)
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_maker() as session:
        session.add(Bill(
            bill_number="C-27", parliament="44-1", title_en="An Act respecting AI and data",
            status="Second reading", sponsor="Minister of Industry", introduced_date="2025-01-15",
        ))
        session.add(Contract(
            vendor_name="Acme Corp", canonical_name="acme corp", description="Consulting services",
            contract_value=50_000.0, contract_date="2025-02-01", owner_org_title="Innovation Canada",
        ))
        await session.commit()
    return engine, session_maker


async def _seed_retrieval_set(session_maker, hits: list[dict]) -> str:
    async with session_maker() as session:
        saved = await save_retrieval_set(session, "test query", hits, planner="fallback", embedding_model="test")
        return saved.id


def test_unknown_retrieval_set_raises(tmp_path, monkeypatch):
    asyncio.run(_unknown_set_scenario(tmp_path, monkeypatch))


async def _unknown_set_scenario(tmp_path, monkeypatch):
    engine, session_maker = await _make_db(tmp_path, "unknown.db")
    async with session_maker() as session:
        with pytest.raises(UnknownRetrievalSetError):
            await interpret_finding(session, "does-not-exist", "bills", 1)
    await engine.dispose()


def test_finding_outside_retrieval_set_is_refused_before_any_ai_call(tmp_path, monkeypatch):
    asyncio.run(_outside_set_scenario(tmp_path, monkeypatch))


async def _outside_set_scenario(tmp_path, monkeypatch):
    engine, session_maker = await _make_db(tmp_path, "outside.db")
    retrieval_set_id = await _seed_retrieval_set(session_maker, [{"table": "bills", "pk": 1}])

    fake = FakeProvider(script=[])  # would raise IndexError if ever called
    monkeypatch.setattr(interp_mod, "ClaudeInterpretationProvider", lambda *a, **k: fake)

    async with session_maker() as session:
        with pytest.raises(FindingNotRetrievedError):
            await interpret_finding(session, retrieval_set_id, "contracts", 1)
    assert fake.calls == 0, "the AI provider must never be called for a finding outside the retrieval set"
    await engine.dispose()


def test_compliant_interpretation_persists_and_cites_only_retrieved_ids(tmp_path, monkeypatch):
    asyncio.run(_compliant_scenario(tmp_path, monkeypatch))


async def _compliant_scenario(tmp_path, monkeypatch):
    engine, session_maker = await _make_db(tmp_path, "compliant.db")
    retrieval_set_id = await _seed_retrieval_set(session_maker, [
        {"table": "bills", "pk": 1}, {"table": "contracts", "pk": 1},
    ])

    fake = FakeProvider(script=[_good_tool_input("bills", "1")])
    monkeypatch.setattr(interp_mod, "ClaudeInterpretationProvider", lambda *a, **k: fake)

    async with session_maker() as session:
        result = await interpret_finding(session, retrieval_set_id, "bills", 1)

    assert result["status"] == "ok"
    assert result["generated_by"] == "fake"
    assert result["from_cache"] is False
    assert {"table": "bills", "pk": "1"} in result["cited_record_ids"]
    assert result["cited_records"][0]["internal_url"] == "/records/bills/1"
    assert fake.calls == 1
    await engine.dispose()


def test_citation_outside_retrieval_set_triggers_reprompt_and_is_logged(tmp_path, monkeypatch, caplog):
    asyncio.run(_citation_violation_scenario(tmp_path, monkeypatch))


async def _citation_violation_scenario(tmp_path, monkeypatch):
    engine, session_maker = await _make_db(tmp_path, "violation.db")
    retrieval_set_id = await _seed_retrieval_set(session_maker, [
        {"table": "bills", "pk": 1}, {"table": "contracts", "pk": 1},
    ])

    # First response cites an id outside the retrieval set; the corrected
    # second response is clean. The orchestrator must re-prompt once and
    # accept the corrected result, never the violating one.
    fake = FakeProvider(script=[_bad_citation_tool_input("bills", "1"), _good_tool_input("bills", "1")])
    monkeypatch.setattr(interp_mod, "ClaudeInterpretationProvider", lambda *a, **k: fake)

    async with session_maker() as session:
        result = await interpret_finding(session, retrieval_set_id, "bills", 1)

    assert result["status"] == "ok"
    assert fake.calls == 2, "expected exactly one re-prompt after the citation violation"
    assert {"table": "contracts", "pk": "999999"} not in result["cited_record_ids"]
    await engine.dispose()


def test_citation_violation_persisting_after_reprompt_falls_back_to_template(tmp_path, monkeypatch):
    asyncio.run(_persistent_violation_scenario(tmp_path, monkeypatch))


async def _persistent_violation_scenario(tmp_path, monkeypatch):
    engine, session_maker = await _make_db(tmp_path, "persistent_violation.db")
    retrieval_set_id = await _seed_retrieval_set(session_maker, [{"table": "bills", "pk": 1}])

    fake = FakeProvider(script=[
        _bad_citation_tool_input("bills", "1"), _bad_citation_tool_input("bills", "1"),
    ])
    monkeypatch.setattr(interp_mod, "ClaudeInterpretationProvider", lambda *a, **k: fake)

    async with session_maker() as session:
        result = await interpret_finding(session, retrieval_set_id, "bills", 1)

    assert result["status"] == "rejected"
    assert result["generated_by"] == "template_fallback"
    assert result["rejection_reason"] is not None
    assert "citation_outside_retrieval_set" in result["rejection_reason"]
    # The fallback must cite ONLY the finding itself — never fabricate or
    # carry forward the rejected citation.
    assert result["cited_record_ids"] == [{"table": "bills", "pk": "1"}]
    await engine.dispose()


def test_provider_unavailable_degrades_gracefully_without_crash(tmp_path, monkeypatch):
    asyncio.run(_unavailable_scenario(tmp_path, monkeypatch))


async def _unavailable_scenario(tmp_path, monkeypatch):
    engine, session_maker = await _make_db(tmp_path, "unavailable.db")
    retrieval_set_id = await _seed_retrieval_set(session_maker, [{"table": "bills", "pk": 1}])

    def _raise(*a, **k):
        raise ProviderUnavailable("ANTHROPIC_API_KEY not set")

    monkeypatch.setattr(interp_mod, "ClaudeInterpretationProvider", _raise)

    async with session_maker() as session:
        result = await interpret_finding(session, retrieval_set_id, "bills", 1)

    assert result["status"] == "degraded"
    assert result["generated_by"] == "template_fallback"
    assert result["confidence"] == "low"
    assert result["evidence_limitations"]
    assert "AI interpretation unavailable" in result["interpretation"]
    await engine.dispose()


def test_provider_error_during_call_degrades_gracefully(tmp_path, monkeypatch):
    asyncio.run(_provider_error_scenario(tmp_path, monkeypatch))


async def _provider_error_scenario(tmp_path, monkeypatch):
    engine, session_maker = await _make_db(tmp_path, "provider_error.db")
    retrieval_set_id = await _seed_retrieval_set(session_maker, [{"table": "bills", "pk": 1}])

    fake = FakeProvider(script=[ProviderError("upstream 529 overloaded")])
    monkeypatch.setattr(interp_mod, "ClaudeInterpretationProvider", lambda *a, **k: fake)

    async with session_maker() as session:
        result = await interpret_finding(session, retrieval_set_id, "bills", 1)

    assert result["status"] == "degraded"
    assert result["generated_by"] == "template_fallback"
    assert "provider_error" in result["rejection_reason"]
    await engine.dispose()


def test_identical_finding_and_retrieval_set_uses_cache_no_second_model_call(tmp_path, monkeypatch):
    asyncio.run(_cache_scenario(tmp_path, monkeypatch))


async def _cache_scenario(tmp_path, monkeypatch):
    engine, session_maker = await _make_db(tmp_path, "cache.db")
    retrieval_set_id = await _seed_retrieval_set(session_maker, [{"table": "bills", "pk": 1}])

    fake = FakeProvider(script=[_good_tool_input("bills", "1")])
    monkeypatch.setattr(interp_mod, "ClaudeInterpretationProvider", lambda *a, **k: fake)

    async with session_maker() as session:
        first = await interpret_finding(session, retrieval_set_id, "bills", 1)
    async with session_maker() as session:
        second = await interpret_finding(session, retrieval_set_id, "bills", 1)

    assert first["from_cache"] is False
    assert second["from_cache"] is True
    assert second["id"] == first["id"]
    assert fake.calls == 1, "a cached (finding, retrieval_set) pair must never re-call the model"
    await engine.dispose()


def test_force_refresh_bypasses_cache_and_calls_model_again(tmp_path, monkeypatch):
    asyncio.run(_force_refresh_scenario(tmp_path, monkeypatch))


async def _force_refresh_scenario(tmp_path, monkeypatch):
    engine, session_maker = await _make_db(tmp_path, "force_refresh.db")
    retrieval_set_id = await _seed_retrieval_set(session_maker, [{"table": "bills", "pk": 1}])

    fake = FakeProvider(script=[_good_tool_input("bills", "1"), _good_tool_input("bills", "1")])
    monkeypatch.setattr(interp_mod, "ClaudeInterpretationProvider", lambda *a, **k: fake)

    async with session_maker() as session:
        await interpret_finding(session, retrieval_set_id, "bills", 1)
    async with session_maker() as session:
        second = await interpret_finding(session, retrieval_set_id, "bills", 1, force_refresh=True)

    assert second["from_cache"] is False
    assert fake.calls == 2
    await engine.dispose()


def test_forged_citation_tampered_directly_into_db_row_is_dropped_on_reread(tmp_path, monkeypatch):
    """The B6 pattern, applied to B2: persist a real, compliant interpretation
    via the real write path, then hand-tamper the stored row's output JSON
    directly (bypassing interpret_finding entirely) to add an out-of-run
    citation, both top-level and on the claim. A re-read via
    get_interpretation_response must re-validate against the row's own
    retrieval_set_id and drop the forged citation — Goal B7 / G2."""
    asyncio.run(_forged_citation_scenario(tmp_path, monkeypatch))


async def _forged_citation_scenario(tmp_path, monkeypatch):
    engine, session_maker = await _make_db(tmp_path, "forged_citation.db")
    retrieval_set_id = await _seed_retrieval_set(session_maker, [
        {"table": "bills", "pk": 1}, {"table": "contracts", "pk": 1},
    ])

    fake = FakeProvider(script=[_good_tool_input("bills", "1")])
    monkeypatch.setattr(interp_mod, "ClaudeInterpretationProvider", lambda *a, **k: fake)

    async with session_maker() as session:
        result = await interp_mod.interpret_finding(session, retrieval_set_id, "bills", 1)
        interpretation_id = result["id"]

    forged = {"table": "source_records", "pk": "999999"}  # genuinely never retrieved this run
    async with session_maker() as session:
        row = await interp_mod.get_interpretation(session, interpretation_id)
        output = dict(row.output)
        output["cited_record_ids"] = [*output["cited_record_ids"], forged]
        output["claims"] = [
            {**c, "cited_record_ids": [*c["cited_record_ids"], forged]} for c in output["claims"]
        ]
        row.output = output  # reassign (not in-place mutate) so the plain JSON column persists
        await session.commit()

    async with session_maker() as session:
        reread = await interp_mod.get_interpretation_response(session, interpretation_id)

    assert forged not in reread["cited_record_ids"]
    assert {"table": "bills", "pk": "1"} in reread["cited_record_ids"]
    for c in reread["claims"]:
        assert forged not in c["cited_record_ids"]
    await engine.dispose()


def test_row_identity_tampered_outside_retrieval_set_zeroes_all_citations(tmp_path, monkeypatch):
    """A more severe tamper: the row's own (table, pk) identity is rewritten
    to something outside the retrieval set's membership. The row's own
    grounding can no longer be trusted, so every citation must be zeroed,
    not selectively filtered — Goal B7 / G2."""
    asyncio.run(_row_identity_tamper_scenario(tmp_path, monkeypatch))


async def _row_identity_tamper_scenario(tmp_path, monkeypatch):
    engine, session_maker = await _make_db(tmp_path, "row_identity_tamper.db")
    retrieval_set_id = await _seed_retrieval_set(session_maker, [{"table": "bills", "pk": 1}])

    fake = FakeProvider(script=[_good_tool_input("bills", "1")])
    monkeypatch.setattr(interp_mod, "ClaudeInterpretationProvider", lambda *a, **k: fake)

    async with session_maker() as session:
        result = await interp_mod.interpret_finding(session, retrieval_set_id, "bills", 1)
        interpretation_id = result["id"]

    async with session_maker() as session:
        row = await interp_mod.get_interpretation(session, interpretation_id)
        row.table, row.pk = "contracts", "424242"  # never a member of retrieval_set_id
        await session.commit()

    async with session_maker() as session:
        reread = await interp_mod.get_interpretation_response(session, interpretation_id)

    assert reread["cited_record_ids"] == []
    assert reread["claims"] == []
    await engine.dispose()


def test_reproducibility_record_can_be_fully_reconstructed(tmp_path, monkeypatch):
    asyncio.run(_reproducibility_scenario(tmp_path, monkeypatch))


async def _reproducibility_scenario(tmp_path, monkeypatch):
    engine, session_maker = await _make_db(tmp_path, "repro.db")
    retrieval_set_id = await _seed_retrieval_set(session_maker, [{"table": "bills", "pk": 1}])

    fake = FakeProvider(script=[_good_tool_input("bills", "1")])
    monkeypatch.setattr(interp_mod, "ClaudeInterpretationProvider", lambda *a, **k: fake)

    async with session_maker() as session:
        result = await interpret_finding(session, retrieval_set_id, "bills", 1)

    async with session_maker() as session:
        row = await interp_mod.get_interpretation(session, result["id"])

    assert row is not None
    assert row.retrieval_set_id == retrieval_set_id
    assert row.table == "bills" and row.pk == "1"
    assert row.model == "fake-model-v1"
    assert row.provider == "fake"
    assert row.contract_version == interp_mod.CONTRACT_VERSION
    assert row.system_prompt and "build_interpretation" in row.system_prompt
    assert row.user_prompt  # the exact prompt content sent
    assert row.output["source_fact"]
    assert row.created_at is not None

    async with session_maker() as session:
        rehydrated = await interp_mod.get_interpretation_response(session, result["id"])
    assert rehydrated["source_fact"] == result["source_fact"]
    assert rehydrated["cited_record_ids"] == result["cited_record_ids"]
    await engine.dispose()
