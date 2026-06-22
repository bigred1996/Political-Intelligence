"""Shared raw-storage, manifest, checkpoint, and quarantine helpers.

This is the cross-cutting piece every connector audit this session flagged as
missing: no source retained its original payload, no source had a checkpoint
to resume from, and nothing had anywhere to put a record that failed
validation other than silently dropping it. This module gives every connector
one place to do all three, instead of reinventing it per-source.

Layout under data/ (each created on demand, mirrors the data-ingestion goal):
    raw/<category>/<source_id>/<year>/<month>/<day>/<run_id>/<filename>
    manifests/<category>__<source_id>.jsonl   (one line per save_raw call)
    checkpoints/<source_id>.json               (one JSON object, overwritten)
    quarantine/<category>/<source_id>/<run_id>/<filename> (+ .reason.txt sidecar)

Raw files are immutable once written — a second save_raw() for the same
source whose content hash matches the most recent manifest entry is recorded
as a no-op (manifest entry written, no duplicate file) rather than silently
skipped or silently re-saved, per "do not hide failures" / "avoid keeping
identical duplicates".
"""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger()

DATA_DIR = Path("./data")
RAW_DIR = DATA_DIR / "raw"
EXTRACTED_DIR = DATA_DIR / "extracted"
MANIFESTS_DIR = DATA_DIR / "manifests"
CHECKPOINTS_DIR = DATA_DIR / "checkpoints"
QUARANTINE_DIR = DATA_DIR / "quarantine"
LOGS_DIR = DATA_DIR / "logs"

# The category set is intentionally closed — an unknown category is almost
# always a typo, and a silently-created stray directory is exactly the kind
# of thing this module exists to prevent elsewhere.
CATEGORIES = frozenset({
    "open-government", "parliament", "elections-canada", "lobbying", "statcan",
    "bank-of-canada", "iaac", "cer", "npri", "transport-canada", "canada-gazette",
    "canadabuys", "proactive-disclosure", "courts", "geospatial",
    "government-news", "news-rss", "orders-in-council", "canadian-news",
})


def _check_category(category: str) -> None:
    if category not in CATEGORIES:
        raise ValueError(f"Unknown raw-storage category {category!r}; must be one of {sorted(CATEGORIES)}")


def _now_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _manifest_path(category: str, source_id: str) -> Path:
    return MANIFESTS_DIR / f"{category}__{source_id}.jsonl"


def _last_manifest_entry(category: str, source_id: str) -> dict[str, Any] | None:
    path = _manifest_path(category, source_id)
    if not path.exists():
        return None
    last_line = None
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                last_line = line
    return json.loads(last_line) if last_line else None


def save_raw(category: str, source_id: str, filename: str, content: bytes, *,
             run_id: str | None = None, source_url: str | None = None) -> dict[str, Any]:
    """Persist an immutable raw payload and append a manifest record.

    Returns a dict describing what happened: {"path", "checksum", "size",
    "run_id", "duplicate"}. `duplicate=True` means the content hash matched
    the previous save for this (category, source_id) — no new file was
    written, but the manifest still records that this run checked and found
    no change (this IS the "last checked" signal the spec asks for).
    """
    _check_category(category)
    run_id = run_id or _now_run_id()
    checksum = _sha256(content)
    now = datetime.now(timezone.utc)

    previous = _last_manifest_entry(category, source_id)
    duplicate = previous is not None and previous.get("checksum") == checksum

    if duplicate:
        path = Path(previous["path"])
    else:
        # The checksum suffix is load-bearing, not cosmetic: two saves with
        # different content can land in the same wall-clock second (run_id
        # only has second resolution), and without something content-derived
        # in the path, the second save would silently overwrite the first —
        # breaking the "raw files are immutable, never overwritten" guarantee.
        leaf_dir = f"{run_id}-{checksum[:8]}"
        day_dir = RAW_DIR / category / source_id / now.strftime("%Y") / now.strftime("%m") / now.strftime("%d") / leaf_dir
        day_dir.mkdir(parents=True, exist_ok=True)
        path = day_dir / filename
        path.write_bytes(content)

    return _append_manifest_entry(category, source_id, filename, path, checksum,
                                   len(content), run_id, source_url, duplicate, now)


def _append_manifest_entry(category: str, source_id: str, filename: str, path: Path,
                            checksum: str, size: int, run_id: str, source_url: str | None,
                            duplicate: bool, now: datetime) -> dict[str, Any]:
    entry = {
        "category": category, "source_id": source_id, "filename": filename,
        "path": str(path), "checksum": checksum, "size": size,
        "run_id": run_id, "source_url": source_url,
        "saved_at": now.isoformat(), "duplicate": duplicate,
    }
    MANIFESTS_DIR.mkdir(parents=True, exist_ok=True)
    with _manifest_path(category, source_id).open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

    log.info("raw_storage_saved", category=category, source_id=source_id,
              duplicate=duplicate, size=size, path=str(path))
    return entry


async def save_raw_streamed(category: str, source_id: str, filename: str, url: str, *,
                             headers: dict[str, str] | None = None, run_id: str | None = None,
                             timeout: float = 600) -> dict[str, Any]:
    """Memory-safe variant of save_raw() for multi-GB sources (contracts,
    donations) — streams the URL straight to disk and hashes incrementally,
    never holding the full file in RAM. The checksum is only known after the
    full download completes, so the file is staged under raw/<category>/
    <source_id>/_staging/ and moved into its final checksum-suffixed path
    once hashing finishes (a cheap rename, not a copy).
    """
    import httpx

    _check_category(category)
    run_id = run_id or _now_run_id()
    now = datetime.now(timezone.utc)

    staging_dir = RAW_DIR / category / source_id / "_staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    staging_path = staging_dir / f"{run_id}.partial"

    hasher = hashlib.sha256()
    size = 0
    async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True) as c:
        async with c.stream("GET", url) as resp:
            resp.raise_for_status()
            with open(staging_path, "wb") as fh:
                async for chunk in resp.aiter_bytes():
                    fh.write(chunk)
                    hasher.update(chunk)
                    size += len(chunk)
    checksum = hasher.hexdigest()

    previous = _last_manifest_entry(category, source_id)
    duplicate = previous is not None and previous.get("checksum") == checksum
    if duplicate:
        staging_path.unlink()
        path = Path(previous["path"])
    else:
        leaf_dir = f"{run_id}-{checksum[:8]}"
        day_dir = RAW_DIR / category / source_id / now.strftime("%Y") / now.strftime("%m") / now.strftime("%d") / leaf_dir
        day_dir.mkdir(parents=True, exist_ok=True)
        path = day_dir / filename
        staging_path.rename(path)

    return _append_manifest_entry(category, source_id, filename, path, checksum,
                                   size, run_id, url, duplicate, now)


def read_checkpoint(source_id: str) -> dict[str, Any] | None:
    """Return the last saved checkpoint state for a source, or None if never set."""
    path = CHECKPOINTS_DIR / f"{source_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_checkpoint(source_id: str, state: dict[str, Any]) -> None:
    """Overwrite the checkpoint for a source (cursor, page token, since-date, etc.).

    Checkpoints are a single current-state JSON object, not a log — connectors
    read this at the start of a run to resume, and write it at the end.
    """
    CHECKPOINTS_DIR.mkdir(parents=True, exist_ok=True)
    path = CHECKPOINTS_DIR / f"{source_id}.json"
    payload = {**state, "updated_at": datetime.now(timezone.utc).isoformat()}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    log.info("checkpoint_written", source_id=source_id)


def quarantine(category: str, source_id: str, filename: str, content: bytes, *,
               reason: str, run_id: str | None = None) -> Path:
    """Save a record/payload that failed validation, instead of discarding it.

    Writes the payload plus a `<filename>.reason.txt` sidecar explaining why
    — per "quarantine invalid records instead of discarding them."
    """
    _check_category(category)
    run_id = run_id or _now_run_id()
    qdir = QUARANTINE_DIR / category / source_id / run_id
    qdir.mkdir(parents=True, exist_ok=True)
    path = qdir / filename
    path.write_bytes(content)
    (qdir / f"{filename}.reason.txt").write_text(reason, encoding="utf-8")
    log.warning("raw_storage_quarantined", category=category, source_id=source_id,
                filename=filename, reason=reason)
    return path


# ── Goal 6: extraction + backfill bookkeeping ───────────────────────────────

def extract_zip(save_result: dict[str, Any]) -> dict[str, Any]:
    """Extract a ZIP previously written by save_raw() into data/extracted/,
    mirroring the same category/source_id/run_id path. Validates as it goes:
    zipfile.testzip() (CRC check) plus confirming every member actually wrote
    a non-empty file. Returns a summary; never raises on a corrupt member —
    callers get extraction_validated=False and a reason instead.
    """
    raw_path = Path(save_result["path"])
    category, source_id = save_result["category"], save_result["source_id"]
    run_id = save_result["run_id"]
    dest_dir = EXTRACTED_DIR / category / source_id / run_id
    dest_dir.mkdir(parents=True, exist_ok=True)

    with open(raw_path, "rb") as f:
        magic = f.read(2)
    if magic != b"PK":
        return {"extracted_path": None, "files": [], "extraction_validated": False,
                "reason": "not a ZIP file (no PK magic bytes) — nothing to extract"}

    try:
        # Open by path (not io.BytesIO(read_bytes())) and stream each member
        # through zf.open()/copyfileobj in chunks — some source zips (e.g.
        # StatCan bulk tables) decompress to several GB; reading the whole
        # zip plus a fully-decompressed member into memory at once OOM-killed
        # the process on a 631MB zip that unpacked to a multi-GB CSV.
        with zipfile.ZipFile(raw_path) as zf:
            bad = zf.testzip()
            if bad:
                return {"extracted_path": str(dest_dir), "files": [], "extraction_validated": False,
                        "reason": f"CRC check failed on member {bad!r}"}
            extracted: list[dict[str, Any]] = []
            for name in zf.namelist():
                if name.endswith("/"):
                    continue
                out_path = dest_dir / name
                out_path.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(name) as src, open(out_path, "wb") as dst:
                    shutil.copyfileobj(src, dst, length=1024 * 1024)
                extracted.append({"name": name, "size": out_path.stat().st_size})
    except zipfile.BadZipFile as exc:
        return {"extracted_path": str(dest_dir), "files": [], "extraction_validated": False,
                "reason": f"BadZipFile: {exc}"}

    empty = [f["name"] for f in extracted if f["size"] == 0]
    validated = len(extracted) > 0 and not empty
    reason = "ok" if validated else (
        "zip had no members" if not extracted else f"empty file(s) after extraction: {empty}")
    log.info("raw_storage_extracted", category=category, source_id=source_id,
              files=len(extracted), validated=validated)
    return {"extracted_path": str(dest_dir), "files": extracted,
            "extraction_validated": validated, "reason": reason}


def count_csv_rows(path: Path, *, encoding: str = "latin-1") -> int:
    """Count data rows (excluding header) in a CSV file without loading it
    fully into memory — just streams and counts newlines via csv.reader."""
    with open(path, encoding=encoding, errors="replace", newline="") as f:
        reader = csv.reader(f)
        try:
            next(reader)  # header
        except StopIteration:
            return 0
        return sum(1 for _ in reader)


def _backfill_record_path(category: str, source_id: str) -> Path:
    return MANIFESTS_DIR / f"{category}__{source_id}.backfill.json"


def record_backfill(category: str, source_id: str, *, covered_years: list[int] | None = None,
                     row_count: int | None = None, extraction_validated: bool = False,
                     source_checksum: str | None = None, source_size_bytes: int | None = None,
                     notes: str | None = None) -> dict[str, Any]:
    """Write the current-state backfill summary for a source — the "is this
    source fully backfilled and accounted for" record Goal 6 asks for, distinct
    from the per-save .jsonl manifest log (which is an append-only history)."""
    _check_category(category)
    MANIFESTS_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "category": category, "source_id": source_id,
        "covered_years": sorted(covered_years) if covered_years else [],
        "row_count": row_count, "extraction_validated": extraction_validated,
        "source_checksum": source_checksum, "source_size_bytes": source_size_bytes,
        "notes": notes, "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    _backfill_record_path(category, source_id).write_text(json.dumps(record, indent=2), encoding="utf-8")
    log.info("backfill_recorded", category=category, source_id=source_id,
              row_count=row_count, validated=extraction_validated)
    return record


def read_backfill_record(category: str, source_id: str) -> dict[str, Any] | None:
    path = _backfill_record_path(category, source_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def all_backfill_records() -> list[dict[str, Any]]:
    """Every recorded backfill summary — the "what's stored and accounted
    for" half of Goal 6's done-when report."""
    if not MANIFESTS_DIR.exists():
        return []
    return [json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(MANIFESTS_DIR.glob("*.backfill.json"))]
