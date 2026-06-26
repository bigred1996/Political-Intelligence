"""Industry-lens layer — read every data point through the industry it touches.

Nessus is positioned around *industries*, not companies: a contract, a bill, a
lobbying notice or a pollutant release matters because of what it means for a
*sector* and which *political players* shape that sector. This module turns any
record into three things:

  * `resolve_sector(...)`   — which industry the record belongs to (by entity
                              roster first, then by keyword), and how confident.
  * `industry_impact(...)`  — a plain-language reading of what the record means
                              for that industry, with a severity signal.
  * `relevant_players(...)` — the political players in play: the bill's sponsor,
                              MPs who raised the sector/entity in the House, and
                              the regulators that govern the industry.

Interpretation is deterministic (works with no API key); when ANTHROPIC_API_KEY
is set the caller can layer a richer Claude reading on top of the same inputs.
"""
from __future__ import annotations

from typing import Any

from pipeline.sector_mapper import SECTORS, Sector, sector_for_entity


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


# A single keyword hit is too weak to assert an industry — "procurement" alone
# matched every PSPC contract to Aerospace & Defence. Require corroboration.
_KEYWORD_MIN_HITS = 2

# Confidence the (sector, how) pairing earns. Drives whether the UI states the
# industry as fact ("Telecommunications") or as a hedge ("Likely: Transportation").
_CONFIDENCE_BY_HOW = {"entity": "confirmed", "keyword": "likely", "regulator": "likely", "": ""}


def sector_confidence(how: str) -> str:
    """Confidence label for a `how` match strategy. Only a roster (entity) match
    is treated as confirmed; keyword/regulator matches are tentative."""
    return _CONFIDENCE_BY_HOW.get(how, "")


def resolve_sector(
    canonical: str | None, title: str, summary: str, *, regulators_text: str = "",
) -> tuple[Sector | None, str, str]:
    """Return (sector, how, confidence).

    how ∈ {'entity','keyword','regulator',''}; confidence ∈ {'confirmed','likely',''}.
    Entity-roster matches are confirmed; keyword matches need ≥2 corroborating hits
    before they're asserted (single-hit guesses are dropped, not surfaced wrong).
    """
    if canonical:
        s = sector_for_entity(canonical)
        if s:
            return s, "entity", "confirmed"
    blob = f"{title} {summary}".lower()
    best: Sector | None = None
    best_hits = 0
    for s in SECTORS.values():
        hits = sum(1 for kw in s.keywords if kw in blob)
        if hits > best_hits:
            best, best_hits = s, hits
    if best and best_hits >= _KEYWORD_MIN_HITS:
        return best, "keyword", "likely"
    # Regulator-name fallback (e.g. a Gazette item from "Canada Energy Regulator").
    rt = regulators_text.lower()
    if rt:
        for s in SECTORS.values():
            if any(reg.lower() in rt for reg in s.regulators):
                return s, "regulator", "likely"
    return None, "", ""


# Per-record-type reading of what the data point means for its industry.
def industry_impact(
    record_type: str, sector: Sector | None, *, entity: str | None,
    amount: float | None, status: str | None = None, how: str = "",
) -> dict[str, Any]:
    sec = sector.name if sector else "the broader economy"
    who = entity or "this organization"
    amt = _money(amount)
    rt = (record_type or "").lower()

    high_amount = bool(amount and amount >= 1_000_000)
    sev = "watch"
    meaning: str

    if rt in ("contract",):
        sev = "high" if high_amount else "elevated"
        meaning = (
            f"A {amt or 'federal'} procurement award to {who}, a {sec} player. "
            f"Awards of this kind signal government reliance on specific {sec} suppliers and "
            f"shape competitive dynamics in the industry. Track the contracting department and "
            f"any follow-on or amended awards as a measure of {sec}'s federal footprint."
        )
    elif rt in ("grant",):
        sev = "elevated" if high_amount else "watch"
        meaning = (
            f"A {amt or 'federal'} grant/contribution to {who}. Transfers like this reveal where "
            f"Ottawa is directing money inside {sec} — a leading signal of policy priorities and "
            f"which industry players are favoured for support."
        )
    elif rt in ("donation",):
        sev = "watch"
        meaning = (
            f"A political contribution linked to {who}. Since the 2007 corporate-donation ban these "
            f"are individuals, but donation patterns still map the political relationships of {sec} — "
            f"concentration toward one party can foreshadow alignment on {sec} policy."
        )
    elif "lobby" in rt:
        sev = "elevated"
        meaning = (
            f"{who} engaged federal officials. Lobbying is a leading indicator in {sec}: it frequently "
            f"precedes regulatory, funding or procurement decisions. Watch which institutions were "
            f"contacted and whether the activity clusters before a policy moment."
        )
    elif rt in ("bill",):
        sev = "high" if (status and any(k in status.lower() for k in ("third reading", "royal assent", "report stage"))) else "elevated"
        meaning = (
            f"Legislation relevant to {sec} (status: {status or 'in progress'}). Bills represent the "
            f"sharpest form of policy volatility for an industry — the further a bill advances, the more "
            f"concrete the compliance, cost or market impact for {sec} operators."
        )
    elif "regulation" in rt or "gazette" in rt:
        sev = "high"
        meaning = (
            f"A regulatory action touching {sec}. Canada Gazette items become binding rules with direct "
            f"compliance and cost consequences for {sec} — this is policy turning into obligation."
        )
    elif "incident" in rt:
        sev = "high"
        meaning = (
            f"An operational/safety incident involving {who}. Incidents raise regulatory scrutiny and "
            f"social-licence risk across {sec}, and often precede tightened oversight of the whole industry."
        )
    elif "pollutant" in rt or "release" in rt:
        sev = "elevated"
        meaning = (
            f"A reported environmental release by {who}. Emissions and release data feed environmental "
            f"policy and ESG scrutiny of {sec}, and can become the evidence base for new {sec} regulation."
        )
    elif "appointment" in rt:
        sev = "elevated"
        meaning = (
            f"A Governor-in-Council appointment. Who sits on {sec}'s regulators sets the posture of the "
            f"bodies overseeing the industry — appointments are a quiet but decisive lever on {sec}."
        )
    elif "news" in rt:
        sev = "watch"
        meaning = (
            f"A government communication relevant to {sec}. Departmental announcements signal ministerial "
            f"priorities and the likely direction of upcoming {sec} policy."
        )
    else:
        meaning = (
            f"A federal data point relevant to {sec}. Read alongside the connected records to see how it "
            f"fits the industry's pattern of contracts, lobbying and regulation."
        )

    if sector is None:
        meaning = (
            "This record isn't tied to one of the tracked industries. It still connects to other records "
            "through its entity; assign it an industry by the entity or keyword to see sector impact."
        )
        sev = "watch"

    return {
        "industry": sector.name if sector else None,
        "industry_slug": sector.slug if sector else None,
        "how": how,
        "severity": sev,
        "meaning": meaning,
        "regulators": sector.regulators if sector else [],
    }


# NOTE: the old `relevant_players()` keyword-Hansard sweep was removed — it surfaced
# any MP who once said a sector keyword in the House as a "player on this record",
# which was noise (often procedural names like "The Speaker"). Genuinely-linked
# people are now derived from materialized record_links in api/routes/records.py.
