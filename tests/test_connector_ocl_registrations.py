"""Tests for the BaseConnector interface and its first real implementation
(OCLRegistrationsConnector). No live network calls — discover()/download()
are monkeypatched; _parse() is exercised against a small synthetic ZIP built
from the real (verified 2026-06-21) column headers, not a live download.
"""
from __future__ import annotations

import asyncio
import csv
import io
import zipfile

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import api.database as db
import pipeline.raw_storage as rs
from pipeline.connector_base import DiscoveryResult
from pipeline.connector_ocl_registrations import OCLRegistrationsConnector

from api.models import (  # noqa: F401
    appointment, contract, donation, entity, grant, ocl_registration,
    politician, regulation, report, request, scheduler_log, source_record,
)


def _make_zip(rows: list[dict[str, str]]) -> bytes:
    header = [
        "REG_NUM_ENR", "EN_CLIENT_ORG_CORP_NM_AN", "RGSTRNT_1ST_NM_PRENOM_DCLRNT",
        "RGSTRNT_LAST_NM_DCLRNT", "EN_FIRM_NM_FIRME_AN", "REG_TYPE_ENR",
        "EFFECTIVE_DATE_VIGUEUR", "END_DATE_FIN", "GOVT_FUND_IND_FIN_GOUV",
    ]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=header)
    writer.writeheader()
    for row in rows:
        writer.writerow({h: row.get(h, "null") for h in header})

    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w") as zf:
        zf.writestr("Registration_BeneficiariesExport.csv", "WRONG_COL\nshould not be picked\n")
        zf.writestr("Registration_PrimaryExport.csv", buf.getvalue())
    return zbuf.getvalue()


REAL_SHAPED_ROW = {
    "REG_NUM_ENR": "775615-4611-11",
    "EN_CLIENT_ORG_CORP_NM_AN": "Harris/SolaCom ATC Solutions",
    "RGSTRNT_1ST_NM_PRENOM_DCLRNT": "ALEXANDER",
    "RGSTRNT_LAST_NM_DCLRNT": "WALDRUM",
    "EN_FIRM_NM_FIRME_AN": "Waldrum & Associates",
    "REG_TYPE_ENR": "1",
    "EFFECTIVE_DATE_VIGUEUR": "2009-11-20",
    "END_DATE_FIN": "2010-04-18",
    "GOVT_FUND_IND_FIN_GOUV": "N",
}


# ── validate() ────────────────────────────────────────────────────────────────

def test_validate_accepts_well_formed_rows():
    conn = OCLRegistrationsConnector()
    rows = [
        {"registration_num": "R1", "client_org": "Acme", "effective_date": "2026-01-01"},
        {"registration_num": "R2", "client_org": "Beta", "effective_date": None},
    ]
    result = conn.validate(rows)
    assert result.valid_count == 2
    assert result.rejected_count == 0


def test_validate_rejects_missing_registration_num():
    conn = OCLRegistrationsConnector()
    result = conn.validate([{"registration_num": None, "client_org": "Acme"}])
    assert result.valid_count == 0
    assert "registration_num" in result.rejected[0][1]


def test_validate_rejects_missing_client_org():
    conn = OCLRegistrationsConnector()
    result = conn.validate([{"registration_num": "R1", "client_org": None}])
    assert result.valid_count == 0
    assert "client_org" in result.rejected[0][1]


def test_validate_rejects_duplicate_registration_num_within_batch():
    conn = OCLRegistrationsConnector()
    rows = [
        {"registration_num": "R1", "client_org": "Acme"},
        {"registration_num": "R1", "client_org": "Acme (dup)"},
    ]
    result = conn.validate(rows)
    assert result.valid_count == 1
    assert result.rejected_count == 1
    assert "duplicate" in result.rejected[0][1]


def test_validate_rejects_malformed_date():
    conn = OCLRegistrationsConnector()
    result = conn.validate([{"registration_num": "R1", "client_org": "Acme", "effective_date": "not-a-date"}])
    assert result.valid_count == 0
    assert "effective_date" in result.rejected[0][1]


# ── estimate() ────────────────────────────────────────────────────────────────

def test_estimate_unknown_size_is_unsafe():
    conn = OCLRegistrationsConnector()
    result = asyncio.run(conn.estimate(DiscoveryResult(resource_url="https://x", estimated_size_bytes=None)))
    assert result.safe_to_run_uncapped is False


def test_estimate_small_file_is_safe():
    conn = OCLRegistrationsConnector()
    result = asyncio.run(conn.estimate(DiscoveryResult(resource_url="https://x", estimated_size_bytes=82_848_109)))
    assert result.safe_to_run_uncapped is True


def test_estimate_huge_file_is_unsafe():
    conn = OCLRegistrationsConnector()
    result = asyncio.run(conn.estimate(DiscoveryResult(resource_url="https://x", estimated_size_bytes=2_256_228_144)))
    assert result.safe_to_run_uncapped is False


# ── _parse() ──────────────────────────────────────────────────────────────────

def test_parse_picks_primary_export_not_first_file_in_zip():
    conn = OCLRegistrationsConnector()
    zip_bytes = _make_zip([REAL_SHAPED_ROW])
    rows = conn._parse(zip_bytes)
    assert len(rows) == 1
    row = rows[0]
    assert row["registration_num"] == "775615-4611-11"
    assert row["client_org"] == "Harris/SolaCom ATC Solutions"
    assert row["canonical_name"] == "harris solacom atc solutions"
    assert row["registrant_name"] == "ALEXANDER WALDRUM"
    assert row["firm_name"] == "Waldrum & Associates"
    assert row["effective_date"] == "2009-11-20"
    assert row["government_funding"] == "N"


def test_parse_treats_literal_null_string_as_none():
    conn = OCLRegistrationsConnector()
    row = dict(REAL_SHAPED_ROW)
    row["EN_FIRM_NM_FIRME_AN"] = "null"
    rows = conn._parse(_make_zip([row]))
    assert rows[0]["firm_name"] is None


def test_parse_respects_max_rows():
    conn = OCLRegistrationsConnector()
    rows_in = [dict(REAL_SHAPED_ROW, REG_NUM_ENR=f"R{i}") for i in range(10)]
    rows = conn._parse(_make_zip(rows_in), max_rows=3)
    assert len(rows) == 3


# ── backfill() / sync() / checkpoint() / health_check() integration ─────────

@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(rs, "DATA_DIR", tmp_path)
    monkeypatch.setattr(rs, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(rs, "MANIFESTS_DIR", tmp_path / "manifests")
    monkeypatch.setattr(rs, "CHECKPOINTS_DIR", tmp_path / "checkpoints")
    monkeypatch.setattr(rs, "QUARANTINE_DIR", tmp_path / "quarantine")
    yield


async def _make_session_maker(tmp_path, name):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / name}", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(db.Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def test_backfill_end_to_end_with_quarantine(tmp_path, monkeypatch):
    asyncio.run(_backfill_scenario(tmp_path, monkeypatch))


async def _backfill_scenario(tmp_path, monkeypatch):
    session_maker = await _make_session_maker(tmp_path, "ocl_reg.db")
    monkeypatch.setattr(db, "AsyncSessionLocal", session_maker)

    conn = OCLRegistrationsConnector()

    discovery = DiscoveryResult(resource_url="https://example.ca/registrations.zip",
                                 estimated_size_bytes=1000)
    monkeypatch.setattr(conn, "discover", lambda: _async_return(discovery))

    good = dict(REAL_SHAPED_ROW)
    bad = dict(REAL_SHAPED_ROW, REG_NUM_ENR="null")  # will fail validate() -> quarantined
    zip_bytes = _make_zip([good, bad])
    monkeypatch.setattr(conn, "download", lambda d: _async_return(zip_bytes))

    result = await conn.backfill()

    assert result["parsed"] == 2
    assert result["valid"] == 1
    assert result["rejected"] == 1
    assert result["added"] == 1

    from api.models.ocl_registration import OCLRegistration
    from sqlalchemy import select
    async with session_maker() as session:
        rows = (await session.execute(select(OCLRegistration))).scalars().all()
    assert len(rows) == 1
    assert rows[0].registration_num == "775615-4611-11"

    # Raw payload retained with real provenance.
    manifest = rs.MANIFESTS_DIR / "lobbying__ocl_registrations.jsonl"
    assert manifest.exists()

    # Rejected row was quarantined, not silently dropped.
    quarantined = list(rs.QUARANTINE_DIR.rglob("rejected_rows.json"))
    assert len(quarantined) == 1
    assert "rejected_rows.json.reason.txt" in str(list(rs.QUARANTINE_DIR.rglob("*.reason.txt"))[0])

    # Checkpoint was written.
    state = conn.checkpoint()
    assert state["added"] == 1
    assert state["valid"] == 1

    # Re-running backfill is idempotent (existence-check dedup).
    monkeypatch.setattr(conn, "discover", lambda: _async_return(discovery))
    monkeypatch.setattr(conn, "download", lambda d: _async_return(zip_bytes))
    result2 = await conn.backfill()
    assert result2["added"] == 0  # already exists
    async with session_maker() as session:
        rows2 = (await session.execute(select(OCLRegistration))).scalars().all()
    assert len(rows2) == 1  # still just one row, not duplicated

    # sync() respects the cooldown right after a backfill.
    sync_result = await conn.sync()
    assert sync_result["skipped"] is True


async def _async_return(value):
    return value


def test_health_check_reports_unhealthy_with_no_history(tmp_path, monkeypatch):
    asyncio.run(_health_check_scenario(tmp_path, monkeypatch))


async def _health_check_scenario(tmp_path, monkeypatch):
    session_maker = await _make_session_maker(tmp_path, "ocl_reg_health.db")
    monkeypatch.setattr(db, "AsyncSessionLocal", session_maker)

    conn = OCLRegistrationsConnector()
    status = await conn.health_check()
    assert status.healthy is False
    assert status.last_successful_import is None
    assert status.checkpoint_state is None
