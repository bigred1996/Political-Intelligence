"""Weekly strategic newsletter issues."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from ulid import ULID

from ..database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class NewsletterIssue(Base):
    __tablename__ = "newsletter_issues"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: str(ULID()))
    week_start: Mapped[str] = mapped_column(String(10), index=True)
    week_end: Mapped[str] = mapped_column(String(10), index=True)
    title: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(24), default="generated", index=True)
    generated_by: Mapped[str] = mapped_column(String(32), default="claude")
    model: Mapped[str] = mapped_column(String(64), default="claude-opus-4-8")
    word_count: Mapped[int] = mapped_column(Integer, default=0)

    sections: Mapped[dict] = mapped_column(JSON, default=dict)
    visuals: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    source_references: Mapped[list] = mapped_column(JSON, default=list)
    validation: Mapped[dict] = mapped_column(JSON, default=dict)
    html: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
