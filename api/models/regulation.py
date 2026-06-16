"""Gazette entries — Canada Gazette Part I (proposed) and Part II (final) regulations."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class GazetteEntry(Base):
    __tablename__ = "gazette_entries"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    gazette_part: Mapped[str] = mapped_column(String(8), index=True)   # "I" or "II"
    title: Mapped[str] = mapped_column(String(1024), index=True)
    published_date: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    guid: Mapped[str | None] = mapped_column(String(256), nullable=True, unique=True)
    department: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    regulation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str] = mapped_column(String(128), default="Canada Gazette RSS")
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class TribunalDecision(Base):
    __tablename__ = "tribunal_decisions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    body: Mapped[str] = mapped_column(String(64), index=True)    # "CRTC", "Competition Bureau", etc.
    decision_number: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(1024), index=True)
    decision_date: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    outcome: Mapped[str | None] = mapped_column(String(256), nullable=True)
    parties: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    source: Mapped[str] = mapped_column(String(128), default="CRTC")
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
