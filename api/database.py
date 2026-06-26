"""Async SQLite (swap to PostgreSQL via DATABASE_URL)."""
from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(settings.database_url, echo=False, future=True)

if settings.database_url.startswith("sqlite"):
    # Long-running requests (e.g. multi-round research) hold the connection
    # across many sequential commits while the scheduler's background jobs
    # write the same file concurrently. Without a busy_timeout, SQLite raises
    # "database is locked" immediately on any write collision instead of
    # waiting for the other writer to finish.
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_busy_timeout(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA busy_timeout = 10000")

AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
SessionLocal = AsyncSessionLocal  # alias for backwards compat


async def init_db() -> None:
    # Import models so they register on Base.metadata before create_all.
    from .models import (  # noqa: F401
        appointment, catalogue_entry, contract, donation, entity, grant, hansard_speech,
        interpretation, ocl_registration, politician, regulation, report, request,
        record_link, research_run, retrieval_set, review, scheduler_log, source_record,
        statcan_observation,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session
