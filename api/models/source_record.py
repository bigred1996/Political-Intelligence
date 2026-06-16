"""Unified source-record store for the breadth data sources.

Architecture decision (senior call): Polaris keeps rich, typed tables for the
core sources it runs analytics and risk scoring on (contracts, donations,
lobbying, bills, grants). The wider breadth sources — StatCan, IAAC, CER, NPRI,
Transport Canada, NRCan/GeoGratis geospatial, GC News — are heterogeneous and
feed *search and cross-source insight* rather than bespoke scorecards. Forcing a
new typed table + model + route for each would be 7× the surface area for little
gain.

Instead every breadth record lands here in one uniform shape: typed columns for
the fields the platform actually queries/joins/ranks on (entity, title, summary,
date, amount, province, url) plus a JSON `raw` blob holding the full original
record. This makes unified search trivial (one table to scan + embed) while the
`canonical_name` column still lets a breadth record join the entity-resolution
graph alongside a contract or a lobbying filing.

If a breadth source later earns its own analytics, promote it to a typed table —
nothing here blocks that.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SourceRecord(Base):
    __tablename__ = "source_records"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Which connector produced this row, e.g. "statcan", "npri", "cer", "iaac",
    # "transport", "geospatial", "gc_news". Indexed for per-source filtering.
    source: Mapped[str] = mapped_column(String(32), index=True)
    record_type: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Stable upstream id used for idempotent upserts (source + external_id unique).
    external_id: Mapped[str | None] = mapped_column(String(256), nullable=True)

    # Entity linkage — lets a breadth record join the entity graph.
    entity_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    canonical_name: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)

    # Human-facing, searchable fields. `summary`/`full_text` are the text the
    # semantic indexer embeds; `title` is always rendered in result lists.
    title: Mapped[str] = mapped_column(String(1024))
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    full_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    event_date: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    province: Mapped[str | None] = mapped_column(String(64), nullable=True)
    url: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    raw: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_source_external"),
        Index("ix_source_records_source_date", "source", "event_date"),
    )
