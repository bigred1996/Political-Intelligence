"""Report request intake (Step 2 slice) + shared enums.

Full report generation arrives in later build steps; this captures the intake
shape from CLAUDE.md so the frontend can submit requests now.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from ulid import ULID

from ..database import Base


class ReportType(str, Enum):
    deal_due_diligence = "deal_due_diligence"
    sector_monitoring = "sector_monitoring"
    sector_outlook = "sector_outlook"
    regulatory_risk = "regulatory_risk"
    public_accountability = "public_accountability"


class TimeHorizon(str, Enum):
    current = "current"
    outlook_18m = "outlook_18m"


class ReportStatus(str, Enum):
    pending = "pending"
    drafting = "drafting"
    analyst_review = "analyst_review"
    approved = "approved"
    delivered = "delivered"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ReportRequestRow(Base):
    __tablename__ = "report_requests"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: str(ULID()))
    company_name: Mapped[str] = mapped_column(String(255), index=True)
    sector: Mapped[str | None] = mapped_column(String(255), nullable=True)
    deal_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    specific_asset: Mapped[str | None] = mapped_column(Text, nullable=True)
    report_type: Mapped[str] = mapped_column(String(40), default=ReportType.deal_due_diligence.value)
    time_horizon: Mapped[str] = mapped_column(String(20), default=TimeHorizon.current.value)
    customer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=ReportStatus.pending.value)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
