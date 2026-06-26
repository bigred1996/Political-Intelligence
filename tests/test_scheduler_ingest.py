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
import pipeline.conditional_fetch as cf
import pipeline.raw_storage as rs
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


@pytest.fixture(autouse=True)
def _no_network_conditional_fetch(tmp_path, monkeypatch):
    """_run_appointments/_run_grants/_run_ocl_registrations now check
    conditional_fetch before fetching (Goal 11) — isolate the checkpoint
    dir so tests never touch the real data/checkpoints/, and stub the CKAN
    lookup itself so these stay live-network-free, matching this module's
    documented "no live network calls" contract."""
    monkeypatch.setattr(rs, "CHECKPOINTS_DIR", tmp_path / "checkpoints")

    async def _fake_fingerprint(*args, **kwargs):
        return cf.ResourceFingerprint(url="https://example.test/fixture.csv")
    monkeypatch.setattr(cf, "fingerprint_ckan_resource", _fake_fingerprint)
    yield


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

    def fake_parse(records):
        return list(FAKE_APPOINTMENTS)

    monkeypatch.setattr("pipeline.ingest.parse_appointments_from_precis", fake_parse)

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


def test_grants_quarterly_skips_download_when_resource_unchanged(tmp_path, monkeypatch):
    asyncio.run(_grants_skips_when_unchanged(tmp_path, monkeypatch))


async def _grants_skips_when_unchanged(tmp_path, monkeypatch):
    """Goal 11: a second run against the same upstream resource must not
    re-stream the CSV at all — the actual "incremental checks download only
    new or changed material" behavior, not just idempotent row counts."""
    session_maker = await _make_temp_session(tmp_path, "grants_unchanged.db")
    monkeypatch.setattr(db, "AsyncSessionLocal", session_maker)

    same_fp = cf.ResourceFingerprint(url="https://x/grants.csv", last_modified="Mon, 01 Jun 2026", size=999)

    async def _stable_fingerprint(*args, **kwargs):
        return same_fp
    monkeypatch.setattr(cf, "fingerprint_ckan_resource", _stable_fingerprint)

    calls = {"n": 0}

    async def fake_iter(max_rows: int = 0):
        calls["n"] += 1
        for row in FAKE_GRANTS:
            yield row

    monkeypatch.setattr("pipeline.ingest.iter_grant_rows", fake_iter)

    from api.scheduler import _run_grants

    await _run_grants(triggered_by="test")
    await _run_grants(triggered_by="test")  # same fingerprint — must be a no-op

    assert calls["n"] == 1
    async with session_maker() as session:
        count = (await session.execute(select(func.count()).select_from(Grant))).scalar_one()
    assert count == len(FAKE_GRANTS)

    from api.models.scheduler_log import SchedulerLog
    async with session_maker() as session:
        statuses = (await session.execute(
            select(SchedulerLog.status).order_by(SchedulerLog.id)
        )).scalars().all()
    assert statuses == ["ok", "skipped"]


FAKE_DONATIONS = [
    {"contributor_name": "Jane Donor", "canonical_name": "jane donor", "recipient": "Local EDA",
     "party": "Liberal", "contributor_city": "Ottawa", "contributor_province": "ON",
     "received_date": "2026-01-01", "amount": 50.0},
]


def test_donations_quarterly_skips_when_cache_would_otherwise_go_stale_forever(tmp_path, monkeypatch):
    """Regression test for the documented bug: _ensure_donations_cache()
    reuses an existing cache file forever, so the quarterly cron trigger
    never actually refreshed donations past the first download. Proves the
    fix: an UNCHANGED upstream resource is a real no-op (status=skipped,
    iter_donation_rows never called); a CHANGED one always re-fetches."""
    asyncio.run(_donations_conditional_fetch(tmp_path, monkeypatch))


async def _donations_conditional_fetch(tmp_path, monkeypatch):
    from api.models.donation import Donation

    session_maker = await _make_temp_session(tmp_path, "donations.db")
    monkeypatch.setattr(db, "AsyncSessionLocal", session_maker)
    monkeypatch.setattr("pipeline.ingest.DONATIONS_CACHE", tmp_path / "donations_cache.zip")

    fingerprints = [
        cf.ResourceFingerprint(url="https://elections.ca/od.zip", last_modified="Mon, 01 Jun 2026", size=100),
        cf.ResourceFingerprint(url="https://elections.ca/od.zip", last_modified="Mon, 01 Jun 2026", size=100),
        cf.ResourceFingerprint(url="https://elections.ca/od.zip", last_modified="Tue, 02 Jun 2026", size=200),
    ]

    async def _next_fingerprint(*args, **kwargs):
        return fingerprints.pop(0)
    monkeypatch.setattr(cf, "fingerprint_url", _next_fingerprint)

    calls = {"n": 0}

    async def fake_iter(max_rows: int = 0):
        calls["n"] += 1
        for row in FAKE_DONATIONS:
            yield row
    monkeypatch.setattr("pipeline.ingest.iter_donation_rows", fake_iter)

    from api.scheduler import _run_donations

    await _run_donations(triggered_by="test")   # first ever check — always fetches
    await _run_donations(triggered_by="test")   # same fingerprint — must skip
    await _run_donations(triggered_by="test")   # source changed — must fetch again

    assert calls["n"] == 2
    async with session_maker() as session:
        count = (await session.execute(select(func.count()).select_from(Donation))).scalar_one()
    assert count == len(FAKE_DONATIONS)  # full-replace each real fetch, never duplicated

    from api.models.scheduler_log import SchedulerLog
    async with session_maker() as session:
        statuses = (await session.execute(
            select(SchedulerLog.status).order_by(SchedulerLog.id)
        )).scalars().all()
    assert statuses == ["ok", "skipped", "ok"]


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


def test_canadabuys_and_boc_series_jobs_are_registered_and_log_runs(tmp_path, monkeypatch):
    """Goal 11: these two Goal-7 connectors had a working raw-archival walk
    but were never wired into the scheduler at all — "Active procurement
    opportunities" and "Bank of Canada" had zero recurring checks. Proves
    they're now registered AND that a run actually logs to scheduler_log,
    without making a live network call."""
    asyncio.run(_canadabuys_and_boc_series_registered(tmp_path, monkeypatch))


async def _canadabuys_and_boc_series_registered(tmp_path, monkeypatch):
    from api import scheduler as sched

    assert "canadabuys_tenders" in sched.JOB_RUNNERS
    assert "bank_of_canada" in sched.JOB_RUNNERS
    assert any(c["id"] == "canadabuys_tenders" for c in sched.SOURCE_CONFIGS)
    assert any(c["id"] == "bank_of_canada" for c in sched.SOURCE_CONFIGS)

    session_maker = await _make_temp_session(tmp_path, "canadabuys_boc.db")
    monkeypatch.setattr(db, "AsyncSessionLocal", session_maker)

    async def fake_rolling_sync():
        return {"files": [{"label": "open", "duplicate": False}], "changed": 1}
    monkeypatch.setattr("pipeline.connector_canadabuys.sync_rolling_tender_notices", fake_rolling_sync)

    from pipeline.api_paginator import BackfillSummary

    async def fake_backfill_all_series(*, max_pages=200):
        return BackfillSummary(cursor_start="A", cursor_end="B", pages_fetched=2,
                               pages_skipped_already_done=0, rows=[], gaps=[],
                               stopped_reason="max_pages")
    monkeypatch.setattr("pipeline.connector_boc_series.backfill_all_series", fake_backfill_all_series)

    await sched._run_canadabuys(triggered_by="test")
    await sched._run_boc_series(triggered_by="test")

    from api.models.scheduler_log import SchedulerLog
    async with session_maker() as session:
        logs = (await session.execute(
            select(SchedulerLog).order_by(SchedulerLog.id)
        )).scalars().all()
    assert [(log.job_id, log.status, log.rows_added) for log in logs] == [
        ("canadabuys_tenders", "ok", 1),
        ("bank_of_canada", "ok", 2),
    ]


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
