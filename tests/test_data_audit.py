"""Tests for Goal 12's ingestion-completeness audit engine
(pipeline/data_audit.py) — the module backing `scripts/nessus.py data ...`
and `GET /api/data/health`.

No live network: registry parsing reads a fixture yaml, DB metrics run
against a temp SQLite engine (mirrors tests/test_scheduler_ingest.py), and
raw_storage paths are isolated to tmp_path (mirrors tests/test_raw_storage.py).
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import api.database as db
import pipeline.data_audit as da
import pipeline.raw_storage as rs

from api.models import (  # noqa: F401 — register tables on Base.metadata
    appointment, catalogue_entry, contract, donation, entity, grant, ocl_registration,
    politician, regulation, report, request, scheduler_log, source_record,
)
from api.models.donation import Bill
from api.models.scheduler_log import SchedulerLog
from api.models.source_record import SourceRecord


@pytest.fixture(autouse=True)
def _isolated_raw_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(rs, "DATA_DIR", tmp_path)
    monkeypatch.setattr(rs, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(rs, "EXTRACTED_DIR", tmp_path / "extracted")
    monkeypatch.setattr(rs, "MANIFESTS_DIR", tmp_path / "manifests")
    monkeypatch.setattr(rs, "CHECKPOINTS_DIR", tmp_path / "checkpoints")
    monkeypatch.setattr(rs, "QUARANTINE_DIR", tmp_path / "quarantine")
    yield tmp_path


async def _temp_session_maker(tmp_path, name: str):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / name}", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(db.Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def _run(coro):
    return asyncio.run(coro)


# ── load_registry() ──────────────────────────────────────────────────────────

def test_load_registry_reads_sources_list(tmp_path):
    path = tmp_path / "registry.yaml"
    path.write_text(
        "sources:\n"
        "  - id: foo\n"
        "    name: Foo Source\n"
        "    enabled: true\n"
        "  - id: bar\n"
        "    name: Bar Source\n"
        "    enabled: false\n",
        encoding="utf-8",
    )
    registry = da.load_registry(path)
    assert {s["id"] for s in registry} == {"foo", "bar"}
    assert next(s for s in registry if s["id"] == "foo")["enabled"] is True


def test_load_registry_missing_file_returns_empty_list(tmp_path):
    assert da.load_registry(tmp_path / "does_not_exist.yaml") == []


# ── manifest_summary() ────────────────────────────────────────────────────────

def test_manifest_summary_counts_files_bytes_duplicates_and_flags_missing(tmp_path):
    manifests_dir = rs.MANIFESTS_DIR
    manifests_dir.mkdir(parents=True, exist_ok=True)

    present_file = tmp_path / "raw" / "present.csv"
    present_file.parent.mkdir(parents=True, exist_ok=True)
    present_file.write_bytes(b"hello")

    lines = [
        {"category": "lobbying", "source_id": "ocl_registrations", "path": str(present_file),
         "size": 5, "saved_at": "2026-01-01T00:00:00+00:00", "duplicate": False},
        {"category": "lobbying", "source_id": "ocl_registrations", "path": str(present_file),
         "size": 5, "saved_at": "2026-01-02T00:00:00+00:00", "duplicate": True},
        {"category": "lobbying", "source_id": "ocl_registrations", "path": str(tmp_path / "raw" / "gone.csv"),
         "size": 9, "saved_at": "2026-01-03T00:00:00+00:00", "duplicate": False},
    ]
    (manifests_dir / "lobbying__ocl_registrations.jsonl").write_text(
        "\n".join(json.dumps(line) for line in lines), encoding="utf-8")

    summary = da.manifest_summary()
    entry = summary["ocl_registrations"]
    assert entry["category"] == "lobbying"
    assert entry["entries"] == 3
    assert entry["files"] == 2          # the two non-duplicate entries
    assert entry["duplicates"] == 1
    assert entry["bytes"] == 14         # 5 (present) + 9 (gone) — both non-duplicate
    assert entry["last_saved_at"] == "2026-01-03T00:00:00+00:00"
    assert entry["missing_on_disk"] == [str(tmp_path / "raw" / "gone.csv")]


def test_manifest_summary_empty_when_no_manifests_dir():
    assert da.manifest_summary() == {}


# ── checkpoint_summary() ──────────────────────────────────────────────────────

def test_checkpoint_summary_detects_paginated_checkpoint():
    rs.write_checkpoint("orders_in_council", {
        "last_cursor": [2026], "status": "in_progress",
        "gaps": [{"cursor": 2024, "error": "timeout"}],
    })
    summary = da.checkpoint_summary("orders_in_council")
    assert summary["kind"] == "paginated"
    assert summary["status"] == "in_progress"
    assert summary["open_gaps"] == 1


def test_checkpoint_summary_detects_conditional_fetch_checkpoint():
    rs.write_checkpoint("grants_quarterly", {
        "_conditional_fetch_fingerprint": {"url": "https://example.test", "size": 100},
        "rows": 500,
    })
    summary = da.checkpoint_summary("grants_quarterly")
    assert summary["kind"] == "conditional_fetch"
    assert summary["status"] is None
    assert summary["open_gaps"] == 0


def test_checkpoint_summary_none_when_no_checkpoint():
    assert da.checkpoint_summary("never_run_source") is None


# ── _classify_backfill() ──────────────────────────────────────────────────────

def test_classify_backfill_zero_rows_is_not_started():
    assert da._classify_backfill(0, None, None) == "not_started"


def test_classify_backfill_complete_checkpoint_no_gaps_is_full():
    cp = {"status": "complete", "open_gaps": 0}
    assert da._classify_backfill(100, cp, None) == "full"


def test_classify_backfill_in_progress_checkpoint_is_partial():
    cp = {"status": "in_progress", "open_gaps": 0}
    assert da._classify_backfill(100, cp, None) == "partial"


def test_classify_backfill_complete_checkpoint_with_open_gaps_is_partial():
    cp = {"status": "complete", "open_gaps": 2}
    assert da._classify_backfill(100, cp, None) == "partial"


def test_classify_backfill_dropped_stream_with_committed_rows_is_partial():
    last_definitive = {"status": "error", "rows_added": 500}
    assert da._classify_backfill(500, None, last_definitive) == "partial"


def test_classify_backfill_clean_run_no_checkpoint_is_full():
    last_definitive = {"status": "ok", "rows_added": 500}
    assert da._classify_backfill(500, None, last_definitive) == "full"


# ── _is_stale() ───────────────────────────────────────────────────────────────

def test_is_stale_none_without_cadence_or_last_success():
    assert da._is_stale(None, None) is None
    assert da._is_stale("daily", None) is None


def test_is_stale_true_when_past_cadence_window():
    old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    assert da._is_stale("daily", {"finished_at": old}) is True


def test_is_stale_false_when_within_cadence_window():
    recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    assert da._is_stale("daily", {"finished_at": recent}) is False


def test_is_stale_none_for_unrecognized_cadence_label():
    recent = datetime.now(timezone.utc).isoformat()
    assert da._is_stale("n/a until licensed", {"finished_at": recent}) is None


# ── _years_present() / _missing_years() ──────────────────────────────────────

def test_missing_years_finds_gap_inside_range():
    assert da._missing_years({2020, 2021, 2023}) == [2022]


def test_missing_years_empty_set_returns_empty_list():
    assert da._missing_years(set()) == []


def test_years_present_rejects_garbage_year_but_keeps_anomalous_real_value(tmp_path):
    async def run():
        session_maker = await _temp_session_maker(tmp_path, "years.db")
        async with session_maker() as session:
            session.add_all([
                Bill(bill_number="C-1", title_en="A", introduced_date="2020-01-01"),
                Bill(bill_number="C-2", title_en="B", introduced_date="1899-01-01"),  # real anomaly, kept
                Bill(bill_number="C-3", title_en="C", introduced_date="4043-01-01"),  # garbage, rejected
            ])
            await session.commit()
            years = await da._years_present(session, Bill, "introduced_date")
        return years
    years = _run(run())
    assert years == {2020, 1899}


# ── tier1_metrics() ───────────────────────────────────────────────────────────

def test_tier1_metrics_computes_rows_dates_and_missing_years(tmp_path):
    async def run():
        session_maker = await _temp_session_maker(tmp_path, "tier1.db")
        async with session_maker() as session:
            session.add_all([
                Bill(bill_number="C-1", title_en="A", introduced_date="2020-01-01"),
                Bill(bill_number="C-2", title_en="B", introduced_date="2022-06-01"),
            ])
            await session.commit()
            return await da.tier1_metrics(session, deep=False)
    metrics = _run(run())
    bills = metrics["bills_daily"]
    assert bills["rows"] == 2
    assert bills["row_count_method"] == "exact"
    assert bills["earliest_date"] == "2020-01-01"
    assert bills["latest_date"] == "2022-06-01"
    assert bills["missing_years"] == [2021]
    assert bills["missing_years_computed"] is True
    # Tier1 ids with zero rows are still present (every job_id always appears).
    assert metrics["tribunal_decisions"]["rows"] == 0
    assert metrics["tribunal_decisions"]["missing_years_computed"] is False


def test_tier1_metrics_skips_date_range_for_big_tables_unless_deep(tmp_path):
    from api.models.contract import Contract

    async def run(deep: bool):
        session_maker = await _temp_session_maker(tmp_path, f"contracts-{deep}.db")
        async with session_maker() as session:
            session.add(Contract(vendor_name="Acme", canonical_name="acme", contract_date="2024-01-01"))
            await session.commit()
            return await da.tier1_metrics(session, deep=deep)

    shallow = _run(run(False))["contracts_monthly"]
    assert shallow["rows"] == 1
    assert shallow["row_count_method"] == "max_id"
    assert shallow["earliest_date"] is None
    assert shallow["missing_years_computed"] is False

    deep = _run(run(True))["contracts_monthly"]
    assert deep["earliest_date"] == "2024-01-01"
    assert deep["missing_years_computed"] is True


# ── breadth_metrics() ─────────────────────────────────────────────────────────

def test_breadth_metrics_groups_by_source_with_dates(tmp_path):
    async def run():
        session_maker = await _temp_session_maker(tmp_path, "breadth.db")
        async with session_maker() as session:
            session.add_all([
                SourceRecord(source="npri", title="A", event_date="2021-01-01"),
                SourceRecord(source="npri", title="B", event_date="2023-01-01"),
                SourceRecord(source="cer", title="C", event_date="2022-05-01"),
            ])
            await session.commit()
            return await da.breadth_metrics(session, deep=True)
    metrics = _run(run())
    assert metrics["npri"]["rows"] == 2
    assert metrics["npri"]["earliest_date"] == "2021-01-01"
    assert metrics["npri"]["missing_years"] == [2022]
    assert metrics["cer"]["rows"] == 1
    assert "statcan" not in metrics  # zero rows -> no GROUP BY row at all


def test_breadth_metrics_skips_years_for_large_source_unless_deep(tmp_path):
    async def run(deep: bool):
        session_maker = await _temp_session_maker(tmp_path, f"breadth-big-{deep}.db")
        async with session_maker() as session:
            session.add_all(
                SourceRecord(source="npri", title=f"r{i}", event_date="2020-01-01") for i in range(3)
            )
            await session.commit()
            old = da._BREADTH_DEEP_ROW_THRESHOLD
            try:
                da._BREADTH_DEEP_ROW_THRESHOLD = 1  # force "large" classification with only 3 rows
                return await da.breadth_metrics(session, deep=deep)
            finally:
                da._BREADTH_DEEP_ROW_THRESHOLD = old
    shallow = _run(run(False))["npri"]
    assert shallow["missing_years_computed"] is False
    deep = _run(run(True))["npri"]
    assert deep["missing_years_computed"] is True


# ── run_validation() ──────────────────────────────────────────────────────────

def _source(**overrides):
    base = {
        "id": "x", "wired_in_scheduler": True, "rows": 10, "last_run": None,
        "checkpoint": None, "stale": False, "earliest_date": None, "latest_date": None,
    }
    base.update(overrides)
    return base


def test_run_validation_flags_enabled_yaml_source_with_no_scheduler_job():
    registry = [{"id": "ghost_source", "enabled": True}]
    checks = da.run_validation([], registry, wired_ids=set(), disk={"free_pct": 50}, manifests={})
    check = next(c for c in checks if c["check"] == "registry_enabled_sources_are_wired")
    assert check["status"] == "warn"
    assert "ghost_source" in check["detail"]


def test_run_validation_flags_wired_source_with_zero_rows():
    sources = [_source(id="empty_source", rows=0)]
    checks = da.run_validation(sources, [], {"empty_source"}, {"free_pct": 50}, {})
    check = next(c for c in checks if c["check"] == "wired_sources_have_data")
    assert check["status"] == "fail"
    assert "empty_source" in check["detail"]


def test_run_validation_flags_low_disk_headroom():
    checks = da.run_validation([], [], set(), {"free_pct": 2.0}, {})
    check = next(c for c in checks if c["check"] == "disk_headroom")
    assert check["status"] == "fail"


def test_run_validation_passes_disk_headroom_when_plenty_free():
    checks = da.run_validation([], [], set(), {"free_pct": 40.0}, {})
    check = next(c for c in checks if c["check"] == "disk_headroom")
    assert check["status"] == "pass"


def test_run_validation_flags_implausible_dates():
    sources = [_source(id="weird_source", earliest_date="1899-01-01")]
    checks = da.run_validation(sources, [], {"weird_source"}, {"free_pct": 50}, {})
    check = next(c for c in checks if c["check"] == "dates_within_plausible_range")
    assert check["status"] == "warn"
    assert "weird_source" in check["detail"]


def test_run_validation_flags_missing_manifest_files():
    manifests = {"some_source": {"missing_on_disk": ["data/raw/gone.csv"]}}
    checks = da.run_validation([], [], set(), {"free_pct": 50}, manifests)
    check = next(c for c in checks if c["check"] == "manifest_files_exist_on_disk")
    assert check["status"] == "fail"


# ── build_inventory() — end-to-end smoke test ────────────────────────────────

def test_build_inventory_assembles_full_report(tmp_path, monkeypatch):
    registry_path = tmp_path / "registry.yaml"
    registry_path.write_text(
        "sources:\n"
        "  - id: bills_daily\n"
        "    name: Bills\n"
        "    category: parliament\n"
        "    enabled: true\n"
        "  - id: not_a_real_job\n"
        "    name: Phantom\n"
        "    enabled: true\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(da, "REGISTRY_PATH", registry_path)

    async def run():
        session_maker = await _temp_session_maker(tmp_path, "inventory.db")
        async with session_maker() as session:
            session.add(Bill(bill_number="C-1", title_en="A", introduced_date="2020-01-01"))
            session.add(SchedulerLog(job_id="bills_daily", source_name="Bills", status="ok",
                                      rows_added=1, rows_total=1))
            await session.commit()
            return await da.build_inventory(session, deep=False)

    inventory = _run(run())
    assert inventory["registry_summary"]["total_registered"] == 2
    assert inventory["registry_summary"]["enabled_in_registry"] == 2

    bills = next(s for s in inventory["sources"] if s["id"] == "bills_daily")
    assert bills["rows"] == 1
    assert bills["wired_in_scheduler"] is True
    assert bills["enabled_in_registry"] is True
    assert bills["backfill_state"] == "full"
    assert bills["last_success"]["status"] == "ok"

    assert any(c["check"] == "wired_jobs_are_documented" for c in inventory["validate"])
    assert "disk" in inventory and "totals" in inventory
