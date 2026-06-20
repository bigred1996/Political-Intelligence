# Supabase Setup — moving Nessus off local SQLite

This is the one part only you can do (it needs your account). It takes ~10 minutes.
Once you paste the connection string into `.env`, I run the migration and we're on Postgres.

---

## Why we're doing this

- Your Mac disk is **94% full (~13 GB free)** and the SQLite DB is already **2.1 GB**.
  The CLAUDE.md already records hitting `database or disk is full` mid-ingest. We
  physically can't hold the full data here much longer.
- Supabase = hosted **Postgres + pgvector**, always-on, so an LLM chat and the app
  can query every record live — exactly the "pull up any record" requirement.
- The code is already engine-agnostic. Nothing to rewrite; we only move the rows.

---

## Step 1 — Create the project

1. Go to https://supabase.com → sign in → **New project**.
2. **Name:** `polaris` (anything).
3. **Database password:** click *Generate*, then **copy it somewhere safe** —
   you cannot see it again, and the migration needs it. (If it has special
   characters like `@ : / #`, note that we'll URL-encode it in Step 3.)
4. **Region:** pick the one closest to you — **East US (Ohio/N. Virginia)** is a
   good default for Canada. (Region only affects latency, not correctness.)
5. Create. Wait ~2 min for it to provision.

## Step 2 — Pick the plan

- **Free tier = 500 MB database.** Our data is already ~2 GB and grows. Free is
  **not enough** for the real corpus — but it's fine if you want to do a *small
  test migration first* (I can copy just the small tables to prove the pipe works).
- **Pro = $25/mo, 8 GB included** (+~$0.125/GB beyond). This is what we need for
  the full data. The giant tables (contracts, donations) are numeric and don't
  get embedded, so vector storage stays cheap.

**Recommendation:** create on Free, let me run a test migration of the small tables
to confirm the connection works, then upgrade to Pro before the full copy. Upgrade
under **Settings → Billing**.

## Step 3 — Get the connection string

1. In the project: **Settings (gear) → Database**.
2. Find **Connection string** → choose the **Session pooler** tab.
   - Use **Session pooler** (port **5432**), *not* Transaction pooler (6543).
     Session mode gives us IPv4 + full prepared-statement support, which the
     async Postgres driver (asyncpg) needs. (If you only see "Direct connection",
     that's also fine on port 5432 — but it may require IPv6; the Session pooler
     is the safe choice on home internet.)
3. It looks like:
   ```
   postgresql://postgres.abcdefgh:[YOUR-PASSWORD]@aws-0-us-east-2.pooler.supabase.com:5432/postgres
   ```
4. Replace `[YOUR-PASSWORD]` with the password from Step 1.
   - If the password has special characters, percent-encode them
     (`@`→`%40`, `:`→`%3A`, `/`→`%2F`, `#`→`%23`). Generated passwords are usually
     alphanumeric, so this rarely matters.

## Step 4 — Put it in `.env`

Add this line to `polaris/.env` (the migration script and the app both read it).
The driver prefix `postgresql+asyncpg://` is required — just paste the URL after it,
dropping the original `postgresql://`:

```
DATABASE_URL=postgresql+asyncpg://postgres.abcdefgh:YOURPASSWORD@aws-0-us-east-2.pooler.supabase.com:5432/postgres
```

(The migration script also accepts a plain `postgresql://...` and upgrades the prefix
automatically, so if you paste it as-is it still works.)

## Step 5 — Hand it to me

Tell me it's set, or paste the connection string and I'll:

```bash
# 1. Stop the API / scheduler so SQLite isn't being written during the copy.
# 2. (optional) prove the pipe on small tables first:
.venv/bin/python scripts/migrate_to_postgres.py --only bills,gazette_entries,politicians

# 3. full copy (resumable — safe to re-run if the connection drops):
.venv/bin/python scripts/migrate_to_postgres.py

# 4. confirm row counts match on both sides:
.venv/bin/python scripts/migrate_to_postgres.py --verify
```

The big tables (6.2M donations, 1.15M contracts) take a while over the network, but
the copy is **resumable** — if Supabase drops the connection it picks up from where
it stopped, no duplicates. Then we flip the app to `DATABASE_URL` and we're live on
Postgres.

---

## Later (not now): pgvector for semantic search

Supabase ships the `pgvector` extension. Once we're on Postgres we can move the
semantic search index from the local `data/index/*.npy` files into a `vector`
column (enable with `create extension vector;` in the SQL editor). Not required for
the migration — the current local index keeps working against Postgres unchanged.

## Notes / gotchas

- **Transaction pooler (port 6543) + asyncpg** breaks on prepared statements. If you
  ever must use it, the driver needs `?prepared_statement_cache_size=0` on the URL.
  Avoid it — use the **Session pooler (5432)** and this never comes up.
- **Don't commit `.env`** — it now holds your DB password. It's already gitignored;
  keep it that way.
- The migration **reads** SQLite and **writes** Postgres; your local `polaris.db` is
  untouched, so we can always fall back or re-run.
