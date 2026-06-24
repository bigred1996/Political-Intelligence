"""Goal B4 — Start-Diligence form + persistent workspace tests.

Hermetic, no network: `research.retrieve` is monkeypatched with scripted hits
and the planner / synthesis / interpretation providers are fakes returning
scripted tool inputs — the same approach `tests/test_research.py` uses. Real
`create_review`, `run_research`, `build_workspace`, and DB persistence run, so
the form→run linkage, tier→caps mapping, deterministic (no-model) rehydration,
facet computation, link resolution, and the failed-run path are all genuinely
exercised.
"""
from __future__ import annotations

import asyncio

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import pipeline.diligence as diligence_mod
import pipeline.interpretation as interp_mod
import pipeline.research as research_mod
from api.database import Base
from api.models.contract import Contract
from api.models.donation import Bill
from api.models.research_run import ResearchRun
from api.models.review import Review
from pipeline.ai_provider import ProviderTurn, ProviderUnavailable
from pipeline.diligence import (
    build_workspace,
    compose_seed_topic,
    create_review,
    get_review_response,
)
from pipeline.research import TIERS

# Register all model tables (mirrors tests/test_research.py).
from api.models import (  # noqa: F401
    appointment, donation, entity, grant, interpretation, ocl_registration,
    politician, regulation, report, request, research_run, retrieval_set,
    review, scheduler_log, source_record,
)


# --- scripted fakes -------------------------------------------------------

def _hit(table: str, pk, score: float = 0.9, title: str | None = None) -> dict:
    return {
        "table": table, "pk": pk, "score": score,
        "title": title or f"{table} {pk}", "record_type": "record",
        "source": table, "snippet": "", "match": "both",
        "date": None, "amount": None,
    }


def _fake_retrieve(hits: list[dict]):
    async def _retrieve(session, query, *, limit=15, balanced=False):
        return {"results": list(hits), "plan": {"planner": "fallback"}, "embedding_model": "test"}
    return _retrieve


def _good_interp_input() -> dict:
    fid = {"table": "bills", "pk": "1"}
    return {
        "source_fact": "Bill C-1 was introduced and is at second reading.",
        "interpretation": "This may reflect legislative attention to the sector.",
        "impact": "Could affect timing of related regulatory approvals.",
        "recommendation": "Ask whether the target tracks this bill.",
        "confidence": "medium",
        "evidence_limitations": "Only a small set of records was retrieved for this query.",
        "cited_record_ids": [fid],
        "claims": [{"text": "Bill C-1 was introduced.", "label": "observed", "cited_record_ids": [fid]}],
    }


class FakeInterpProvider:
    name = "fake"
    model = "fake-interp-v1"

    def __init__(self):
        self.calls = 0

    async def call(self, system, user_content) -> ProviderTurn:
        self.calls += 1
        return ProviderTurn(tool_input=_good_interp_input(), tool_use_id=f"i{self.calls}", messages=[], model=self.model)

    async def continue_call(self, system, prior, correction) -> ProviderTurn:
        self.calls += 1
        return ProviderTurn(tool_input=_good_interp_input(), tool_use_id=f"i{self.calls}", messages=[], model=self.model)


def _raise_unavailable(*a, **k):
    raise ProviderUnavailable("no key in test")


def _patch(monkeypatch, *, retrieve_hits, interp=None):
    """Keyless deterministic run: no planner, no synth provider (both raise
    Unavailable → deterministic single round + template synthesis), faked B2."""
    monkeypatch.setattr(research_mod, "retrieve", _fake_retrieve(retrieve_hits))
    monkeypatch.setattr(research_mod, "ClaudeResearchPlanner", _raise_unavailable)
    monkeypatch.setattr(research_mod, "ClaudeSynthesisProvider", _raise_unavailable)
    interp = interp or FakeInterpProvider()
    monkeypatch.setattr(interp_mod, "ClaudeInterpretationProvider", lambda *a, **k: interp)
    return interp


async def _make_db(tmp_path, name: str):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / name}", future=True)
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_maker() as session:
        session.add(Bill(
            bill_number="C-1", parliament="44-1", title_en="An Act number 1",
            status="Second reading", sponsor="Minister", introduced_date="2025-01-15",
        ))
        session.add(Contract(
            vendor_name="Acme Corp", canonical_name="acme corp", description="Consulting",
            contract_value=50_000.0, contract_date="2025-02-01", owner_org_title="Innovation Canada",
        ))
        await session.commit()
    return engine, session_maker


def _form(**over) -> dict:
    base = {
        "company": "Acme Corp", "sectors": ["telecom"], "transaction_type": "acquisition",
        "jurisdiction": "Federal", "date_from": "2024", "date_to": "2025",
        "key_concerns": "regulatory exposure", "keywords": ["spectrum"],
        "research_question": None, "depth_tier": "standard",
    }
    base.update(over)
    return base


# --- tests ----------------------------------------------------------------

def test_compose_seed_topic_is_focused_for_retrieval():
    # Research question (the analyst's explicit framing) leads when given …
    topic = compose_seed_topic(_form(research_question="What is Acme's lobbying footprint?"))
    assert topic == "What is Acme's lobbying footprint?"
    # … otherwise the company alone is the entity anchor (sector/keyword noise is
    # deliberately NOT jammed into the seed query — it collapses retrieval).
    topic2 = compose_seed_topic(_form(research_question=None))
    assert topic2 == "Acme Corp"
    assert len(compose_seed_topic(_form(company="x" * 800)) ) <= 500


def test_submit_creates_one_review_and_one_run_at_chosen_tier(tmp_path, monkeypatch):
    asyncio.run(_submit(tmp_path, monkeypatch))


async def _submit(tmp_path, monkeypatch):
    engine, session_maker = await _make_db(tmp_path, "submit.db")
    _patch(monkeypatch, retrieve_hits=[_hit("bills", 1)])
    async with session_maker() as session:
        resp = await create_review(session, _form(depth_tier="deep"))

        n_reviews = (await session.execute(select(func.count()).select_from(Review))).scalar_one()
        n_runs = (await session.execute(select(func.count()).select_from(ResearchRun))).scalar_one()

    assert n_reviews == 1 and n_runs == 1, "exactly one Review and one run"
    assert resp["review"]["status"] == "ready"
    assert resp["review"]["depth_tier"] == "deep"
    assert resp["review"]["research_run_id"] == resp["run"]["id"]
    # tier flowed form → B3 → stored caps
    assert (resp["run"]["max_rounds"], resp["run"]["max_interpretations"]) == TIERS["deep"]
    await engine.dispose()


def test_workspace_rehydrates_with_no_model_calls(tmp_path, monkeypatch):
    asyncio.run(_rehydrate(tmp_path, monkeypatch))


async def _rehydrate(tmp_path, monkeypatch):
    engine, session_maker = await _make_db(tmp_path, "rehydrate.db")
    interp = _patch(monkeypatch, retrieve_hits=[_hit("bills", 1), _hit("contracts", 1)])
    async with session_maker() as session:
        created = await create_review(session, _form())
        calls_after_create = interp.calls
        run_count_1 = (await session.execute(select(func.count()).select_from(ResearchRun))).scalar_one()

        # Two reloads — must call no model and create no new run.
        r1 = await get_review_response(session, created["review"]["id"])
        r2 = await get_review_response(session, created["review"]["id"])
        run_count_2 = (await session.execute(select(func.count()).select_from(ResearchRun))).scalar_one()

    assert interp.calls == calls_after_create, "rehydration must call no model"
    assert run_count_1 == run_count_2 == 1, "rehydration must not create a new run"
    assert r1["run"]["id"] == r2["run"]["id"] == created["run"]["id"], "same workspace on reload"
    assert len(r1["workspace"]["findings"]) == len(r2["workspace"]["findings"])
    await engine.dispose()


def test_insufficient_evidence_renders_empty_workspace(tmp_path, monkeypatch):
    asyncio.run(_empty(tmp_path, monkeypatch))


async def _empty(tmp_path, monkeypatch):
    engine, session_maker = await _make_db(tmp_path, "empty.db")
    _patch(monkeypatch, retrieve_hits=[])  # nothing retrieved
    async with session_maker() as session:
        resp = await create_review(session, _form())

    assert resp["run"]["status"] == "insufficient_evidence"
    ws = resp["workspace"]
    assert ws["findings"] == [] and ws["source_coverage"] == []
    assert ws["facets"]["date_min"] is None and ws["facets"]["sectors"] == []
    assert resp["review"]["status"] == "ready", "a completed run with no evidence is still ready, not failed"
    await engine.dispose()


def test_facets_and_metadata_support_filtering(tmp_path, monkeypatch):
    asyncio.run(_facets(tmp_path, monkeypatch))


async def _facets(tmp_path, monkeypatch):
    engine, session_maker = await _make_db(tmp_path, "facets.db")
    _patch(monkeypatch, retrieve_hits=[_hit("bills", 1), _hit("contracts", 1)])
    async with session_maker() as session:
        resp = await create_review(session, _form())
    ws = resp["workspace"]

    findings = ws["findings"]
    assert len(findings) == 2, "both evidentiary hits interpreted into findings"
    facets = ws["facets"]
    # Multi-source facets present.
    src_keys = {s["key"] for s in facets["source_types"]}
    assert {"bills", "contracts"} <= src_keys
    assert "bill" in facets["signal_types"] and "contract" in facets["signal_types"]
    assert "medium" in facets["confidences"]
    assert "observed" in facets["interpretation_types"]
    # Every finding carries the full filterable meta.
    for f in findings:
        for k in ("date", "sector_slug", "jurisdiction", "source_type", "risk_level",
                  "confidence", "signal_type", "entity", "interpretation_types"):
            assert k in f["meta"]
    # A combined filter (source_type==bills AND confidence==medium) narrows correctly.
    narrowed = [f for f in findings
                if f["meta"]["source_type"] == "bills" and f["meta"]["confidence"] == "medium"]
    assert len(narrowed) == 1 and narrowed[0]["table"] == "bills"
    await engine.dispose()


def test_every_evidence_item_resolves_to_a_real_page(tmp_path, monkeypatch):
    asyncio.run(_links(tmp_path, monkeypatch))


async def _links(tmp_path, monkeypatch):
    engine, session_maker = await _make_db(tmp_path, "links.db")
    _patch(monkeypatch, retrieve_hits=[_hit("bills", 1), _hit("contracts", 1)])
    async with session_maker() as session:
        resp = await create_review(session, _form())
    for f in resp["workspace"]["findings"]:
        assert f["internal_url"] and f["internal_url"].startswith("/records/"), f["internal_url"]
    await engine.dispose()


def test_failed_run_is_clean_not_crash(tmp_path, monkeypatch):
    asyncio.run(_failed(tmp_path, monkeypatch))


async def _failed(tmp_path, monkeypatch):
    engine, session_maker = await _make_db(tmp_path, "failed.db")

    async def _boom(session, topic, tier):
        raise RuntimeError("provider exploded mid-run")
    monkeypatch.setattr(diligence_mod, "run_research", _boom)

    async with session_maker() as session:
        resp = await create_review(session, _form())
        # The review must persist as failed; the endpoint must return cleanly.
        again = await get_review_response(session, resp["review"]["id"])

    assert resp["review"]["status"] == "failed"
    assert "exploded" in (resp["review"]["error"] or "")
    assert resp["run"] is None
    assert resp["workspace"]["findings"] == []  # empty workspace, no crash
    assert again["review"]["status"] == "failed", "revisiting a failed review is still clean"
    await engine.dispose()


def test_build_workspace_handles_none_run():
    # Defensive: an empty/None run never crashes the projection.
    async def _run():
        engine = create_async_engine("sqlite+aiosqlite://", future=True)
        sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with sm() as session:
            ws = await build_workspace(session, {"rounds": [], "synthesis": {}})
        await engine.dispose()
        return ws
    ws = asyncio.run(_run())
    assert ws["findings"] == [] and ws["facets"]["date_min"] is None
