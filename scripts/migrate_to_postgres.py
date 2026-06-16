"""One-time migration: copy every table from the local SQLite DB into a target
Postgres (Supabase) database.

Why this exists: the data layer is engine-agnostic (see api/database.py), so the
ONLY thing standing between local SQLite and Supabase is moving the rows. This
script does that — schema first (via SQLAlchemy metadata, identical to what the
app creates), then a resumable, memory-safe row copy.

Design:
  * Schema is created on the target with Base.metadata.create_all (same models
    the app registers in init_db — guaranteed parity).
  * Each table is copied by paginating on the integer `id` PK
    (WHERE id > :last ORDER BY id LIMIT batch). Nothing is ever fully
    materialized in memory, so the 6.2M-row donations table is fine.
  * RESUMABLE: the copy for each table resumes from the target's current
    max(id). Re-running after an interruption (or a dropped Supabase
    connection) picks up exactly where it stopped — no duplicates, no
    re-copying millions of rows.
  * After each table, the Postgres identity sequence is reset to max(id) so
    future inserts from the app don't collide with migrated ids.

Usage (stop the API / scheduler first so SQLite isn't being written):
    .venv/bin/python scripts/migrate_to_postgres.py \
        --target 'postgresql+asyncpg://postgres:PASSWORD@HOST:5432/postgres'

    # or read the target from DATABASE_URL in the environment / .env:
    DATABASE_URL='postgresql+asyncpg://...' .venv/bin/python scripts/migrate_to_postgres.py

Options:
    --source URL   override the source (default: sqlite+aiosqlite:///./polaris.db)
    --batch N      rows per insert batch (default 5000)
    --only a,b     copy only these tables
    --skip a,b     skip these tables
    --truncate     empty each target table before copying (full re-migration)
    --verify       just print source-vs-target row counts and exit
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Make `import api...` work when run as a standalone script from polaris/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, func, insert, select, text
from sqlalchemy.ext.asyncio import create_async_engine

from api.database import Base


def _register_models() -> None:
    """Import every model module so its table registers on Base.metadata.

    Mirrors api.database.init_db's import block exactly — keep in sync if a new
    model module is added there.
    """
    from api.models import (  # noqa: F401
        appointment, contract, donation, entity, grant, ocl_registration,
        politician, regulation, report, request, scheduler_log, source_record,
    )


def _normalize_async_url(url: str) -> str:
    """Accept the plain libpq URL Supabase shows in its dashboard and upgrade it
    to the async driver SQLAlchemy needs."""
    if url.startswith("postgresql+asyncpg://") or url.startswith("sqlite+aiosqlite://"):
        return url
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://"):]
    return url


async def _count(engine, table) -> int:
    async with engine.connect() as conn:
        return (await conn.execute(select(func.count()).select_from(table))).scalar_one()


async def _max_id(engine, table) -> int:
    async with engine.connect() as conn:
        val = (await conn.execute(select(func.max(table.c.id)))).scalar_one()
        return val or 0


async def copy_table(src, dst, table, batch: int, truncate: bool) -> tuple[int, int]:
    """Copy one table. Returns (source_count, copied_this_run)."""
    name = table.name
    src_total = await _count(src, table)

    if truncate:
        async with dst.begin() as conn:
            await conn.execute(delete(table))

    last = await _max_id(dst, table)  # resume point
    if last:
        print(f"  [{name}] resuming from id > {last}")

    copied = 0
    while True:
        async with src.connect() as sconn:
            rows = (
                await sconn.execute(
                    select(table).where(table.c.id > last).order_by(table.c.id).limit(batch)
                )
            ).mappings().all()
        if not rows:
            break
        payload = [dict(r) for r in rows]
        async with dst.begin() as dconn:
            await dconn.execute(insert(table), payload)
        last = payload[-1]["id"]
        copied += len(payload)
        dst_total = await _max_id(dst, table)
        print(f"  [{name}] +{len(payload):>5}  copied={copied:>9}  (last id {last}, ~{dst_total}/{src_total})")

    # Reset the Postgres identity sequence so app inserts don't collide.
    if dst.dialect.name == "postgresql":
        async with dst.begin() as conn:
            await conn.execute(
                text(
                    "SELECT setval(pg_get_serial_sequence(:t, 'id'), "
                    "GREATEST((SELECT COALESCE(MAX(id), 1) FROM \"%s\"), 1))" % name
                ),
                {"t": name},
            )
    return src_total, copied


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="sqlite+aiosqlite:///./polaris.db")
    ap.add_argument("--target", default=os.environ.get("DATABASE_URL", ""))
    ap.add_argument("--batch", type=int, default=5000)
    ap.add_argument("--only", default="")
    ap.add_argument("--skip", default="")
    ap.add_argument("--truncate", action="store_true")
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args()

    if not args.target:
        print("ERROR: no target. Pass --target '...' or set DATABASE_URL.", file=sys.stderr)
        return 2

    source_url = _normalize_async_url(args.source)
    target_url = _normalize_async_url(args.target)
    _register_models()

    src = create_async_engine(source_url)
    dst = create_async_engine(target_url)

    only = {s.strip() for s in args.only.split(",") if s.strip()}
    skip = {s.strip() for s in args.skip.split(",") if s.strip()}
    tables = [
        t for t in Base.metadata.sorted_tables
        if (not only or t.name in only) and t.name not in skip
    ]

    if args.verify:
        print(f"{'table':24} {'source':>10} {'target':>10}")
        for t in tables:
            try:
                s = await _count(src, t)
            except Exception:
                s = -1
            try:
                d = await _count(dst, t)
            except Exception:
                d = -1
            flag = "" if s == d else "  <-- MISMATCH" if s >= 0 and d >= 0 else "  <-- ERR"
            print(f"{t.name:24} {s:>10} {d:>10}{flag}")
        await src.dispose()
        await dst.dispose()
        return 0

    print(f"Creating schema on target ({dst.url.host})...")
    async with dst.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    print(f"Copying {len(tables)} tables (batch={args.batch})...\n")
    summary = []
    for t in tables:
        print(f"==> {t.name}")
        try:
            src_total, copied = await copy_table(src, dst, t, args.batch, args.truncate)
            summary.append((t.name, src_total, copied))
        except Exception as e:
            print(f"  [{t.name}] ERROR: {e}")
            summary.append((t.name, -1, -1))

    print("\n=== summary ===")
    for name, src_total, copied in summary:
        print(f"{name:24} source={src_total:>9}  copied_this_run={copied:>9}")

    await src.dispose()
    await dst.dispose()
    print("\nDone. Re-run with --verify to confirm source/target counts match.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
