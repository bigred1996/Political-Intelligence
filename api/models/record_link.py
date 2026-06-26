"""Typed links between records in different source tables.

This is the materialized connective tissue for relationships that are more
specific than entity-name matching: Hansard speeches to MPs, bill mentions,
vote participants, same-sitting vote context, and similar future joins.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class RecordLink(Base):
    __tablename__ = "record_links"
    __table_args__ = (
        UniqueConstraint(
            "source_table", "source_pk", "target_table", "target_pk", "relationship",
            name="uq_record_link",
        ),
        Index("ix_record_links_source", "source_table", "source_pk"),
        Index("ix_record_links_target", "target_table", "target_pk"),
        Index("ix_record_links_relationship", "relationship"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_table: Mapped[str] = mapped_column(String(64))
    source_pk: Mapped[int] = mapped_column()
    target_table: Mapped[str] = mapped_column(String(64))
    target_pk: Mapped[int] = mapped_column()
    relationship: Mapped[str] = mapped_column(String(64))
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
