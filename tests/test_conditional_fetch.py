"""Tests for the conditional-fetch gate (Goal 11).

Proves the actual behavior the goal asks for: a sync call against an
unchanged resource does no real work (skips the download), a changed
resource is always treated as worth fetching, and an unreadable signal
(HEAD blocked, CKAN lookup failed) fails open to "fetch it" rather than
silently skipping real work.
"""
from __future__ import annotations

from typing import Any

import httpx
import pytest

import pipeline.conditional_fetch as cf
import pipeline.raw_storage as rs


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(rs, "DATA_DIR", tmp_path)
    monkeypatch.setattr(rs, "CHECKPOINTS_DIR", tmp_path / "checkpoints")
    yield tmp_path


# ── unchanged() / record() — no network involved ────────────────────────────

def test_first_ever_check_is_never_unchanged():
    fp = cf.ResourceFingerprint(url="https://x/y.csv", last_modified="Mon, 01 Jun 2026 00:00:00 GMT", size=100)
    assert cf.unchanged("src_a", fp) is False


def test_identical_fingerprint_after_record_is_unchanged():
    fp = cf.ResourceFingerprint(url="https://x/y.csv", last_modified="Mon, 01 Jun 2026 00:00:00 GMT", size=100)
    cf.record("src_b", fp, rows_added=42)
    assert cf.unchanged("src_b", fp) is True


def test_changed_size_is_not_unchanged():
    fp1 = cf.ResourceFingerprint(url="https://x/y.csv", last_modified="Mon, 01 Jun 2026 00:00:00 GMT", size=100)
    cf.record("src_c", fp1)
    fp2 = cf.ResourceFingerprint(url="https://x/y.csv", last_modified="Mon, 01 Jun 2026 00:00:00 GMT", size=999)
    assert cf.unchanged("src_c", fp2) is False


def test_changed_last_modified_is_not_unchanged():
    fp1 = cf.ResourceFingerprint(url="https://x/y.csv", last_modified="Mon, 01 Jun 2026 00:00:00 GMT", size=100)
    cf.record("src_d", fp1)
    fp2 = cf.ResourceFingerprint(url="https://x/y.csv", last_modified="Tue, 02 Jun 2026 00:00:00 GMT", size=100)
    assert cf.unchanged("src_d", fp2) is False


def test_rotated_url_is_not_unchanged_even_if_other_fields_match():
    fp1 = cf.ResourceFingerprint(url="https://x/old.csv", last_modified="Mon, 01 Jun 2026 00:00:00 GMT", size=100)
    cf.record("src_e", fp1)
    fp2 = cf.ResourceFingerprint(url="https://x/new.csv", last_modified="Mon, 01 Jun 2026 00:00:00 GMT", size=100)
    assert cf.unchanged("src_e", fp2) is False


def test_unreadable_fingerprint_fails_open_to_a_real_fetch():
    # Every comparable field is None (HEAD blocked / CKAN call failed) — must
    # never be treated as "unchanged", even against an identical prior record.
    blank = cf.ResourceFingerprint(url="https://x/y.csv")
    cf.record("src_f", blank)
    assert cf.unchanged("src_f", blank) is False


def test_record_persists_extra_bookkeeping_fields():
    fp = cf.ResourceFingerprint(url="https://x/y.csv", size=100)
    cf.record("src_g", fp, rows_added=7, last_run_status="ok")
    checkpoint = rs.read_checkpoint("src_g")
    assert checkpoint["rows_added"] == 7
    assert checkpoint["last_run_status"] == "ok"
    assert checkpoint[cf._KEY]["size"] == 100


# ── fingerprint_url() / fingerprint_ckan_resource() — fake transport ───────

_RealAsyncClient = httpx.AsyncClient


def _client_with(handler):
    def _make_client(**kwargs):
        kwargs.pop("follow_redirects", None)
        kwargs.pop("transport", None)
        return _RealAsyncClient(transport=httpx.MockTransport(handler), **kwargs)
    return _make_client


@pytest.mark.asyncio
async def test_fingerprint_url_reads_head_headers(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "HEAD"
        return httpx.Response(200, headers={"last-modified": "Mon, 01 Jun 2026 00:00:00 GMT",
                                            "content-length": "12345", "etag": '"abc"'})
    monkeypatch.setattr(cf.httpx, "AsyncClient", _client_with(handler))
    fp = await cf.fingerprint_url("https://elections.ca/donations.zip")
    assert fp.last_modified == "Mon, 01 Jun 2026 00:00:00 GMT"
    assert fp.size == 12345
    assert fp.etag == '"abc"'


@pytest.mark.asyncio
async def test_fingerprint_url_4xx_returns_blank_fingerprint(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)
    monkeypatch.setattr(cf.httpx, "AsyncClient", _client_with(handler))
    fp = await cf.fingerprint_url("https://elections.ca/gone.zip")
    assert fp.last_modified is None and fp.size is None
    # A 4xx fingerprint must fail open, not be cached as a stable "unchanged" state.
    assert cf.unchanged("src_404", fp) is False


@pytest.mark.asyncio
async def test_fingerprint_url_network_error_returns_blank_fingerprint(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")
    monkeypatch.setattr(cf.httpx, "AsyncClient", _client_with(handler))
    fp = await cf.fingerprint_url("https://elections.ca/unreachable.zip")
    assert fp == cf.ResourceFingerprint(url="https://elections.ca/unreachable.zip")


@pytest.mark.asyncio
async def test_fingerprint_ckan_resource_picks_largest_csv_when_asked(monkeypatch):
    payload: dict[str, Any] = {"result": {"resources": [
        {"format": "CSV", "name": "Nothing to report", "url": "https://x/tiny.csv",
         "size": 100, "last_modified": "2026-01-01"},
        {"format": "CSV", "name": "grants and contributions", "url": "https://x/real.csv",
         "size": 2_000_000_000, "last_modified": "2026-06-01", "hash": "deadbeef"},
        {"format": "XML", "name": "metadata", "url": "https://x/meta.xml", "size": 50},
    ]}}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)
    monkeypatch.setattr(cf.httpx, "AsyncClient", _client_with(handler))

    fp = await cf.fingerprint_ckan_resource("dataset-id", pick="largest")
    assert fp.url == "https://x/real.csv"
    assert fp.size == 2_000_000_000
    assert fp.hash == "deadbeef"


@pytest.mark.asyncio
async def test_fingerprint_ckan_resource_network_error_fails_open(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")
    monkeypatch.setattr(cf.httpx, "AsyncClient", _client_with(handler))
    fp = await cf.fingerprint_ckan_resource("dataset-id")
    assert fp.url is None
    assert cf.unchanged("src_ckan_down", fp) is False


@pytest.mark.asyncio
async def test_fingerprint_ckan_resource_no_matching_format_returns_blank(monkeypatch):
    payload = {"result": {"resources": [{"format": "XLSX", "url": "https://x/y.xlsx", "size": 10}]}}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)
    monkeypatch.setattr(cf.httpx, "AsyncClient", _client_with(handler))

    fp = await cf.fingerprint_ckan_resource("dataset-id")
    assert fp.url is None
