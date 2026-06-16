# Scheduled ingestion on this Mac (launchd)

The data-refresh scheduler runs as a **standalone background process**
(`scripts/run_scheduler.py`), kept alive by launchd. It reuses the exact cadences
defined in `api/scheduler.py` (bills daily, gazette/appointments weekly,
contracts/OCL monthly, donations/grants quarterly, breadth sources staggered) and
writes every run to the `scheduler_log` table.

It runs **separately from the API** on purpose: a multi-million-row streaming ingest
must never run inside uvicorn (it can block the event loop / crash the preview
server). Isolated here, a heavy load can't take the app down, and launchd restarts
the process if it ever dies.

## ⚠️ Do this AFTER the Supabase migration

The whole point is to stop filling the local disk. Enable the scheduler only once
`.env` points `DATABASE_URL` at Supabase Postgres (see `../SUPABASE_SETUP.md`).
Running scheduled full ingests into the near-full local SQLite is exactly what we're
avoiding.

## Install

```bash
# 1. Symlink (or copy) the plist into your LaunchAgents dir:
ln -sf "/Users/codymcmullen/Documents/Claude Code/polaris/deploy/com.polaris.scheduler.plist" \
       ~/Library/LaunchAgents/com.polaris.scheduler.plist

# 2. Load + start it (-w marks it enabled across reboots):
launchctl load -w ~/Library/LaunchAgents/com.polaris.scheduler.plist

# 3. Confirm it's running and see the next-run times it logged:
launchctl list | grep polaris
tail -f "/Users/codymcmullen/Documents/Claude Code/polaris/logs/scheduler.out.log"
```

## Manage

```bash
# Stop / disable:
launchctl unload -w ~/Library/LaunchAgents/com.polaris.scheduler.plist

# Restart after a code change:
launchctl unload ~/Library/LaunchAgents/com.polaris.scheduler.plist
launchctl load   ~/Library/LaunchAgents/com.polaris.scheduler.plist

# Trigger one job immediately (without waiting for its cron time),
# run it standalone instead — same code path:
.venv/bin/python scripts/run_ingest.py bills_daily
```

## Caveats

- **Only fires while the Mac is awake and online.** macOS launchd does not wake the
  machine for an agent; a missed cron time runs at the next opportunity. Fine
  pre-launch. When you want true always-on cadence, lift `run_scheduler.py` onto a
  small always-on host (Fly.io / Railway / a VPS) — same script, just set
  `DATABASE_URL` there. Nothing else changes.
- Logs rotate nowhere by default — `logs/scheduler.{out,err}.log` grow slowly. Add a
  `newsyslog`/logrotate entry if they get large.
