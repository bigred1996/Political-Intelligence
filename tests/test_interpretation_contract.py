"""Hard-rule tests for the Goal B2 interpretation contract — pure, no DB, no AI.

These pin the rules `pipeline.interpretation` must enforce in code before any
AI-produced contract is persisted or shown: citation integrity against the
retrieval set, fact/inference separation in `source_fact`, the no-conclusion
policy on interpretation/impact/recommendation, and that low confidence or
thin evidence always surfaces a real (non-dismissive) limitation.
"""
from __future__ import annotations

from pipeline.interpretation_contract import (
    Claim,
    InterpretationContract,
    build_correction_message,
    contract_from_tool_input,
    find_conclusion_language,
    find_inference_markers,
    validate_contract,
)

ALLOWED = [("bills", "1"), ("contracts", "42"), ("source_records", "7")]


def _base_contract(**overrides) -> InterpretationContract:
    defaults = dict(
        source_fact="Bill C-27 was introduced on 2025-01-15 and is at second reading.",
        interpretation="This may signal heightened legislative attention to the sector.",
        impact="Could affect the timeline for related regulatory approvals.",
        recommendation="Ask counsel whether this bill affects the target's compliance obligations.",
        confidence="medium",
        evidence_limitations="Only one bill record was retrieved; broader Hansard coverage is thin.",
        cited_record_ids=[("bills", "1")],
        claims=[Claim(text="Bill C-27 was introduced on 2025-01-15.", label="observed", cited_record_ids=[("bills", "1")])],
        generated_by="claude",
    )
    defaults.update(overrides)
    return InterpretationContract(**defaults)


def test_compliant_contract_passes():
    result = validate_contract(_base_contract(), ALLOWED)
    assert result.ok, result.errors


# ── citation integrity ───────────────────────────────────────────────────
def test_citation_outside_retrieval_set_is_rejected():
    contract = _base_contract(cited_record_ids=[("bills", "1"), ("contracts", "999999")])
    result = validate_contract(contract, ALLOWED)
    assert not result.ok
    assert any("citation_outside_retrieval_set" in e for e in result.errors)


def test_claim_level_citation_outside_retrieval_set_is_rejected():
    contract = _base_contract(
        claims=[Claim(text="x", label="observed", cited_record_ids=[("contracts", "not-real")])]
    )
    result = validate_contract(contract, ALLOWED)
    assert not result.ok
    assert any("citation_outside_retrieval_set" in e for e in result.errors)


def test_citations_fully_inside_retrieval_set_pass():
    contract = _base_contract(cited_record_ids=[("bills", "1"), ("contracts", "42")])
    result = validate_contract(contract, ALLOWED)
    assert result.ok, result.errors


# ── fact/inference separation ────────────────────────────────────────────
def test_source_fact_with_inference_language_is_caught():
    contract = _base_contract(
        source_fact="The filing pattern suggests the company is trying to avoid scrutiny."
    )
    result = validate_contract(contract, ALLOWED)
    assert not result.ok
    assert any("source_fact_contains_inference" in e for e in result.errors)
    assert "suggests" in find_inference_markers(contract.source_fact)


def test_purely_literal_source_fact_passes():
    contract = _base_contract(source_fact="The contract was awarded on 2025-04-01 for $250,000.")
    result = validate_contract(contract, ALLOWED)
    assert result.ok, result.errors


# ── no-conclusion rule ────────────────────────────────────────────────────
def test_recommendation_with_buy_sell_proceed_valuation_language_is_blocked():
    contract = _base_contract(
        recommendation="We recommend the buyer proceed with the acquisition at the current valuation."
    )
    result = validate_contract(contract, ALLOWED)
    assert not result.ok
    assert any("recommendation_contains_conclusion_language" in e for e in result.errors)


def test_impact_with_conclusion_language_is_blocked():
    contract = _base_contract(impact="This is a clear sell signal for the target before due diligence concludes.")
    result = validate_contract(contract, ALLOWED)
    assert not result.ok
    assert any("impact_contains_conclusion_language" in e for e in result.errors)


def test_diligence_style_recommendation_is_not_flagged():
    contract = _base_contract(recommendation="Request the vendor's most recent compliance filing for review.")
    result = validate_contract(contract, ALLOWED)
    assert result.ok, result.errors


def test_find_conclusion_language_detects_bare_keywords():
    assert "buy" in find_conclusion_language("Investors should buy this stock now.")
    assert "proceed" in find_conclusion_language("It is safe to proceed with the deal.")


# ── claim labeling ────────────────────────────────────────────────────────
def test_invalid_claim_label_is_rejected():
    contract = _base_contract(claims=[Claim(text="x", label="definitely_true", cited_record_ids=[("bills", "1")])])
    result = validate_contract(contract, ALLOWED)
    assert not result.ok
    assert any("invalid_label" in e for e in result.errors)


# ── low confidence / thin evidence must surface, never hide ─────────────
def test_low_confidence_with_empty_limitations_is_rejected():
    contract = _base_contract(confidence="low", evidence_limitations="")
    result = validate_contract(contract, ALLOWED)
    assert not result.ok
    assert any("evidence_limitations_missing_or_dismissive" in e for e in result.errors)


def test_low_confidence_with_dismissive_limitations_is_rejected():
    for dismissive in ("none", "N/A", "No limitations.", "no known limitations"):
        contract = _base_contract(confidence="low", evidence_limitations=dismissive)
        result = validate_contract(contract, ALLOWED)
        assert not result.ok, f"{dismissive!r} should have been rejected"
        assert any("evidence_limitations_missing_or_dismissive" in e for e in result.errors)


def test_thin_evidence_forces_limitations_even_at_medium_confidence():
    contract = _base_contract(confidence="medium", evidence_limitations="")
    result = validate_contract(contract, ALLOWED, evidence_thin=True)
    assert not result.ok
    assert any("evidence_limitations_missing_or_dismissive" in e for e in result.errors)


def test_high_confidence_with_specific_limitations_passes():
    contract = _base_contract(
        confidence="high",
        evidence_limitations="Coverage is strong: multiple corroborating bill and gazette records.",
    )
    result = validate_contract(contract, ALLOWED)
    assert result.ok, result.errors


# ── non-empty citations (Goal B7 / G4) ───────────────────────────────────
def test_empty_top_level_citations_is_rejected():
    contract = _base_contract(cited_record_ids=[])
    result = validate_contract(contract, ALLOWED)
    assert not result.ok
    assert any("cited_record_ids_empty" in e for e in result.errors)


def test_claim_with_empty_citations_is_rejected():
    contract = _base_contract(
        claims=[Claim(text="An uncited assertion.", label="observed", cited_record_ids=[])]
    )
    result = validate_contract(contract, ALLOWED)
    assert not result.ok
    assert any("claim_0_has_no_cited_records" in e for e in result.errors)


# ── tool-input parsing + correction message ──────────────────────────────
def test_contract_from_tool_input_round_trips():
    raw = {
        "source_fact": "fact", "interpretation": "interp", "impact": "impact",
        "recommendation": "rec", "confidence": "high", "evidence_limitations": "none needed",
        "cited_record_ids": [{"table": "bills", "pk": 1}],
        "claims": [{"text": "fact", "label": "observed", "cited_record_ids": [{"table": "bills", "pk": 1}]}],
    }
    contract = contract_from_tool_input(raw, generated_by="claude")
    assert contract.cited_record_ids == [("bills", "1")]
    assert contract.claims[0].label == "observed"
    assert contract.claims[0].cited_record_ids == [("bills", "1")]
    assert contract.to_dict()["cited_record_ids"] == [{"table": "bills", "pk": "1"}]


def test_build_correction_message_lists_every_error():
    msg = build_correction_message(["citation_outside_retrieval_set: [('bills', '2')]", "source_fact_contains_inference: ['suggests']"])
    assert "citation_outside_retrieval_set" in msg
    assert "source_fact_contains_inference" in msg
    assert "build_interpretation" in msg
