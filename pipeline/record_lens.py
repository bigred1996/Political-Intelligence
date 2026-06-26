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


def _yr(date: Any) -> str | None:
    """Year out of an ISO-ish or M/D/Y date string."""
    if not date:
        return None
    s = str(date)
    for i in range(len(s) - 3):
        chunk = s[i:i + 4]
        if chunk.isdigit() and 1990 <= int(chunk) <= 2035:
            return chunk
    return None


def _count_word(n: int, singular: str) -> str:
    return f"{n:,} {singular}{'' if n == 1 else 's'}"


def _contract_band(amount: float | None) -> str:
    if not amount:
        return "a federal"
    if amount >= 5_000_000:
        return "a major"
    if amount >= 1_000_000:
        return "a large"
    if amount >= 250_000:
        return "a mid-sized"
    if amount < 50_000:
        return "a small, routine"
    return "a standard"


def _entity_footprint(facts: dict[str, Any]) -> list[str]:
    """Plain-language pieces describing the entity's real federal footprint."""
    bits: list[str] = []
    c = facts.get("contracts")
    if c:
        bits.append(f"{_count_word(c['count'], 'federal contract')} worth {_money(c['total'])}")
    g = facts.get("grants")
    if g:
        bits.append(f"{_count_word(g['count'], 'grant')} worth {_money(g['total'])}")
    lob = facts.get("lobbying")
    if lob:
        bits.append(_count_word(lob["count"], "lobbying communication"))
    d = facts.get("donations")
    if d:
        bits.append(f"{_money(d['total'])} in political donations")
    return bits


def _party_concentration(facts: dict[str, Any]) -> tuple[str, int, str] | None:
    """(top_party, pct, qualifier) for a donor's giving, or None."""
    d = facts.get("donations")
    if not d or not d.get("parties"):
        return None
    parties = {k: v for k, v in d["parties"].items() if v}
    total = sum(parties.values())
    if not total:
        return None
    top = max(parties, key=parties.get)
    share = parties[top] / total
    pct = round(share * 100)
    if share >= 0.85:
        return (top, pct, "almost entirely")
    if share >= 0.6:
        return (top, pct, "mostly")
    if len(parties) > 1:
        return (top, pct, "with a plurality")
    return (top, pct, "entirely")


def assessment(
    *, record_type: str, entity: str | None, sector_name: str | None,
    sector_confidence: str, amount: float | None, status: str | None,
    signature: dict[str, Any], total_connections: int, distinct_sources: int,
    signal_level: str, fields: dict[str, Any] | None = None, facts: dict[str, Any] | None = None,
    date: str | None = None,
) -> dict[str, str]:
    """Record-specific means / matters / impact / what-to-watch beats + a one-line
    strategic read. Reads the record's own field values and the entity's computed
    aggregates (`facts`) so the prose is about *this* record, not its type."""
    f = fields or {}
    facts = facts or {}
    key = _rt_key(record_type)
    _subject = {"bill": "this bill", "regulation": "this regulation", "tribunal": "this matter", "news": "this announcement"}
    who = entity or _subject.get(key, "this organization")
    amt = _money(amount)
    sec = _sector_phrase(sector_name, sector_confidence)
    has_sector = bool(sector_name)
    when = _yr(date)
    dept = f.get("department")
    footprint = _entity_footprint(facts)

    sector_impact = (
        f"For {sec}, this is one data point in how Ottawa shapes the industry — read it against the connected records for the pattern."
        if has_sector else
        "It reads against government-wide activity rather than a single tracked industry."
    )

    means = matters = impact = watch = ""

    if key == "contract":
        means = f"{dept or 'A federal department'} awarded {who} {amt or 'an undisclosed sum'}" + (f" for {f['description']}" if f.get("description") else "") + (f" in {when}" if when else "") + "."
        band = _contract_band(amount)
        if facts.get("contracts") and facts["contracts"]["count"] > 1:
            c = facts["contracts"]
            matters = f"At {amt}, {band} award. {who} holds {_count_word(c['count'], 'federal contract')} worth {_money(c['total'])}" + (f", concentrated with {c['top']}" if c.get("top") else "") + "."
        else:
            matters = f"At {amt}, {band} award. It is {who}'s only federal contract on record — a one-off, not a pattern."
        impact = sector_impact
        watch = f"Watch {dept or 'the department'} for follow-on or amended awards to {who}" + (" — and whether the firm's lobbying continues to precede federal work." if facts.get("lobbying") else ".")

    elif key == "grant":
        means = f"{dept or 'A federal department'} granted {who} {amt or 'funding'}" + (f" under {f['program']}" if f.get("program") else "") + (f" in {when}" if when else "") + "."
        if facts.get("grants") and facts["grants"]["count"] > 1:
            g = facts["grants"]
            matters = f"{who} has received {_count_word(g['count'], 'federal grant')} totalling {_money(g['total'])} — a recurring recipient of federal funding."
        else:
            matters = f"This is {who}'s only grant on record. Transfers like it show where Ottawa is directing money and which players it backs."
        impact = sector_impact
        watch = "Watch for renewal or follow-on funding" + (f" under {f['program']}" if f.get("program") else "") + (f"; the agreement runs to {f['end_date']}." if f.get("end_date") else ".")

    elif key == "donation":
        means = f"{who} contributed {amt or 'a donation'} to the {f.get('party') or 'a federal party'}" + (f" ({f['province']})" if f.get("province") else "") + (f" in {when}" if when else "") + "."
        conc = _party_concentration(facts)
        if conc:
            party, pct, qual = conc
            d = facts["donations"]
            matters = f"{who}'s political giving runs {qual} to the {party} ({pct}% of {_money(d['total'])} across {_count_word(d['count'], 'contribution')}) — a clear partisan lean."
        else:
            matters = "Since the 2007 corporate-donation ban these are individual donors; the pattern of giving still maps political relationships."
        money_footprint = [b for b in footprint if "contract" in b or "grant" in b]
        impact = (f"Note: this donor also has {', '.join(money_footprint)} on record — political giving alongside federal funding is a relationship worth scrutinising." if money_footprint else sector_impact)
        watch = f"Watch whether giving stays concentrated toward the {f.get('party') or 'same party'}" + (" — and whether it tracks with the federal funding above." if money_footprint else ".")

    elif key == "lobby":
        means = f"{who} lobbied federal officials" + (f" at {f['institutions']}" if f.get("institutions") else "") + (f" in {when}" if when else "") + (f"; registrant {f['registrant']}." if f.get("registrant") else ".")
        lob = facts.get("lobbying")
        intensity = f"{who} has logged {_count_word(lob['count'], 'lobbying communication')}" + (f" since {_yr(lob['earliest'])}" if _yr(lob.get("earliest")) else "") + "." if lob and lob["count"] > 1 else f"This is the only lobbying communication on record for {who}."
        money_footprint = [b for b in footprint if "contract" in b or "grant" in b]
        matters = intensity + (f" It also holds {', '.join(money_footprint)}." if money_footprint else "")
        impact = (f"For {sec}, lobbying is a leading indicator — it frequently precedes regulatory, funding, or procurement decisions." if has_sector else "Lobbying is a leading indicator — it frequently precedes funding or regulatory decisions.")
        watch = f"Watch {f['institutions']}" if f.get("institutions") else "Watch the contacted institutions"
        watch += f" and any {sec} procurement or rule-making that follows this contact." if has_sector else " and any procurement or rule-making that follows."

    elif key == "bill":
        means = f"{f.get('bill_number') or 'A bill'}" + (f", {f['title']}," if f.get("title") else "") + (f" sponsored by {f['sponsor']}," if f.get("sponsor") else "") + f" is currently {status or 'in progress'}."
        adv = (status or "").lower()
        if any(k in adv for k in ("royal assent", "became law")):
            matters = "It has received Royal Assent — now law. The compliance and cost implications are real, not prospective."
            watch = "Watch implementation: coming-into-force dates and the regulations made under it."
        elif any(k in adv for k in ("third reading", "report stage", "senate")):
            matters = "It is well advanced through Parliament — close enough to law that affected operators should be preparing."
            watch = "Watch its remaining stages; at this point passage is a live prospect."
        else:
            matters = "It is early in the legislative process — introduced but far from law, so the impact is still prospective."
            watch = "Watch whether it advances past first reading; most early bills never become law."
        impact = (f"For {sec}, bills are the sharpest form of policy volatility — the further this advances, the more concrete the compliance and cost impact." if has_sector else "Bills are the sharpest form of policy volatility for whichever industry they touch.")

    elif key == "appointment":
        pos = f.get("position")
        org = f.get("organization")
        # The position title often already contains the body ("Chair of the X") —
        # don't repeat it as "… at X".
        at_org = f" at {org}" if org and (not pos or org.lower() not in pos.lower()) else ""
        means = f"{f.get('appointee') or who} was appointed" + (f" {pos}" if pos else "") + at_org + (f" in {when}" if when else "") + "."
        matters = f"Who sits on {f.get('organization') or 'a federal body'} sets the posture of the institution — appointments are a quiet but decisive lever on the sector it oversees."
        impact = sector_impact
        watch = f"Watch this appointee's posture at {f.get('organization') or 'the body'}" + (f"; the term runs to {f['end_date']}." if f.get("end_date") else ".")

    elif key == "regulation":
        means = (f.get("title") or "A regulatory action") + " was published in the Canada Gazette."
        matters = "Gazette items become enforceable rules with direct compliance and cost consequences — this is policy turning into binding obligation."
        impact = sector_impact
        watch = "Watch the comment period and the coming-into-force date, where the obligation actually bites."

    elif key == "tribunal":
        means = f"{f.get('body') or 'A federal tribunal'} issued decision {f.get('decision_number') or ''}".strip() + (f" involving {f['parties']}" if f.get("parties") else "") + "."
        matters = "Tribunal decisions bind the parties and set precedent; the outcome signals how the regulator is leaning."
        impact = sector_impact
        watch = "Watch for an appeal or related proceedings that could widen the precedent."

    elif key == "hansard":
        means = f"{f.get('speaker') or who} spoke" + (f" on {f['subject']}" if f.get("subject") else "") + " in the House of Commons" + (f" in {when}" if when else "") + "."
        matters = "House interventions show which issues MPs are actively raising and how positions are forming ahead of any bill or committee study."
        impact = sector_impact
        watch = "Watch whether the issue advances into a bill, a committee study, or a recorded vote."

    else:  # release / incident / news / source_records / default
        means = (f.get("title") or f"A federal record involving {who}") + (f" ({when})" if when else "") + "."
        matters = (f"{who} is active across {', '.join(footprint)}." if footprint else "Read it against the connected records to see how it fits the wider pattern.")
        impact = sector_impact
        watch = "Watch the connected records for whether this is an isolated entry or part of a developing pattern."

    # ── Strategic read — the one-line verdict: signal + sharpest fact + watch hook.
    signal_phrase = {"strong": "Strong signal", "moderate": "Moderate signal"}.get(signal_level, "Low standalone signal")
    insight = signature.get("insight")
    if insight:
        lead = insight
    elif footprint:
        lead = f"{who} carries {', '.join(footprint[:3])} across the federal record."
    elif total_connections > 0:
        lead = f"{who} links to {_count_word(total_connections, 'federal record')} across {distinct_sources} source{'s' if distinct_sources != 1 else ''}."
    else:
        lead = f"An isolated record — no other federal activity found for {who}."
    watch_hook = watch.split(" — ")[0].rstrip(".") if watch else ""
    strategic = f"{signal_phrase}. {lead}" + (f" {watch_hook}." if watch_hook else "")

    return {"means": means, "matters": matters, "impact": impact, "what_to_watch": watch, "strategic_read": strategic}
