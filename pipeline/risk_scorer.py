"""Risk scorer — four 0–10 scores from the gathered evidence.

Deterministic, explainable heuristics (no model call). Each score returns a value
and a short driver string so the report can justify it. Tunable as real data
volume grows; the point is transparency, not false precision.
"""
from __future__ import annotations

import math
from typing import Any


def _clamp(x: float) -> float:
    return round(max(0.0, min(10.0, x)), 1)


def _log_scale(n: float, mid: float = 20.0, max_score: float = 10.0) -> float:
    """Map a count to a 0–max_score score with diminishing returns.

    mid maps to 5.0 (half of max_score). Calibrated for real OCL data:
    20 lobbying communications → 5/10, 100+ → ~8–9/10.
    """
    if n <= 0:
        return 0.0
    return min(max_score, max_score * math.log(1 + n) / math.log(1 + 2 * mid))


# Sectors with structurally higher political/regulatory exposure in Canada.
_HIGH_RISK_SECTORS = {
    "energy", "oil", "gas", "pipeline", "telecom", "telecommunications", "bank",
    "banking", "pharma", "pharmaceutical", "health", "mining", "defence", "defense",
    "airline", "rail", "broadcasting", "cannabis", "grocery",
}

# Regulatory bodies whose contact signals meaningful oversight exposure.
_REGULATORY_INSTS = {
    "CRTC", "Competition Bureau", "Tribunal", "NEB", "CER", "OSFI",
    "Health Canada", "Treasury Board", "Immigration", "IRB",
}


def score(evidence: dict[str, Any]) -> dict[str, Any]:
    lob = evidence["lobbying"]
    con = evidence["contracts"]
    don = evidence["donations"]
    bills = evidence["bills"]
    sector = (evidence.get("sector") or "").lower()

    sector_hit = any(s in sector or s in evidence["canonical"] for s in _HIGH_RISK_SECTORS)
    lob_count = lob["count"]
    lob_insts = lob.get("institutions", [])

    # Count contacts with regulatory bodies — each adds meaningful exposure.
    reg_inst_hits = sum(
        1 for inst in lob_insts
        if any(r in inst for r in _REGULATORY_INSTS)
    )
    reg_bonus = min(3.0, reg_inst_hits * 1.5)

    # Lobbying intensity — log scale so 20 comms → 5/10, not 10/10.
    lobbying_intensity = _clamp(
        _log_scale(lob_count, mid=20) * 0.55
        + _log_scale(len(lob_insts), mid=8) * 0.35
        + (1.0 if sector_hit else 0)
    )

    # Regulatory risk — sector exposure + regulatory body contacts + bills + dept breadth.
    regulatory_risk = _clamp(
        (4.0 if sector_hit else 1.5)
        + reg_bonus
        + min(2.5, bills["count"] * 0.5)
        + min(1.5, len(con.get("by_department", [])) * 0.3)
    )

    # Policy volatility — bills in motion + lobbying activity as proxy for contested policy.
    policy_volatility = _clamp(
        _log_scale(bills["count"], mid=5) * 0.45
        + _log_scale(lob_count, mid=30) * 0.40
        + (1.5 if sector_hit else 0.5)
    )

    # Election sensitivity — consumer-facing/regulated sectors + donation signal.
    election_sensitivity = _clamp(
        (3.5 if sector_hit else 1.5)
        + min(2.5, don["count"] * 0.5)
        + _log_scale(lob_count, mid=40) * 0.30
    )

    overall = _clamp(
        0.30 * regulatory_risk + 0.25 * policy_volatility
        + 0.20 * election_sensitivity + 0.25 * lobbying_intensity
    )

    reg_inst_label = f"; {reg_inst_hits} regulatory body contact(s)" if reg_inst_hits else ""
    return {
        "regulatory_risk": regulatory_risk,
        "policy_volatility": policy_volatility,
        "election_sensitivity": election_sensitivity,
        "lobbying_intensity": lobbying_intensity,
        "overall": overall,
        "drivers": {
            "regulatory_risk": (
                f"{'high-exposure sector; ' if sector_hit else ''}"
                f"{bills['count']} relevant bill(s), "
                f"{len(con.get('by_department', []))} contracting dept(s)"
                f"{reg_inst_label}"
            ),
            "policy_volatility": f"{bills['count']} bill(s) in motion, {lob_count} lobbying communication(s)",
            "election_sensitivity": f"{don['count']} contribution record(s), {lob_count} lobbying communication(s)",
            "lobbying_intensity": f"{lob_count} communication(s) across {len(lob_insts)} institution(s)",
        },
    }
