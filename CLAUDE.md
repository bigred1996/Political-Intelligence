# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## What This Is

**Polaris Intelligence** — a Canadian political due-diligence platform. It bulk-ingests federal open-data sources into a DB, then surfaces them through a premium **Next.js client app** (`web/`, the product) plus a FastAPI backend. **The product is positioned industry-first, not company-first** — every data point is read through the lens of the *industry* it touches and the *political players* who shape it.

Core capabilities: (1) **sector & region intelligence** — roll up cross-source political-risk signals by industry (and province), with deterministic cross-source "connections" and time-series — the client-app centerpiece; (2) **entity intelligence** — one synthesized cross-source profile per company; (3) **universal record detail** — pull up ANY individual record (every contract, bill, lobby notice, donation, incident…) at `/records/{table}/{pk}` with its industry impact, relevant political players, and full cross-source connection graph; (4) **politicians / political players** — a directory + profile per MP with photos; (5) **risk reports** — score four dimensions (0–10) and draft a 9-section report via Claude, analyst-reviewed, served as branded HTML/PDF; (6) **unified hybrid search** over every individual record. **Entity resolution across sources is the moat.** The repo has two front-ends: the `web/` client app (the product) and the legacy `frontend/index.html` ops console (now at `/internal`).

---

## Commands

```bash
# Run the server (from polaris/)
.venv/bin/python -m uvicorn api.main:app --host 127.0.0.1 --port 8077

# Run tests — MUST invoke as a module (adds cwd to sys.path; bare `pytest` fails to import `pipeline`)
.venv/bin/python -m pytest tests/ -q

# Run a single test
.venv/bin/python -m pytest tests/test_pipeline.py::test_scorer_bounds_and_drivers -v

# Lint
.venv/bin/ruff check .

# Install deps
.venv/bin/pip install -r requirements.txt

# Run a big ingest standalone (NOT through the web server — see gotchas)
.venv/bin/python scripts/run_ingest.py contracts_monthly   # any id in JOB_RUNNERS

# Rebuild the semantic search index after ingesting text sources
curl -X POST http://127.0.0.1:8077/api/search/reindex

# Standalone scheduler (runs the data-refresh cron OUTSIDE uvicorn; see deploy/ for launchd)
.venv/bin/python scripts/run_scheduler.py

# One-time data jobs
.venv/bin/python scripts/migrate_to_postgres.py            # SQLite → Supabase (resumable; --verify)
.venv/bin/python scripts/enrich_politicians.py             # MP photos/role/email from openparliament
.venv/bin/python scripts/download_mp_photos.py             # download photos local → web/public/mp/*
.venv/bin/python scripts/deepen_hansard.py                 # sector-keyword Hansard pull

# Front-end (Next.js client app) — run from polaris/web/, needs the API on :8077 too
cd web && npm run dev          # dev server on :3000 (proxies /api + /report → :8077)
cd web && npm run build        # production build; ALSO the fastest full TypeScript check across all pages
```

Most scripts read `DATABASE_URL` from `.env`; when running them from a shell that needs the env, `set -a && . ./.env && set +a` first.

Dashboard (internal ops console): `http://127.0.0.1:8077/internal`  (FastAPI `/` 307-redirects here)
Client app (the product): `http://localhost:3000`
OpenAPI docs: `http://127.0.0.1:8077/docs`

---

## Architecture

### Data flow

```
POST /api/reports/generate
  → pipeline/orchestrator.py      # coordinates everything
  → pipeline/gather.py            # queries DB for all 9 source types
  → pipeline/risk_scorer.py       # 4 scores with log-scale + regulatory body bonus
  → pipeline/report_builder.py    # Claude path (API key set) or template path
  → stored in DB as Report row
  → GET /report/{id}              # customer-facing HTML view
  → GET /report/{id}/pdf          # WeasyPrint PDF
```

### Sector & entity intelligence (the client-app data layer)

The Next.js client app is powered by a separate read-only layer (additive; no schema changes), distinct from the report pipeline:

- **`pipeline/sector_mapper.py`** — the sector taxonomy. Each `Sector` is a **curated roster of canonical entity slugs** + keyword list + regulator-name fragments. `entities_for_sector` / `sector_for_entity` map between them. Add a sector = add one entry to `SECTORS`.
- **`pipeline/sector_intel.py`** — `gather_sector_data(sector, province)` and `gather_entity_data(name, sector)` build cross-source evidence bundles (reusing `risk_scorer.score()` unchanged), plus `detect_connections` / `detect_entity_connections` (the deterministic "so what" insight layer) and `_trends` (yearly time-series for charts).
- **Routes** (all read-only, write nothing — unlike `/api/reports/generate`): `api/routes/sectors.py` (`/api/sectors`, `/api/sectors/{slug}/overview?province=`), `entities.py` (`/api/entities/{name}`), `overview.py` (`/api/overview` — backs the home dashboard), `briefing.py` (`/api/briefing`).

**PERFORMANCE RULE (critical):** the big tables (contracts ~1.15M, donations ~6.2M, lobbying ~363k) MUST be queried by the indexed `canonical_name.in_(roster)` — an `ILIKE` over them is a 5–27s full scan (this is why `gather_company_data`'s ILIKE fallback is too slow for interactive pages, so the entity route uses the fast roster path instead). Keyword `ILIKE` is fine only on the small tables (bills, gazette, source_records). Also: SQLite `count(*)` full-scans (no cached row count) — `count(*)` on donations is ~12s; use `max(id)` as an instant total-records proxy for the append-only big tables (see `overview.py`).

The sector/entity evidence record dicts (`_bills`/`_regulations`/`_tribunal`/`_appointments`/`_breadth` in `sector_intel.py`) each carry `id` + `table` so the front-end lists link straight into `/records/{table}/{pk}`. Keep that when adding evidence sources.

### Universal record detail + industry lens

**`api/routes/records.py` — `GET /api/records/{table}/{pk}`** resolves ANY record in ANY table generically (no per-source code) by reusing `search.sql_search.SPECS` (one `TableSpec` per table). It returns: the full column dump + `raw` blob, the **industry lens** (`pipeline/impact.py`), the **relevant political players**, and the **relation graph** (same canonical entity across every table + sector peers + a chronological timeline). Accepts table-name aliases (`gazette_entries`↔`gazette`, `tribunal_decisions`↔`tribunal`, `lobbying_records`↔`lobbying`) because the semantic vs SQL layers label tables differently.

**`pipeline/impact.py`** is the industry layer: `resolve_sector` (entity roster → keyword → regulator-name), `industry_impact` (deterministic per-record-type "what this means" + severity, no API key needed), `relevant_players` (bill sponsor + Hansard speakers + sector regulators; MPs linked to their profile by name). Front-end record page (`web/app/records/[table]/[pk]/page.tsx`) leads with the industry, then impact + players, then connections; every related item links to its own record page. Search results and entity/sector lists also link in.

### Politicians / political players

**`api/routes/politicians.py`** — `/api/politicians` (directory + party/province facets) and `/api/politicians/{slug}` (profile: composed summary, sponsored bills, House interventions, industries-touched). Backed by the `politicians` table (343 MPs seeded from openparliament, **enriched** with `photo_url`/`role`/`email`/`since_date`/`commons_url` via `scripts/enrich_politicians.py`). Front-end: `web/app/politicians/page.tsx` (photo grid) + `[slug]/page.tsx`. Profiles match bills/speeches by `speaker`/`sponsor` ILIKE name (best-effort; thin until Hansard deepens).

### The ingest architecture

Polaris **does not scrape per request**. It bulk-ingests government open-data files once (triggered via API or scheduler), normalizes every entity name via `pipeline/entity_resolver.normalize()`, and stores in SQLite. Per-company queries hit the DB only.

There are **two tiers of sources**, and which one you touch depends on the source:

**Tier 1 — core analytics sources** (contracts, donations, lobbying, bills, grants, appointments, gazette, parliament). Each has a rich typed table/model and the original hand-wired pattern:
- A `fetch_*_rows()` (or `iter_*_rows()` generator) in `pipeline/ingest.py`
- A model in `api/models/`, a route in `api/routes/`
- A hand-written `_run_*` job in `api/scheduler.py`

**Tier 2 — breadth sources** (StatCan, IAAC, CER, NPRI, Transport, NRCan/GeoGratis geospatial, GC News). These flow through a **declarative connector registry** and land in ONE unified `source_records` table — do NOT add a typed table/route/job per breadth source. To add or change one:
- Write/edit a `fetch_*_records()` in `pipeline/breadth.py` returning dicts shaped for `source_records` (see `api/models/source_record.py`)
- Add/edit one `SourceConnector(...)` entry in `pipeline/connectors.py`
- That's it — `api/scheduler.py:_register_breadth_connectors()` auto-creates the cron job + `run_connector()` does the upsert + logging. The search indexer reads the same registry.

`source_records` keeps typed search columns (entity, canonical, title, summary, event_date, amount, province, url) plus a JSON `raw` blob. Rich typed tables stay for sources you run scorecards/analytics on; breadth sources feed search and cross-source insight. `canonical_name` lets a breadth record still join the entity graph.

**Full-corpus / streaming ingests:** `iter_contract_rows()` / `iter_donation_rows()` are async generators; `api/scheduler.py:_stream_load()` consumes them and batch-inserts so a multi-million-row load never materializes in memory. `max_rows<=0` means uncapped. `pipeline/breadth.py:_stream_csv()` aborts if the first bytes are HTML (`<`) or a zip/xlsx (`PK`) — government "CSV" links frequently serve catalogue pages or zipped payloads; callers fall back to the CKAN org catalogue.

### Unified hybrid search (`search/`)

Natural-language search across **every** source — `GET/POST /api/search`, plus the top card on the dashboard. Pipeline (`search/engine.py`): `make_plan` → `structured_search` ∪ `semantic_search` → merge/rank → optional cited answer.
- **`search/planner.py`** — NL → structured plan. Claude via a forced tool call when `ANTHROPIC_API_KEY` is set; deterministic regex/keyword fallback otherwise. Same output schema either way.
- **`search/sql_search.py`** — exact predicate search across all tables via one declarative `TableSpec` per source. Keywords are OR'd (precision comes from entity/date/amount/source filters); add a table = add a spec.
- **`search/index.py` + `search/embeddings.py`** — local fastembed/BGE-small (384-dim, CPU, **no API key, no per-token cost**). Only text-bearing sources are embedded (bills, gazette, tribunal, and the text breadth sources); numeric tables (contracts, donations, NPRI) are SQL-only by design. Index persists to `data/index/` and must be rebuilt after ingesting text sources — the scheduler auto-rebuilds via `_rebuild_search_index()` after embedded ingests; otherwise `POST /api/search/reindex`.
- A result tagged `match: "both"` was found by SQL **and** vectors → ranked highest.

### Entity resolution

`pipeline/entity_resolver.normalize(name) → str` collapses suffix variants: "IBM Canada Ltd." and "IBM CANADA LIMITED" both → `"ibm"`. All DB writes store a `canonical_name` column. Queries always use `canonical_name == canonical OR raw_name ILIKE "%company%"` — never `LIKE "%canonical%"` (short canonicals like `"bce"` cause false positives).

### Evidence bundle

`pipeline/gather.py:gather_company_data()` returns a single dict consumed by both the risk scorer and report builder. Shape:

```python
{
  "company", "canonical", "sector", "report_type",
  "lobbying":   {"count", "records", "registrants", "institutions"},
  "ocl_registrations": {"count", "records", "active"},
  "contracts":  {"count", "total_value", "by_department", "records"},
  "grants":     {"count", "total_value", "records"},
  "donations":  {"count", "total_value", "records"},
  "bills":      {"count", "records"},
  "regulations":        {"count", "records"},   # Canada Gazette entries
  "tribunal_decisions": {"count", "records"},   # CRTC etc.
  "appointments":       {"count", "records"},   # GIC regulatory body appointments
  "stakeholders": [...],                         # MPs from Hansard + DPOH contacts
}
```

### Report builder (two paths)

`pipeline/report_builder.py:build_sections(ev, scores)` returns `(dict[section→html], generated_by)`.

- **Claude path**: `ANTHROPIC_API_KEY` is set and valid → one API call per section, prompts loaded from `/prompts/`. Returns `generated_by="claude"`.
- **Template path**: no key → deterministic HTML from evidence dict. Returns `generated_by="template"`. Marked visibly in reports so analysts know to review harder.

Prompts live in `/prompts/sections/*.md` and `/prompts/report_types/*.md`. Never hardcode prompt text in Python.

### Scheduler

`api/scheduler.py` — APScheduler `AsyncIOScheduler`, started in FastAPI lifespan. 14 jobs across the two source tiers:

| Job ID | Cadence | Source |
|---|---|---|
| `bills_daily` | Daily 6am ET | LEGISinfo JSON API |
| `gazette_weekly` | Sat 8am ET | Canada Gazette RSS Part I+II |
| `appointments_weekly` | Mon 7am ET | GIC Appointments (open.canada.ca) |
| `contracts_monthly` | 3rd of month, 2am | Proactive Disclosure CSV |
| `ocl_monthly` | 4th of month, 3am | OCL Monthly Communications ZIP |
| `grants_quarterly` | Jan/Apr/Jul/Oct 5th | Grants & Contributions (open.canada.ca) |
| `donations_quarterly` | Jan/Apr/Jul/Oct 6th | Elections Canada contributions ZIP |
| breadth jobs (`gc_news`, `statcan`, `iaac`, `cer`, `npri`, `transport`, `geospatial`) | daily/weekly, staggered | Registered automatically from `pipeline/connectors.py` |

14 jobs total. Core jobs are hand-written `_run_*` functions; breadth jobs are generated by `_register_breadth_connectors()` from the connector registry. Every run writes a row to `scheduler_log`. Trigger manually: `POST /api/scheduler/trigger/{job_id}` (runs in a FastAPI `BackgroundTask`). Status: `GET /api/scheduler/status`. Jobs that ingest **embedded** sources call `_rebuild_search_index()` on success.

### MCP server

`mcp-servers/polaris_server.py` — 15 tools exposing all data sources to Claude directly. Runs as a stdio MCP server. Configure in `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "polaris": {
      "command": "/path/to/polaris/.venv/bin/python",
      "args": ["/path/to/polaris/mcp-servers/polaris_server.py"]
    }
  }
}
```

Primary tool: `gather_company_evidence(company_name, sector)` — returns the full cross-source evidence bundle + risk scores in one call.

---

## Front-end (`web/`)

The premium client app — **Next.js 16 (App Router) + React 19 + Tailwind v4**. The legacy `frontend/index.html` is now the internal ops console at `/internal`; the product lives in `web/`.

- **READ `web/AGENTS.md` first.** Next 16 has breaking changes vs training data — read the relevant guide in `web/node_modules/next/dist/docs/` before writing Next code. Notably `params` and `searchParams` are **Promises** (`await` them, or `use()` / `useSearchParams()` under a `<Suspense>` boundary).
- **No CORS:** `next.config.ts` rewrites `/api/*` and `/report/*` → `127.0.0.1:8077`. The dev server therefore needs the FastAPI backend running too.
- **Theming is CSS-based (Tailwind v4):** all tokens live in `app/globals.css` `@theme` — there is **no `tailwind.config`**. ⚠️ Changing an `@theme` token *value* requires `rm -rf web/.next` + restart; HMR serves stale compiled CSS otherwise (this has bitten twice).
- **App shell** (`app/layout.tsx`): `AppTopBar` / (`AppSidebar` + scrolling `main`) / `AppTicker`, wrapping every page (`h-screen overflow-hidden`, content scrolls in the middle). Components in `components/app-*.tsx`.
- **Two visual surfaces:** (1) the **dark terminal workspace** — neutral near-black canvas, brass as the single brand accent, functional green/amber/red, IBM Plex Mono numerics (`mono` class); (2) the **report "deliverable"** at `/briefings/[id]` only — light parchment + Playfair serif, using the `navy`/`parchment` brand tokens + `.briefing-prose`. Don't reuse the dark `Scorecard` on the light reader (it has its own `LightScorecard`).
- **Pages** are client components fetching via `lib/api.ts` (typed fetchers) + `lib/use-api.ts` (`useApi` hook): `/` (Overview dashboard), `/sectors` + `/sectors/[slug]` (the centerpiece, province-filterable), `/entities` + `/entities/[canonical]`, `/records/[table]/[pk]` (universal record detail), `/politicians` + `/politicians/[slug]`, `/search` (Ask Polaris), `/briefings` + `/briefings/[id]`. `lib/api.ts` also exports `recordHref()` (build `/records` links) and `partyColor()`.
- **MP photos** are served from `web/public/mp/{slug}.jpg` (downloaded local — openparliament hotlink-blocks images), referenced via the DB `photo_url`.
- **Data-viz** (hand-built SVG, minimal deps — d3 utilities only, React-19-safe): `components/dataviz.tsx` — `CanadaMap` (d3-geo choropleth rendering `public/canada-provinces.json`; province full-names→2-letter via `NAME2CODE`), `TrendArea`, `TrendBars`, `BarList`, `RadialNetwork`. `components/charts.tsx` — `RiskGauge`, `Scorecard`, `ConnectionCard`. `components/ui.tsx` — `Panel`, `Eyebrow`, `RiskBadge`, etc.

---

## Storage

| What | Location | Notes |
|---|---|---|
| Database | `polaris.db` (SQLite) or Supabase Postgres | Set by `DATABASE_URL` in `.env` (engine-agnostic; only an unused `sqlite_insert` import was SQLite-specific). Supabase project provisioned (Session pooler, port 5432) — see `SUPABASE_SETUP.md`; migrate with `scripts/migrate_to_postgres.py`. SQLite is ~2GB+ at full corpus and hits the local disk ceiling, which is the reason to move to Postgres. |
| MP photos | `web/public/mp/{slug}.jpg` | Downloaded local (openparliament blocks hotlinking); served same-origin by Next. |
| Vector index | `data/index/` | `vectors.npy` + `meta.json`, rebuilt from the DB — disposable. |
| Cached ZIPs | `data/cache/` | OCL comms (~22MB), Elections Canada (~109MB). Reused across restarts. |
| Reports | `reports/` | JSON + HTML per report ID |
| Prompts | `prompts/` | All AI prompt text. Edit here, not in Python. |
| Embedding model | `~/.cache/huggingface` | One-time local BGE-small download. |

---

## Data sources — live vs blocked

| Source | Status | Records |
|---|---|---|
| Federal Contracts | ✅ Live | ~1.15M (full corpus) |
| OCL Lobbying Communications | ✅ Live | ~363k — browser UA required on lobbycanada.gc.ca |
| Elections Canada Donations | ✅ Live | full ingest uncapped (`scripts/run_ingest.py donations_quarterly`); corporate donations banned since 2007 |
| Bills (LEGISinfo) | ✅ Live | 176 current Parliament |
| Canada Gazette Part I+II | ✅ Live | 638 entries via RSS |
| MPs / Hansard | ✅ Live | 343 MPs (photos/roles enriched); ~41 sector-keyword speech mentions (openparliament keyword search overlaps heavily — thin until a per-MP pass) |
| Breadth row-level: CER (~2k incidents), NPRI (~60k releases, one recent year), GC News (~20k releases) | ✅ Row-level | in `source_records` |
| Breadth catalogue-level: StatCan, IAAC, Transport, Geospatial | 🟡 Catalogue | dataset-metadata records only; IAAC/Transport need dedicated row-level connectors; full StatCan series + full NPRI history deferred to Postgres (disk) |
| Grants & Contributions, GIC Appointments | ⬜ Wired | trigger to populate |
| CanLII / Supreme Court (legal) | ⬜ Deferred | CanLII needs an approved API key; SCC needs a scraper |
| Social / Press releases | ⬜ Not started | Phase 2 |

---

## Key gotchas

- **Entity matching**: always `canonical_name == canonical OR raw_name ILIKE "%company%"`. Never `canonical_name ILIKE "%canonical%"` — short slugs cause false positives (e.g. `"bce"` matches "AbCellera").
- **OCL download**: requires `User-Agent: Mozilla/5.0 ...Chrome...` header. Without it, lobbycanada.gc.ca returns 403.
- **Hansard dates**: openparliament.ca sometimes returns year 4043. Filter: `1990 <= year <= 2035`.
- **CRTC RSS**: returns HTML 404 pages with HTTP 200. Check `content-type` header, not status code.
- **Gazette RSS**: URLs are `gazette.gc.ca/rss/p1-eng.xml` and `/p2-eng.xml` — the `/rpc-arc/rss/` path pattern 404s.
- **Report sections use new evidence fields**: if you add a new source to `gather.py`, also update `report_builder.py` template renderers and `risk_scorer.py` if the signal is risk-relevant.
- **DB init**: `api/database.py:init_db()` imports all models to register them on `Base.metadata` before `create_all`. Add new model imports there when adding tables (including `source_record`).
- **Big ingests must NOT run through the web server.** A multi-minute streaming ingest inside uvicorn can block the event loop and a remote stream dropping at the tail can crash the process — observed taking down the preview server mid-load. Use `scripts/run_ingest.py <job_id>` (standalone, single SQLite writer). Run big ingests **sequentially**, not concurrently — SQLite locks the whole file on write.
- **Government "CSV" links lie.** Many serve an HTML catalogue page or a zipped/XLSX payload with a 200 status. `pipeline/breadth.py:_stream_csv()` guards on the first bytes (`<` / `PK`) and bails so the caller falls back to the CKAN org catalogue. Resolve resource URLs live via CKAN `package_show` (they rotate) rather than hardcoding.
- **A dropped stream at the tail ≠ data lost.** `_stream_load` commits in batches as it goes, so a connection error near the end still leaves all committed rows in the DB even though the job logs `error`. Check the actual row count, not just job status.
- **`ANTHROPIC_API_KEY`**: search + reports degrade gracefully without it (deterministic planner, template prose, local embeddings still work). An *invalid* key logs 401 and falls back — check `.env` for a stale placeholder before assuming the Claude path is broken.
- **Reindex after text ingests**: scheduled jobs auto-reindex, but a manual/standalone ingest of an embedded source needs `POST /api/search/reindex`. SQL-only sources (contracts, donations, NPRI) never need it.
- **Full-corpus ingests need real disk headroom.** Contracts ~1.15M and the full Elections Canada donations corpus (multi-million rows) push `polaris.db` into the multi-GB range; a low disk throws `(sqlite3.OperationalError) database or disk is full` mid-ingest (committed batches survive — it just stops). This is the practical ceiling that motivates the Postgres move (`DATABASE_URL=postgresql+asyncpg://…`, code is engine-agnostic). Check `df -h` before kicking off full ingests.
- **Scheduled refresh runs standalone, not just in-server.** The scheduler also runs as `scripts/run_scheduler.py` (reuses `start_scheduler()`), kept alive by launchd (`deploy/com.polaris.scheduler.plist` + `deploy/README.md`) — enable it only AFTER moving to Postgres (a near-full SQLite disk is what we're escaping). `migrate_to_postgres.py` is resumable (paginates by `id`, resumes from target max id, resets PG sequences).
- **openparliament image hotlinking is blocked** (Referer-based) — server-side fetch works but the browser `<img>` 403s. MP photos must be downloaded local (`download_mp_photos.py` → `web/public/mp/`), not pointed at openparliament URLs. Its keyword speech search returns heavily overlapping results across keywords, so a sector-keyword sweep yields few unique rows.
- **Next 16 duplicate-import = app-wide blank.** A duplicate `import Link` (or any compile error) in one route surfaces as a build error that blanks affected UI across routes until fixed — check the dev console/`preview_console_logs` when links/components silently vanish.
- **Records route is generic via `SPECS`.** Any new table added to `search.sql_search.SPECS` is automatically pullable at `/records/{table}/{pk}`; add its alias to `_ALIASES` in `records.py` if the semantic/SQL layers label it differently.
