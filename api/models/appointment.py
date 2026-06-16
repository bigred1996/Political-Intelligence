"""GIC Appointments model — Governor in Council appointments to regulatory bodies."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Appointment(Base):
    __tablename__ = "appointments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    appointee_name: Mapped[str] = mapped_column(String(256), index=True)
    canonical_name: Mapped[str] = mapped_column(String(255), index=True)
    position_title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    organization: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    appointment_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    end_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    order_in_council: Mapped[str | None] = mapped_column(String(64), nullable=True)
    appointment_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    remuneration: Mapped[str | None] = mapped_column(String(128), nullable=True)
    province: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str] = mapped_column(String(128), default="open.canada.ca GIC Appointments")
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
