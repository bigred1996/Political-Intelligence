"""Grants & Contributions model — federal money to organizations beyond contracts."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Grant(Base):
    __tablename__ = "grants"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ref_number: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    recipient_name: Mapped[str] = mapped_column(String(512), index=True)
    canonical_name: Mapped[str] = mapped_column(String(255), index=True)
    recipient_city: Mapped[str | None] = mapped_column(String(128), nullable=True)
    recipient_province: Mapped[str | None] = mapped_column(String(64), nullable=True)
    owner_org: Mapped[str | None] = mapped_column(String(64), nullable=True)
    owner_org_title: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    program_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    agreement_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    agreement_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    agreement_start: Mapped[str | None] = mapped_column(String(32), nullable=True)
    agreement_end: Mapped[str | None] = mapped_column(String(32), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(128), default="open.canada.ca Grants & Contributions")
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
