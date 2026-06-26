"""Deterministic record intelligence — the editorial layer for one data point.

Every record-detail page answers five questions, in this order:

    What does it mean?  ·  Why does it matter?  ·  How does it connect?
    What is the impact?  ·  Strategic assessment.

This module computes that reading with **no API calls** — purely from the record's
own fields plus the cross-source connection stats already gathered by the records
route. It is the single source of truth for:

  * `signal_strength(...)`     — a calibrated Strong/Moderate/Low signal (replaces
                                 the old miscalibrated per-type "severity") with the
                                 drivers that produced it, so the score is legible.
  * `cross_source_signature(...)` — the "so what" of the connections: which distinct
                                 sources this entity touches and the pattern they form
                                 (lobbied AND won contracts AND donated …).
  * `assessment(...)`          — the four narrative beats (means / matters / impact)
                                 plus a one-line strategic read that references the
                                 signal and the connection signature.

Deterministic on purpose: instant, free, identical every load, and defensible for a
due-diligence product. An AI layer can be added on top of the same inputs later.
"""
from __future__ import annotations

import math
from typing import Any

# ── Source-label vocabulary used to detect cross-source patterns. These match the
# group labels produced by api/routes/records.py:_related_by_entity.
_LOBBY_LABELS = {"Lobbying communications", "Lobbying registrations"}
_CONTRACT_LABEL = "Federal contracts"
_GRANT_LABEL = "Grants & contributions"
_DONATION_LABEL = "Political donations"


def _money(n: float | None) -> str:
    if not n:
        return ""
    if n >= 1_000_000_000:
        return f"${n / 1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"${n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"${n / 1_000:.0f}K"
    return f"${n:,.0f}"


# ──────────────────────────────────────────────────────────────────────────────
# Signal strength
# ──────────────────────────────────────────────────────────────────────────────

# Inherent policy weight of a record type, even when the record is isolated: a
# binding regulation matters more standalone than a single small contract does.
_TYPE_WEIGHT = {
    "regulation": 15, "gazette": 15, "bill": 15, "tribunal_decision": 14,
    "appointment": 12, "lobbying_communication": 8, "lobbying_registration": 7,
    "incident": 12, "release": 9, "contract": 5, "grant": 5, "news": 4,
    "hansard_speech": 4, "hansard_mention": 4, "donation": 3,
}


def _type_weight(record_type: str) -> int:
    rt = (record_type or "").lower()
    if rt in _TYPE_WEIGHT:
        return _TYPE_WEIGHT[rt]
    for key, weight in _TYPE_WEIGHT.items():
        if key in rt:
            return weight
    return 5


def signal_strength(
    *, record_type: str, amount: float | None, total_connections: int,
    distinct_sources: int, sector_confidence: str, status: str | None = None,
) -> dict[str, Any]:
    """Calibrated signal for how much this record lights up the wider graph.

    Blends four legible factors and returns the level plus the drivers that earned
    it, so a reader sees *why* it's Strong, not just that it is. This measures the
    record's footprint, not the abstract importance of its institution — a pro-forma
    bill with no debate reads Low even though "a bill" sounds important.
    """
    drivers: list[dict[str, str]] = []

    # 1. Cross-source footprint — the strongest diligence signal (max 40).
    diversity = min(distinct_sources, 6) / 6 * 40
    if distinct_sources >= 2:
        drivers.append({
            "label": "Cross-source footprint",
            "detail": f"appears across {distinct_sources} federal sources",
        })

    # 2. Connection volume, log-scaled so 10k ≈ full credit (max 20).
    volume = min(math.log10(total_connections + 1) / 4, 1.0) * 20 if total_connections else 0.0
    if total_connections >= 25:
        drivers.append({
            "label": "Connected activity",
            "detail": f"{total_connections:,} linked federal records",
        })

    # 3. Materiality of the record's own dollar amount, log-scaled (max 25).
    material = min(math.log10(amount + 1) / 8, 1.0) * 25 if amount else 0.0
    if amount and amount >= 1_000_000:
        drivers.append({"label": "Materiality", "detail": f"{_money(amount)} on this record"})

    # 4. Record-type weight + bill advancement bonus.
    type_pts = _type_weight(record_type)
    if (status or "").lower() and any(
        k in status.lower() for k in ("third reading", "royal assent", "report stage")
    ):
        type_pts += 8
        drivers.append({"label": "Advancement", "detail": f"status: {status}"})

    # 5. Industry confidence — a confirmed sector sharpens the read (max 8).
    sector_pts = {"confirmed": 8, "likely": 4}.get(sector_confidence, 0)

    score = min(round(diversity + volume + material + type_pts + sector_pts), 100)
    level = "strong" if score >= 60 else "moderate" if score >= 30 else "low"

    if not drivers:
        drivers.append({"label": "Isolated record", "detail": "no cross-source activity found"})

    return {"level": level, "score": score, "drivers": drivers[:4]}


# ──────────────────────────────────────────────────────────────────────────────
# Cross-source signature — the "how does it connect" insight
# ──────────────────────────────────────────────────────────────────────────────

def cross_source_signature(
    by_source_groups: list[dict[str, Any]], this_source_label: str,
) -> dict[str, Any]:
    """Distil grouped connections into the pattern that matters for diligence.

    Returns the distinct sources the entity touches and a plain-language insight
    naming the *combination* (lobbied AND won contracts AND donated), which is the
    cross-source co-occurrence an analyst is actually hunting for.
    """
    labels = {g.get("label") for g in by_source_groups if g.get("count")}
    distinct = len(labels)
    if not distinct:
        return {"sources": [], "distinct": 0, "insight": None}

    has_lobby = bool(labels & _LOBBY_LABELS)
    has_contract = _CONTRACT_LABEL in labels
    has_grant = _GRANT_LABEL in labels
    has_donation = _DONATION_LABEL in labels
    has_money = has_contract or has_grant

    parts: list[str] = []
    if has_lobby and has_money:
        what = " and ".join(
            x for x in [
                "won federal contracts" if has_contract else "",
                "received federal grants" if has_grant else "",
            ] if x
        )
        parts.append(f"lobbied Ottawa and {what}")
    elif has_lobby:
        parts.append("has registered federal lobbying activity")
    elif has_contract and has_grant:
        parts.append("receives both federal procurement and grant funding")

    if has_donation and has_money:
        parts.append("with political donations on record alongside federal funding")
    elif has_donation and not parts:
        parts.append("has political donations on record")
    elif has_donation:
        parts.append("with political donations on record")

    insight = None
    if parts:
        insight = "This entity " + ", ".join(parts) + "."
    elif distinct >= 2:
        insight = f"This entity is active across {distinct} federal sources."

    # Order labels by group count (the groups arrive count-sorted already).
    ordered = [g.get("label") for g in by_source_groups if g.get("count")]
    return {"sources": ordered, "distinct": distinct, "insight": insight}


# ──────────────────────────────────────────────────────────────────────────────
# The four narrative beats + strategic read
# ──────────────────────────────────────────────────────────────────────────────

def _sector_phrase(sector_name: str | None, confidence: str) -> str:
    if not sector_name:
        return "multiple federal domains"
    if confidence == "confirmed":
        return sector_name
    return f"{sector_name} (likely)"


def _rt_key(record_type: str) -> str:
    """Collapse a raw record_type into a beat bucket."""
    rt = (record_type or "").lower()
    if "lobby" in rt:
        return "lobby"
    if rt in ("regulation", "gazette") or "regulation" in rt or "gazette" in rt:
        return "regulation"
    if "tribunal" in rt:
        return "tribunal"
    if "appointment" in rt:
        return "appointment"
    if "incident" in rt:
        return "incident"
    if "pollutant" in rt or "release" in rt or rt == "npri":
        return "release"
    if "news" in rt:
        return "news"
    if "hansard" in rt:
        return "hansard"
    if rt in ("contract", "grant", "donation", "bill"):
        return rt
    return "default"


def assessment(
    *, record_type: str, entity: str | None, sector_name: str | None,
    sector_confidence: str, amount: float | None, status: str | None,
    signature: dict[str, Any], total_connections: int, distinct_sources: int,
    signal_level: str,
) -> dict[str, str]:
    """The means / matters / impact beats + a one-line strategic read."""
    key = _rt_key(record_type)
    # Records with no named entity need a sensible subject for the prose.
    _subject = {
        "bill": "this bill", "regulation": "this regulation",
        "tribunal": "this matter", "news": "this announcement",
    }
    who = entity or _subject.get(key, "this organization")
    amt = _money(amount)
    sec = _sector_phrase(sector_name, sector_confidence)
    has_sector = bool(sector_name)

    # Sector-impact clause reused across beats.
    if has_sector:
        impact_lead = f"For {sec}, "
    else:
        impact_lead = "Across government, "

    beats: dict[str, dict[str, str]] = {
        "contract": {
            "means": f"A {amt or 'federal'} procurement award to {who} — the government paying for goods or services.",
            "matters": "Procurement is concrete federal reliance on a named supplier. Award size, the contracting department, and any follow-on or amended awards measure that footprint.",
            "impact": f"{impact_lead}awards like this signal where Ottawa places operational reliance and shape competitive dynamics among suppliers.",
        },
        "grant": {
            "means": f"A {amt or 'federal'} grant or contribution to {who} — money transferred, not paid for services rendered.",
            "matters": "Transfers reveal where Ottawa is directing money and which players it chooses to back — a leading signal of policy priorities.",
            "impact": f"{impact_lead}funding decisions show the government's hand in which players and projects it wants to advance.",
        },
        "donation": {
            "means": f"A political contribution linked to {who}. Since the 2007 corporate-donation ban these are individual donors.",
            "matters": "Donation patterns map political relationships; concentration toward one party can foreshadow alignment on policy.",
            "impact": f"{impact_lead}the flow of political money traces which relationships an industry's actors are cultivating.",
        },
        "lobby": {
            "means": f"{who} formally engaged — or registered to engage — federal officials.",
            "matters": "Lobbying is a leading indicator: it frequently precedes regulatory, funding, or procurement decisions. The institutions contacted, and any clustering before a policy moment, are the signal.",
            "impact": f"{impact_lead}lobbying activity is an early read on where the policy and spending agenda is about to move.",
        },
        "bill": {
            "means": f"Federal legislation (status: {status or 'in progress'}).",
            "matters": "Bills are the sharpest form of policy volatility — the further one advances, the more concrete its compliance, cost, or market impact.",
            "impact": f"{impact_lead}legislation sets the rules of the game; its progress is the clearest forward signal of regulatory change.",
        },
        "regulation": {
            "means": "A regulatory action published in the Canada Gazette — policy turning into binding obligation.",
            "matters": "Gazette items become enforceable rules with direct compliance and cost consequences.",
            "impact": f"{impact_lead}this is policy crossing the line from proposal into legal obligation.",
        },
        "tribunal": {
            "means": "A decision by a federal tribunal or regulator (e.g. CRTC) resolving a specific matter.",
            "matters": "Tribunal decisions bind the parties and set precedent; outcomes signal how regulators are leaning.",
            "impact": f"{impact_lead}regulator decisions are a direct read on enforcement posture and likely precedent.",
        },
        "appointment": {
            "means": f"A Governor-in-Council appointment{(' of ' + who) if entity else ''} to a federal body.",
            "matters": "Who sits on a sector's regulators sets the posture of the bodies overseeing it — a quiet but decisive lever.",
            "impact": f"{impact_lead}appointments shape the orientation of the institutions that hold the industry to account.",
        },
        "incident": {
            "means": f"An operational or safety incident involving {who}.",
            "matters": "Incidents raise regulatory scrutiny and social-licence risk, and often precede tightened oversight.",
            "impact": f"{impact_lead}incidents are frequently the trigger for new scrutiny across the whole industry.",
        },
        "release": {
            "means": f"A reported environmental release by {who}.",
            "matters": "Release data feeds environmental policy and ESG scrutiny and can become the evidence base for new regulation.",
            "impact": f"{impact_lead}emissions and release records often become the factual basis for future rule-making.",
        },
        "news": {
            "means": "A government communication or announcement.",
            "matters": "Departmental announcements signal ministerial priorities and the likely direction of upcoming policy.",
            "impact": f"{impact_lead}official communications telegraph where attention — and policy — is heading.",
        },
        "hansard": {
            "means": f"A statement made in the House of Commons{(' by ' + who) if entity else ''}.",
            "matters": "House interventions show which issues MPs are actively raising and how positions are forming.",
            "impact": f"{impact_lead}parliamentary debate is where political will around an issue becomes visible.",
        },
        "default": {
            "means": "A federal data point.",
            "matters": "Read alongside the connected records to see how it fits the wider pattern of contracts, lobbying, and regulation.",
            "impact": f"{impact_lead}its significance comes mainly from how it connects to the surrounding record.",
        },
    }
    beat = beats.get(key, beats["default"])

    # Strategic read — the verdict line, referencing signal + connection signature.
    signal_phrase = {
        "strong": "Strong signal", "moderate": "Moderate signal",
    }.get(signal_level, "Low standalone signal")
    insight = signature.get("insight")
    sector_tail = f" in {sec}" if has_sector else ""

    if insight:
        strategic = f"{signal_phrase}. {insight} Read the connections{sector_tail} for the full footprint."
    elif total_connections > 0:
        strategic = (
            f"{signal_phrase}. {who} shows {total_connections:,} connected federal "
            f"record{'s' if total_connections != 1 else ''} across {distinct_sources} "
            f"source{'s' if distinct_sources != 1 else ''}{sector_tail}."
        )
    else:
        strategic = (
            f"{signal_phrase} — an isolated record with no other federal activity found "
            f"for {who}{sector_tail}. Its value here is as a primary source, not a pattern."
        )

    return {
        "means": beat["means"],
        "matters": beat["matters"],
        "impact": beat["impact"],
        "strategic_read": strategic,
    }
