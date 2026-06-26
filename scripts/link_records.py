#!/usr/bin/env python
"""Materialize explicit links between imported records."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.record_linker import build_links, sqlite_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build deterministic record_links rows")
    parser.add_argument("--db", type=Path, default=None, help="SQLite DB path; defaults to DATABASE_URL")
    parser.add_argument("--raw-root", type=Path, default=None, help="Raw archive root; defaults to data/raw beside DB")
    args = parser.parse_args()

    counts = build_links(args.db or sqlite_path(), args.raw_root)
    for key, value in counts.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
