"""Smoke tests for the report pipeline (no network, no DB)."""
from __future__ import annotations

from pipeline.entity_resolver import normalize
from pipeline.report_builder import SECTION_ORDER, build_sections
from pipeline.risk_scorer import score


def test_entity_normalization_collapses_variants():
    assert normalize("IBM CANADA LTD.") == normalize("IBM Canada Limited") == "ibm"
    assert normalize("TELUS Communications Inc.") == "telus"


def _evidence(**over):
    ev = {
        "company": "TELUS", "canonical": "telus", "sector": "telecommunications",
        "report_type": "deal_due_diligence",
        "lobbying": {"count": 2, "records": [], "registrants": [], "institutions": ["ISED", "CRTC"]},
        "contracts": {"count": 1, "total_value": 1336358.0, "by_department": [{"dept": "AAFC", "value": 1336358.0, "count": 1}], "records": []},
        "donations": {"count": 5, "total_value": 1050.0, "records": []},
        "bills": {"count": 1, "records": [{"bill_number": "C-8", "title_en": "Telecom Act", "status": "Awaiting royal assent", "sponsor": "X"}]},
        "stakeholders": [{"name": "Minister", "role": "x", "position": "neutral"}],
    }
    ev.update(over)
    return ev


def test_scorer_bounds_and_drivers():
    s = score(_evidence())
    for k in ("regulatory_risk", "policy_volatility", "election_sensitivity", "lobbying_intensity", "overall"):
        assert 0 <= s[k] <= 10
    assert "drivers" in s
    # High-exposure sector should not score zero regulatory risk.
    assert s["regulatory_risk"] >= 4


def test_template_builder_produces_all_sections():
    ev = _evidence()
    sections, gen = build_sections(ev, score(ev))
    assert gen in ("template", "claude")
    assert set(sections) == set(SECTION_ORDER)
    assert "TELUS" in sections["executive_summary"]
    assert "$1,336,358" in sections["government_contracts"]
