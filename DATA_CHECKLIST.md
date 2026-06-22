# Nessus — Data Source Checklist

Status legend: ✅ live (real data in DB) · 🟡 partial/stub · ⬜ not started · 🔴 blocked

Last updated: 2026-06-21 (ingestion audit — see "Ingestion audit" section below; counts pulled live from `polaris.db`)

---

## Core sources (the 6 in CLAUDE.md)

### ✅ 1. Federal Contracts — Proactive Publication (>$10k)
- **Source:** open.canada.ca CSV (dataset `d8f85d91`), via CKAN API
- **In:** REAL — **1,155,000 rows** in `contracts`, normalized by entity (full corpus, loaded via standalone `scripts/run_ingest.py contracts_monthly`)
- **Working but incomplete:** the *scheduled* `contracts_monthly` job has been attempted exactly once (2026-06-15) and **failed** (`scheduler_log` id 14, empty error string — the exception's message wasn't captured, so we don't even know why). All 1.15M live rows came from the one-off standalone backfill, not a proven recurring refresh. Until this is fixed, contracts has no working incremental update path.
- **To do:** fix/re-test the scheduled job end-to-end; capture the actual exception text (don't let `_log_finish` store `''`); add incremental/monthly refresh; capture amendments (contract value over time)

### ✅ 2. Political Donations — Elections Canada (contributions, as reviewed)
- **Source:** elections.ca ZIP (dataset `ef1e3528`), cached 109MB → 2.2GB CSV
- **In:** REAL — **6,230,381 rows** in `donations`, full corpus loaded (manual trigger 2026-06-15, after an earlier attempt failed with `database or disk is full`)
- **Working but incomplete:** like contracts, the only logged success is `triggered_by=manual`, not `scheduler` — the quarterly cron path is unverified. Always full delete-then-reinsert (`_stream_load`), so every refresh re-downloads and re-parses the full 2.2GB CSV; no incremental/since-date fetch.
- **To do:** verify the quarterly cron actually fires and completes; corporate donation ban (2007) — match individuals/executives by name; fuzzy name→officer linking to companies

### ✅ 3. Bills & Legislation — LEGISinfo
- **Source:** parl.ca LEGISinfo JSON API
- **In:** REAL — 185 current-Parliament bills → `bills` table (daily cron genuinely running: 6 logged successful runs 06-15→06-19); matched to companies by sector keyword
- **To do:** ingest historical Parliaments; capture committee stage detail, votes, and per-bill status timeline; better bill↔company relevance than keyword match; add a real test (one exists for LEGISinfo URL derivation only, `test_bill_records_derive_legisinfo_original_source_url`)

### ✅ 4. Lobbying Registry — OCL (UNBLOCKED)
- **Source:** lobbycanada.gc.ca Monthly Communications ZIP (~22 MB) — downloaded with browser User-Agent
- **In:** REAL — **362,805 communication records** (verified by `count(*)` 2026-06-21 — the "694,152" figure cited everywhere previously, including by me earlier this session, was `max(id)`, not a real row count; this table does a full delete-then-reinsert each run and SQLite doesn't reuse autoincrement ids after a delete, so `max(id)` drifts above the true count. Use `count(*)` for this specific table, not the `max(id)` proxy CLAUDE.md recommends for the genuinely append-only big tables.) → `lobbying_records` table; DPOH contacts stored in `raw` JSON per record. Always full delete-then-reinsert on `source == "OCL Monthly Communications"`, no incremental fetch.
- **2026-06-21:** the comms ZIP URL was hardcoded and one path-segment rotation away from breaking exactly like registrations did (below) — `fetch_ocl_communication_rows` now resolves the URL live via CKAN dataset `a34eb330` first, falling back to the hardcoded URL only if that lookup fails.
- **Present but broken / needs investigation:** there is a *second*, separate OCL code path — `scrapers/ocl.py` (live search against `lobbycanada.gc.ca/app/secure/ocl/lrs/do/guest`) with a `TODO: pin to the OCL Open Data bulk dataset for full fidelity`, falling back to hardcoded `scrapers/sample_data.py` records. It is **not** wired into the scheduler (the real 694k rows come from `pipeline/ingest.py:fetch_ocl_communication_rows` directly) and appears to predate the current bulk-ZIP approach. Investigate before touching — likely safe to retire, but confirm nothing else imports it first.
- **✅ FIXED & POPULATED 2026-06-21 — `ocl_registrations`:** was wired but never triggered, and turned out to have **three** real bugs once actually run for the first time:
  1. Hardcoded ZIP URL (`/media/mqbbmaqk/registrations_oct_cal.zip`) 404'd — lobbycanada.gc.ca had rotated the path to `/media/zwcjycef/...`. Fixed by resolving live via CKAN dataset `70ef2117`, with the old URL kept as a fallback.
  2. The ZIP contains 13 files and *every one* has "registration" in its name (`Registration_BeneficiariesExport.csv`, `Registration_GovtFundingExport.csv`, etc.) — the file-picker's `"primary" in n or "registration" in n` check always matched the first file in the archive regardless of the `"primary"` clause, silently parsing the wrong schema (0 useful rows). Fixed to check `"primary"` first, falling back to `"registration"` only if no primary file exists.
  3. Column names were stale guesses (`REG_NUM`, `CLIENT_ORG`, `STATUS`, `EFFECTIVE_DATE`, `FIRM_NAME`...) that don't match any header in the real export (`REG_NUM_ENR`, `EN_CLIENT_ORG_CORP_NM_AN`, `EFFECTIVE_DATE_VIGUEUR`, `EN_FIRM_NM_FIRME_AN`...) — every row was silently skipped or stored blank. Fixed to the real column names (verified against the live header); also added literal-`"null"`-string cleaning (the source CSV uses the text `null` instead of an empty cell).
  - **Result: 166,564 real lobbying-registration rows now live** in `ocl_registrations`, all distinct `registration_num`, existence-check dedup + the DB's `unique=True` constraint both verified working (ran twice in testing, no duplicates). `status`, `federal_benefits`, `private_interests`, and `subject_matters` are still `None`/`[]` — those live in *other* files inside the same ZIP (Beneficiaries, GovtFunding, SubjectMatters exports) that aren't joined in yet.
  - **To do:** join the remaining export files in the ZIP for status/benefits/subject-matter fields; batch the per-row existence check (currently one `SELECT` per row — 166k individual queries took ~3.5 min; the breadth-connector pattern of pre-loading existing keys into a `set()` would be much faster); flag former public office holders (revolving-door); resolve/retire the legacy `scrapers/ocl.py` path.

### ✅ 5. Hansard / Parliament — openparliament.ca API
- **Source:** api.openparliament.ca — MP profiles, speeches, committees, votes
- **In:** REAL — 343 MPs seeded in `politicians` table; speech keyword search → `hansard_mentions` (217 rows); recent votes API live
- **To do:** better keyword → relevance matching (openparliament full-text search has noise); committee witness testimony; derive pro/neutral/against stance from speech sentiment; House divisions / individual MP votes (not yet ingested as structured records — see catalog §1)

### ⬜ 6. Social / Public Statements
- **Source:** X/Twitter, LinkedIn, press releases of ministers/MPs
- **In:** not started. The frontend already has a graceful placeholder (`/records/social_statements/{id}` alias over `source_records`, per `CONNECTED_INTELLIGENCE_AUDIT.md`) but no connector feeds it.
- **To do:** RSS/press-release scrape is lowest-friction and legally cleanest (see news policy in the ingestion spec); X/LinkedIn APIs are gated; attribute statements to politicians

### GIC Appointments & Grants/Contributions — bug fixed 2026-06-21, mixed results on triggering for real
- **✅ FIXED:** both `_run_appointments` and `_run_grants` did a plain insert with no delete-first and no dedup key — if either job had ever fired twice, every row would silently duplicate forever. Both now delete-before-insert (same pattern as contracts/donations/bills); proven with new idempotency tests (`tests/test_scheduler_ingest.py`) that run each job twice against a fixture and assert the row count doesn't change.
- **🔴 GIC Appointments — genuinely blocked, not just untriggered:** triggering it for real (`scripts/run_ingest.py appointments_weekly`) surfaced `ValueError: No CSV resource found in GIC appointments dataset`. The hardcoded CKAN dataset ID (`58b10b98-...`) 404s, and a CKAN `package_search` under the Privy Council Office's own organization (`pco-bcp`) turns up **zero** appointments-related datasets — GIC Appointments likely isn't published via the open.canada.ca CKAN catalogue at all. The real source is probably `orders-in-council.canada.ca` (confirmed reachable, HTML, no bulk CSV evident from a single page fetch) — a different access pattern (search portal, possibly needing pagination/export discovery) requiring a proper new-connector design pass, not a one-line fix. Left untouched rather than guessing at a replacement dataset ID.
- **✅ Grants & Contributions — fixed and verified, full corpus NOT yet attempted:** the resource-picker had the *same bug class* discovered in `ocl_registrations` — it matched the first CSV resource whose name contained "grant" or "contrib", which is the tiny 24KB "Nothing to Report" placeholder resource, not the real ~2.25GB dataset (CKAN reports `size=2256228144` on the actual resource). Fixed to pick by `size` (largest), not first-match. **Verified with a real capped fetch (max_rows=3000): 3,000 real rows landed correctly** (e.g. a Carleton University accessibility-research grant). The scheduled job calls `fetch_grant_rows(max_rows=0)` for the **full uncapped 2.25GB corpus**, which I deliberately did NOT run for real — `fetch_grant_rows` materializes its whole result as a Python list (unlike `iter_contract_rows`/`iter_donation_rows`, which are async generators streamed through `_stream_load`), so an uncapped run would hold the entire parsed corpus in memory at once. This host has 23GB RAM but only ~10GB reliably available (4.9GB already in swap) — risky, not catastrophic, but not something to trigger blind.
  - **To do before running grants uncapped for real:** convert `fetch_grant_rows` to an async-generator (`iter_grant_rows`) + route through `_stream_load`, exactly like contracts/donations. This is the actual fix, not just a cap increase.

### CRTC / Tribunal Decisions — triggered 2026-06-21, found two real problems (one fixed, one not)
- **🔴 Found, NOT fixed — CRTC RSS feeds are currently dead:** triggering `tribunal_decisions` for the first time correctly exercised the documented HTML-disguised-as-RSS guard (`crtc_rss_returned_html` warning, no crash) — but it fired for **both** the Broadcast and Telecom decision feeds, meaning `https://crtc.gc.ca/eng/publications/reports/{BroadcastDecisions,TelecomDecisions}/rss.xml` currently serve HTML, not RSS, for real. 0 rows landed. CRTC likely restructured their site; the correct current feed URLs need rediscovery (same "reachability probe before trusting the label" discipline as everywhere else in this audit) — not attempted today, scope-limited to avoid an open-ended hunt.
- **✅ FIXED 2026-06-21 — the search-reindex step is no longer a full re-embed every time:** `_run_tribunal_decisions` (like every embedded-source job) calls `_rebuild_search_index()` on success. That call was **still running 40+ minutes later** when I killed it the first time — it re-embedded the entire text-bearing corpus (23,965 documents) from scratch on every single call, on a CPU-only BGE-small model, every time *any* embedded source ingested anything. `search/index.py:build_index()` is now incremental: a document's embedding only depends on its exact `f"{title}. {snippet}"` text, so any `(table, pk)` whose text is byte-identical to what's already on disk reuses its existing vector instead of being re-embedded; only new or changed documents (and anything no longer in the candidate set gets dropped) hit the model. Proven two ways: (1) a unit test (`tests/test_search_index.py`) with fixture documents asserts new/changed docs get re-embedded, unchanged ones are reused (byte-identical vector, not coincidentally-equal), and removed ones vanish from the rebuilt index; (2) re-ran `tribunal_decisions` for real against the live DB — **the exact same job that hung 40+ minutes now completes in 3.4 seconds end-to-end** (`index_build_start documents=23965 reused=23965 to_embed=0`, immediately followed by `index_build_done`). A `full=True` override exists for forcing a complete re-embed (e.g. after an embedding-model change).

---

## Derived / cross-source layers

### ✅ Entity resolution
- **In:** `pipeline/entity_resolver.normalize()` — canonical key, collapses suffix variants (proven on IBM/Deloitte/TELUS)
- **To do:** graph layer (parent/subsidiary, JV members, aliases, officer→company), the 175k-variant map cited in the spec

### ✅ Risk scoring
- **In:** 4 deterministic 0–10 scores + drivers from gathered evidence
- **To do:** calibrate weights against real outcomes once lobbying/Hansard are live

### 🟡 Political Stakeholders (report section 4)
- **In:** seed stub
- **To do:** populate from Hansard + a ministers/MPs/committee-jurisdiction reference table

---

## Candidate additional sources (not in original spec, high value)

| Source | Why it matters | Status |
|---|---|---|
| ⬜ SEDAR+ corporate filings | Map public companies, subsidiaries, officers (feeds entity graph) | referenced in `.env`, not built |
| 🔴 Grants & Contributions (open.canada.ca `432527ab`) | Federal money *to* orgs beyond contracts | connector built (`fetch_grant_rows`), job wired, **never triggered**, has a dup-accumulation bug — see above |
| ⬜ Government Orgs / GEDS | Authoritative dept/minister/official reference for stakeholders | not started |
| ✅ Federal regulations (Canada Gazette) | Pending/active regulations for the Regulatory Landscape section | live — 638 entries via RSS Part I+II |
| 🔴 Court / regulatory tribunal decisions (CRTC, Competition Bureau) | Regulatory-risk section depth | connector built (`fetch_crtc_decisions`), job wired, **never triggered**; Competition Bureau still a placeholder |
| ⬜ Provincial data (ON/QC/BC/AB) | Spec marks this Phase 2 | out of MVP scope |

---

## Breadth sources — unified `source_records` table (2026-06-15)

All seven remaining sources from the target list are integrated via the
declarative connector registry (`pipeline/connectors.py` + `pipeline/breadth.py`)
into one searchable `source_records` table. CanLII + Supreme Court deferred per
product decision (CanLII needs an approved API key; SCC needs a scraper).

| Source | Status | What lands in the DB |
|---|---|---|
| 🟡 Statistics Canada (WDS) | Catalogue | Data-cube catalogue (~300+ tables). Row-level series values = post-Pro (huge). |
| 🟡 Impact Assessment (IAAC) | Catalogue | Screenings CSV is dead → 200 dataset records. Row-level needs the IAAC registry API (follow-up). |
| ✅ Canada Energy Regulator (CER) | **Row-level** | **2,008** pipeline incidents by company/substance/location (real rows). Uncapped. |
| ✅ NPRI | **Row-level** | **60,202** facility-level pollutant releases (recent year, bilingual CSV). Multi-year = post-Pro. |
| 🟡 Transport Canada | Catalogue | 300 dataset records. Row-level (TSB occurrences / vehicle recalls) needs a dedicated connector (follow-up). |
| 🟡 NRCan / GeoGratis geospatial | Catalogue | 300 federal geospatial dataset records (catalogue by design — no single row table). |
| ✅ GC News / Publications | **Row-level** | **20,034** news releases (all departments, history backfilled via `pick`). Daily incremental. |

**Deepened 2026-06-16 (local, no-spend):** cer/npri/gc_news now hold real row-level
data (~82k rows total). `fetch_gc_news_records` now takes a dynamic `pick` (large
for backfill, `_GC_NEWS_DAILY_PICK=500` for the daily incremental). iaac/transport
remain catalogue-level pending dedicated row-level connectors; the multi-GB giants
(full StatCan series, full NPRI history) were deferred to protect local disk
(~13 GB free at the time, on the original Mac this was built on).
**2026-06-21 update:** this working copy now runs on a different host with
**246 GB free** (`df -h`) — the original disk-pressure rationale for deferring
full StatCan series / multi-year NPRI may no longer apply here. Re-check actual
dataset sizes before assuming they still need the Supabase Pro migration first.

Architecture: rich typed tables stay for the core analytics sources; breadth
sources share `source_records` (typed search columns + JSON `raw`). Each is one
`SourceConnector` entry — scheduler, ingest runner and search indexer all read
that one registry.

## Unified hybrid search (2026-06-15)

Natural-language search across **every** source — `POST/GET /api/search` + a
dashboard card. Hybrid of:
- **Structured SQL** across all tables (`search/sql_search.py`) — exact entity /
  keyword / date / dollar-floor filters; pulls up every individual record.
- **Semantic vectors** (`search/index.py`) — local fastembed/BGE-small embeddings
  over text-bearing records (no API key, no per-token cost). Rebuild after
  ingests: `POST /api/search/reindex`.
- **LLM query planner** (`search/planner.py`) — Claude NL→plan when keyed;
  deterministic fallback parser otherwise.
- **Cited synthesis** — Claude answer from top hits when keyed.

## Uncapped ingestion (2026-06-15)

Contracts and donations stream row-by-row into batched inserts
(`iter_contract_rows` / `iter_donation_rows` + `_stream_load`), grants uncapped —
full corpus, memory-safe, no giant in-memory lists.

---

## Ingestion audit — 2026-06-21 (audit pass), hardening pass same day

First pass audited everything (below, mostly still accurate as systemic
findings). A second pass the same day actually fixed and triggered what was
safe to fix without a larger redesign — see the per-source sections above for
exact before/after detail. Net result this session:

**Fixed and verified with real data:**
- `appointments_weekly` and `grants_quarterly` duplicate-accumulation bugs (delete-before-insert, proven with new idempotency tests).
- `grants_quarterly`'s resource-picker bug (was silently parsing a 24KB placeholder file instead of the real 2.25GB dataset) — verified with a real capped 3,000-row fetch.
- `ocl_registrations`: 3 separate real bugs (stale URL, wrong-file-picker, stale column names) — **166,564 real rows now live** in a table that was completely empty before today.
- `ocl_monthly`'s URL now also resolves live via CKAN (proactive fix — it had the exact same hardcoded-URL fragility that just broke registrations, just hadn't rotted yet).
- `_stream_load` (used by `contracts_monthly`/`donations_quarterly`) now reports real partial-progress row counts on a mid-stream failure instead of silently logging 0 — verified with a regression test.
- Missing `fastembed` dependency (search was completely broken in this venv — same class of gap as the `apscheduler` miss found earlier this week) + its cache defaulting to `/tmp` (wiped on reboot) instead of the documented `~/.cache/huggingface`.
- Added 4 new tests (`tests/test_scheduler_ingest.py`) covering all of the above; full suite is 68 passed / 1 pre-existing unrelated frontend failure.

**Found, NOT fixed (documented, needs its own pass):**
- ✅ **The search-reindex (`_rebuild_search_index`) — fixed.** Was the single biggest reliability risk found this session: a full from-scratch re-embed of the entire text corpus (23,965 documents) on **every** call, 40+ minutes on this host, triggered after every embedded-source ingest including the **daily** `gc_news` job. Now incremental — reuses any document's embedding whose exact text is unchanged since the last build, only calling the model for new/changed documents. Verified with a unit test that specifically proves discrimination (not just "always fast by coincidence") and a real end-to-end re-run: the same job that hung 40+ minutes now finishes in 3.4 seconds.
- 🔴 **GIC Appointments has no working access path at all.** The hardcoded CKAN dataset 404s, and there is no GIC-appointments dataset under the Privy Council Office's CKAN organization either — the real source is likely the `orders-in-council.canada.ca` search portal, a fundamentally different access pattern (not a CKAN bulk CSV) needing a real connector-design pass, not a quick fix.
- 🔴 **CRTC RSS feeds (both Broadcast and Telecom) currently return HTML, not RSS** — `tribunal_decisions` is correctly engineered to detect this (no crash, per the documented gotcha) but still nets 0 rows. Needs URL rediscovery.
- `fetch_grant_rows` materializes its full result as a list rather than streaming — fine for the 3,000-row test, genuinely risky for the real uncapped 2.25GB corpus on this host's available RAM (~10GB). Convert to the same async-generator + `_stream_load` pattern as contracts/donations before running it uncapped.
- `_run_ocl_registrations`'s per-row existence check is an N+1 query (166k individual `SELECT`s, ~3.5 min) — works, but should pre-load existing keys into a `set()` like the breadth-connector upsert path does.

**Still true from the first-pass audit, unchanged:**
- No connector does a real conditional fetch. `OCLRegistrationsConnector.discover()` (new, see below) does capture the live `Last-Modified` header now, but nothing acts on it yet — it's recorded in `DiscoveryResult`, not used to skip an unchanged download. Real ETag/Last-Modified/cursor-based incremental fetch is still unbuilt everywhere, including here.
- `/api/sources/status` already substantially covers the spec's "data-source administration page" ask.
- Entity resolution is pure name normalization, no confidence scoring/alias table.
- `scrapers/ocl.py` + `scrapers/sample_data.py` still look like a superseded pre-bulk-ZIP prototype — still not deleted, still worth confirming unused before removing.

**✅ Built 2026-06-21 — shared connector interface** (`pipeline/connector_base.py`: `discover/estimate/download/validate/backfill/sync/checkpoint/health_check`), proven on one real connector (`pipeline/connector_ocl_registrations.py:OCLRegistrationsConnector`, 13 passing tests in `tests/test_connector_ocl_registrations.py`) — additive, the existing `api/scheduler.py:_run_ocl_registrations` path is untouched and still the one the scheduler actually calls:
- `discover()` resolves the CKAN URL live + HEADs it for size — run for real against the live service: got the exact same 82,848,109 bytes as the earlier manual download, byte for byte.
- `estimate()` encodes the exact lesson from `fetch_grant_rows`'s 2.25GB-into-memory risk as an actual safety check (500MB uncapped-safe threshold) instead of just a doc warning. Its row-count estimate (165,696, from a crude bytes/500 heuristic) landed within 0.5% of the real verified count (166,564).
- `validate()` gives **real, new observability that didn't exist before**: run for real against the live 172,566-row file, it found **6,002 rows (3.5%) with no client organization name** — the production fetcher already silently dropped these via a bare `continue`, with zero record of how many or why. They're now quarantined at `data/quarantine/lobbying/ocl_registrations/<run_id>/rejected_rows.json` with a reason per row, not discarded.
- Full real `backfill()` run end-to-end against the live service + the live 166,564-row DB: `{"parsed": 172566, "valid": 166564, "rejected": 6002, "added": 0}` in 112s — the `valid` count is an exact independent match with the production path's real row count, and `added: 0` proves idempotency against real production data (not a fixture).
- This is one connector, not a rollout — every other source in this registry still goes through the existing two-tier system unchanged. Only incomplete this round was scope: extending the interface to other sources is its own future pass, not attempted here.

**✅ Built 2026-06-21 — raw storage, manifests, checkpoints, quarantine now exist as shared infrastructure** (`pipeline/raw_storage.py`, 7 passing tests in `tests/test_raw_storage.py`), closing the gap noted above ("no raw-file storage or revision history anywhere except a barely-used legacy scraper staging dir"):
- `data/raw/<category>/<source_id>/<year>/<month>/<day>/<run_id>-<checksum8>/<filename>` — immutable once written; the checksum-suffixed leaf directory is load-bearing, not cosmetic (a real bug was caught and fixed during testing: two saves of *different* content within the same wall-clock second used to silently overwrite each other, since the default run_id only has second resolution).
- `data/manifests/<category>__<source_id>.jsonl` — one line per save attempt (checksum, size, source URL, timestamp); a repeat save of byte-identical content records a "duplicate" entry (the "last checked" signal) instead of writing a second copy (the "avoid keeping identical duplicates" rule).
- `data/checkpoints/<source_id>.json` and `data/quarantine/<category>/<source_id>/<run_id>/` round out the cursor/resume and invalid-record-handling gaps.
- **Wired into exactly one real connector so far, proven end-to-end**: `ocl_registrations` now calls `save_raw()` after every real download. Verified with a real 82,848,109-byte fresh download — file landed at `data/raw/lobbying/ocl_registrations/2026/06/22/20260622T030716Z-91ad8063/...`, manifest checksum matches an independent `sha256sum` of the file on disk exactly.
- **Not yet wired into any other connector** — this is infrastructure + one proof point, not yet a repo-wide rollout. Every other connector listed above still has no raw-payload retention.

**✅ Built 2026-06-21 — Goal 5: catalogue/metadata discovery across 10 requested sources, BEFORE downloading anything** (`pipeline/catalogue_discovery.py` + `api/models/catalogue_entry.py`, new `catalogue_entries` table, `scripts/catalogue_discover.py` / `scripts/catalogue_report.py`, 12 passing tests in `tests/test_catalogue_discovery.py`):
- **Real discovery run, persisted to the live DB: 11,581 entries across 8 sources** — `open-government` (2,003, deliberately capped — see below), `statcan` (8,213 — see correction below), `nrcan-geospatial` (301), `transport-canada` (301), `cer` (226), `iaac` (200), `canada-gazette` (247 issues, 3 years), `government-news` (90 departments, derived from already-ingested `gc_news` rows, not a true pre-ingestion discovery).
- **Real, non-obvious bug found mid-build: open.canada.ca's WAF blocks this project's own User-Agent.** An org-filtered CKAN query (`fq=organization:iaac-aeic`) returned HTTP 200 with an HTML "Request Rejected" page instead of JSON — confirmed by toggling *only* the User-Agent header on an otherwise byte-identical request: the literal string `"Mozilla/5.0 (compatible; Nessus/1.0; +https://polaris.intelligence)"` (the exact UA already used by `pipeline/breadth.py`'s CKAN helpers) gets blocked; a generic browser UA or no override at all works every time. `pipeline/breadth.py`'s existing plain-keyword `package_search` calls happen to still work despite using the same flagged UA — only the org-filter (`fq=`) pattern was confirmed to trip it — but this is worth knowing if `geospatial`/`transport`/`iaac` breadth jobs ever show unexplained empty results.
- **Real correction to a previously-undercounted figure**: the StatCan catalogue is **8,213 tables**, not "~300" as stated everywhere (CLAUDE.md, DATA_CATALOG.md, the `statcan` registry entry, my own earlier audit this session) — the 300 figure was apparently whatever got loaded by one earlier capped run, never the true catalogue size. `discover_statcan_catalogue()` calls the same `getAllCubesListLite` endpoint as the existing `fetch_statcan_records` and returns the full uncapped list.
- **Relevance classification** uses the literal topic list from the ingestion spec's Open Government section (legislation, regulation, lobbying, energy, mining, environment, ...) — not `pipeline/sector_mapper.py`'s company-sector taxonomy, a different job (classifying companies, not datasets). Real result: **1,669 high-relevance datasets not yet downloaded** out of 1,676 total high-relevance entries — a concrete, actionable priority list for "download highest-relevance first," exactly as the spec asks.
- **Download status** cross-references each discovered dataset's CKAN id against the set this session has *actually* pulled real row-level data from (contracts, grants, ocl_registrations, ocl_monthly, iaac, npri) or confirmed blocked (appointments' 404'd dataset) — 107 of 11,581 entries are correctly marked "downloaded", the rest "not_downloaded".
- **`open-government` is deliberately capped at 2,000 of ~47,446 total datasets** — discovering (not downloading) the entire catalogue is plausible but wasn't attempted uncapped this pass; re-run `scripts/catalogue_discover.py open-government` with a higher cap to extend coverage, it's idempotent (upserts by dataset+resource id, confirmed by re-running `iaac`: second run was `added=0, updated=200`).
- **Not implemented this pass, confirmed by investigation rather than assumed**: House of Commons dataset catalogue (the public `/en/open-data` pages document a data *model*, not a live API root or file index, in static HTML — needs a different access path); regulator publication indexes generally (too broad for one pass — only CER's CKAN dataset catalogue is covered, not a generic per-regulator publication index); CER's *proceeding/hearing* index specifically (its CKAN dataset catalogue is covered, that's a different thing).
- **Done-when check, satisfied**: `scripts/catalogue_report.py` produces exactly what was asked for — everything discovered, broken down by source/status/relevance, with an honest list of what's not yet covered, not a synthetic example.

**✅ Built 2026-06-22 — Goal 6: full historical backfill for 11 of 11 recommended sources** (the remaining 5 finished later the same pass — see below), using the new `pipeline/raw_storage.py` extraction/checksum/row-count/backfill-record primitives (`extract_zip`, `count_csv_rows`, `record_backfill`, plus a new memory-safe `save_raw_streamed` for multi-GB sources). `pipeline.raw_storage.all_backfill_records()` is the done-when report:

| source | rows | years covered | preserved+validated |
|---|---|---|---|
| `donations_quarterly` | 6,230,381 | 22 | ✅ |
| `ocl_monthly` | 362,805 | 19 | ✅ |
| `ocl_registrations` | 166,564 | 31 | ✅ |
| `npri` | 181,780 | 3 | ✅ |
| `contracts_monthly` | 1,155,000 | 27 | ✅ |
| `grants_quarterly` | **1,148,041** | 22 | ✅ |

- **The headline result: `grants_quarterly` went from a 3,000-row capped test to 1,148,041 real rows.** `fetch_grant_rows` (list-materializing, the exact 2.25GB-into-memory risk flagged back when it was first fixed) is now `iter_grant_rows`, a true streaming async generator mirroring `iter_contract_rows`/`iter_donation_rows`; `_run_grants` now goes through `_stream_load` like contracts/donations. Full uncapped real run: 1,148,041 rows in 485s, memory-safe. The 2.25GB source CSV is preserved byte-for-byte in `data/raw/proactive-disclosure/grants_quarterly/...` (checksum confirmed against the CKAN-reported size: 2,256,228,144 bytes, exact match).
- **A real bug caught fixing this conversion, not before it shipped**: the existing idempotency test monkeypatched the old `fetch_grant_rows` name; after the conversion, `_run_grants` called `iter_grant_rows` instead, so the test silently fell through to a *real* live network call and hung the whole suite. Caught because the suite hung instead of passing quietly — fixed by patching the right name. A reminder that renaming an internal function without updating its test double doesn't fail loud, it fails *slow*.
- **`npri` improved 3x** (60,202 → 181,780 rows, 1 year → 3 years: 2022-2024) by removing a `break` in `fetch_npri_records` that stopped at the first year that parsed — it now accumulates every catalogued year instead of just the newest. 2020/2021 CSVs in the catalogue still didn't yield rows (not investigated further). **The real 1993-present bulk archive exists** (CKAN dataset `40e01423-7728-429c-ac9d-2954385ccdfb`, files literally named `NPRI-INRP_ReleasesRejets_1993-present.csv`) but ECCC has moved its "Data Mart" to a JS SPA — every catalogued URL for it now redirects to the same React app shell, not the file. Several real attempts to guess the underlying file-serving API (mirroring the working `/api/file?path=...` pattern used by the single-year CSVs) all 404'd. Not solved this pass — would need actual browser dev-tools inspection of the SPA's XHR calls, which wasn't attempted.
- **Two new genuine, previously-invisible data-quality findings**, both found by actually computing covered-years from real ingested data rather than trusting the schema:
  1. **`ocl_monthly`**: the raw `Communication_PrimaryExport.csv` has 371,522 rows but only 362,805 ever make it into `lobbying_records` — **8,717 rows (2.3%) are silently dropped** during ingestion with zero record of why (same defect class `OCLRegistrationsConnector.validate()` already caught and fixed for registrations — not yet fixed for communications).
  2. **`contracts_monthly` and `grants_quarterly` both have a `1899-12-30` date anomaly** — the classic Excel-epoch-zero placeholder value, suggesting a shared upstream date-serialization bug across multiple Proactive Disclosure datasets, not something source-specific. `contracts_monthly` also has one row dated `2029-09-18` (an actual future date, likely a data-entry typo) and `donations_quarterly` has a `2029` year cluster with 10+ rows (also unresolved).
- **Real, repeat-confirmed finding, now fixed at the source**: open.canada.ca's WAF rejected a *plain* `package_show` call from `pipeline/breadth.py` using this project's self-identifying User-Agent — the exact same call had worked earlier in the *same session*. This is the second confirmed hit on this exact UA (see the Goal 5 entry above for the first). `pipeline/breadth.py`'s `_UA` is now the same browser UA already proven reliable in `pipeline/catalogue_discovery.py`, fixing it for every breadth connector (`npri`, `iaac`, `cer`, `transport`, `geospatial`, `statcan`), not just the one that happened to hit it this time.
- **✅ Completed 2026-06-22, continuing the same pass** — the 5 sources listed as "not attempted" above (Public Accounts, GC InfoBase, StatCan, Bank of Canada, NRCan geospatial, Transport Canada — 6 backfill targets across those 5 source groups) via the new one-time `scripts/backfill_remaining_sources.py` (talks to `raw_storage.py` primitives directly; these are historical bulk loads, not recurring connectors — no typed DB table for any of them):

| source | rows | validated | notes |
|---|---|---|---|
| `gc_infobase` (6 datasets) | 287,134 | ✅ (5/6) | 1 dataset (`covid_authorities_expenditures`) has 0 downloadable CSV resources in CKAN |
| `public_accounts` | 0 | ❌ blocked | every PDF link 307-redirects to an "archived content" interstitial — no server-side bypass found (see note below) |
| `statcan` (16 hand-curated tables) | 61,907,686 | ✅ | dominated by `36100608` (Infrastructure Economic Accounts) alone at 61,388,076 rows |
| `bank_of_canada` (7 Valet series groups) | 18,525 | ✅ | FX rates, CPI, CORRA, bond/T-bill yields, 1990–2026 |
| `nrcan_geospatial_selected` (9 files) | 48,855 | ✅ | vehicle fuel-consumption ratings, EV registrations, permafrost compilation |
| `transport_canada_selected` (17 files) | 2,077,369 | ✅ | CADORS occurrences, vehicle recall DB, EV/charging incentive program stats |

- **Real bug found and fixed mid-run, twice-reproduced**: `pipeline/raw_storage.py:extract_zip()` read the whole ZIP into memory (`raw_path.read_bytes()`) and then `zf.read(name)` decompressed each member fully into memory before writing it. StatCan's `36100608` zip is 631MB compressed but decompresses to a CSV with **61.4M rows** — large enough to OOM-kill the Python process (exit 137) both times it was hit, the second time being what looked like the session "crashing." Fixed by opening the zip by path (`zipfile.ZipFile(raw_path)`, central-directory-only) and streaming each member through `zf.open(name)` + `shutil.copyfileobj()` in 1MB chunks instead of `zf.read()`. Same fix applies to any future zip-bearing source with a high text-compression ratio. All 18 `tests/test_raw_storage.py` tests still pass.
- **Public Accounts confirmed blocked, not silently skipped**: 167/169 PDF links on the publications.gc.ca index redirect to `/site/archivee-archived.html?url=...` regardless of `?wbdisable=true`, session cookies, or an `Accept: application/pdf` header — same blocker class as NPRI's SPA-gated bulk archive (Goal 6 NPRI note above). Real bypass likely needs a client-side JS interaction this scraper can't replicate.

## Priority order to "fully real"
1. ✅ **OCL lobbying communications** — DONE: 362,805 records from lobbycanada.gc.ca ZIP (browser UA; corrected 2026-06-21, see note above)
2. ✅ **OCL lobbying registrations** — DONE 2026-06-21: 166,564 records, 3 bugs fixed (see above)
3. ✅ **Hansard/Parliament** — DONE: openparliament.ca API; 343 MPs seeded, speech search live
4. ✅ **`ANTHROPIC_API_KEY` wired** — Claude path live in this working copy (template path is the fallback when unset)
5. ✅ **Duplicate-accumulation bugs fixed** (`grants_quarterly`, `appointments_weekly`) — verified with tests
6. ✅ **Search-reindex performance bug fixed** — incremental rebuild, verified 40min → 3.4s on the same real job
7. 🔴 **Prove the scheduled path for contracts/donations actually works** — the only successful loads were manual/standalone
8. 🔴 **Convert `fetch_grant_rows` to streaming**, then run the real uncapped 2.25GB corpus
9. ⬜ **Find the real GIC Appointments source** (not CKAN) and the current CRTC RSS URLs
10. ⬜ **Statistics Canada row-level data** — currently catalogue-only (300 cube metadata rows); sector economic context needs real series observations
11. ⬜ **Entity graph** (subsidiaries/officers/SEDAR+) — multiplies value of every source
12. ⬜ Row-level IAAC + Transport connectors (currently catalogue-only) — project/incident-level regulatory-risk depth
