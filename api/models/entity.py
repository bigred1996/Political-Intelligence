"""Entity + lobbying-record persistence (Step 2, minimal slice).

LobbyingRecord stores normalized OCL results so the analyst workspace and, later,
the entity resolver and report pipeline have a stable table to read from.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class LobbyingRecord(Base):
    __tablename__ = "lobbying_records"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    company_query: Mapped[str] = mapped_column(String(255), index=True)
    canonical_name: Mapped[str] = mapped_column(String(255), index=True)
    registration_id: Mapped[str] = mapped_column(String(64), index=True)
    client: Mapped[str] = mapped_column(String(512))
    registrant: Mapped[str] = mapped_column(String(512))
    subject_matters: Mapped[list] = mapped_column(JSON, default=list)
    institutions: Mapped[list] = mapped_column(JSON, default=list)
    communication_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source: Mapped[str] = mapped_column(String(128), default="OCL Lobbying Registry")
    raw: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
