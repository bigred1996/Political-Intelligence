# Polaris — Data Source Checklist

Status legend: ✅ live (real data in DB) · 🟡 partial/stub · ⬜ not started · 🔴 blocked

Last updated: 2026-06-15

---

## Core sources (the 6 in CLAUDE.md)

### ✅ 1. Federal Contracts — Proactive Publication (>$10k)
- **Source:** open.canada.ca CSV (dataset `d8f85d91`), via CKAN API
- **In:** REAL data streamed → `contracts` table, normalized by entity
- **To do:** remove the row cap (full ~1M rows) as a background ingest job; add incremental/quarterly refresh; capture amendments (contract value over time)

### ✅ 2. Political Donations — Elections Canada (contributions, as reviewed)
- **Source:** elections.ca ZIP (dataset `ef1e3528`), cached 109MB → 2.2GB CSV
- **In:** REAL data streamed → `donations` table (80k rows loaded)
- **To do:** uncap to full corpus; note federal **corporate donation ban (2007)** — match individuals/executives by name; add fuzzy name→officer linking to companies

### ✅ 3. Bills & Legislation — LEGISinfo
- **Source:** parl.ca LEGISinfo JSON API
- **In:** REAL — 176 current-Parliament bills → `bills` table; matched to companies by sector keyword
- **To do:** ingest historical Parliaments; capture committee stage detail, votes, and per-bill status timeline; better bill↔company relevance than keyword match

### ✅ 4. Lobbying Registry — OCL (UNBLOCKED)
- **Source:** lobbycanada.gc.ca Monthly Communications ZIP (~22 MB) — downloaded with browser User-Agent
- **In:** REAL — 363,770 communication records, 7,497 unique clients → `lobbying_records` table; DPOH contacts stored in `raw` JSON per record
- **To do:** load Registrations ZIP (82 MB) for richer subject-matter data; flag former public office holders (revolving-door); subject-matter code → human-readable label lookup

### ✅ 5. Hansard / Parliament — openparliament.ca API
- **Source:** api.openparliament.ca — MP profiles, speeches, committees, votes
- **In:** REAL — 343 MPs seeded in `politicians` table; speech keyword search → `hansard_mentions`; 30 committees available; recent votes API live
- **To do:** better keyword → relevance matching (openparliament full-text search has noise); committee witness testimony; derive pro/neutral/against stance from speech sentiment

### ⬜ 6. Social / Public Statements
- **Source:** X/Twitter, LinkedIn, press releases of ministers/MPs
- **In:** not started
- **To do:** RSS/press-release scrape is lowest-friction; X/LinkedIn APIs are gated; attribute statements to politicians

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
| ⬜ Grants & Contributions (open.canada.ca `432527ab`) | Federal money *to* orgs beyond contracts | dataset confirmed reachable |
| ⬜ Government Orgs / GEDS | Authoritative dept/minister/official reference for stakeholders | not started |
| ⬜ Federal regulations (Canada Gazette) | Pending/active regulations for the Regulatory Landscape section | not started |
| ⬜ Court / regulatory tribunal decisions (CRTC, Competition Bureau) | Regulatory-risk section depth | not started |
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
| ✅ GC News / Publications | **Row-level** | **19,901** news releases (all departments, history backfilled via `pick`). Daily incremental. |

**Deepened 2026-06-16 (local, no-spend):** cer/npri/gc_news now hold real row-level
data (~82k rows total). `fetch_gc_news_records` now takes a dynamic `pick` (large
for backfill, `_GC_NEWS_DAILY_PICK=500` for the daily incremental). iaac/transport
remain catalogue-level pending dedicated row-level connectors; the multi-GB giants
(full StatCan series, full NPRI history) are deferred to the Supabase Pro phase to
protect local disk (~13 GB free).

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

## Priority order to "fully real"
1. ✅ **OCL lobbying** — DONE: 363,770 records from lobbycanada.gc.ca ZIP (browser UA)
2. ✅ **Hansard/Parliament** — DONE: openparliament.ca API; 343 MPs seeded, speech search live
3. ⬜ **Wire `ANTHROPIC_API_KEY`** — switch report drafting from template → Claude prose
4. ⬜ **Statistics Canada API** — sector economic context for report framing
5. ⬜ **Canada Gazette / Justice Laws** — regulatory landscape section (pending/active regs)
6. ⬜ **Full uncapped ingests** (contracts, donations) as background jobs
7. ⬜ **Entity graph** (subsidiaries/officers/SEDAR+) — multiplies value of every source
8. ⬜ Administrative tribunals (CRTC, Competition Bureau, CER) — regulatory-risk section depth
