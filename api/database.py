"""Async SQLite (swap to PostgreSQL via DATABASE_URL)."""
from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(settings.database_url, echo=False, future=True)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
SessionLocal = AsyncSessionLocal  # alias for backwards compat


async def init_db() -> None:
    # Import models so they register on Base.metadata before create_all.
    from .models import (  # noqa: F401
        appointment, catalogue_entry, contract, donation, entity, grant, interpretation,
        ocl_registration, politician, regulation, report, request, research_run,
        retrieval_set, scheduler_log, source_record,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session
