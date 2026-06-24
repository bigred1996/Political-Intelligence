"""Goal B3 — multi-step research loop tests (`pipeline/research.py`).

Hermetic, no network: `research.retrieve` is monkeypatched with scripted hits,
and the planner / synthesis / interpretation providers are all fakes returning
scripted tool inputs — the same approach `tests/test_interpretation.py` uses.
Real `save_retrieval_set`, `interpret_finding`, and DB persistence run so the
linkage, citation validation, and reproducibility paths are genuinely exercised.

Covers every required behaviour: depth cap, interpretation call cap, out-of-run
synthesis citation rejection, pseudo-hit coverage gaps (no crash), empty
research, reproducibility from a run id, deterministic structure, and graceful
degradation on an AI failure mid-loop.
"""
from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import pipeline.interpretation as interp_mod
import pipeline.research as research_mod
from api.database import Base
from api.models.donation import Bill
from api.models.contract import Contract
from pipeline.ai_provider import ProviderError, ProviderTurn
from pipeline.research import get_research_run_response, run_research

# Register all model tables on Base.metadata (mirrors tests/test_interpretation.py).
from api.models import (  # noqa: F401
    appointment, donation, entity, grant, interpretation, ocl_registration,
    politician, regulation, report, request, research_run, retrieval_set,
    scheduler_log, source_record,
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
    """Return the same scripted hit list for any query."""
    async def _retrieve(session, query, *, limit=15, balanced=False, entity=None):  # noqa: F811
        return {
            "results": list(hits),
            "plan": {"planner": "fallback"},
            "embedding_model": "test",
        }
    return _retrieve


def _good_interp_input() -> dict:
    fid = {"table": "bills", "pk": "1"}
    return {
        "source_fact": "Bill C-27 was introduced and is at second reading.",
        "interpretation": "This may reflect legislative attention to the sector.",
        "impact": "Could affect timing of related regulatory approvals.",
        "recommendation": "Ask whether the target tracks this bill.",
        "confidence": "medium",
        "evidence_limitations": "Only a small set of records was retrieved for this query.",
        "cited_record_ids": [fid],
        "claims": [{"text": "Bill C-27 was introduced.", "label": "observed", "cited_record_ids": [fid]}],
    }


class FakeInterpProvider:
    """interpret_finding's provider — always returns a compliant contract that
    cites bills:1 (present in every retrieval set the tests build)."""

    name = "fake"
    model = "fake-interp-v1"

    def __init__(self):
        self.calls = 0

    async def call(self, system: str, user_content: str) -> ProviderTurn:
        self.calls += 1
        return ProviderTurn(tool_input=_good_interp_input(), tool_use_id=f"i{self.calls}", messages=[], model=self.model)

    async def continue_call(self, system, prior, correction) -> ProviderTurn:
        self.calls += 1
        return ProviderTurn(tool_input=_good_interp_input(), tool_use_id=f"i{self.calls}", messages=[], model=self.model)


class ScriptedToolProvider:
    """Generic planner/synthesis fake: each `call` pops the next scripted item
    (a dict tool_input, or an Exception to raise)."""

    name = "fake"
    model = "fake-research-v1"

    def __init__(self, script: list):
        self.script = list(script)
        self.calls = 0

    async def call(self, system: str, user_content: str) -> ProviderTurn:
        return await self._next()

    async def continue_call(self, system, prior, correction) -> ProviderTurn:
        return await self._next()

    async def _next(self) -> ProviderTurn:
        self.calls += 1
        item = self.script.pop(0) if self.script else self._default()
        if isinstance(item, Exception):
            raise item
        return ProviderTurn(tool_input=item, tool_use_id=f"t{self.calls}", messages=[], model=self.model)

    def _default(self):
        return {"queries": [f"gap query {self.calls}"], "material_gaps_remain": True, "rationale": "more"}


class AlwaysGapPlanner(ScriptedToolProvider):
    """Planner that forever demands another round with a fresh query."""

    async def _next(self) -> ProviderTurn:
        self.calls += 1
        return ProviderTurn(
            tool_input={"queries": [f"gap query {self.calls}"], "material_gaps_remain": True, "rationale": "more"},
            tool_use_id=f"t{self.calls}", messages=[], model=self.model,
        )


def _good_synth_input(finding=("bills", "1")) -> dict:
    fid = {"table": finding[0], "pk": finding[1]}
    return {
        "themes": [{"title": "Legislative activity", "summary": "Records cluster around one bill.",
                    "label": "observed", "finding_ids": [fid]}],
        "material_risks": [{"text": "Pending legislation may change compliance obligations.",
                            "label": "inferred", "finding_ids": [fid]}],
        "opportunities": [],
        "diligence_questions": ["Does the target monitor this bill?"],
        "overall_confidence": "medium",
        "coverage_summary": "Searched bills; donation and lobbying coverage is thin.",
    }


def _bad_synth_input() -> dict:
    data = _good_synth_input()
    data["material_risks"][0]["finding_ids"].append({"table": "contracts", "pk": "999999"})
    return data


# --- DB helpers -----------------------------------------------------------

async def _make_db(tmp_path, name: str, n_bills: int = 1):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / name}", future=True)
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_maker() as session:
        for i in range(1, n_bills + 1):
            session.add(Bill(
                bill_number=f"C-{i}", parliament="44-1", title_en=f"An Act number {i}",
                status="Second reading", sponsor="Minister", introduced_date="2025-01-15",
            ))
        session.add(Contract(
            vendor_name="Acme Corp", canonical_name="acme corp", description="Consulting",
            contract_value=50_000.0, contract_date="2025-02-01", owner_org_title="Innovation Canada",
        ))
        await session.commit()
    return engine, session_maker


def _patch(monkeypatch, *, retrieve_hits, planner=None, synth=None, interp=None):
    monkeypatch.setattr(research_mod, "retrieve", _fake_retrieve(retrieve_hits))
    if planner is None:
        monkeypatch.setattr(research_mod, "ClaudeResearchPlanner", _raise_unavailable)
    else:
        monkeypatch.setattr(research_mod, "ClaudeResearchPlanner", lambda *a, **k: planner)
    if synth is None:
        monkeypatch.setattr(research_mod, "ClaudeSynthesisProvider", _raise_unavailable)
    else:
        monkeypatch.setattr(research_mod, "ClaudeSynthesisProvider", lambda *a, **k: synth)
    interp = interp or FakeInterpProvider()
    monkeypatch.setattr(interp_mod, "ClaudeInterpretationProvider", lambda *a, **k: interp)
    return interp


def _raise_unavailable(*a, **k):
    from pipeline.ai_provider import ProviderUnavailable
    raise ProviderUnavailable("no key in test")


# --- tests ----------------------------------------------------------------

def test_depth_cap_limits_rounds_regardless_of_planner(tmp_path, monkeypatch):
    asyncio.run(_depth_cap(tmp_path, monkeypatch))


async def _depth_cap(tmp_path, monkeypatch):
    engine, session_maker = await _make_db(tmp_path, "depth.db", n_bills=1)
    planner = AlwaysGapPlanner([])  # always wants another round
    synth = ScriptedToolProvider([_good_synth_input()])
    _patch(monkeypatch, retrieve_hits=[_hit("bills", 1)], planner=planner, synth=synth)

    async with session_maker() as session:
        run = await run_research(session, "telecom regulation", "brief")  # brief = 2 rounds

    assert run["rounds_used"] == 2, "brief tier must hard-cap at 2 rounds even though planner kept demanding more"
    assert run["max_rounds"] == 2
    await engine.dispose()


def test_interpretation_call_cap_is_never_exceeded(tmp_path, monkeypatch):
    asyncio.run(_call_cap(tmp_path, monkeypatch))


async def _call_cap(tmp_path, monkeypatch):
    engine, session_maker = await _make_db(tmp_path, "callcap.db", n_bills=20)
    # One round, twenty distinct evidentiary hits — far more than the cap.
    hits = [_hit("bills", i) for i in range(1, 21)]
    synth = ScriptedToolProvider([_good_synth_input()])
    interp = FakeInterpProvider()
    _patch(monkeypatch, retrieve_hits=hits, planner=None, synth=synth, interp=interp)

    async with session_maker() as session:
        run = await run_research(session, "telecom", "brief")  # brief = 8 interpretation cap

    assert run["interpretations_used"] == 8, "must stop interpreting at the tier cap"
    assert interp.calls == 8, "the B2 provider must never be called beyond the cap"
    gaps = [g for rd in run["rounds"] for g in rd["coverage_gaps"]]
    assert any(g["type"] == "interpretation_cap_reached" for g in gaps)
    await engine.dispose()


def test_out_of_run_synthesis_citation_is_rejected(tmp_path, monkeypatch):
    asyncio.run(_out_of_run(tmp_path, monkeypatch))


async def _out_of_run(tmp_path, monkeypatch):
    engine, session_maker = await _make_db(tmp_path, "outofrun.db", n_bills=1)
    # The synthesis mixes a valid in-run citation (bills:1) with a bogus one
    # (contracts:999999, never retrieved). Validation fails, the re-prompt also
    # fails, then item-level salvage drops ONLY the bogus citation and keeps the
    # real analysis — the forged id must not survive anywhere.
    synth = ScriptedToolProvider([_bad_synth_input(), _bad_synth_input()])
    _patch(monkeypatch, retrieve_hits=[_hit("bills", 1)], planner=None, synth=synth)

    async with session_maker() as session:
        run = await run_research(session, "telecom", "brief")

    assert run["synthesis"]["generated_by"] == "claude_salvaged"
    cited = [
        (f["table"], f["pk"])
        for group in ("themes", "material_risks", "opportunities")
        for item in run["synthesis"][group]
        for f in item["findings"]
    ]
    assert ("contracts", "999999") not in cited, "an out-of-run citation must never reach the result"
    assert ("bills", "1") in cited, "the valid in-run citation must be preserved by salvage"
    assert synth.calls == 2, "expected one re-prompt before salvage"
    await engine.dispose()


def test_unsalvageable_synthesis_falls_back_to_template(tmp_path, monkeypatch):
    """When EVERY synthesis citation is out-of-run, nothing survives item-level
    salvage and the run must fall back to the deterministic placeholder."""
    asyncio.run(_unsalvageable(tmp_path, monkeypatch))


async def _unsalvageable(tmp_path, monkeypatch):
    engine, session_maker = await _make_db(tmp_path, "unsalvageable.db", n_bills=1)

    def _all_bad() -> dict:
        # Every theme/risk/opportunity cites ONLY contracts:999999 (never retrieved).
        data = _good_synth_input()
        for group in ("themes", "material_risks", "opportunities"):
            for item in data.get(group, []):
                item["finding_ids"] = [{"table": "contracts", "pk": "999999"}]
        return data

    synth = ScriptedToolProvider([_all_bad(), _all_bad()])
    _patch(monkeypatch, retrieve_hits=[_hit("bills", 1)], planner=None, synth=synth)

    async with session_maker() as session:
        run = await run_research(session, "telecom", "brief")

    assert run["synthesis"]["generated_by"] == "template_fallback"
    cited = [
        (f["table"], f["pk"])
        for group in ("themes", "material_risks", "opportunities")
        for item in run["synthesis"][group]
        for f in item["findings"]
    ]
    assert ("contracts", "999999") not in cited
    await engine.dispose()


def test_retrieved_but_uninterpreted_citation_is_rejected_at_write_time(tmp_path, monkeypatch):
    """Goal B7 / G6: a citation to a record that was genuinely retrieved this
    run, but never interpreted (cut off by the interpretation cap), has no
    corresponding row in the evidence appendix — the synthesis prompt only
    ever shows the model the interpreted set (ALLOWED_FINDING_IDS), so
    validation must reject this just as it rejects an out-of-run forgery."""
    asyncio.run(_uninterpreted_citation(tmp_path, monkeypatch))


async def _uninterpreted_citation(tmp_path, monkeypatch):
    engine, session_maker = await _make_db(tmp_path, "uninterpreted.db", n_bills=20)
    hits = [_hit("bills", i) for i in range(1, 21)]
    # bills:15 is one of the 20 retrieved hits but falls past the brief tier's
    # 8-interpretation cap, so it's retrieved without ever being interpreted.
    synth = ScriptedToolProvider([
        _good_synth_input(finding=("bills", "15")), _good_synth_input(finding=("bills", "15")),
    ])
    _patch(monkeypatch, retrieve_hits=hits, planner=None, synth=synth)

    async with session_maker() as session:
        run = await run_research(session, "telecom", "brief")  # brief = 8 interpretation cap

    assert run["interpretations_used"] == 8
    assert run["synthesis"]["generated_by"] == "template_fallback", (
        "citing a retrieved-but-uninterpreted record must be rejected, forcing fallback"
    )
    cited = [
        (f["table"], f["pk"])
        for group in ("themes", "material_risks", "opportunities")
        for item in run["synthesis"][group]
        for f in item["findings"]
    ]
    assert ("bills", "15") not in cited
    await engine.dispose()


def test_forged_content_tampered_directly_into_run_row_is_dropped_on_reread(tmp_path, monkeypatch):
    """The B6 pattern, applied to B3: after a real run completes, hand-tamper
    the persisted run row directly (bypassing run_research entirely) — inject
    a REAL interpretation that genuinely exists in the DB but belongs to a
    retrieval set never part of this run, an out-of-run coverage gap, and an
    out-of-run synthesis citation. A re-read via get_research_run_response
    must drop every forged piece — Goal B7 / G1."""
    asyncio.run(_forged_run_row_scenario(tmp_path, monkeypatch))


async def _forged_run_row_scenario(tmp_path, monkeypatch):
    from pipeline.citation_registry import save_retrieval_set

    engine, session_maker = await _make_db(tmp_path, "forged_run.db", n_bills=1)
    synth = ScriptedToolProvider([_good_synth_input()])
    _patch(monkeypatch, retrieve_hits=[_hit("bills", 1)], planner=None, synth=synth)

    async with session_maker() as session:
        run = await run_research(session, "telecom", "standard")
        run_id = run["id"]

    # A real interpretation that genuinely exists in the DB, but against a
    # retrieval set that was never part of the run above — distinct from a
    # plain nonexistent-id forgery, which the pre-existing "if i in
    # interp_by_id" guard already caught.
    async with session_maker() as session:
        other_set = await save_retrieval_set(
            session, "unrelated query", [{"table": "contracts", "pk": 1}],
            planner="fallback", embedding_model="test",
        )
        outside_interp = await interp_mod.interpret_finding(session, other_set.id, "contracts", 1)

    async with session_maker() as session:
        run_row = await research_mod.get_research_run(session, run_id)
        rounds = list(run_row.rounds or [])
        rounds[0] = {
            **rounds[0],
            "interpretation_ids": [*rounds[0]["interpretation_ids"], outside_interp["id"]],
            "coverage_gaps": [
                *rounds[0]["coverage_gaps"],
                {"type": "non_evidentiary", "table": "contracts", "pk": "1", "title": "forged gap"},
            ],
        }
        run_row.rounds = rounds

        synthesis = dict(run_row.synthesis or {})
        synthesis["material_risks"] = [
            *(synthesis.get("material_risks") or []),
            {
                "text": "Forged risk citing a record outside this run.", "label": "observed", "title": "Forged",
                "finding_ids": [{"table": "contracts", "pk": "1"}],
            },
        ]
        run_row.synthesis = synthesis
        await session.commit()

    async with session_maker() as session:
        reread = await get_research_run_response(session, run_id)

    all_interp_ids = {i["id"] for rd in reread["rounds"] for i in rd["interpretations"]}
    assert outside_interp["id"] not in all_interp_ids

    all_gaps = [(g.get("table"), g.get("pk")) for rd in reread["rounds"] for g in rd["coverage_gaps"]]
    assert ("contracts", "1") not in all_gaps

    risk_titles = [it.get("title") for it in reread["synthesis"]["material_risks"]]
    assert "Forged" not in risk_titles
    await engine.dispose()


def test_pseudo_hit_becomes_coverage_gap_without_crashing(tmp_path, monkeypatch):
    asyncio.run(_pseudo(tmp_path, monkeypatch))


async def _pseudo(tmp_path, monkeypatch):
    engine, session_maker = await _make_db(tmp_path, "pseudo.db", n_bills=1)
    hits = [_hit("politicians", "jane-doe", title="Jane Doe"), _hit("bills", 1)]
    synth = ScriptedToolProvider([_good_synth_input()])
    interp = FakeInterpProvider()
    _patch(monkeypatch, retrieve_hits=hits, planner=None, synth=synth, interp=interp)

    async with session_maker() as session:
        run = await run_research(session, "telecom", "brief")

    gaps = [g for rd in run["rounds"] for g in rd["coverage_gaps"]]
    assert any(g["type"] == "non_evidentiary" and g["table"] == "politicians" for g in gaps)
    assert interp.calls == 1, "only the evidentiary bill is interpreted, never the politician pseudo-hit"
    assert run["status"] in {"complete", "degraded"}
    await engine.dispose()


def test_empty_research_returns_clean_insufficient_evidence(tmp_path, monkeypatch):
    asyncio.run(_empty(tmp_path, monkeypatch))


async def _empty(tmp_path, monkeypatch):
    engine, session_maker = await _make_db(tmp_path, "empty.db", n_bills=1)
    _patch(monkeypatch, retrieve_hits=[], planner=None, synth=None)

    async with session_maker() as session:
        run = await run_research(session, "nonexistent topic", "standard")

    assert run["status"] == "insufficient_evidence"
    assert run["interpretations_used"] == 0
    assert run["rounds_used"] == 1, "the deterministic seed round still runs, then stops cleanly"
    assert run["synthesis"]["generated_by"] == "template_fallback"
    await engine.dispose()


def test_run_is_reproducible_from_its_id(tmp_path, monkeypatch):
    asyncio.run(_repro(tmp_path, monkeypatch))


async def _repro(tmp_path, monkeypatch):
    engine, session_maker = await _make_db(tmp_path, "repro.db", n_bills=2)
    planner = ScriptedToolProvider([{"queries": ["second round query"], "material_gaps_remain": True, "rationale": "x"},
                                    {"queries": [], "material_gaps_remain": False, "rationale": "done"}])
    synth = ScriptedToolProvider([_good_synth_input()])
    _patch(monkeypatch, retrieve_hits=[_hit("bills", 1), _hit("bills", 2)], planner=planner, synth=synth)

    async with session_maker() as session:
        run = await run_research(session, "telecom", "standard")
    run_id = run["id"]

    async with session_maker() as session:
        rehydrated = await get_research_run_response(session, run_id)

    assert rehydrated is not None
    assert rehydrated["id"] == run_id
    assert rehydrated["rounds_used"] == run["rounds_used"]
    assert len(rehydrated["rounds"]) == len(run["rounds"])
    # Every round reconstructs its retrieval sets (with query text) and interpretations.
    for rd in rehydrated["rounds"]:
        assert all(s["query"] for s in rd["retrieval_sets"])
    assert rehydrated["interpretations_used"] == run["interpretations_used"]
    assert rehydrated["model_call_count"] == run["model_call_count"]
    # Synthesis citations resolve to fresh internal links.
    risks = rehydrated["synthesis"]["material_risks"]
    assert risks and risks[0]["findings"][0]["internal_url"] == "/records/bills/1"
    await engine.dispose()


def test_same_topic_and_tier_yields_stable_structure(tmp_path, monkeypatch):
    asyncio.run(_determinism(tmp_path, monkeypatch))


async def _determinism(tmp_path, monkeypatch):
    engine, session_maker = await _make_db(tmp_path, "determ.db", n_bills=1)

    async def _one():
        # No planner/synthesis providers → deterministic single seed round.
        _patch(monkeypatch, retrieve_hits=[_hit("bills", 1)], planner=None, synth=None)
        async with session_maker() as session:
            return await run_research(session, "telecom regulation", "standard")

    a = await _one()
    b = await _one()

    assert a["rounds_used"] == b["rounds_used"] == 1
    assert [rd["queries"] for rd in a["rounds"]] == [rd["queries"] for rd in b["rounds"]]
    assert a["interpretations_used"] == b["interpretations_used"]
    assert a["id"] != b["id"]  # different run ids, identical structure
    await engine.dispose()


def test_planner_failure_mid_loop_degrades_and_preserves_prior_rounds(tmp_path, monkeypatch):
    asyncio.run(_midloop_failure(tmp_path, monkeypatch))


async def _midloop_failure(tmp_path, monkeypatch):
    engine, session_maker = await _make_db(tmp_path, "midloop.db", n_bills=1)
    # Round 1 is the deterministic seed (no planner call). Round 2 asks the
    # planner, which errors — the run must degrade but keep round 1 intact.
    planner = ScriptedToolProvider([ProviderError("upstream 529 overloaded")])
    synth = ScriptedToolProvider([_good_synth_input()])
    _patch(monkeypatch, retrieve_hits=[_hit("bills", 1)], planner=planner, synth=synth)

    async with session_maker() as session:
        run = await run_research(session, "telecom", "standard")

    assert run["status"] == "degraded"
    assert run["rounds_used"] == 1, "round 1 must be preserved after the mid-loop failure"
    assert run["interpretations_used"] == 1
    # Synthesis still ran over the surviving round-1 finding.
    assert run["synthesis"]["material_risks"]
    await engine.dispose()
