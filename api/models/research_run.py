"""Goal B3 — the persisted "research run": one multi-step deep-research session.

A run is keyed to a topic + depth tier and stores the ENTIRE reproducible
trail: every round's planned queries and the retrieval-set ids they produced,
every B2 interpretation id consumed, the cross-finding synthesis, the resolved
caps actually enforced, model/provider, timestamps, and a total model-call
count for cost visibility. One run id rehydrates the whole trail
(`pipeline.research.get_research_run_response`) without re-calling any model.

Linkage is deliberately stored HERE rather than as a foreign key on
`retrieval_sets`/`interpretations`: B1/B2 stay unforked, and the run row is the
single authoritative evidence trail. `rounds` holds the per-round structure;
`interpretation_ids` is the flat de-duplicated list of B2 rows used.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from ulid import ULID

from ..database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ResearchRun(Base):
    __tablename__ = "research_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: str(ULID()))
    topic: Mapped[str] = mapped_column(Text)
    depth_tier: Mapped[str] = mapped_column(String(16), default="standard")  # brief | standard | deep
    contract_version: Mapped[str] = mapped_column(String(16), default="b3-v1")

    # Resolved caps actually enforced for this run (stored so reproducibility
    # does not depend on the TIERS table never changing).
    max_rounds: Mapped[int] = mapped_column(Integer, default=4)
    max_interpretations: Mapped[int] = mapped_column(Integer, default=20)

    status: Mapped[str] = mapped_column(String(24), default="running")
    # running | complete | insufficient_evidence | degraded | error

    # Per-round records: [{round, queries, retrieval_set_ids, interpretation_ids,
    #                      coverage_gaps, gap_assessment}, ...]
    rounds: Mapped[list] = mapped_column(JSON, default=list)
    rounds_used: Mapped[int] = mapped_column(Integer, default=0)
    # Flat, de-duplicated list of every B2 interpretation id consumed by the run.
    interpretation_ids: Mapped[list] = mapped_column(JSON, default=list)

    synthesis: Mapped[dict] = mapped_column(JSON, default=dict)

    provider: Mapped[str] = mapped_column(String(32), default="none")
    model: Mapped[str] = mapped_column(String(64), default="none")
    # Total provider round-trips (planner + per-finding interpretation + synthesis)
    # for cost visibility.
    model_call_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
