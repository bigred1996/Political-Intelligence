"""Goal B4 — the persisted "diligence review": the entry form's inputs plus the
ONE research run they launched, owned together as a revisitable workspace.

A Review is the durable object behind the Start-Diligence form. It stores the
analyst's framing (company/asset, sectors, transaction type, jurisdiction, date
range, concerns, optional keywords/question) and the chosen DEPTH TIER, then
links to exactly one B3 `ResearchRun` (`research_run_id`). One Review = one run
= one workspace: the workspace view (`pipeline.diligence`) READS the stored run,
it never re-runs the loop. `depth_tier` lives here as the single source of truth
that flowed form → B3 (and that B6 will read back for the PDF).

The linked run holds the entire reproducible evidence trail (B3), so this row
deliberately stores only the inputs + linkage + status, not a copy of findings.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from ulid import ULID

from ..database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: str(ULID()))

    # --- form inputs (the analyst's framing) ---
    company: Mapped[str] = mapped_column(Text)                       # company/asset — required
    sectors: Mapped[list] = mapped_column(JSON, default=list)        # list[str] sector slugs/names
    transaction_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    jurisdiction: Mapped[str | None] = mapped_column(String(64), nullable=True)
    date_from: Mapped[str | None] = mapped_column(String(16), nullable=True)   # YYYY or YYYY-MM-DD
    date_to: Mapped[str | None] = mapped_column(String(16), nullable=True)
    key_concerns: Mapped[str | None] = mapped_column(Text, nullable=True)
    keywords: Mapped[list] = mapped_column(JSON, default=list)       # optional list[str]
    research_question: Mapped[str | None] = mapped_column(Text, nullable=True)  # optional

    # DEPTH TIER — supplied to B3, single source of truth for this review's run.
    depth_tier: Mapped[str] = mapped_column(String(16), default="standard")  # brief | standard | deep

    # --- linkage + lifecycle ---
    research_run_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="researching")  # researching | ready | failed
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
