"""Generated report storage."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from ulid import ULID

from ..database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: str(ULID()))
    request_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    company_name: Mapped[str] = mapped_column(String(255), index=True)
    canonical_name: Mapped[str] = mapped_column(String(255), index=True)
    report_type: Mapped[str] = mapped_column(String(40))
    time_horizon: Mapped[str] = mapped_column(String(20), default="current")
    status: Mapped[str] = mapped_column(String(20), default="drafting")

    sections: Mapped[dict] = mapped_column(JSON, default=dict)        # section_key -> HTML/text
    risk_scores: Mapped[dict] = mapped_column(JSON, default=dict)     # the four + overall
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)        # raw counts/aggregates used
    generated_by: Mapped[str] = mapped_column(String(32), default="template")  # template | claude

    analyst_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
