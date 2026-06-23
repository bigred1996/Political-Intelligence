"""Stored interpretations — the reproducibility record for Goal B2.

Every call to `pipeline.interpretation.interpret_finding` writes one row here,
success or failure: the exact prompt sent, the model + version, the
retrieval-set it was checked against, and the final structured output. This is
what a future audit (B7) replays to confirm an interpretation is reproducible,
and what `pipeline.interpretation`'s cache keys off so identical
(retrieval_set, finding) pairs never re-call the model.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from ulid import ULID

from ..database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Interpretation(Base):
    __tablename__ = "interpretations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: str(ULID()))
    retrieval_set_id: Mapped[str] = mapped_column(String(32), index=True)
    table: Mapped[str] = mapped_column(String(64), index=True)
    pk: Mapped[str] = mapped_column(String(64), index=True)
    cache_key: Mapped[str] = mapped_column(String(64), index=True)
    contract_version: Mapped[str] = mapped_column(String(16), default="b2-v1")

    provider: Mapped[str] = mapped_column(String(32), default="none")
    model: Mapped[str] = mapped_column(String(64), default="none")
    system_prompt: Mapped[str] = mapped_column(Text)
    user_prompt: Mapped[str] = mapped_column(Text)

    output: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="ok")  # ok | degraded | rejected
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
