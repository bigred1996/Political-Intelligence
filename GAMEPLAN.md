# Game Plan — Fix the old stuff, then go provincial

**Started:** 2026-06-25. **Owner instruction:** fix everything broken in the federal estate
documented in [`DATA.md`](DATA.md) §5 (known bugs) and §3.5 (built-not-wired), then start
real provincial ingestion (ON, QC, BC, AB) — autonomously, no check-ins mid-execution.

This doc is the execution tracker. `DATA.md` stays the state-of-the-world doc (what exists,
what's verified); this doc is the punch list + working notes for *getting there*. Update the
checkboxes as items land; don't let this go stale — if a fix turns out to be infeasible,
write down why instead of silently dropping it.

---

## Phase 0 — Fix the old stuff

- [x] **CSV streaming parser bug** (`pipeline/ingest.py:stream_csv_rows`) — splits raw text on
  `\n` before CSV-aware parsing; breaks on embedded newlines in quoted fields. Affects
  `iter_contract_rows` and `iter_grant_rows`. Fixed: parse with `csv.reader` over the whole
  decoded stream, not pre-split lines. Corrupted rows purged.
- [x] **Donations mojibake** (`pipeline/ingest.py:iter_donation_rows`) — file is UTF-8 (with
  BOM), code force-decoded as `latin-1`, mangling every accented name. Fixed (`utf-8-sig`),
  full re-ingest run from cached ZIP: 6,230,597 rows landed. **Residual, separate defect found
  and accepted, not fixed**: 70 rows (0.001%) carry a genuine *upstream* double-encoded name
  (mojibake baked into the government's own CSV, confirmed via raw byte inspection — three
  different byte-level encodings of the same name across different rows in their file).
  Negligible scale, not worth per-row repair overhead on a 6.2M-row hot path.
- [x] **Donations garbage dates** — ~43 rows with `received_date` years like 0025/4002 (dirty
  source data, not a parser bug). Sane-year guard added, out-of-range dates now null.
  Verified: 0 bad dates in the re-ingested table.
- [x] **CER incident date format** (`pipeline/breadth.py:fetch_cer_records`) — naive `[:10]`
  slice assumed `YYYY-MM-DD`, source is `M/D/YYYY`. Code was already fixed (`_cer_date()` parses
  via `strptime` across 3 known formats) but had never actually been re-run. Re-ran the `cer`
  connector for real: 2,008 rows, verified 0 malformed `event_date` values, sample dates check
  out (e.g. `2008-01-02`).
- [x] **`house_votes` connector never wired** — `pipeline/connector_house_votes.py` registered
  as a `SourceConnector`. First backfill attempt silently returned 0 rows: 5 stale checkpoint
  files (`data/checkpoints/house_votes_p*.json`) were left over from an earlier standalone test
  of `backfill_votes()` that never went through `run_connector()`'s DB-persistence step, so
  `stop_on_empty` checkpointing had already marked all 5 sessions `"complete"` with nothing
  ever actually written to `source_records`. Deleted the stale checkpoints and re-ran a real
  live walk through the full pipeline: **2,182 vote records landed** across all 5 sessions
  ((42,1) through (45,1)), verified directly via SQL (most recent: Vote #173, Parliament 45
  Session 1, 2026-06-18). `embed=False` is correct as configured — title/summary are tally
  counts ("Yea: 52, Nay: 276..."), not free text, same SQL-only-by-design class as
  contracts/donations/NPRI.
- [x] **yaml id drift** — `config/data-sources.yaml`'s `the_conversation_ca` entry renamed to
  match the scheduler's actual job id `conversation_ca_politics`.
- [x] **GIC Appointments broken** (`fetch_appointment_rows` hit a dead/404 CKAN dataset,
  0 rows). Fixed: `parse_appointments_from_precis()` derives appointments from the
  already-ingested `orders_in_council` `source_records` rows' `raw.precis` field. Wired into
  `_run_appointments` + the manual ingest route + the idempotency test. Real run: 9,825
  appointments derived from 20,304 OIC records.
- [x] **Appointment date format bug (found during verification of the fix above)** — the
  `_APPT_EFFECTIVE_RE` regex captured the précis's raw textual "effective DATE" string
  (e.g. `"December 2, 2002"`) without normalizing it, while the `date_made` fallback was
  already ISO — 36.7% (3,601 of 9,825) of derived rows had inconsistent date formats. Fixed:
  parse the captured date through `datetime.strptime(..., "%B %d, %Y")` and store ISO, with a
  `try/except ValueError` guard for anything that doesn't match. Re-ran; verified 0 bad-format
  dates remaining across all 9,825 rows.
- [x] **CRTC tribunal decisions broken** (feed returned HTML, 0 rows). Fixed: confirmed the
  RSS feeds are still dead, found CRTC's real per-year decision index
  (`/eng/8045/d{year}.htm`, live 1995-2026), built `pipeline/connector_crtc_decisions.py` and
  wired it into `_run_tribunal_decisions`. Run for real: 14,619 decisions parsed, 13,827 net
  new rows landed, with bonus `outcome` (Approved/Denied/Renewed) recovered from inline title
  keywords where the source embeds them. Old dead RSS code deleted from `pipeline/ingest.py`.
- [x] **16 recovered StatCan cubes never ingested** (`data/extracted/statcan/`, 14G,
  recovered from OLD NESSUS). Built a new typed `statcan_observations` table
  (`api/models/statcan_observation.py`) — cube-specific dimension columns (e.g. "NAICS",
  "Age group") land in a JSON `dimensions` field since every cube's schema differs beyond the
  fixed `REF_DATE/GEO/VALUE` spine, and these rows have no entity to anchor on so they don't
  fit `source_records`' shape. Parser (`pipeline/connector_statcan_cubes.py`) + one-time loader
  (`scripts/ingest_statcan_cubes.py`). Ran for real: **521,367 rows landed across all 15
  cubes**, verified via `SELECT COUNT(*)` / `COUNT(DISTINCT cube_id)`. **Deferred**
  `statcan_36100608` (61.4M rows, a narrow infrastructure-asset table, 14G alone) —
  disk/time cost isn't justified by its narrow product value relative to the other 15.
- [x] **Old-docs correction**: `archive/data.md` claimed `scrapers/ocl.py` was "likely safe
  to retire." Confirmed false — it's a live fallback in `pipeline/gather.py` and
  `api/routes/lobbying.py`. DATA.md does not repeat this mistake.
- [x] Update `DATA.md` (§3, §5) and `config/data-sources.yaml` to reflect every fix above with
  honest verification notes (rows before/after, what was actually run). Done for all of: CSV
  parser, donations encoding/dates, appointments (both the CKAN-dead-end fix and the
  date-format bug found during verification), CER, house_votes, CRTC, StatCan cubes, yaml id
  drift.

## Phase 1 — Provincial ingestion (ON → QC → BC → AB)

Decided scope (user, session 1): all four provinces, this priority order. First-wave source
types per province: lobbyist registry, procurement/contracts, political-finance/donations,
legislature bills/Hansard, orders/appointments. Schema needs **no migration** —
`source_records.province` already exists; provincial sources slot into the existing Tier-2
`SourceConnector` pattern, one connector per province per source type, tagged
`province="ON"/"QC"/"BC"/"AB"`.

Legal posture (decided): robots.txt + open-licence only, same bar as federal.

**Reality check (researched 2026-06-26, live-verified, not assumed):** of the four priority
provinces, only **BC** currently exposes a real bulk/API channel for its lobbyist registry.
Ontario (Office of the Integrity Commissioner), Quebec (Carrefour Lobby Québec — an Angular
SPA, no documented API; its companion info site `lobbyisme.quebec` explicitly blocks AI
crawlers via robots.txt), and Alberta (an Oracle APEX search app) are all interactive-search-
only with **no** bulk export, and none of their provincial open-data portals (data.ontario.ca,
données québec, open.alberta.ca) mirror the registry. This flips the practical execution
order from the original ON→QC→BC→AB priority — BC went first because it's the only one with
real data to ingest today. ON/QC/AB stay blocked until those registries publish a bulk
channel (or until a heavier, riskier interactive-form scrape is explicitly approved — not
attempted here, since none of the three has a confirmed ToS/ToU position on bulk redistribution
and Quebec's posture is actively unfriendly to automated access).

- [x] **British Columbia** — lobbyist registry (`pipeline/connector_bc_lobbyist_registry.py`,
  source id `bc_lobbyist_registry`) — registered as a weekly `SourceConnector`, run for real:
  26,357 registrations landed in `source_records` (8,699 consultant + 17,658 in-house),
  joined against the subject-matter-topics export for a searchable summary. Source publishes
  monthly; weekly check is cheap since upsert-by-external_id only inserts genuinely new rows.
  Added to `search/index.py`'s `EMBED_SOURCES` allowlist (a second, separate place every new
  text-bearing breadth source must be registered — easy to miss, caught this session because
  the first reindex silently embedded 0 of the 26,357 new rows).
- [ ] Ontario — blocked, no bulk export found (see reality-check note above). Revisit if/when
  the Integrity Commissioner publishes one, or if approved to build an interactive-form
  scraper instead.
- [ ] Quebec — blocked, no documented public API for the Carrefour Lobby Québec SPA (see
  reality-check note above). Same encoding care as the donations fix would apply here
  (French-language source) if a path opens up.
- [ ] Alberta — blocked, no bulk export found (Oracle APEX search-only app; see reality-check
  note above).
- [x] BC — second source type (procurement or political finance), researched 2026-06-26,
  **blocked, both candidates**:
  - **BC Bid** (`bcbid.gov.bc.ca`, procurement) — robots.txt is the standard gov.bc.ca
    template: `User-agent: *` / `Disallow: /` (only Googlebot/bingbot/BCGovSearch are
    allowed). Hard block, no path excluded.
  - **Elections BC** (`elections.bc.ca`, political finance/contributions) — identical
    template, identical `Disallow: /` for all generic agents. Hard block.
  - Checked whether either dataset is mirrored on BC's general open-data catalogue
    (`catalogue.data.gov.bc.ca`, the BC analogue of `open.canada.ca`) as a workaround, the
    same pattern that makes the federal CKAN catalogue usable: found a real "Ministry
    Contract Awards" dataset there, but the catalogue itself disallows `/api/` and
    `/client-api/` in its robots.txt — unlike `open.canada.ca`, which only blocks CMS
    internals (`/core/`, `/admin/`, etc.) and explicitly permits its API. Confirmed the
    catalogue's dataset pages are a bare `<div id="app">` SPA shell (19 lines of HTML, no
    static resource links) that depends entirely on that disallowed API to render anything
    — so there is no robots.txt-compliant path through the catalogue either, same failure
    shape as Quebec's lobbyist SPA. Both candidates stay blocked; not attempted further.
    Revisit if BC ever opens its catalogue API or either site's robots.txt.
- [x] Update DATA.md §6 (future sources) → move BC into §3 (current state) with verification
  notes; document ON/QC/AB as a researched-and-blocked gap, not a silent skip.

---

## Phase 2 — Hansard full transcripts (user-directed, 2026-06-26)

User instruction: "continue the data import... Focus on Hansard, get all of it, every word
spoken, full transcripts." DATA.md §6.1 had flagged this as a P1/High-effort gap — the only
Hansard data in the DB was `hansard_search`'s third-party openparliament.ca keyword sweep
(217 rows, ~500-char excerpts, heavily overlapping across keywords). This phase builds a
first-party, full-text replacement source sitting alongside it (kept separate, not merged).

- [x] **Found and verified live** (not assumed) ourcommons.ca's per-sitting Hansard XML:
  `GET /Content/House/{parliament}{session}/Debates/{NNN}/HAN{NNN}-E.XML`. A sitting that
  doesn't exist returns **HTTP 302** (never 404) — confirmed by probing sitting 999 of every
  session. robots.txt disallows `/Search/`, `/PublicationSearch/`, `/ErrorPage/`,
  `/Embed/`, `/ParlDataWidgets/` — `/Content/` and `/documentviewer/` (used for citation
  URLs) are both unrestricted.
- [x] **Confirmed the real session list live**, not from memory: probed sitting 1 of every
  (parliament, session) pair from 37 through 45. Structured XML Hansard only exists from
  the **38th Parliament (2004) onward** — 35-37 are PDF-only. 13 real sessions: (38,1),
  (39,1), (39,2), (40,1), (40,2), (40,3), (41,1), (41,2), (42,1), (43,1), (43,2), (44,1),
  (45,1). (42,2), (44,2), (45,2) don't exist — consistent with `house_votes`' independent
  finding of the same three gaps.
- [x] **New table** `hansard_speeches` (`api/models/hansard_speech.py`) — one row per
  `Intervention` (Debate/Question/Answer/Interjection) plus standalone `ProceduralText`
  notes, not a row per sitting. Full text in `content`, not an excerpt.
- [x] **New connector** `pipeline/connector_hansard_transcripts.py` — XML parser
  (document-order `root.iter()` traversal with "most-recently-seen heading/timestamp" state;
  a `parent_map` check distinguishes standalone `ProceduralText` from the copy already nested
  inside an `Intervention`'s `Content`, avoiding double-counting) + per-session checkpointed
  walk (`pipeline/api_paginator.py:walk_cursor_pages`, same pattern as `connector_house_
  votes.py`, each session its own independent checkpoint).
- [x] **Crash-resilience departure from the `house_votes` pattern, on purpose**: `house_votes`
  buffers everything in memory and writes once at the end — fine at a few thousand rows, not
  at Hansard's scale. Here, each sitting's parsed rows are inserted and committed to the DB
  *inside* the per-page fetch callback, before `walk_cursor_pages` advances that sitting's
  checkpoint — so the checkpoint can never claim a sitting is done unless its rows already
  landed. A second, sitting-granularity dedup check (one query per sitting, not per row)
  covers the one remaining gap: a crash between a sitting's commit and its checkpoint write.
  Verified both layers live: checkpoint-resume correctly continued from sitting 3 without
  re-fetching 1-2 after an interrupted test run, and the dedup check correctly detected
  sitting 1 as already-loaded and skipped re-insert when called directly.
- [x] Caught and fixed a real bug **before** it could silently corrupt the corpus: Hansard
  XML files are served with a leading UTF-8 BOM before the `<?xml` declaration — the
  non-XML-response guard regex didn't tolerate it and would have rejected every genuine file
  as "unexpected non-XML response." Found by testing against real fixture files before the
  live run, not after.
- [x] XML schema vocabulary (confirmed live, not assumed): `Hansard`, `ExtractedInformation` (use
  `MetaDateNum{Year,Month,Day}` for a clean ISO date — more robust than parsing the
  human-readable `"Friday, June 6, 2025"` string), `HansardBody` → `OrderOfBusiness` →
  `SubjectOfBusiness` → `SubjectOfBusinessContent` → `Intervention`/`ProceduralText`,
  `PersonSpeaking`/`Affiliation` (`DbId`/`Type` attrs — `Type` is a numeric code with no
  documented meaning found anywhere; stored raw in `speaker_role`, no label invented).
- [x] Wired `hansard_transcripts` as a hand-wired Tier-1 scheduler job (daily, budget-capped
  at 200 sittings/call so a routine cron tick can't block the event loop for hours) +
  `scripts/run_ingest.py hansard_transcripts` for the unbounded historical backfill, per
  CLAUDE.md's "big ingests must not run through the web server."
- [x] Registered in `search/sql_search.py` SPECS (`hansard_speeches`, SQL-only — not added to
  `search/index.py`'s embedding allowlist; same scale rationale as contracts/donations/NPRI),
  `api/routes/sources.py` SOURCE_DEFS + the `models` dict (id `hansard_transcripts`, `approx`+
  `date_strategy: skip` since this table could reach 500k+ rows), and the front-end's
  table-name/source-id registries (`web/lib/navigation.ts`, `web/app/records/page.tsx`,
  `web/app/page.tsx`, `web/app/committees/[slug]/page.tsx`) — every place a new source needs
  registering per CLAUDE.md's "Records route is generic via SPECS" gotcha, found by tracing
  each existing `hansard_mentions` reference rather than guessing which files mattered.
- [x] Smoke-tested the parser against two real downloaded sitting XMLs before any live run;
  ran a tiny bounded live end-to-end test (2 sittings) and verified both DB rows and
  idempotency before committing to the full historical backfill.
- [x] **Full historical backfill run live** 2026-06-26 via `scripts/run_ingest.py
  hansard_transcripts` (standalone, not through the web server, took 1,234s/~20.5min).
  **639,695 rows landed** (real `count(*)`), spanning 2004-10-04 to 2026-06-18 across all 13
  sessions, **0 gaps, 0 errors** — every session's walk ended `stopped_reason="exhausted"`
  (its true empty/302 terminus), not a partial stop. 2,266 sittings fetched total (2,262 in
  this run + 4 from the earlier bounded end-to-end test, correctly skipped here via
  checkpoint resume — `sittings_already_loaded=0`, `sittings_skipped_already_done=4`).
- [x] Updated DATA.md (§1, §3.1, §6.1, §8) and `config/data-sources.yaml` (new
  `hansard_transcripts` entry) with verification notes.

---


## Phase 3 — Materialize record links (user-directed continuation, 2026-06-26)

User instruction: "records should link together, Hansard linked to MPs, bills, etc; everything
interconnected." This phase adds a real cross-record link table rather than relying only on
shared `canonical_name` inference.

- [x] Added `record_links` (`api/models/record_link.py`) with a uniqueness constraint on
  `(source_table, source_pk, target_table, target_pk, relationship)` plus source/target lookup
  indexes. Registered it in `api/database.py`.
- [x] Built `pipeline/record_linker.py` + `scripts/link_records.py`, idempotent via
  `INSERT OR IGNORE`, for three first-pass edge types:
  `hansard_speeches -> politicians` (`spoken_by`), `hansard_speeches -> bills`
  (`mentions_bill`), and `source_records/house_votes -> politicians` (`mp_voted`).
- [x] Fixed a subtle identifier issue during verification: Hansard XML `Affiliation DbId` is
  not the same as the ourcommons member profile `PersonId`, so the speaker linker now uses
  that ID only when it happens to match and otherwise falls back to exact normalized MP names
  parsed from the Hansard speaker label. Generic roles like `The Speaker` stay unlinked unless
  the XML label contains an actual person name in parentheses.
- [x] Ran the linker for real against `polaris.db` on 2026-06-26. Result: **589,836**
  materialized links — **210,519** `spoken_by`, **6,445** `mentions_bill`, **372,872**
  `mp_voted`. Spot checks: C-5 has 1,018 Hansard links; vote participant links resolve to
  current MPs via archived XML `PersonId`; recent Hansard rows resolve to MP profiles by exact
  parsed name with confidence `0.92`.
- [x] Wired explicit links into `api/routes/records.py` (`relations.explicit_links`) and
  `/api/graph/record/{table}/{pk}` so record pages and graph views show these edges alongside
  the older inferred shared-entity relations. Added `politicians` to `search/sql_search.py`
  SPECS so linked MP records can be resolved generically.
- [x] Tests: `tests/test_record_linker.py` covers member-ID extraction, bill mention
  normalization, Hansard speaker parsing, and vote XML participant parsing. Verification run:
  `.venv/bin/python -m pytest tests/test_api_smoke.py::test_record_detail_resolves_linkable_record tests/test_record_linker.py -q` → 5 passed;
  `.venv/bin/python -m pytest tests/test_product_contracts.py::test_politician_detail_uses_live_api_and_internal_hansard_links tests/test_product_contracts.py::test_search_result_context_is_preserved_on_record_detail_links -q` → 2 passed.
- [ ] Remaining cleaning gap: import a historical MP/parliamentarian roster, not just current
  MPs, then rerun `scripts/link_records.py` to connect older Hansard speakers and historical
  vote participants that are currently unlinked because no `politicians` row exists for them.

## Working notes (append as you go — don't lose findings mid-session)
