"""Discovered-catalogue index — what's AVAILABLE upstream, not what's downloaded.

Goal 5 of the 2026-06-21 ingestion work: before downloading large datasets,
discover what exists. One row per (catalogue_source, resource) — a dataset
with 3 resource formats (CSV/XLSX/JSON) gets 3 rows, since download_url/
format/estimated_size are resource-level facts, not dataset-level ones.

This is deliberately separate from `source_records` (which holds actual
ingested ROW-level content for the breadth sources) — this table holds
METADATA ABOUT AVAILABLE DATASETS, most of which have never been downloaded
at all. Mixing the two would conflate "what we have" with "what exists."
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class CatalogueEntry(Base):
    __tablename__ = "catalogue_entries"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Which discovery connector found this, e.g. "open-government",
    # "nrcan-geospatial", "transport-canada", "statcan", "iaac", "canada-gazette".
    catalogue_source: Mapped[str] = mapped_column(String(64), index=True)
    dataset_external_id: Mapped[str] = mapped_column(String(256), index=True)
    resource_external_id: Mapped[str | None] = mapped_column(String(256), nullable=True)

    title: Mapped[str] = mapped_column(String(1024))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    publisher: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    format: Mapped[str | None] = mapped_column(String(64), nullable=True)
    download_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    dataset_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    subject: Mapped[list] = mapped_column(JSON, default=list)
    geographic_coverage: Mapped[str | None] = mapped_column(String(256), nullable=True)
    date_coverage: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_modified: Mapped[str | None] = mapped_column(String(32), nullable=True)
    license: Mapped[str | None] = mapped_column(String(256), nullable=True)
    estimated_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # "high" | "medium" | "low" | "unclassified" — see
    # pipeline/catalogue_discovery.py:classify_relevance().
    relevance: Mapped[str] = mapped_column(String(16), default="unclassified", index=True)
    relevance_topics: Mapped[list] = mapped_column(JSON, default=list)

    # "not_downloaded" | "downloaded" | "partial" | "blocked" — see
    # pipeline/catalogue_discovery.py:classify_download_status().
    download_status: Mapped[str] = mapped_column(String(16), default="not_downloaded", index=True)

    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (
        UniqueConstraint("catalogue_source", "dataset_external_id", "resource_external_id",
                          name="uq_catalogue_dataset_resource"),
    )
