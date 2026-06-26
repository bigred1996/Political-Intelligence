"""StatCan cube observations — economic/social time-series, not entity-centric.

Distinct from `source_records`: these rows have no company/political entity
to anchor on (a cube row is "Forestry jobs, Canada, 2007 = 621 thousand", not
a record about a named party), so they don't fit source_record's
entity_name/canonical_name shape and aren't meant for the unified search box.
They exist to back economic-context charts (sector_intel.py's "what's the
broader economic backdrop" framing) via direct cube_id + geo + ref_date
queries. Every StatCan cube has a different set of dimension columns beyond
the fixed REF_DATE/GEO/VALUE spine (e.g. "Estimates", "Sector", "Age group"),
so the cube-specific columns land in `dimensions` (JSON) rather than getting
named columns that would only apply to some cubes.
"""
from __future__ import annotations

from sqlalchemy import JSON, Float, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class StatcanObservation(Base):
    __tablename__ = "statcan_observations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    cube_id: Mapped[str] = mapped_column(String(16), index=True)
    cube_title: Mapped[str] = mapped_column(String(512))
    frequency: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    ref_date: Mapped[str] = mapped_column(String(16), index=True)  # "2007" or "2007-01" — cubes vary
    geo: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    dguid: Mapped[str | None] = mapped_column(String(32), nullable=True)

    dimensions: Mapped[dict] = mapped_column(JSON, default=dict)  # cube-specific dimension columns

    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    uom: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scalar_factor: Mapped[str | None] = mapped_column(String(32), nullable=True)
    vector: Mapped[str | None] = mapped_column(String(32), nullable=True)
    coordinate: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str | None] = mapped_column(String(16), nullable=True)

    __table_args__ = (
        Index("ix_statcan_cube_geo_date", "cube_id", "geo", "ref_date"),
    )
