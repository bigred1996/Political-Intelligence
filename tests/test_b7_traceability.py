"""Goal B7 — full-chain traceability hardening tests.

B1-B6 each re-derive their claims from the layer below rather than trusting
their own past output; this file is the integration proof that the chain
holds end-to-end through the real services (`create_review` -> B3 ->
`get_review_response` -> `get_memo_response`), not just at each layer in
isolation (those layer-specific adversarial tests live in
`test_interpretation.py`, `test_research.py`, and `test_memo.py`).

Every check here reuses the one canonical primitive, `validate_citations`
(`pipeline/citation_registry.py`), and the existing conclusion-language
denylist (`find_conclusion_language`) — nothing here reimplements either.
"""
from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import pipeline.interpretation as interp_mod
import pipeline.research as research_mod
from api.database import Base
from api.models.contract import Contract
from api.models.donation import Bill
from pipeline.ai_provider import ProviderTurn, ProviderUnavailable
from pipeline.citation_registry import validate_citations
from pipeline.diligence import create_review, get_review_response
from pipeline.interpretation import _fallback_contract, get_interpretation
from pipeline.interpretation_contract import find_conclusion_language
from pipeline.memo_builder import SECTION_ORDER, _collect_run_allowed_ids, get_memo_response
from pipeline.memo_charts import risk_distribution
from pipeline.research import _fallback_synthesis, get_research_run

# Register all model tables (mirrors tests/test_memo.py and tests/test_reviews.py).
from api.models import (  # noqa: F401
    appointment, donation, entity, grant, interpretation, ocl_registration,
    politician, regulation, report, request, research_run, retrieval_set,
    review, scheduler_log, source_record,
)


# --- scripted fakes (mirrors tests/test_research.py / tests/test_memo.py) --

def _hit(table: str, pk, score: float = 0.9, title: str | None = None) -> dict:
    return {
        "table": table, "pk": pk, "score": score,
        "title": title or f"{table} {pk}", "record_type": "record",
        "source": table, "snippet": "", "match": "both",
        "date": None, "amount": None,
    }


def _fake_retrieve(hits: list[dict]):
    async def _retrieve(session, query, *, limit=15, balanced=False, entity=None):  # noqa: F811
        return {"results": list(hits), "plan": {"planner": "fallback"}, "embedding_model": "test"}
    return _retrieve


def _good_interp_input(finding=("bills", "1")) -> dict:
    fid = {"table": finding[0], "pk": finding[1]}
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


class ScriptedToolProvider:
    """Generic synthesis fake: each `call` pops the next scripted tool_input."""

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
        item = self.script.pop(0) if self.script else self.script[-1]
        return ProviderTurn(tool_input=item, tool_use_id=f"t{self.calls}", messages=[], model=self.model)


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


def _raise_unavailable(*a, **k):
    raise ProviderUnavailable("no key in test")


def _patch(monkeypatch, *, retrieve_hits, synth=None, interp=None):
    monkeypatch.setattr(research_mod, "retrieve", _fake_retrieve(retrieve_hits))
    monkeypatch.setattr(research_mod, "ClaudeResearchPlanner", _raise_unavailable)
    if synth is None:
        monkeypatch.setattr(research_mod, "ClaudeSynthesisProvider", _raise_unavailable)
    else:
        monkeypatch.setattr(research_mod, "ClaudeSynthesisProvider", lambda *a, **k: synth)
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


def _all_html(sections: dict[str, str]) -> str:
    return "\n".join(sections.values())


# --- 1. happy path: numbers agree, every citation validates ----------------

def test_full_chain_happy_path_numbers_agree_and_every_citation_validates(tmp_path, monkeypatch):
    asyncio.run(_happy_path_scenario(tmp_path, monkeypatch))


async def _happy_path_scenario(tmp_path, monkeypatch):
    engine, session_maker = await _make_db(tmp_path, "b7_happy.db")
    synth = ScriptedToolProvider([_good_synth_input()])
    _patch(monkeypatch, retrieve_hits=[_hit("bills", 1), _hit("contracts", 1)], synth=synth)

    async with session_maker() as session:
        created = await create_review(session, _form())
        review_id = created["review"]["id"]
        workspace = created["workspace"]
        run = created["run"]
        memo = await get_memo_response(session, review_id)
        allowed = await _collect_run_allowed_ids(session, run)

    # Workspace finding count <-> chart series total <-> PDF appendix row count.
    n = len(workspace["findings"])
    assert n == 2
    bars = risk_distribution(workspace["findings"])
    assert sum(b["value"] for b in bars) == n
    assert memo["sections"]["appendix"].count("<tr>") == n + 1  # rows + header

    # Every synthesis citation in the memo's own run is a real, in-run record —
    # checked with validate_citations itself, never a hand-rolled equivalent.
    synthesis = (memo.get("run") or {}).get("synthesis") or {}
    cited = [
        (str(fd["table"]), str(fd["pk"]))
        for group in ("themes", "material_risks", "opportunities")
        for it in synthesis.get(group, [])
        for fd in it.get("findings", [])
    ]
    assert cited, "the happy-path synthesis must actually cite something"
    check = validate_citations(allowed, cited)
    assert check["invalid"] == []
    await engine.dispose()


# --- 2. multi-layer forgery: B2 + B3 tampered at once, nothing survives -----

def test_multi_layer_forgery_is_dropped_everywhere_in_the_chain(tmp_path, monkeypatch):
    """Hand-tamper a real B2 Interpretation row AND the B3 run's `rounds` +
    `synthesis` columns directly (bypassing every write path at once), then
    re-fetch through the full real chain (`get_review_response` ->
    `get_memo_response`). No forged content may survive at any layer."""
    asyncio.run(_multi_layer_forgery_scenario(tmp_path, monkeypatch))


async def _multi_layer_forgery_scenario(tmp_path, monkeypatch):
    engine, session_maker = await _make_db(tmp_path, "b7_multilayer.db")
    synth = ScriptedToolProvider([_good_synth_input()])
    _patch(monkeypatch, retrieve_hits=[_hit("bills", 1)], synth=synth)

    async with session_maker() as session:
        created = await create_review(session, _form())
        review_id = created["review"]["id"]
        run_id = created["run"]["id"]
        interpretation_id = created["run"]["rounds"][0]["interpretations"][0]["id"]

    forged_id = {"table": "contracts", "pk": "999999"}  # never retrieved this run

    # Forge B2: tamper the persisted Interpretation row's output JSON directly.
    async with session_maker() as session:
        row = await get_interpretation(session, interpretation_id)
        output = dict(row.output)
        output["cited_record_ids"] = [*output["cited_record_ids"], forged_id]
        output["claims"] = [{**c, "cited_record_ids": [*c["cited_record_ids"], forged_id]} for c in output["claims"]]
        row.output = output  # reassignment, not in-place mutation — plain JSON column
        await session.commit()

    # Forge B3: tamper the persisted ResearchRun's rounds + synthesis JSON directly.
    async with session_maker() as session:
        run_row = await get_research_run(session, run_id)
        rounds = list(run_row.rounds or [])
        rounds[0] = {
            **rounds[0],
            "coverage_gaps": [
                *rounds[0]["coverage_gaps"],
                {"type": "non_evidentiary", "table": "contracts", "pk": "999999", "title": "forged gap"},
            ],
        }
        run_row.rounds = rounds

        synthesis = dict(run_row.synthesis or {})
        synthesis["material_risks"] = [
            *(synthesis.get("material_risks") or []),
            {
                "text": "Forged unsupported risk claim.", "label": "observed", "title": "Forged Risk Title",
                "finding_ids": [forged_id],
            },
        ]
        run_row.synthesis = synthesis
        await session.commit()

    async with session_maker() as session:
        resp = await get_review_response(session, review_id)
        memo = await get_memo_response(session, review_id)

    # Nowhere in the rehydrated run (B3 read path / G1) ...
    run = resp["run"]
    for rd in run["rounds"]:
        for it in rd["interpretations"]:
            assert forged_id not in it["cited_record_ids"]
            for c in it["claims"]:
                assert forged_id not in c["cited_record_ids"]
        assert ("contracts", "999999") not in [(g.get("table"), g.get("pk")) for g in rd["coverage_gaps"]]
    risk_titles = [it.get("title") for it in run["synthesis"]["material_risks"]]
    assert "Forged Risk Title" not in risk_titles

    # ... nor in the workspace projection (B4) ...
    workspace_text = repr(resp["workspace"])
    assert "Forged" not in workspace_text
    assert "999999" not in workspace_text

    # ... nor anywhere in the rendered PDF memo sections (B6).
    html = _all_html(memo["sections"])
    assert "Forged unsupported risk claim" not in html
    assert "Forged Risk Title" not in html
    assert "forged gap" not in html
    assert 'href="/records/contracts/999999"' not in html
    await engine.dispose()


# --- 3. conclusion-language sweep over degraded/fallback content -----------

def test_fallback_content_never_contains_conclusion_language():
    """The no-conclusion denylist (`find_conclusion_language`, reused, never
    reimplemented) must hold in DEGRADED/fallback content too, not just
    AI-produced content — a buyer must never see buy/sell/proceed/valuation
    language regardless of which path produced the memo."""
    finding = {"table": "bills", "pk": "1", "literal_fact": "Bill C-1 was introduced."}
    contract = _fallback_contract(finding, "test_reason")
    for field in (contract.source_fact, contract.interpretation, contract.impact, contract.recommendation,
                  contract.evidence_limitations):
        assert find_conclusion_language(field) == [], field

    synthesis = _fallback_synthesis(
        [{"table": "bills", "pk": "1"}, {"table": "contracts", "pk": "1"}], "test_reason",
    )
    assert find_conclusion_language(synthesis.coverage_summary) == []
    for q in synthesis.diligence_questions:
        assert find_conclusion_language(q) == [], q
    for item in synthesis.themes + synthesis.material_risks + synthesis.opportunities:
        assert find_conclusion_language(item.text) == [], item.text


def test_section_order_is_stable_seven_sections():
    """Sanity pin so a future change to SECTION_ORDER doesn't silently change
    the contract the rest of this file (and the PDF) assumes."""
    assert len(SECTION_ORDER) == 7
