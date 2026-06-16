"""Political contribution records (Elections Canada, as reviewed).

Note: federal law bans corporate/union political donations (since 2007), so most
rows are individuals. Search is by contributor name (catches executives / named
individuals). The report layer treats an empty corporate-donation result as a
meaningful, expected signal — not a gap.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Donation(Base):
    __tablename__ = "donations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    contributor_name: Mapped[str] = mapped_column(String(512))
    canonical_name: Mapped[str] = mapped_column(String(512), index=True)
    recipient: Mapped[str | None] = mapped_column(String(512), nullable=True)
    party: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    contributor_city: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contributor_province: Mapped[str | None] = mapped_column(String(64), nullable=True)
    received_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(128), default="Elections Canada — Contributions")
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Bill(Base):
    __tablename__ = "bills"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    bill_number: Mapped[str] = mapped_column(String(32), index=True)
    parliament: Mapped[str | None] = mapped_column(String(32), nullable=True)
    title_en: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sponsor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    latest_activity: Mapped[str | None] = mapped_column(String(255), nullable=True)
    introduced_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source: Mapped[str] = mapped_column(String(128), default="LEGISinfo")
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
