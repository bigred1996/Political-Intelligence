"""MP / politician and Hansard mention tables.

Politicians are seeded from openparliament.ca (covers all federal MPs).
HansardMention records speeches that mention a company or sector keyword.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Politician(Base):
    __tablename__ = "politicians"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(256), index=True)
    party: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    riding: Mapped[str | None] = mapped_column(String(256), nullable=True)
    province: Mapped[str | None] = mapped_column(String(64), nullable=True)
    url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Enriched from the openparliament politician detail (photo + role + contact).
    photo_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    role: Mapped[str | None] = mapped_column(String(256), nullable=True)   # e.g. "Conservative MP for Edmonton Manning"
    email: Mapped[str | None] = mapped_column(String(256), nullable=True)
    since_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    commons_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source: Mapped[str] = mapped_column(String(128), default="openparliament.ca")
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class HansardMention(Base):
    __tablename__ = "hansard_mentions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    canonical_name: Mapped[str] = mapped_column(String(255), index=True)
    keyword: Mapped[str] = mapped_column(String(255), index=True)
    speech_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    speaker: Mapped[str | None] = mapped_column(String(256), nullable=True)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    speech_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source: Mapped[str] = mapped_column(String(128), default="openparliament.ca")
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
