"""Shared connector interface.

Adapts the ingestion spec's discover/backfill/fetch_incremental/normalize/
validate/persist/link_entities/checkpoint/health_check list down to 8
concrete methods, building directly on the raw-storage/checkpoint/quarantine
infrastructure in pipeline/raw_storage.py (built 2026-06-21, same session).

This is ADDITIVE, not a replacement: the existing two-tier system (hand-wired
Tier 1 jobs in api/scheduler.py + the declarative Tier 2 registry in
pipeline/connectors.py) keeps working exactly as it does today. Nothing here
changes their behavior. This interface is for connectors that adopt it going
forward — proven on exactly one real connector so far
(connector_ocl_registrations.py:OCLRegistrationsConnector), not yet a
repo-wide rewrite.

Method contracts:
    discover()      — probe the source for its CURRENT resource location/size
                       without downloading the full payload. Must resolve
                       live (e.g. via CKAN package_show), never trust a
                       hardcoded URL — that exact assumption broke two real
                       connectors earlier this session (ocl_registrations,
                       and would have broken ocl_monthly next).
    estimate()       — given discover()'s result, decide whether a full
                       backfill is safe to run uncapped on this host right
                       now (size vs available memory/disk), or whether it
                       needs capping/streaming first. fetch_grant_rows's
                       2.25GB-into-a-list risk earlier this session is
                       exactly the failure mode this method exists to catch
                       BEFORE a connector is triggered, not after.
    download()       — fetch raw bytes only. Does not parse, does not
                       persist to the DB. Callers are expected to pass the
                       result through pipeline.raw_storage.save_raw() for
                       provenance before parsing it.
    validate()       — given parsed rows, split into valid vs
                       quarantine-worthy with a concrete reason per
                       rejection. Never silently drops a row — that's the
                       behavior fetch_ocl_registration_rows's bare
                       `continue` has today, which this interface considers
                       a defect to design out, not a pattern to copy forward.
    backfill()       — full historical load: discover -> download -> save_raw
                       -> parse -> validate -> persist. Returns a summary.
    sync()           — incremental refresh using checkpoint() state.
    checkpoint()     — read (no args) or write (state=...) cursor/resume
                       state for this source. Thin wrapper over
                       pipeline.raw_storage.read_checkpoint/write_checkpoint
                       — provided as a base-class default, not abstract.
    health_check()   — lightweight status: last checked, last successful
                       import, last error, current checkpoint. Should be
                       cheap enough to call from an admin/status page.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class DiscoveryResult:
    """What discover() found before committing to a download."""
    resource_url: str
    estimated_size_bytes: int | None = None
    format: str | None = None
    last_modified: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EstimateResult:
    """What estimate() projects for a prospective backfill."""
    estimated_rows: int | None
    estimated_size_bytes: int | None
    safe_to_run_uncapped: bool
    reason: str


@dataclass
class ValidationResult:
    """Output of validate(): which rows are usable, and why the rest aren't."""
    valid_rows: list[dict[str, Any]]
    rejected: list[tuple[dict[str, Any], str]]  # (row, reason)

    @property
    def valid_count(self) -> int:
        return len(self.valid_rows)

    @property
    def rejected_count(self) -> int:
        return len(self.rejected)


@dataclass
class HealthStatus:
    """Output of health_check()."""
    healthy: bool
    last_checked: str | None
    last_successful_import: str | None
    last_error: str | None
    checkpoint_state: dict[str, Any] | None
    detail: str


class BaseConnector(ABC):
    """One connector instance per source. See module docstring for contracts."""

    source_id: str
    category: str

    @abstractmethod
    async def discover(self) -> DiscoveryResult:
        """Probe the source; resolve the current resource location live."""

    @abstractmethod
    async def estimate(self, discovery: DiscoveryResult) -> EstimateResult:
        """Decide whether a full backfill is safe to run uncapped right now."""

    @abstractmethod
    async def download(self, discovery: DiscoveryResult) -> bytes:
        """Fetch raw bytes only — no parsing, no persistence."""

    @abstractmethod
    def validate(self, rows: list[dict[str, Any]]) -> ValidationResult:
        """Split parsed rows into valid vs quarantine-worthy with reasons."""

    @abstractmethod
    async def backfill(self, *, max_rows: int = 0) -> dict[str, Any]:
        """Full historical load. Returns a summary dict."""

    @abstractmethod
    async def sync(self) -> dict[str, Any]:
        """Incremental refresh using checkpoint() state. Returns a summary dict."""

    def checkpoint(self, state: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """Read the checkpoint (state=None) or write a new one (state=dict)."""
        from pipeline.raw_storage import read_checkpoint, write_checkpoint
        if state is None:
            return read_checkpoint(self.source_id)
        write_checkpoint(self.source_id, state)
        return state

    @abstractmethod
    async def health_check(self) -> HealthStatus:
        """Lightweight status: last checked/succeeded/errored, checkpoint state."""
