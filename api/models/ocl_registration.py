"""OCL Registrations model — full lobbying registration filings (not just communications)."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class OCLRegistration(Base):
    __tablename__ = "ocl_registrations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    registration_num: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    client_org: Mapped[str] = mapped_column(String(512), index=True)
    canonical_name: Mapped[str] = mapped_column(String(255), index=True)
    registrant_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    firm_name: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    registration_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    effective_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    end_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    subject_matters: Mapped[list] = mapped_column(JSON, default=list)
    federal_benefits: Mapped[str | None] = mapped_column(Text, nullable=True)
    private_interests: Mapped[str | None] = mapped_column(Text, nullable=True)
    government_funding: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(128), default="OCL Registrations")
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
