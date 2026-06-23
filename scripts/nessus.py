"""nessus — operator CLI for ingestion completeness (Goal 12).

One snapshot from pipeline.data_audit.build_inventory(), sliced six ways, so
"what data do we have, what period does it cover, and what are we missing"
has a direct answer instead of cross-referencing the registry doc, the
scheduler dashboard, and a database console by hand.

Usage (run from the polaris/ repo root):
    .venv/bin/python scripts/nessus.py data inventory        [--deep] [--json]
    .venv/bin/python scripts/nessus.py data status                   [--json]
    .venv/bin/python scripts/nessus.py data missing           [--deep] [--json]
    .venv/bin/python scripts/nessus.py data backfill-status    [--deep] [--json]
    .venv/bin/python scripts/nessus.py data disk-usage                [--json]
    .venv/bin/python scripts/nessus.py data validate           [--deep] [--json]

--deep additionally scans for missing years on the handful of >1M-row tables
(contracts, donations) and large breadth sources — skipped by default per
CLAUDE.md's full-table-scan performance rule. `validate` exits 1 if any
check fails (suitable for a cron/CI gate); every other subcommand exits 0.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Callable

# Unlike `python -m pytest` (which puts the repo root on sys.path via
# pytest's own rootdir insertion), `python scripts/nessus.py` only puts
# scripts/ itself on sys.path — `import api`/`import pipeline` would fail
# without this, regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _fmt_bytes(n: int | float | None) -> str:
    if n is None:
        return "—"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:,.0f}{unit}" if unit == "B" else f"{n:,.1f}{unit}"
        n /= 1024
    return f"{n:,.1f}TB"


def _fmt_rows(n: int | None) -> str:
    return f"{n:,}" if n is not None else "—"


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    str_rows = [[str(c) if c is not None else "—" for c in row] for row in rows]
    widths = [len(h) for h in headers]
    for row in str_rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    lines = ["  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))]
    lines.append("  ".join("-" * w for w in widths))
    for row in str_rows:
        lines.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))
    return "\n".join(lines)


async def _get_report(deep: bool) -> dict[str, Any]:
    from api.database import AsyncSessionLocal, init_db
    from pipeline.data_audit import build_inventory
    await init_db()
    async with AsyncSessionLocal() as session:
        return await build_inventory(session, deep=deep)


# ── Subcommands ──────────────────────────────────────────────────────────────

def cmd_inventory(args: argparse.Namespace) -> int:
    report = asyncio.run(_get_report(args.deep))
    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return 0

    reg = report["registry_summary"]
    print(f"Registered: {reg['total_registered']}  ·  Enabled (yaml): {reg['enabled_in_registry']}"
          f"  ·  Wired in scheduler: {reg['wired_in_scheduler']}")
    t = report["totals"]
    print(f"Fully backfilled: {t['fully_backfilled']}  ·  Partially: {t['partially_backfilled']}"
          f"  ·  Not started: {t['not_started']}")
    print()

    rows = [
        [s["id"], s["category"] or "—",
         "yes" if s["enabled_in_registry"] else ("no" if s["enabled_in_registry"] is False else "—"),
         "yes" if s["wired_in_scheduler"] else "no",
         _fmt_rows(s["rows"]), s["earliest_date"] or "—", s["latest_date"] or "—", s["backfill_state"]]
        for s in report["sources"]
    ]
    print(_table(["id", "category", "yaml_enabled", "wired", "rows", "earliest", "latest", "backfill"], rows))
    if not args.deep:
        print("\n(run with --deep to also scan year-coverage gaps on the largest tables)")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    report = asyncio.run(_get_report(False))
    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return 0

    rows = []
    for s in report["sources"]:
        last = s["last_run"]
        status = last["status"] if last else "never"
        last_at = (last.get("finished_at") or last.get("started_at")) if last else None
        stale = "yes" if s["stale"] else ("no" if s["stale"] is False else "—")
        cadence = (s["cadence"] or "—")[:32]
        rows.append([s["id"], status, last_at, cadence, s["next_scheduled_sync"], stale])
    print(_table(["id", "last_status", "last_run_at", "cadence", "next_sync", "stale"], rows))

    t = report["totals"]
    print(f"\nLast successful sync (any source): {t['last_successful_sync'] or '—'}")
    print(f"Next scheduled sync (any source): {t['next_scheduled_sync'] or '—'}")
    print(f"Failed downloads (lifetime error-run count, summed across sources): {t['failed_downloads']}")
    return 0


def cmd_missing(args: argparse.Namespace) -> int:
    report = asyncio.run(_get_report(args.deep))
    if args.json:
        payload = {
            "not_started": [s["id"] for s in report["sources"]
                             if s["backfill_state"] == "not_started" and s["wired_in_scheduler"]],
            "missing_years": {s["id"]: s["missing_years"] for s in report["sources"] if s["missing_years"]},
            "open_page_gaps": {s["id"]: s["checkpoint"]["gaps"] for s in report["sources"]
                                if s["checkpoint"] and s["checkpoint"]["open_gaps"]},
            "id_mismatches": [c for c in report["validate"] if c["check"] in
                               ("registry_enabled_sources_are_wired", "wired_jobs_are_documented")],
        }
        print(json.dumps(payload, indent=2, default=str))
        return 0

    not_started = [s["id"] for s in report["sources"] if s["backfill_state"] == "not_started" and s["wired_in_scheduler"]]
    print(f"Not started ({len(not_started)}): {', '.join(not_started) or '(none)'}")
    print()
    print("Missing years (gaps inside each source's own observed date range):")
    found = False
    for s in report["sources"]:
        if s["missing_years"]:
            found = True
            print(f"  {s['id']}: {s['missing_years']}")
    if not found:
        suffix = "" if args.deep else " among sources cheap enough to scan without --deep"
        print(f"  (none found{suffix})")
    print()
    print("Open page-fetch gaps (pipeline/api_paginator.py checkpoints):")
    found = False
    for s in report["sources"]:
        cp = s["checkpoint"]
        if cp and cp["open_gaps"]:
            found = True
            print(f"  {s['id']}: {cp['open_gaps']} gap(s) — {cp['gaps']}")
    if not found:
        print("  (none)")
    print()
    for c in report["validate"]:
        if c["check"] in ("registry_enabled_sources_are_wired", "wired_jobs_are_documented") and c["status"] != "pass":
            print(f"[{c['status'].upper()}] {c['check']}: {c['detail']}")
    return 0


def cmd_backfill_status(args: argparse.Namespace) -> int:
    report = asyncio.run(_get_report(args.deep))
    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return 0

    t = report["totals"]
    print(f"Full: {t['fully_backfilled']}  ·  Partial: {t['partially_backfilled']}  ·  Not started: {t['not_started']}")
    print()
    rows = []
    for s in report["sources"]:
        rec = s["backfill_record"]
        note = (rec.get("notes") or "")[:70] if rec else ""
        cp_status = s["checkpoint"]["status"] if s["checkpoint"] else "—"
        rows.append([s["id"], s["backfill_state"], _fmt_rows(s["rows"]), cp_status or "—", note or "—"])
    print(_table(["id", "state", "rows", "checkpoint_status", "notes"], rows))
    return 0


def cmd_disk_usage(args: argparse.Namespace) -> int:
    report = asyncio.run(_get_report(False))
    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return 0

    d = report["disk"]
    print(f"Disk: {_fmt_bytes(d['used_bytes'])} used / {_fmt_bytes(d['total_bytes'])} total "
          f"({_fmt_bytes(d['free_bytes'])} free, {d['free_pct']}%)")
    print(f"polaris.db: {_fmt_bytes(d['db_file_bytes'])}" if d["db_file_bytes"] is not None else d["db_file_note"])
    print()
    print(_table(["data/ subdir", "bytes"], [[k, _fmt_bytes(v)] for k, v in d["breakdown_bytes"].items()]))

    t = report["totals"]
    print(f"\nFiles downloaded: {_fmt_rows(t['files_downloaded'])}  ·  "
          f"Bytes downloaded: {_fmt_bytes(t['bytes_downloaded'])}  ·  "
          f"Duplicate fetches avoided: {_fmt_rows(t['duplicate_files'])}")

    top = sorted((s for s in report["sources"] if s["manifest"]), key=lambda s: s["manifest"]["bytes"], reverse=True)[:10]
    if top:
        print("\nTop sources by raw bytes on disk:")
        print(_table(["id", "bytes", "files"], [[s["id"], _fmt_bytes(s["manifest"]["bytes"]), s["manifest"]["files"]] for s in top]))
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    report = asyncio.run(_get_report(args.deep))
    checks = report["validate"]
    if args.json:
        print(json.dumps(checks, indent=2, default=str))
    else:
        for c in checks:
            print(f"[{c['status'].upper()}] {c['check']}: {c['detail']}")
        failed = sum(1 for c in checks if c["status"] == "fail")
        warned = sum(1 for c in checks if c["status"] == "warn")
        print(f"\n{len(checks) - failed - warned} passed, {warned} warned, {failed} failed.")
    return 1 if any(c["status"] == "fail" for c in checks) else 0


# ── argparse wiring ───────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nessus", description="Nessus operator CLI.")
    domains = parser.add_subparsers(dest="domain", required=True)

    data = domains.add_parser("data", help="Ingestion completeness — what data do we have, what's missing.")
    actions = data.add_subparsers(dest="action", required=True)

    specs: list[tuple[str, str, Callable[[argparse.Namespace], int], bool]] = [
        ("inventory", "Per-source registry status, row counts, and date coverage.", cmd_inventory, True),
        ("status", "Per-source health: last run, freshness, next sync.", cmd_status, False),
        ("missing", "Missing years, open page-fetch gaps, never-started sources.", cmd_missing, True),
        ("backfill-status", "Full vs partial vs not-started backfill per source.", cmd_backfill_status, True),
        ("disk-usage", "Disk headroom plus bytes/files downloaded per source.", cmd_disk_usage, False),
        ("validate", "Run sanity checks; exits 1 if any check fails.", cmd_validate, True),
    ]
    for name, help_text, func, supports_deep in specs:
        p = actions.add_parser(name, help=help_text)
        p.add_argument("--json", action="store_true", help="Emit raw JSON instead of a formatted table.")
        if supports_deep:
            p.add_argument("--deep", action="store_true",
                            help="Also scan for missing years on tables >1M rows — slower.")
        p.set_defaults(func=func)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
