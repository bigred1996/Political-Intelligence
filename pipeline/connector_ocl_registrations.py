"""OCL Lobbying Registrations, implemented against BaseConnector.

Proof-of-interface connector — the first (and so far only) source using the
shared discover/estimate/download/validate/backfill/sync/checkpoint/
health_check interface from pipeline/connector_base.py. Deliberately
self-contained: it duplicates the small CSV column-mapping fixed earlier this
session in pipeline/ingest.py:fetch_ocl_registration_rows rather than
importing it, so this new path and the existing production path (still used
by api/scheduler.py:_run_ocl_registrations) don't entangle. Both can be run
side by side; nothing about the existing scheduler job changes.
"""
from __future__ import annotations

import csv
import io
import re
import zipfile
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

from pipeline.connector_base import (
    BaseConnector, DiscoveryResult, EstimateResult, HealthStatus, ValidationResult,
)
from pipeline.entity_resolver import normalize

log = structlog.get_logger()

CKAN_API = "https://open.canada.ca/data/api/3/action"
OCL_REG_DATASET = "70ef2117-1095-4d77-80eb-b87f2bada2a4"
OCL_REG_URL_FALLBACK = "https://lobbycanada.gc.ca/media/mqbbmaqk/registrations_oct_cal.zip"
_OCL_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Above this, a full uncapped backfill risks materializing too much in memory
# at once on a host with ~10GB reliably available — the exact failure mode
# found in fetch_grant_rows's 2.25GB-into-a-list risk this same session.
_UNCAPPED_SAFE_BYTES = 500_000_000

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _clean(val: str | None) -> str | None:
    v = (val or "").strip()
    return v if v and v.lower() != "null" else None


class OCLRegistrationsConnector(BaseConnector):
    source_id = "ocl_registrations"
    category = "lobbying"

    async def discover(self) -> DiscoveryResult:
        """Resolve the current resource URL live via CKAN, then HEAD it for size."""
        url = OCL_REG_URL_FALLBACK
        fmt = "ZIP"
        try:
            async with httpx.AsyncClient(timeout=20) as c:
                r = await c.get(f"{CKAN_API}/package_show", params={"id": OCL_REG_DATASET})
                r.raise_for_status()
                for res in r.json()["result"]["resources"]:
                    if (res.get("format") or "").upper() == "CSV":
                        url = res["url"]
                        fmt = res.get("format")
                        break
        except Exception as exc:
            log.warning("ocl_registrations_discover_ckan_failed", error=str(exc))

        size = None
        last_modified = None
        try:
            async with httpx.AsyncClient(timeout=20, headers={"User-Agent": _OCL_UA},
                                          follow_redirects=True) as c:
                r = await c.head(url)
                if r.status_code < 400:
                    size = int(r.headers["content-length"]) if "content-length" in r.headers else None
                    last_modified = r.headers.get("last-modified")
        except Exception as exc:
            log.warning("ocl_registrations_discover_head_failed", url=url, error=str(exc))

        return DiscoveryResult(resource_url=url, estimated_size_bytes=size, format=fmt,
                                last_modified=last_modified, metadata={"dataset": OCL_REG_DATASET})

    async def estimate(self, discovery: DiscoveryResult) -> EstimateResult:
        size = discovery.estimated_size_bytes
        if size is None:
            return EstimateResult(estimated_rows=None, estimated_size_bytes=None,
                                   safe_to_run_uncapped=False,
                                   reason="discover() could not determine size (HEAD failed/blocked) — "
                                          "treat as unsafe until confirmed, don't assume small")
        safe = size <= _UNCAPPED_SAFE_BYTES
        # ~500 bytes/row is roughly what this CSV runs (82.8MB / 166,564 real
        # rows observed 2026-06-21) — a rough order-of-magnitude estimate, not
        # a precise count; good enough to size a progress bar, not to budget.
        rows_estimate = size // 500
        reason = (f"{size:,} bytes <= {_UNCAPPED_SAFE_BYTES:,} byte safety threshold"
                   if safe else
                   f"{size:,} bytes exceeds the {_UNCAPPED_SAFE_BYTES:,} byte uncapped-safe threshold "
                   f"for this host's available memory — cap max_rows or stream instead")
        return EstimateResult(estimated_rows=rows_estimate, estimated_size_bytes=size,
                               safe_to_run_uncapped=safe, reason=reason)

    async def download(self, discovery: DiscoveryResult) -> bytes:
        headers = {"User-Agent": _OCL_UA, "Accept": "*/*"}
        async with httpx.AsyncClient(timeout=360, headers=headers, follow_redirects=True) as c:
            r = await c.get(discovery.resource_url)
            r.raise_for_status()
            return r.content

    def _parse(self, zip_bytes: bytes, max_rows: int = 0) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
            primary = next((n for n in names if "primary" in n.lower()), None)
            if not primary:
                primary = next((n for n in names if "registration" in n.lower()), None)
            if not primary:
                primary = names[0]
            with zf.open(primary) as f:
                for row in csv.DictReader(io.TextIOWrapper(f, encoding="latin-1")):
                    client = _clean(row.get("EN_CLIENT_ORG_CORP_NM_AN"))
                    reg_num = _clean(row.get("REG_NUM_ENR"))
                    registrant = (
                        f"{(row.get('RGSTRNT_1ST_NM_PRENOM_DCLRNT') or '').strip()} "
                        f"{(row.get('RGSTRNT_LAST_NM_DCLRNT') or '').strip()}"
                    ).strip()
                    out.append({
                        "registration_num": reg_num, "client_org": client,
                        "canonical_name": normalize(client) if client else None,
                        "registrant_name": registrant or None,
                        "firm_name": _clean(row.get("EN_FIRM_NM_FIRME_AN")),
                        "registration_type": _clean(row.get("REG_TYPE_ENR")),
                        "status": None,
                        "effective_date": _clean(row.get("EFFECTIVE_DATE_VIGUEUR")),
                        "end_date": _clean(row.get("END_DATE_FIN")),
                        "subject_matters": [],
                        "federal_benefits": None,
                        "private_interests": None,
                        "government_funding": _clean(row.get("GOVT_FUND_IND_FIN_GOUV")),
                    })
                    if max_rows and len(out) >= max_rows:
                        break
        return out

    def validate(self, rows: list[dict[str, Any]]) -> ValidationResult:
        valid: list[dict[str, Any]] = []
        rejected: list[tuple[dict[str, Any], str]] = []
        seen_reg_nums: set[str] = set()
        for row in rows:
            reg_num = row.get("registration_num")
            client = row.get("client_org")
            if not reg_num:
                rejected.append((row, "missing registration_num (the dedup/unique key)"))
                continue
            if not client:
                rejected.append((row, "missing client_org"))
                continue
            if reg_num in seen_reg_nums:
                rejected.append((row, f"duplicate registration_num {reg_num!r} within this batch"))
                continue
            eff = row.get("effective_date")
            if eff is not None and not _DATE_RE.match(eff):
                rejected.append((row, f"effective_date {eff!r} doesn't look like YYYY-MM-DD"))
                continue
            seen_reg_nums.add(reg_num)
            valid.append(row)
        return ValidationResult(valid_rows=valid, rejected=rejected)

    async def _persist(self, rows: list[dict[str, Any]]) -> int:
        from sqlalchemy import select
        from api.database import AsyncSessionLocal
        from api.models.ocl_registration import OCLRegistration

        added = 0
        async with AsyncSessionLocal() as session:
            batch = 2000
            for i in range(0, len(rows), batch):
                for r in rows[i:i + batch]:
                    exists = (await session.execute(
                        select(OCLRegistration).where(
                            OCLRegistration.registration_num == r["registration_num"]
                        ).limit(1)
                    )).scalar_one_or_none()
                    if exists:
                        continue
                    session.add(OCLRegistration(**r))
                    added += 1
                await session.commit()
        return added

    async def backfill(self, *, max_rows: int = 0) -> dict[str, Any]:
        from pipeline.raw_storage import save_raw

        discovery = await self.discover()
        estimate = await self.estimate(discovery)
        if not estimate.safe_to_run_uncapped and max_rows == 0:
            log.warning("ocl_registrations_backfill_capped_for_safety", reason=estimate.reason)
            max_rows = 50_000  # arbitrary safe cap; explicit max_rows=N always wins

        content = await self.download(discovery)
        save_raw(self.category, self.source_id, "registrations_enregistrements_ocl_cal.zip",
                  content, source_url=discovery.resource_url)

        parsed = self._parse(content, max_rows=max_rows)
        validation = self.validate(parsed)
        if validation.rejected:
            from pipeline.raw_storage import quarantine
            import json
            quarantine(self.category, self.source_id, "rejected_rows.json",
                       json.dumps(validation.rejected[:1000], default=str).encode(),
                       reason=f"{validation.rejected_count} rows failed validate(); first 1000 saved")

        added = await self._persist(validation.valid_rows)
        self.checkpoint({
            "last_backfill_at": datetime.now(timezone.utc).isoformat(),
            "last_resource_url": discovery.resource_url,
            "parsed": len(parsed), "valid": validation.valid_count,
            "rejected": validation.rejected_count, "added": added,
        })
        return {
            "discovered_url": discovery.resource_url, "downloaded_bytes": len(content),
            "parsed": len(parsed), "valid": validation.valid_count,
            "rejected": validation.rejected_count, "added": added,
        }

    async def sync(self) -> dict[str, Any]:
        """OCL registrations is a full-snapshot bulk file, not a paginated
        incremental API — sync() is a cooldown-aware wrapper around
        backfill(), not a separate fetch path."""
        state = self.checkpoint()
        if state and state.get("last_backfill_at"):
            last = datetime.fromisoformat(state["last_backfill_at"])
            age_hours = (datetime.now(timezone.utc) - last).total_seconds() / 3600
            if age_hours < 24:
                return {"skipped": True, "reason": f"last backfill was {age_hours:.1f}h ago, cooldown is 24h"}
        return await self.backfill()

    async def health_check(self) -> HealthStatus:
        from sqlalchemy import select
        from api.database import AsyncSessionLocal
        from api.models.scheduler_log import SchedulerLog

        state = self.checkpoint()
        last_checked = None
        last_successful = None
        last_error = None
        try:
            async with AsyncSessionLocal() as session:
                row = (await session.execute(
                    select(SchedulerLog)
                    .where(SchedulerLog.job_id == self.source_id)
                    .order_by(SchedulerLog.started_at.desc())
                    .limit(1)
                )).scalar_one_or_none()
                if row:
                    last_checked = row.started_at.isoformat() if row.started_at else None
                    if row.status == "ok":
                        last_successful = row.finished_at.isoformat() if row.finished_at else None
                    else:
                        last_error = row.error
        except Exception as exc:
            return HealthStatus(healthy=False, last_checked=None, last_successful_import=None,
                                 last_error=str(exc), checkpoint_state=state,
                                 detail="health_check failed querying scheduler_log")

        healthy = last_error is None and (state is not None or last_successful is not None)
        detail = "healthy" if healthy else "no successful run on record"
        return HealthStatus(healthy=healthy, last_checked=last_checked,
                             last_successful_import=last_successful, last_error=last_error,
                             checkpoint_state=state, detail=detail)
