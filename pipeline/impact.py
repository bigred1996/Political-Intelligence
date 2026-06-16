"""Industry-lens layer — read every data point through the industry it touches.

Polaris is positioned around *industries*, not companies: a contract, a bill, a
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

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

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


def resolve_sector(
    canonical: str | None, title: str, summary: str, *, regulators_text: str = "",
) -> tuple[Sector | None, str]:
    """Return (sector, how) where how ∈ {'entity','keyword','regulator',''}."""
    if canonical:
        s = sector_for_entity(canonical)
        if s:
            return s, "entity"
    blob = f"{title} {summary}".lower()
    best: Sector | None = None
    best_hits = 0
    for s in SECTORS.values():
        hits = sum(1 for kw in s.keywords if kw in blob)
        if hits > best_hits:
            best, best_hits = s, hits
    if best:
        return best, "keyword"
    # Regulator-name fallback (e.g. a Gazette item from "Canada Energy Regulator").
    rt = regulators_text.lower()
    if rt:
        for s in SECTORS.values():
            if any(reg.lower() in rt for reg in s.regulators):
                return s, "regulator"
    return None, ""


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


async def relevant_players(
    session: AsyncSession, *, sector: Sector | None, canonical: str | None,
    sponsor: str | None = None,
) -> list[dict[str, Any]]:
    """The political players in play for this record.

    Combines: the bill's sponsor (if any), MPs who raised this entity or the
    sector's keywords in the House, and the regulators that govern the industry.
    MPs are linked to their profile by slug where we can resolve them.
    """
    from api.models.politician import HansardMention, Politician

    players: list[dict[str, Any]] = []
    seen: set[str] = set()

    async def _add_mp(name: str | None, why: str) -> None:
        if not name:
            return
        key = name.lower().strip()
        if key in seen:
            return
        pol = (await session.execute(
            select(Politician).where(Politician.name.ilike(f"%{name.strip()}%")).limit(1)
        )).scalar_one_or_none()
        seen.add(key)
        players.append({
            "type": "politician",
            "name": pol.name if pol else name,
            "slug": pol.slug if pol else None,
            "party": pol.party if pol else None,
            "role": (pol.role if pol else None),
            "photo_url": getattr(pol, "photo_url", None) if pol else None,
            "why": why,
        })

    # 1. Bill sponsor.
    if sponsor:
        await _add_mp(sponsor, "Sponsored this legislation")

    # 2. MPs who raised this entity / sector in Hansard.
    conds = []
    if canonical:
        conds.append(HansardMention.canonical_name == canonical)
    if sector:
        for kw in sector.keywords[:6]:
            conds.append(HansardMention.keyword.ilike(f"%{kw}%"))
    if conds:
        rows = (await session.execute(
            select(HansardMention.speaker).where(or_(*conds)).limit(40)
        )).scalars().all()
        for speaker in rows:
            if speaker and len(seen) < 8:
                await _add_mp(speaker, f"Raised {sector.name if sector else 'the topic'} in the House")

    # 3. Industry regulators (institutional players, no profile).
    if sector:
        for reg in sector.regulators[:4]:
            players.append({"type": "regulator", "name": reg, "slug": None,
                            "party": None, "role": "Federal regulator/department",
                            "photo_url": None, "why": f"Oversees {sector.name}"})

    return players[:14]
