"""Goal B6 — branded PDF memo tests.

Hermetic, no network: reuses `tests/test_reviews.py`'s scripted-fake approach
to build a real Review + B3 run, then exercises `pipeline.memo_builder` on top
of it. Two layers are tested separately, matching the module split:

  * `build_sections` (pure) is hit directly with hand-built workspace dicts —
    no DB needed — to pin down word-cap enforcement and the "tier doesn't
    change section count, only content volume" behavior.
  * `get_memo_response` (the only DB-touching piece) is hit through a real
    `create_review` to prove no-model-call rehydration, workspace/memo number
    parity, link resolution, and — the important one — that a citation forged
    directly into the persisted run's synthesis (never actually retrieved)
    gets dropped, not rendered.
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
from pipeline.diligence import create_review
from pipeline.memo_builder import (
    INSUFFICIENT,
    NO_RUN,
    SECTION_ORDER,
    _cap_words,
    _word_count,
    build_sections,
    get_memo_response,
)
from pipeline.memo_charts import risk_distribution
from pipeline.memo_render import render_memo_html
from pipeline.research import get_research_run

# Register all model tables (mirrors tests/test_reviews.py).
from api.models import (  # noqa: F401
    appointment, donation, entity, grant, interpretation, ocl_registration,
    politician, regulation, report, request, research_run, retrieval_set,
    review, scheduler_log, source_record,
)


# --- scripted fakes (mirrors tests/test_reviews.py) ------------------------

def _hit(table: str, pk, score: float = 0.9, title: str | None = None) -> dict:
    return {
        "table": table, "pk": pk, "score": score,
        "title": title or f"{table} {pk}", "record_type": "record",
        "source": table, "snippet": "", "match": "both",
        "date": None, "amount": None,
    }


def _fake_retrieve(hits: list[dict]):
    async def _retrieve(session, query, *, limit=15):
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


# --- hand-built workspace fixtures for the pure build_sections tests -------

def _fake_review(*, depth_tier="standard", company="Acme Corp", sectors=None) -> dict:
    return {
        "id": "rev-1", "company": company, "sectors": sectors or ["telecom"],
        "depth_tier": depth_tier, "created_at": "2026-01-01T00:00:00", "updated_at": None,
    }


def _fake_finding(table, pk, *, risk="watch", date=None, sector_slug=None, sector_name=None,
                   category="other", source_fact=None, interpretation_="", impact_="") -> dict:
    return {
        "table": table, "pk": str(pk), "title": f"{table}:{pk}",
        "internal_url": f"/records/{table}/{pk}",
        "source_fact": source_fact or f"Fact about {table} {pk}.",
        "interpretation": interpretation_, "impact": impact_, "recommendation": "",
        "evidence_limitations": "", "confidence": "medium", "claims": [], "generated_by": "fake",
        "category": category,
        "meta": {
            "date": date, "sector_slug": sector_slug, "sector_name": sector_name,
            "jurisdiction": "Federal", "source_type": table, "source_label": table.title(),
            "risk_level": risk, "signal_type": "record", "entity": None,
            "confidence": "medium", "interpretation_types": ["observed"],
        },
    }


def _fake_run(synthesis=None) -> dict:
    return {
        "id": "run-1", "topic": "Acme Corp", "depth_tier": "standard", "status": "complete",
        "max_rounds": 4, "max_interpretations": 20, "rounds_used": 1, "interpretations_used": 1,
        "model": "none", "provider": "none", "model_call_count": 0, "rounds": [],
        "synthesis": synthesis if synthesis is not None else {
            "themes": [], "material_risks": [], "opportunities": [], "diligence_questions": [],
            "overall_confidence": "low", "coverage_summary": "", "generated_by": "template_fallback",
        },
    }


def _fake_workspace(findings, connected=None, further=None, coverage=None) -> dict:
    return {
        "findings": findings, "connected": connected or [], "further_research": further or [],
        "source_coverage": coverage or [], "facets": {},
    }


def _all_keys(findings, connected=None, further=None) -> set[tuple[str, str]]:
    keys = {(f["table"], f["pk"]) for f in findings}
    keys |= {(c["table"], c["pk"]) for c in (connected or [])}
    keys |= {(g["table"], g["pk"]) for g in (further or []) if g.get("table") and g.get("pk")}
    return keys


# --- pure build_sections tests ---------------------------------------------

def test_section_order_has_all_seventeen_sections():
    findings = [_fake_finding("bills", 1)]
    sections = build_sections(_fake_review(), _fake_run(), _fake_workspace(findings), _all_keys(findings))
    assert len(SECTION_ORDER) == 17
    assert set(sections.keys()) == set(SECTION_ORDER)


def test_tier_does_not_change_section_count_but_changes_content_volume():
    """The 17-section structure is identical for every tier ('tier changes
    section count correctly' == it correctly does NOT change); what scales
    with tier is the volume of content per section, driven by how many
    findings that tier's run produced."""
    few = [_fake_finding("bills", 1, category="legislative_regulatory")]
    many = [_fake_finding("bills", i, category="legislative_regulatory") for i in range(1, 21)]

    brief_sections = build_sections(_fake_review(depth_tier="brief"), _fake_run(), _fake_workspace(few), _all_keys(few))
    deep_sections = build_sections(_fake_review(depth_tier="deep"), _fake_run(), _fake_workspace(many), _all_keys(many))

    assert len(brief_sections) == len(deep_sections) == 17
    # More findings -> more appendix rows and more bullets in the themed section.
    assert deep_sections["evidence_appendix"].count("<tr>") > brief_sections["evidence_appendix"].count("<tr>")
    assert deep_sections["legislative_regulatory"].count("<li>") >= brief_sections["legislative_regulatory"].count("<li>")


def test_cap_words_trims_trailing_items_without_mid_sentence_truncation():
    items = "".join(f"<li>finding number {i} with five words here</li>" for i in range(30))
    html = f"<p>lead</p><ul>{items}</ul>"
    assert _word_count(html) > 100

    capped = _cap_words(html, 50)
    assert _word_count(capped) <= 70  # cap + the "+N more" note's own small word count
    assert "more finding" in capped
    # never cuts inside an <li> — every kept item is a complete, well-formed tag
    assert capped.count("<li>") == capped.count("</li>")

    # already-short input is returned untouched, no note appended
    short = "<ul><li>one item</li></ul>"
    assert _cap_words(short, 50) == short


def test_per_section_word_caps_enforced_on_realistic_section_volume():
    findings = [
        _fake_finding(
            "bills", i, risk=("high", "elevated", "watch")[i % 3], category="legislative_regulatory",
            source_fact="word " * 15, interpretation_="more words here for the interpretation field too",
            impact_="and the impact field carries more words still",
        )
        for i in range(1, 61)
    ]
    sections = build_sections(_fake_review(), _fake_run(), _fake_workspace(findings), _all_keys(findings))

    # Analytical sections respect the 300-500 word MAX (+ small slack for the drop-note).
    assert _word_count(sections["overall_risk"]) <= 520
    assert _word_count(sections["material_developments"]) <= 520
    assert _word_count(sections["legislative_regulatory"]) <= 520
    # The evidence appendix is explicitly unbounded — it must list every finding,
    # never trimmed by _cap_words (no "+N more" truncation note), unlike the
    # analytical sections above which all got trimmed from this same 60-finding set.
    assert sections["evidence_appendix"].count("<tr>") == 61  # 60 rows + 1 header row
    assert "more-note" not in sections["evidence_appendix"]
    assert "more-note" in sections["overall_risk"]


def test_out_of_run_finding_is_excluded_by_valid_keys_gate():
    """Pure-function check of the gate itself: a finding NOT present in
    valid_keys must never reach any rendered section."""
    real = _fake_finding("bills", 1)
    forged = _fake_finding("contracts", 999, source_fact="A record that was never actually retrieved.")
    workspace = _fake_workspace([real, forged])
    sections = build_sections(_fake_review(), _fake_run(), workspace, {("bills", "1")})  # forged key withheld

    for html in sections.values():
        assert "contracts:999" not in html
        assert "never actually retrieved" not in html
    assert "bills:1" in sections["evidence_appendix"]  # the real finding still renders
    assert sections["evidence_appendix"].count("<tr>") == 2  # 1 row + 1 header row


def test_empty_findings_render_insufficient_placeholders():
    sections = build_sections(_fake_review(), _fake_run(), _fake_workspace([]), set())
    assert sections["overall_risk"] == INSUFFICIENT
    assert sections["material_developments"] == INSUFFICIENT
    assert sections["evidence_appendix"] == INSUFFICIENT
    # exec summary still renders (it doesn't depend on findings being non-empty)
    assert "Acme Corp" in sections["exec_summary"]


def test_no_run_renders_no_run_placeholder_everywhere_that_needs_a_run():
    sections = build_sections(_fake_review(), None, _fake_workspace([]), set())
    assert sections["exec_summary"] == NO_RUN
    assert sections["coverage_limitations"] == NO_RUN


# --- get_memo_response (DB-backed) tests -----------------------------------

def test_memo_generates_with_no_model_calls(tmp_path, monkeypatch):
    asyncio.run(_no_model_calls(tmp_path, monkeypatch))


async def _no_model_calls(tmp_path, monkeypatch):
    engine, session_maker = await _make_db(tmp_path, "memo_no_calls.db")
    interp = _patch(monkeypatch, retrieve_hits=[_hit("bills", 1)])
    async with session_maker() as session:
        created = await create_review(session, _form())
        calls_after_create = interp.calls

        memo = await get_memo_response(session, created["review"]["id"])
        memo2 = await get_memo_response(session, created["review"]["id"])

    assert interp.calls == calls_after_create, "memo generation must call no model"
    assert set(memo["sections"].keys()) == set(SECTION_ORDER)
    assert memo["sections"] == memo2["sections"], "deterministic re-render, same input"
    await engine.dispose()


def test_memo_numbers_match_workspace_no_drift(tmp_path, monkeypatch):
    asyncio.run(_no_drift(tmp_path, monkeypatch))


async def _no_drift(tmp_path, monkeypatch):
    engine, session_maker = await _make_db(tmp_path, "memo_drift.db")
    _patch(monkeypatch, retrieve_hits=[_hit("bills", 1), _hit("contracts", 1)])
    async with session_maker() as session:
        created = await create_review(session, _form())
        workspace = created["workspace"]
        memo = await get_memo_response(session, created["review"]["id"])

    n = len(workspace["findings"])
    assert n == 2
    bars = risk_distribution(workspace["findings"])
    total_from_chart = sum(b["value"] for b in bars)
    assert total_from_chart == n
    assert f"{n} finding(s)" in memo["sections"]["overall_risk"]
    assert memo["sections"]["evidence_appendix"].count("<tr>") == n + 1  # rows + 1 header row
    await engine.dispose()


def test_appendix_links_resolve(tmp_path, monkeypatch):
    asyncio.run(_appendix_links(tmp_path, monkeypatch))


async def _appendix_links(tmp_path, monkeypatch):
    engine, session_maker = await _make_db(tmp_path, "memo_links.db")
    _patch(monkeypatch, retrieve_hits=[_hit("bills", 1), _hit("contracts", 1)])
    async with session_maker() as session:
        created = await create_review(session, _form())
        memo = await get_memo_response(session, created["review"]["id"])
    for f in created["workspace"]["findings"]:
        assert f["internal_url"].startswith("/records/")
        assert f"href=\"{f['internal_url']}\"" in memo["sections"]["evidence_appendix"]
    await engine.dispose()


def test_out_of_run_citation_forged_into_synthesis_is_rejected(tmp_path, monkeypatch):
    asyncio.run(_forged_citation(tmp_path, monkeypatch))


async def _forged_citation(tmp_path, monkeypatch):
    """The adversarial case: a record that genuinely exists in the DB
    (contracts:1) but was NEVER retrieved by this run gets hand-inserted into
    the persisted synthesis as if it were cited evidence. get_memo_response
    must re-validate against the run's own retrieval sets and drop it — never
    render a citation Nessus didn't actually retrieve this run."""
    engine, session_maker = await _make_db(tmp_path, "memo_forged.db")
    _patch(monkeypatch, retrieve_hits=[_hit("bills", 1)])  # contracts is NEVER retrieved
    async with session_maker() as session:
        created = await create_review(session, _form())
        run_id = created["run"]["id"]

        run_row = await get_research_run(session, run_id)
        synthesis = dict(run_row.synthesis or {})
        synthesis["material_risks"] = [
            *(synthesis.get("material_risks") or []),
            {
                "text": "Forged risk citing a record never retrieved this run.",
                "label": "observed", "title": "Forged",
                "finding_ids": [{"table": "contracts", "pk": "1"}],
            },
        ]
        run_row.synthesis = synthesis
        await session.commit()

        memo = await get_memo_response(session, created["review"]["id"])

    assert 'href="/records/contracts/1"' not in memo["sections"]["risks"]
    assert 'href="/records/contracts/1"' not in memo["sections"]["evidence_appendix"]
    # Goal B7 / G3: the whole forged item must be dropped, not just its link —
    # a claim that has lost every citation must never still print as fact.
    assert "Forged risk" not in memo["sections"]["risks"]
    await engine.dispose()


def test_synthesis_item_with_no_surviving_findings_is_dropped_not_rendered_bare():
    """Pure unit test for the Goal B7 / G3 fix: build_sections must drop a
    synthesis item whose findings are filtered down to empty, never render
    its bare text/title without a citation."""
    real = _fake_finding("bills", 1)
    run = _fake_run(synthesis={
        "themes": [], "diligence_questions": [], "overall_confidence": "low",
        "coverage_summary": "covered", "generated_by": "claude",
        "material_risks": [
            {
                "text": "Forged unsupported risk claim.", "label": "observed", "title": "Forged",
                "findings": [{"table": "contracts", "pk": "999", "internal_url": "/records/contracts/999"}],
            },
        ],
        "opportunities": [],
    })
    sections = build_sections(_fake_review(), run, _fake_workspace([real]), {("bills", "1")})
    assert "Forged unsupported risk claim" not in sections["risks"]
    assert sections["risks"] == INSUFFICIENT


def test_empty_workspace_renders_clean(tmp_path, monkeypatch):
    asyncio.run(_empty_clean(tmp_path, monkeypatch))


async def _empty_clean(tmp_path, monkeypatch):
    engine, session_maker = await _make_db(tmp_path, "memo_empty.db")
    _patch(monkeypatch, retrieve_hits=[])  # nothing retrieved -> insufficient_evidence run
    async with session_maker() as session:
        created = await create_review(session, _form())
        memo = await get_memo_response(session, created["review"]["id"])

    assert memo["run"]["status"] == "insufficient_evidence"
    assert memo["sections"]["overall_risk"] == INSUFFICIENT
    html = render_memo_html(memo)
    assert "<html" in html and "Acme Corp" in html
    await engine.dispose()


def test_failed_review_with_no_run_renders_clean(tmp_path, monkeypatch):
    asyncio.run(_failed_clean(tmp_path, monkeypatch))


async def _failed_clean(tmp_path, monkeypatch):
    import pipeline.diligence as diligence_mod

    engine, session_maker = await _make_db(tmp_path, "memo_failed.db")

    async def _boom(session, topic, tier):
        raise RuntimeError("provider exploded mid-run")
    monkeypatch.setattr(diligence_mod, "run_research", _boom)

    async with session_maker() as session:
        created = await create_review(session, _form())
        memo = await get_memo_response(session, created["review"]["id"])

    assert memo["run"] is None
    assert memo["sections"]["exec_summary"] == NO_RUN
    html = render_memo_html(memo, for_pdf=True)
    assert "<html" in html
    await engine.dispose()


def test_unknown_review_id_returns_none(tmp_path):
    asyncio.run(_unknown(tmp_path))


async def _unknown(tmp_path):
    engine, session_maker = await _make_db(tmp_path, "memo_unknown.db")
    async with session_maker() as session:
        memo = await get_memo_response(session, "does-not-exist")
    assert memo is None
    await engine.dispose()
