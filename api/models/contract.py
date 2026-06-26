"""Federal contract records (Proactive Publication — Contracts over $10,000).

Real data, ingested from open.canada.ca bulk CSV via pipeline/ingest.py and
normalized by entity so the entity graph / report pipeline can query by company.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Contract(Base):
    __tablename__ = "contracts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    reference_number: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    vendor_name: Mapped[str] = mapped_column(String(512))
    canonical_name: Mapped[str] = mapped_column(String(512), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    contract_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    contract_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    owner_org: Mapped[str | None] = mapped_column(String(64), nullable=True)
    owner_org_title: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(128), default="Proactive Publication — Contracts")
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
