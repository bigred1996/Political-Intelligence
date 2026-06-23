"""Citation-safety registry: persisted retrieval sets for natural-language queries.

Every retrieval produces an explicit list of (table, pk) record ids that were
actually returned to the caller. Storing it here is what lets a downstream
AI-interpretation layer (B2+) prove a citation came from a real retrieval
instead of inventing one — see ``pipeline/citation_registry.py``.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from ulid import ULID

from ..database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class RetrievalSet(Base):
    __tablename__ = "retrieval_sets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: str(ULID()))
    query: Mapped[str] = mapped_column(Text)
    planner: Mapped[str] = mapped_column(String(32), default="fallback")
    embedding_model: Mapped[str] = mapped_column(String(128), default="")
    record_ids: Mapped[list] = mapped_column(JSON, default=list)  # [[table, pk], ...] — the explicit retrieval set
    result_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
