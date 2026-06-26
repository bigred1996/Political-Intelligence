"""Full House of Commons Hansard transcripts — every spoken intervention,
sourced directly from ourcommons.ca's per-sitting XML (first-party), distinct
from the third-party openparliament.ca keyword-sweep in `HansardMention`
(`api/models/politician.py`) which only captures ~500-char excerpts around
sector keywords. This table holds the full text of every intervention.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class HansardSpeech(Base):
    __tablename__ = "hansard_speeches"
    __table_args__ = (
        Index("ix_hansard_speeches_sitting_seq", "parliament", "session", "sitting_number", "sequence"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    parliament: Mapped[int] = mapped_column(Integer, index=True)
    session: Mapped[int] = mapped_column(Integer, index=True)
    sitting_number: Mapped[int] = mapped_column(Integer, index=True)
    sitting_date: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    # Document-order position within the sitting — lets a record's full
    # context be reconstructed (ORDER BY sequence) and forms the natural
    # per-sitting external_id below.
    sequence: Mapped[int] = mapped_column(Integer)
    external_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    intervention_type: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    speaker: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    speaker_role: Mapped[str | None] = mapped_column(String(512), nullable=True)
    speaker_db_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    time_of_day: Mapped[str | None] = mapped_column(String(8), nullable=True)   # "HH:MM"
    content: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(String(512))
    source: Mapped[str] = mapped_column(String(128), default="House of Commons Hansard (ourcommons.ca)")
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
