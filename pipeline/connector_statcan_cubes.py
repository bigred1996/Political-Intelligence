"""Parse the recovered StatCan cube CSVs (data/extracted/statcan/) into
StatcanObservation rows.

These 16 cubes were recovered from OLD NESSUS (see DATA.md) but never
ingested. They are local files already — full StatCan WDS cubes, not
something behind a connector fetch — so this reads from disk, not the
network. `statcan_36100608` (61.4M rows, 14G) is deliberately excluded here;
see DATA.md for the deferral rationale. Each cube directory holds the same
two files duplicated across several timestamped subdirectories (re-downloaded
more than once during recovery) — only the first timestamp dir is read.

Every StatCan cube has a different set of dimension columns beyond the fixed
REF_DATE/GEO/DGUID/UOM/VALUE spine (e.g. "Estimates", "NAICS", "Sex"). Rather
than a different table per cube, the cube-specific columns land in one JSON
`dimensions` field — see api/models/statcan_observation.py.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger()

STATCAN_DIR = Path("./data/extracted/statcan")
DEFERRED_CUBES = {"statcan_36100608"}  # 61.4M rows / 14G — see DATA.md

_FIXED_COLS = {
    "REF_DATE", "GEO", "DGUID", "UOM", "UOM_ID", "SCALAR_FACTOR", "SCALAR_ID",
    "VECTOR", "COORDINATE", "VALUE", "STATUS", "SYMBOL", "TERMINATED", "DECIMALS",
}


def _to_float(v: str | None) -> float | None:
    v = (v or "").strip()
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _read_metadata(meta_path: Path) -> dict[str, Any]:
    with open(meta_path, encoding="utf-8-sig", newline="") as fh:
        row = next(csv.DictReader(fh))
    return {
        "cube_title": (row.get("Cube Title") or "").strip(),
        "frequency": (row.get("Frequency") or "").strip() or None,
        "source_url": (row.get("URL") or "").strip() or None,
    }


def iter_cube_dirs() -> list[Path]:
    """One directory per recovered cube, skipping the deferred monster cube."""
    if not STATCAN_DIR.exists():
        return []
    return sorted(
        d for d in STATCAN_DIR.iterdir()
        if d.is_dir() and d.name.startswith("statcan_") and d.name not in DEFERRED_CUBES
    )


def parse_cube(cube_dir: Path) -> list[dict[str, Any]]:
    """Parse one cube directory (any of its duplicate timestamp subdirs) into
    StatcanObservation-shaped dicts."""
    cube_id = cube_dir.name.removeprefix("statcan_")
    timestamp_dirs = sorted(d for d in cube_dir.iterdir() if d.is_dir())
    if not timestamp_dirs:
        log.warning("statcan_cube_no_data", cube_id=cube_id)
        return []
    data_dir = timestamp_dirs[0]

    data_csv = next((f for f in data_dir.glob("*.csv") if "MetaData" not in f.name), None)
    meta_csv = next((f for f in data_dir.glob("*MetaData*.csv")), None)
    if not data_csv:
        log.warning("statcan_cube_missing_csv", cube_id=cube_id)
        return []

    meta = _read_metadata(meta_csv) if meta_csv else {"cube_title": cube_id, "frequency": None, "source_url": None}

    out: list[dict[str, Any]] = []
    with open(data_csv, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        dimension_cols = [c for c in (reader.fieldnames or []) if c not in _FIXED_COLS]
        for row in reader:
            out.append({
                "cube_id": cube_id,
                "cube_title": meta["cube_title"],
                "frequency": meta["frequency"],
                "source_url": meta["source_url"],
                "ref_date": (row.get("REF_DATE") or "").strip(),
                "geo": (row.get("GEO") or "").strip() or None,
                "dguid": (row.get("DGUID") or "").strip() or None,
                "dimensions": {c: (row.get(c) or "").strip() for c in dimension_cols if (row.get(c) or "").strip()},
                "value": _to_float(row.get("VALUE")),
                "uom": (row.get("UOM") or "").strip() or None,
                "scalar_factor": (row.get("SCALAR_FACTOR") or "").strip() or None,
                "vector": (row.get("VECTOR") or "").strip() or None,
                "coordinate": (row.get("COORDINATE") or "").strip() or None,
                "status": (row.get("STATUS") or "").strip() or None,
            })
    log.info("statcan_cube_parsed", cube_id=cube_id, count=len(out))
    return out
