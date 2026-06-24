"""Hard-rule tests for the Goal B3 cross-finding synthesis contract — pure, no
DB, no AI. Mirrors `tests/test_interpretation_contract.py`'s structure: one
test per rule `validate_synthesis` enforces. Before this file, the contract
only had indirect coverage via `tests/test_research.py`'s end-to-end
scenarios — this closes that gap as part of the Goal B7 full B-track test
pass, not new scope.
"""
from __future__ import annotations

from pipeline.synthesis_contract import (
    SynthesisContract,
    SynthesisItem,
    build_correction_message,
    contract_from_tool_input,
    validate_synthesis,
)

ALLOWED = [("bills", "1"), ("contracts", "42"), ("source_records", "7")]


def _base_contract(**overrides) -> SynthesisContract:
    defaults = dict(
        themes=[SynthesisItem(text="One bill retrieved.", label="observed", finding_ids=[("bills", "1")], title="Legislative activity")],
        material_risks=[SynthesisItem(text="A contract was awarded recently.", label="observed", finding_ids=[("contracts", "42")])],
        opportunities=[SynthesisItem(text="No specific opportunity identified yet.", label="observed", finding_ids=[("source_records", "7")])],
        diligence_questions=["Has the target disclosed this bill in its compliance program?"],
        overall_confidence="medium",
        coverage_summary="Searched bills, contracts, and source_records; Hansard coverage is thin.",
        generated_by="claude",
    )
    defaults.update(overrides)
    return SynthesisContract(**defaults)


def test_compliant_synthesis_passes():
    result = validate_synthesis(_base_contract(), ALLOWED)
    assert result.ok, result.errors


# ── citation integrity ───────────────────────────────────────────────────
def test_citation_outside_run_is_rejected():
    contract = _base_contract(
        material_risks=[SynthesisItem(text="x", label="observed", finding_ids=[("contracts", "999999")])]
    )
    result = validate_synthesis(contract, ALLOWED)
    assert not result.ok
    assert any("citation_outside_run" in e for e in result.errors)


def test_citations_fully_inside_run_pass():
    contract = _base_contract(
        themes=[SynthesisItem(text="x", label="observed", finding_ids=[("bills", "1"), ("contracts", "42")], title="t")]
    )
    result = validate_synthesis(contract, ALLOWED)
    assert result.ok, result.errors


# ── no-conclusion rule ────────────────────────────────────────────────────
def test_theme_text_with_conclusion_language_is_blocked():
    contract = _base_contract(
        themes=[SynthesisItem(text="This is a clear buy signal.", label="observed", finding_ids=[("bills", "1")], title="t")]
    )
    result = validate_synthesis(contract, ALLOWED)
    assert not result.ok
    assert any("theme_0_text_contains_conclusion_language" in e for e in result.errors)


def test_coverage_summary_with_conclusion_language_is_blocked():
    contract = _base_contract(coverage_summary="Recommend the buyer proceed with the acquisition.")
    result = validate_synthesis(contract, ALLOWED)
    assert not result.ok
    assert any("coverage_summary_contains_conclusion_language" in e for e in result.errors)


def test_diligence_question_with_conclusion_language_is_blocked():
    contract = _base_contract(diligence_questions=["Should we proceed with the acquisition now?"])
    result = validate_synthesis(contract, ALLOWED)
    assert not result.ok
    assert any("diligence_question_0_contains_conclusion_language" in e for e in result.errors)


def test_diligence_style_text_is_not_flagged():
    contract = _base_contract(
        material_risks=[SynthesisItem(text="Ask whether the target tracks this contract internally.", label="observed", finding_ids=[("contracts", "42")])]
    )
    result = validate_synthesis(contract, ALLOWED)
    assert result.ok, result.errors


# ── label validity ────────────────────────────────────────────────────────
def test_invalid_item_label_is_rejected():
    contract = _base_contract(
        opportunities=[SynthesisItem(text="x", label="definitely_true", finding_ids=[("source_records", "7")])]
    )
    result = validate_synthesis(contract, ALLOWED)
    assert not result.ok
    assert any("opportunity_0_invalid_label" in e for e in result.errors)


# ── overall confidence validity ──────────────────────────────────────────
def test_invalid_overall_confidence_is_rejected():
    contract = _base_contract(overall_confidence="extremely-sure")
    result = validate_synthesis(contract, ALLOWED)
    assert not result.ok
    assert any("invalid_overall_confidence" in e for e in result.errors)


def test_valid_overall_confidence_passes():
    for level in ("high", "medium", "low"):
        contract = _base_contract(overall_confidence=level)
        result = validate_synthesis(contract, ALLOWED)
        assert result.ok, result.errors


# ── non-empty coverage_summary ───────────────────────────────────────────
def test_empty_coverage_summary_is_rejected():
    contract = _base_contract(coverage_summary="")
    result = validate_synthesis(contract, ALLOWED)
    assert not result.ok
    assert any("coverage_summary_empty" in e for e in result.errors)


# ── non-empty finding_ids per item (Goal B7 / G5) ────────────────────────
def test_theme_with_no_finding_ids_is_rejected():
    contract = _base_contract(
        themes=[SynthesisItem(text="An uncited theme.", label="observed", finding_ids=[], title="t")]
    )
    result = validate_synthesis(contract, ALLOWED)
    assert not result.ok
    assert any("theme_0_has_no_finding_ids" in e for e in result.errors)


def test_material_risk_with_no_finding_ids_is_rejected():
    contract = _base_contract(
        material_risks=[SynthesisItem(text="An uncited risk.", label="observed", finding_ids=[])]
    )
    result = validate_synthesis(contract, ALLOWED)
    assert not result.ok
    assert any("material_risk_0_has_no_finding_ids" in e for e in result.errors)


def test_opportunity_with_no_finding_ids_is_rejected():
    contract = _base_contract(
        opportunities=[SynthesisItem(text="An uncited opportunity.", label="observed", finding_ids=[])]
    )
    result = validate_synthesis(contract, ALLOWED)
    assert not result.ok
    assert any("opportunity_0_has_no_finding_ids" in e for e in result.errors)


# ── tool-input parsing + correction message ──────────────────────────────
def test_contract_from_tool_input_round_trips():
    raw = {
        "themes": [{"title": "t", "summary": "s", "label": "observed", "finding_ids": [{"table": "bills", "pk": 1}]}],
        "material_risks": [{"text": "r", "label": "observed", "finding_ids": [{"table": "contracts", "pk": 42}]}],
        "opportunities": [],
        "diligence_questions": ["q1"],
        "overall_confidence": "high",
        "coverage_summary": "covered",
    }
    contract = contract_from_tool_input(raw, generated_by="claude")
    assert contract.themes[0].title == "t"
    assert contract.themes[0].finding_ids == [("bills", "1")]
    assert contract.material_risks[0].finding_ids == [("contracts", "42")]
    assert contract.to_dict()["themes"][0]["finding_ids"] == [{"table": "bills", "pk": "1"}]


def test_build_correction_message_lists_every_error():
    msg = build_correction_message(["citation_outside_run: [('bills', '2')]", "coverage_summary_empty"])
    assert "citation_outside_run" in msg
    assert "coverage_summary_empty" in msg
    assert "build_synthesis" in msg
