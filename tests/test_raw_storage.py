"""Tests for the raw-storage / manifest / checkpoint / quarantine module.

This is the cross-cutting infrastructure piece flagged repeatedly during the
2026-06-21 ingestion audit: no connector retained a raw payload, had a
checkpoint to resume from, or quarantined invalid records instead of dropping
them. These tests prove the new shared helpers actually do all three
correctly — not just that they run without raising.
"""
from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import pipeline.raw_storage as rs


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(rs, "DATA_DIR", tmp_path)
    monkeypatch.setattr(rs, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(rs, "EXTRACTED_DIR", tmp_path / "extracted")
    monkeypatch.setattr(rs, "MANIFESTS_DIR", tmp_path / "manifests")
    monkeypatch.setattr(rs, "CHECKPOINTS_DIR", tmp_path / "checkpoints")
    monkeypatch.setattr(rs, "QUARANTINE_DIR", tmp_path / "quarantine")
    monkeypatch.setattr(rs, "LOGS_DIR", tmp_path / "logs")
    yield tmp_path


def test_unknown_category_rejected():
    with pytest.raises(ValueError, match="Unknown raw-storage category"):
        rs.save_raw("not-a-real-category", "some_source", "f.csv", b"data")


def test_save_raw_writes_file_and_manifest_entry(tmp_path):
    result = rs.save_raw("lobbying", "ocl_registrations", "registrations.zip", b"hello world",
                          run_id="20260621T220000Z", source_url="https://example.ca/r.zip")
    assert result["duplicate"] is False
    # Date subdirectories reflect when the save actually happened (wall-clock
    # "now"), not the caller-supplied run_id string. The leaf directory is
    # "<run_id>-<checksum prefix>", not run_id alone — see
    # test_save_raw_writes_new_file_when_content_changes for why that suffix
    # is load-bearing (same-second saves of different content must not collide).
    now = datetime.now(timezone.utc)
    checksum = rs._sha256(b"hello world")
    saved_path = (rs.RAW_DIR / "lobbying" / "ocl_registrations" / now.strftime("%Y") /
                  now.strftime("%m") / now.strftime("%d") / f"20260621T220000Z-{checksum[:8]}" / "registrations.zip")
    assert saved_path.exists()
    assert saved_path.read_bytes() == b"hello world"
    assert result["checksum"] == rs._sha256(b"hello world")
    assert result["size"] == len(b"hello world")
    assert result["source_url"] == "https://example.ca/r.zip"

    manifest_path = rs.MANIFESTS_DIR / "lobbying__ocl_registrations.jsonl"
    assert manifest_path.exists()
    entries = [json.loads(line) for line in manifest_path.read_text().splitlines()]
    assert len(entries) == 1
    assert entries[0]["checksum"] == result["checksum"]


def test_save_raw_dedupes_identical_content_but_still_records_the_check():
    first = rs.save_raw("lobbying", "ocl_registrations", "registrations.zip", b"same bytes")
    second = rs.save_raw("lobbying", "ocl_registrations", "registrations.zip", b"same bytes")

    assert first["duplicate"] is False
    assert second["duplicate"] is True
    assert second["path"] == first["path"]  # no new file written

    # Only ONE physical file should exist even though save_raw was called twice.
    raw_files = list((rs.RAW_DIR / "lobbying" / "ocl_registrations").rglob("registrations.zip"))
    assert len(raw_files) == 1

    # But the manifest has TWO entries — "last checked" must be distinguishable
    # from "last changed".
    manifest_path = rs.MANIFESTS_DIR / "lobbying__ocl_registrations.jsonl"
    entries = [json.loads(line) for line in manifest_path.read_text().splitlines()]
    assert len(entries) == 2
    assert entries[0]["duplicate"] is False
    assert entries[1]["duplicate"] is True


def test_save_raw_writes_new_file_when_content_changes():
    first = rs.save_raw("lobbying", "ocl_registrations", "registrations.zip", b"version one")
    second = rs.save_raw("lobbying", "ocl_registrations", "registrations.zip", b"version two, changed")

    assert second["duplicate"] is False
    assert second["checksum"] != first["checksum"]
    assert second["path"] != first["path"]
    assert (rs.RAW_DIR / "lobbying" / "ocl_registrations" / "registrations.zip").exists() is False  # not at category root
    raw_files = list((rs.RAW_DIR / "lobbying" / "ocl_registrations").rglob("registrations.zip"))
    assert len(raw_files) == 2  # both versions retained — immutable, never overwritten


def test_checkpoint_round_trip():
    assert rs.read_checkpoint("gc_news") is None

    rs.write_checkpoint("gc_news", {"cursor": "page-42", "last_external_id": "abc123"})
    state = rs.read_checkpoint("gc_news")
    assert state["cursor"] == "page-42"
    assert state["last_external_id"] == "abc123"
    assert "updated_at" in state

    rs.write_checkpoint("gc_news", {"cursor": "page-43"})
    updated = rs.read_checkpoint("gc_news")
    assert updated["cursor"] == "page-43"
    assert "last_external_id" not in updated  # full overwrite, not a merge


def test_quarantine_saves_payload_and_reason():
    path = rs.quarantine("statcan", "statcan_cube_123", "bad_row.json", b'{"broken": tru',
                          reason="invalid JSON: unterminated literal", run_id="20260621T999999Z")
    assert path.exists()
    assert path.read_bytes() == b'{"broken": tru'
    reason_path = path.with_name(path.name + ".reason.txt")
    assert reason_path.exists()
    assert "unterminated literal" in reason_path.read_text()


def test_quarantine_rejects_unknown_category():
    with pytest.raises(ValueError, match="Unknown raw-storage category"):
        rs.quarantine("not-a-category", "x", "f.json", b"{}", reason="test")


# ── Goal 6: extract_zip() / count_csv_rows() / backfill records ─────────────

def _make_zip_bytes(members: dict[str, bytes]) -> bytes:
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in members.items():
            zf.writestr(name, content)
    return buf.getvalue()


def test_extract_zip_writes_members_and_validates():
    zip_bytes = _make_zip_bytes({"a.csv": b"col1,col2\n1,2\n3,4\n", "b.csv": b"x,y\n5,6\n"})
    save_result = rs.save_raw("npri", "npri_bulk", "bulk.zip", zip_bytes, run_id="20260622T000000Z")

    result = rs.extract_zip(save_result)
    assert result["extraction_validated"] is True
    assert {f["name"] for f in result["files"]} == {"a.csv", "b.csv"}

    extracted_dir = Path(result["extracted_path"])
    assert (extracted_dir / "a.csv").read_bytes() == b"col1,col2\n1,2\n3,4\n"
    assert (extracted_dir / "b.csv").read_bytes() == b"x,y\n5,6\n"


def test_extract_zip_detects_non_zip_content():
    save_result = rs.save_raw("npri", "npri_bulk", "not_a_zip.csv", b"col1,col2\n1,2\n",
                               run_id="20260622T000001Z")
    result = rs.extract_zip(save_result)
    assert result["extraction_validated"] is False
    assert "not a ZIP" in result["reason"]


def test_extract_zip_detects_empty_member():
    zip_bytes = _make_zip_bytes({"empty.csv": b""})
    save_result = rs.save_raw("npri", "npri_bulk", "bulk2.zip", zip_bytes, run_id="20260622T000002Z")
    result = rs.extract_zip(save_result)
    assert result["extraction_validated"] is False
    assert "empty.csv" in result["reason"]


def test_count_csv_rows(tmp_path):
    p = tmp_path / "data.csv"
    p.write_text("header1,header2\nval1,val2\nval3,val4\nval5,val6\n", encoding="latin-1")
    assert rs.count_csv_rows(p) == 3


def test_count_csv_rows_header_only(tmp_path):
    p = tmp_path / "data.csv"
    p.write_text("header1,header2\n", encoding="latin-1")
    assert rs.count_csv_rows(p) == 0


def test_count_csv_rows_empty_file(tmp_path):
    p = tmp_path / "data.csv"
    p.write_text("", encoding="latin-1")
    assert rs.count_csv_rows(p) == 0


def test_record_backfill_round_trip():
    assert rs.read_backfill_record("npri", "npri_bulk") is None

    record = rs.record_backfill("npri", "npri_bulk", covered_years=[2024, 2020, 2022],
                                 row_count=60202, extraction_validated=True,
                                 source_checksum="abc123", source_size_bytes=999,
                                 notes="single recent year only")
    assert record["covered_years"] == [2020, 2022, 2024]  # sorted

    read_back = rs.read_backfill_record("npri", "npri_bulk")
    assert read_back["row_count"] == 60202
    assert read_back["extraction_validated"] is True
    assert read_back["notes"] == "single recent year only"


def test_record_backfill_rejects_unknown_category():
    with pytest.raises(ValueError, match="Unknown raw-storage category"):
        rs.record_backfill("not-a-category", "x")


@pytest.mark.asyncio
async def test_save_raw_streamed_writes_file_with_correct_checksum(httpx_mock):
    content = b"a" * 50_000  # large enough to span multiple chunks
    httpx_mock.add_response(content=content)

    result = await rs.save_raw_streamed("elections-canada", "donations_quarterly", "donations.csv",
                                         "https://example.ca/donations.csv", run_id="20260622T010000Z")
    assert result["duplicate"] is False
    assert result["size"] == len(content)
    assert result["checksum"] == rs._sha256(content)
    assert Path(result["path"]).read_bytes() == content
    # No leftover staging file.
    staging_dir = rs.RAW_DIR / "elections-canada" / "donations_quarterly" / "_staging"
    assert list(staging_dir.glob("*.partial")) == []


@pytest.mark.asyncio
async def test_save_raw_streamed_dedupes_identical_content(httpx_mock):
    content = b"b" * 10_000
    httpx_mock.add_response(content=content)
    httpx_mock.add_response(content=content)

    first = await rs.save_raw_streamed("elections-canada", "donations_quarterly", "donations.csv",
                                        "https://example.ca/donations.csv", run_id="20260622T010001Z")
    second = await rs.save_raw_streamed("elections-canada", "donations_quarterly", "donations.csv",
                                         "https://example.ca/donations.csv", run_id="20260622T010002Z")
    assert first["duplicate"] is False
    assert second["duplicate"] is True
    assert second["path"] == first["path"]
    matches = list((rs.RAW_DIR / "elections-canada" / "donations_quarterly").rglob("donations.csv"))
    assert len(matches) == 1


def test_all_backfill_records_aggregates_across_sources():
    assert rs.all_backfill_records() == []

    rs.record_backfill("npri", "npri_bulk", row_count=60202, extraction_validated=True)
    rs.record_backfill("lobbying", "ocl_registrations", row_count=166564, extraction_validated=True)

    records = rs.all_backfill_records()
    assert len(records) == 2
    source_ids = {r["source_id"] for r in records}
    assert source_ids == {"npri_bulk", "ocl_registrations"}
