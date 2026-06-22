"""Idempotency tests for scheduler ingest jobs.

These exercise the actual `_run_*` job functions against a temporary SQLite
database with the upstream fetch functions monkeypatched to a small fixed
fixture — no live network calls. The point is to prove a real bug class is
fixed: appointments_weekly and grants_quarterly used to insert with no
delete-first and no dedup key, so running the job twice (e.g. a misfire-retry,
or the job firing twice across a restart) would silently double every row.
"""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import api.database as db
from api.models.appointment import Appointment
from api.models.grant import Grant

# Register all model tables on Base.metadata (mirrors tests/test_api_smoke.py).
from api.models import (  # noqa: F401
    appointment, contract, donation, entity, grant, ocl_registration,
    politician, regulation, report, request, scheduler_log, source_record,
)

FAKE_APPOINTMENTS = [
    {
        "appointee_name": "Jane Smith",
        "canonical_name": "jane smith",
        "position_title": "Member",
        "organization": "Canada Energy Regulator",
        "appointment_date": "2026-01-01",
        "order_in_council": "P.C. 2026-0001",
        "appointment_type": "GIC",
        "province": "ON",
    },
    {
        "appointee_name": "John Doe",
        "canonical_name": "john doe",
        "position_title": "Chairperson",
        "organization": "CRTC",
        "appointment_date": "2026-01-02",
        "order_in_council": "P.C. 2026-0002",
        "appointment_type": "GIC",
        "province": "QC",
    },
]

FAKE_GRANTS = [
    {
        "ref_number": "G-0001",
        "recipient_name": "Example Org",
        "canonical_name": "example org",
        "recipient_city": "Ottawa",
        "recipient_province": "ON",
        "owner_org": "isde",
        "owner_org_title": "Innovation, Science and Economic Development Canada",
        "program_name": "Strategic Innovation Fund",
        "agreement_type": "G",
        "agreement_value": 100000.0,
    },
    {
        "ref_number": None,  # a meaningful fraction of real rows have no ref_number
        "recipient_name": "Another Recipient",
        "canonical_name": "another recipient",
        "recipient_city": "Toronto",
        "recipient_province": "ON",
        "owner_org": "nrcan",
        "owner_org_title": "Natural Resources Canada",
        "program_name": "Clean Growth Program",
        "agreement_type": "C",
        "agreement_value": 50000.0,
    },
]


async def _make_temp_session(tmp_path, name: str):
    db_path = tmp_path / name
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(db.Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def test_appointments_weekly_is_idempotent(tmp_path, monkeypatch):
    asyncio.run(_appointments_idempotent(tmp_path, monkeypatch))


async def _appointments_idempotent(tmp_path, monkeypatch):
    session_maker = await _make_temp_session(tmp_path, "appointments.db")
    monkeypatch.setattr(db, "AsyncSessionLocal", session_maker)

    async def fake_fetch(max_rows: int = 10000):
        return list(FAKE_APPOINTMENTS)

    monkeypatch.setattr("pipeline.ingest.fetch_appointment_rows", fake_fetch)

    from api.scheduler import _run_appointments

    await _run_appointments(triggered_by="test")
    await _run_appointments(triggered_by="test")  # run twice — must not duplicate

    async with session_maker() as session:
        count = (await session.execute(select(func.count()).select_from(Appointment))).scalar_one()
    assert count == len(FAKE_APPOINTMENTS)


def test_grants_quarterly_is_idempotent(tmp_path, monkeypatch):
    asyncio.run(_grants_idempotent(tmp_path, monkeypatch))


async def _grants_idempotent(tmp_path, monkeypatch):
    session_maker = await _make_temp_session(tmp_path, "grants.db")
    monkeypatch.setattr(db, "AsyncSessionLocal", session_maker)

    async def fake_iter(max_rows: int = 0):
        for row in FAKE_GRANTS:
            yield row

    # _run_grants streams via iter_grant_rows (converted from a list-returning
    # fetch_grant_rows 2026-06-22 — see DATA_CHECKLIST.md "Goal 6", the
    # 2.25GB-into-memory risk). Must patch the streaming name, not the old one,
    # or this test silently falls through to the real network call.
    monkeypatch.setattr("pipeline.ingest.iter_grant_rows", fake_iter)

    from api.scheduler import _run_grants

    await _run_grants(triggered_by="test")
    await _run_grants(triggered_by="test")  # run twice — must not duplicate

    async with session_maker() as session:
        count = (await session.execute(select(func.count()).select_from(Grant))).scalar_one()
    assert count == len(FAKE_GRANTS)


FAKE_OCL_REGISTRATIONS = [
    {
        "registration_num": "REG-0001",
        "client_org": "Example Lobbying Client",
        "canonical_name": "example lobbying client",
        "registrant_name": "Jane Lobbyist",
        "firm_name": "Acme Government Relations",
        "registration_type": "Consultant",
        "status": "Active",
        "effective_date": "2026-01-01",
        "subject_matters": ["Energy", "Environment"],
    },
    {
        "registration_num": "REG-0002",
        "client_org": "Another Client Inc",
        "canonical_name": "another client inc",
        "registrant_name": "John Lobbyist",
        "firm_name": None,
        "registration_type": "In-house",
        "status": "Active",
        "effective_date": "2026-01-02",
        "subject_matters": [],
    },
]


def test_ocl_registrations_upsert_is_idempotent(tmp_path, monkeypatch):
    asyncio.run(_ocl_registrations_idempotent(tmp_path, monkeypatch))


async def _ocl_registrations_idempotent(tmp_path, monkeypatch):
    """ocl_registrations already has existence-check-by-registration_num dedup
    logic plus a DB-level unique constraint — unlike appointments/grants, this
    one was never actually broken. This test just proves it, since nothing
    previously verified it (the table has been empty/never-triggered in
    every real environment audited so far)."""
    from api.models.ocl_registration import OCLRegistration

    session_maker = await _make_temp_session(tmp_path, "ocl_registrations.db")
    monkeypatch.setattr(db, "AsyncSessionLocal", session_maker)

    async def fake_fetch(max_rows: int = 0):
        return list(FAKE_OCL_REGISTRATIONS)

    monkeypatch.setattr("pipeline.ingest.fetch_ocl_registration_rows", fake_fetch)

    from api.scheduler import _run_ocl_registrations

    await _run_ocl_registrations(triggered_by="test")
    await _run_ocl_registrations(triggered_by="test")  # run twice — must not duplicate

    async with session_maker() as session:
        count = (await session.execute(select(func.count()).select_from(OCLRegistration))).scalar_one()
    assert count == len(FAKE_OCL_REGISTRATIONS)


def test_stream_load_reports_partial_progress_on_failure(tmp_path, monkeypatch):
    asyncio.run(_stream_load_partial_progress(tmp_path, monkeypatch))


async def _stream_load_partial_progress(tmp_path, monkeypatch):
    """A mid-stream failure must not be reported as zero rows committed.

    Regression test for the documented gotcha: "a dropped stream at the tail
    != data lost" — _stream_load commits in batches, so partial progress
    should survive and be reported even when the generator raises partway.
    """
    session_maker = await _make_temp_session(tmp_path, "stream_load.db")
    monkeypatch.setattr(db, "AsyncSessionLocal", session_maker)

    from api.models.contract import Contract
    from api.scheduler import StreamLoadError, _stream_load

    async def flaky_rows():
        for i in range(3):
            yield {
                "vendor_name": f"Vendor {i}",
                "canonical_name": f"vendor {i}",
                "reference_number": f"REF-{i}",
                "contract_value": 1000.0,
            }
        raise ConnectionError("connection dropped")

    with pytest.raises(StreamLoadError) as exc_info:
        await _stream_load(Contract, flaky_rows(), batch_size=1)

    assert exc_info.value.loaded == 3
    assert "connection dropped" in str(exc_info.value)

    async with session_maker() as session:
        count = (await session.execute(select(func.count()).select_from(Contract))).scalar_one()
    assert count == 3  # the 3 committed batches survive the failure
