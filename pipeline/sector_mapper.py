"""Sector taxonomy — curated entity rosters + keyword/regulator maps.

Sector intelligence rolls up cross-source signals by *industry* (and optionally
region), not by a single company. The challenge is performance: an ``ILIKE`` over
1.15M contracts or 363k lobbying rows is a 5–14s full scan, far too slow for an
interactive request. So we split the matching strategy by table size:

* **Big tables (contracts, donations, lobbying)** — matched by a curated roster of
  canonical entity slugs via the indexed ``canonical_name`` column (fast, precise,
  explainable). The slugs below are the real ``entity_resolver.normalize()`` output
  for each company, verified to carry data in the DB.
* **Small tables (bills, gazette, tribunal, source_records)** — matched by keyword
  ``ILIKE`` (trivial cost at 176 / 638 / 9.7k rows).

Rosters are deliberately analyst-curated rather than ML-derived: precision and
defensibility matter more than recall for a due-diligence product. Add a sector by
adding one entry to ``SECTORS``.
"""
from __future__ import annotations

from typing import Any


class Sector:
    __slots__ = ("slug", "name", "blurb", "entities", "keywords", "regulators")

    def __init__(
        self, slug: str, name: str, blurb: str,
        entities: list[str], keywords: list[str], regulators: list[str],
    ) -> None:
        self.slug = slug
        self.name = name
        self.blurb = blurb
        self.entities = entities      # canonical slugs → indexed big-table lookups
        self.keywords = keywords      # ILIKE terms → small-table text search
        self.regulators = regulators  # org-name fragments → appointments / exposure

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug, "name": self.name, "blurb": self.blurb,
            "entity_count": len(self.entities), "regulators": self.regulators,
        }


# Canadian provinces/territories as stored in `province` columns (2-letter codes).
PROVINCES: dict[str, str] = {
    "AB": "Alberta", "BC": "British Columbia", "MB": "Manitoba",
    "NB": "New Brunswick", "NL": "Newfoundland and Labrador", "NS": "Nova Scotia",
    "NT": "Northwest Territories", "NU": "Nunavut", "ON": "Ontario",
    "PE": "Prince Edward Island", "QC": "Quebec", "SK": "Saskatchewan", "YT": "Yukon",
}


SECTORS: dict[str, Sector] = {
    "telecommunications": Sector(
        "telecommunications", "Telecommunications",
        "Carriers, broadcasters and ISPs under CRTC oversight and spectrum policy.",
        entities=["telus", "rogers", "bce", "shaw", "quebecor", "cogeco"],
        keywords=["telecom", "broadcast", "spectrum", "wireless", "internet", "5g", "cyber security"],
        regulators=["CRTC", "Canadian Radio-television", "Competition Bureau", "Innovation, Science"],
    ),
    "mining": Sector(
        "mining", "Mining & Metals",
        "Precious, base and critical-mineral producers exposed to permitting and royalties.",
        entities=["barrick gold", "teck resources", "nutrien", "cameco", "first quantum minerals"],
        keywords=["mining", "mineral", "critical mineral", "metals", "uranium", "potash", "smelter"],
        regulators=["Impact Assessment", "Natural Resources", "Canadian Nuclear Safety"],
    ),
    "energy": Sector(
        "energy", "Energy & Pipelines",
        "Oil, gas and pipeline operators facing emissions policy and CER regulation.",
        entities=["suncor energy", "enbridge", "tc energy", "imperial oil", "cenovus"],
        keywords=["energy", "pipeline", "oil", "gas", "emissions", "carbon", "lng", "petroleum"],
        regulators=["Canada Energy Regulator", "National Energy Board", "Natural Resources", "Environment"],
    ),
    "banking": Sector(
        "banking", "Banking & Finance",
        "Chartered banks and financial institutions under OSFI prudential oversight.",
        entities=["royal bank of", "td bank", "bank of montreal", "scotiabank", "cibc"],
        keywords=["bank", "financial institution", "OSFI", "payments", "open banking", "anti-money"],
        regulators=["OSFI", "Bank of Canada", "Finance", "FINTRAC", "Competition Bureau"],
    ),
    "grocery": Sector(
        "grocery", "Grocery & Retail",
        "National grocers under affordability scrutiny and competition review.",
        entities=["loblaw", "metro", "empire", "george weston"],
        keywords=["grocery", "grocer", "food price", "affordability", "retail", "competition"],
        regulators=["Competition Bureau", "Agriculture", "Innovation, Science"],
    ),
    "aerospace_defence": Sector(
        "aerospace_defence", "Aerospace & Defence",
        "Aircraft, defence and major procurement suppliers to the federal government.",
        entities=["bombardier", "lockheed martin", "general dynamics", "snc lavalin"],
        keywords=["aerospace", "defence", "defense", "military", "procurement", "aircraft", "shipbuilding"],
        regulators=["National Defence", "Public Services and Procurement", "Innovation, Science"],
    ),
    "transportation": Sector(
        "transportation", "Transportation",
        "Airlines and rail carriers regulated by Transport Canada and the CTA.",
        entities=["westjet", "air", "national railway", "pacific"],
        keywords=["airline", "aviation", "rail", "railway", "transport", "ports", "marine"],
        regulators=["Transport", "Canadian Transportation Agency", "Competition Bureau"],
    ),
    "pharma": Sector(
        "pharma", "Pharmaceuticals & Health",
        "Drug makers and health suppliers under Health Canada and PMPRB pricing rules.",
        entities=["pfizer", "bayer"],
        keywords=["pharma", "pharmaceutical", "drug", "health", "vaccine", "medical device", "pmprb"],
        regulators=["Health Canada", "PMPRB", "Patented Medicine"],
    ),
}


def get_sector(slug: str) -> Sector | None:
    return SECTORS.get(slug.lower().strip())


def sector_for_entity(canonical: str) -> Sector | None:
    """Reverse lookup: which sector roster contains this canonical entity."""
    c = canonical.lower().strip()
    for s in SECTORS.values():
        if c in s.entities:
            return s
    return None


def list_sectors() -> list[dict[str, Any]]:
    return [s.to_dict() for s in SECTORS.values()]
