# DATA.md — Nessus Data: Single Source of Truth

**This is the one human-facing document for the data side of Nessus.** It carries
(1) the **guidance/principles** we've decided to work by, (2) the **honest current
state** of every source — what's *really* live vs. loaded-once vs. broken, (3)
**what's in progress**, and (4) **future sources** (federal gaps, provincial,
municipal) with a **sequenced roadmap**.

- **Last verified:** 2026-06-25, against the live canonical `polaris.db`, `scheduler_log`,
  and live HTTP probes of the non-bulk sources. Every status below says *how* it was
  checked. See [Verification snapshot](#verification-snapshot-2026-06-25).
- **Machine-readable companion:** [`config/data-sources.yaml`](config/data-sources.yaml)
  remains the structured registry the audit CLI reads. This doc is the prose truth;
  the yaml is the queryable form. **They must agree** — when they drift, this doc wins
  and the yaml gets corrected.
- **Superseded docs:** `DATA_CATALOG.md`, `DATA_CHECKLIST.md`, and `data.md` were
  merged into this file and moved to [`archive/`](archive/). Do not edit them; they're
  kept only for history. `Tasks.md` (the ingestion spec) stays as the *requirements*
  reference, not a status tracker.

> **The cardinal rule of this doc:** *Nothing is marked ✅ Live without a verification
> note saying how and when it was confirmed.* We have repeatedly called things "done"
> that were loaded once and never refreshed, or that run "successfully" while silently
> loading zero rows (CRTC, appointments). That stops here.

---

## 1. Guidance & principles (the decisions)

### 1.1 Legal & licensing posture — **strict**

We ingest only where **both** are true: (a) `robots.txt` permits the access path, and
(b) the reuse terms are confirmed open/commercial-OK (Open Government Licence – Canada,
StatCan Open Licence, or an equivalent explicit grant).

- **Respect `robots.txt` always.** Where a site disallows search/pagination but
  publishes sitemaps (IAAC) or a dedicated portal (Orders in Council), use those.
  Where a host is a flat `Disallow: /` (CER REGDOCS `docs2.cer-rec.gc.ca`), we **do
  not** scrape it — we store filing numbers as citation links only.
- **No paid/negotiated news licences for now.** CBC, CTV, Globe and Mail, Toronto Star,
  Financial/National Post, La Presse, Le Devoir, The Logic, The Narwhal, Canadian
  Press, iPolitics, Hill Times, Policy Options, Global News, and paid aggregators
  (Factiva, LexisNexis, Meltwater, NewsAPI.ai) are **out of scope** until there's a
  business decision to license them. *The Conversation Canada* is the one licensed
  commercial news source we use (CC-BY-ND).
- **Full-text storage is gated by licence.** Government department feeds (Crown
  copyright, non-commercial-reproduction terms) are stored as **≤320-char snippets
  only**, never full text. Only sources with an explicit full-text grant store full
  bodies. If `full_text_storage_allowed` is false in the yaml, the connector **must**
  enforce the snippet cap.
- **`commercial_reuse_reviewed: false` is a real debt, not a placeholder.** Several
  high-value sources are live today without a confirmed terms review (donations, OCL
  lobbying, LEGISinfo, openparliament, CRTC). They are flagged honestly in the yaml
  and listed in [§6.4](#64-licence-review-debt). Clearing these is a P1 governance task,
  not optional paperwork.

### 1.2 Status vocabulary & the verification standard

| Status | Means | Bar to claim it |
|---|---|---|
| ✅ **Live** | Queryable rows **and** the refresh path is proven to run on schedule | A dated `scheduler_log` success on the *scheduled* (not manual) path, **or** a live re-trigger this session |
| 🟢 **Loaded** | Real rows exist, but only from a **one-off manual backfill** — the scheduled refresh is unproven or not firing | Real `count(*)` in the DB; note that the cron path is unverified |
| 🟡 **Partial** | Works but materially incomplete (catalogue-only, thin coverage, missing fields) | Stated gap + what "complete" would mean |
| 🔴 **Broken** | Wired and "runs" but produces no/garbage data | The specific failure, reproduced |
| 📦 **Archive-only** | Raw payload fetched & stored, but **not** mapped into queryable rows yet | Raw files on disk; no `source_records`/typed rows |
| ⬜ **Built, not wired** | Connector code exists, never added to the scheduler | File path of the dead-but-working connector |
| 🧱 **Not started** | No connector | — |
| 🚫 **Blocked** | Can't proceed without a licence/key/business decision | What unblocks it |

**Verification standard:** every ✅/🟢/🟡/🔴 row in §3 carries a *"verified"* note —
how and when. "Last successful import" in the yaml must cite whether it was the
**manual** or the **scheduled** path. A green checkmark with no verification note is a
bug in this doc.

### 1.3 Architecture rules (don't relitigate these)

- **Industry-first, not company-first.** Every record is read through the *industry* it
  touches and the *political players* who shape it. New sources must carry enough to
  join the entity/sector graph (`canonical_name` at minimum).
- **Two tiers of sources.** *Tier 1* (contracts, donations, lobbying, bills, grants,
  appointments, gazette, parliament) = rich typed tables + hand-wired jobs. *Tier 2*
  (everything breadth) = one `SourceConnector` entry → unified `source_records` table.
  **Do not add a typed table/route/job per breadth source.** See `CLAUDE.md` for the
  add-a-source recipe.
- **Entity resolution is the moat.** Always query big tables by indexed
  `canonical_name.in_(roster)` — never `ILIKE` over them (5–27s full scan). Match with
  `canonical_name == canonical OR raw_name ILIKE "%company%"`, never
  `canonical_name ILIKE "%canonical%"`.
- **Immutable raw archival.** Every ingest preserves the original payload, checksummed,
  under `data/raw/<source>/<y>/<m>/<d>/<run>-<checksum>/` with a manifest. This is the
  provenance chain and the re-ingest source for the Postgres move — protect it.
  (See [§7](#7-raw-archive--data-recovery-note) — we just recovered 22G of it.)
- **Conditional-fetch before tighter cron.** A new full-snapshot bulk source needs the
  `pipeline/conditional_fetch.py` fingerprint gate **before** its cadence is tightened,
  or every extra fire is a full re-download.

### 1.4 The refresh-loop commitment (the #1 near-term problem)

**Today the data is not actually refreshing.** Most jobs last fired 2026-06-22 or
earlier; only four 4-hour jobs are live (see §3). The agreed sequence to fix this:

1. **Migrate to Postgres** (Supabase, already provisioned — `SUPABASE_SETUP.md`).
   SQLite is at 3.1GB and bumping the local disk ceiling; the standalone scheduler must
   **not** be turned on against a near-full SQLite file. This is the gating prerequisite.
2. **Turn on the standalone scheduler** (`scripts/run_scheduler.py` via launchd/systemd —
   `deploy/`) and prove each Tier-1 job completes on its *scheduled* path, not just
   manually.
3. Only then do new-source breadth work compound, because it'll actually stay fresh.

---

## 2. The honest headline

*(Updated 2026-06-26 — Phase 0 of the roadmap below is now done; see GAMEPLAN.md for the
full execution log.)*

- **~9.9M queryable rows** across federal sources, plus a first provincial source, but
  **mostly loaded once, not refreshing.** (Recomputed 2026-06-26 from real per-table counts
  while reconciling house_votes — the prior "~10.2M" figure double-counted via a stale
  `source_records` total, see §3.2.)
- **Live & actually refreshing right now:** only `gc_news`, `gazette_notices`,
  `conversation_ca_politics`, `canadabuys_tenders` (the four every-4-hour jobs), plus
  `bc_lobbyist_registry` (weekly).
- **Fixed this pass:** GIC Appointments (9,825 rows, derived from `orders_in_council`),
  CRTC tribunal decisions (13,827 rows, new per-year decision-index connector), contracts/
  grants CSV column-shift, donations encoding + bad dates, CER date format, `house_votes`
  wired + backfilled.
- **StatCan**: 15 of the 16 recovered data cubes (14G, downloaded but never ingested) are
  now loaded into `statcan_observations` (521,367 rows). The 16th (`statcan_36100608`,
  61.4M rows/14G alone) is deliberately deferred, not silently skipped.
- **Provincial: one of four shipped.** BC's lobbyist registry (26,357 rows) is live —
  the only one of ON/QC/BC/AB with a real bulk/API channel, confirmed by direct fetch.
  ON/QC/AB are documented-blocked, not unscoped.
- **Hansard full transcripts shipped 2026-06-26** (`hansard_transcripts`, new `hansard_speeches`
  table) — **639,695 rows**, first-party per-sitting XML direct from ourcommons.ca, every
  Intervention's full text, not the third-party openparliament.ca keyword-sweep
  (`hansard_search`, 217 mentions, still kept separately — see §3.1). Full historical backfill
  complete: all 13 sessions, 2004-10-04 to 2026-06-18 (38th Parliament onward; pre-2004 is
  PDF-only Hansard, confirmed out of scope), 0 gaps, 0 errors.
- **Record graph materialized 2026-06-26** (`record_links`, new) — **589,836 explicit
  cross-record links** built from already-imported data: 210,519 Hansard speech→MP
  `spoken_by` links, 6,445 Hansard speech→Bill `mentions_bill` links, and 372,872
  House vote→MP `mp_voted` links from archived vote XML. Current limitation: MP links
  are bounded by the seeded `politicians` roster (343 current MPs), so historical speakers
  without a current profile remain unlinked until a historical MP roster is imported.
- **Still open:** the refresh-loop problem (Postgres migration, proving the scheduled
  paths) — see Phase 1 in §8.

---

## 3. Current state — federal inventory (verified 2026-06-25)

Counts are real `count(*)` where noted; otherwise `max(id)` proxy (✱) per the
performance rule. "Refreshing?" reflects actual `scheduler_log` history, not the
configured cron.

### 3.1 Tier 1 — core analytics (typed tables)

| Source | Rows | Coverage | Status | Refreshing? | Verified |
|---|---|---|---|---|---|
| Federal contracts >$10k (`contracts_monthly`) | **1,155,000** (real count) | full corpus; `contract_date` corruption fixed 2026-06-26 (stream_csv_rows quote-aware parse, see §5) | 🟢 Loaded | ❌ scheduled path has **only ever errored** (2026-06-15) | count(*) + scheduler_log |
| Elections Canada donations (`donations_quarterly`) | **6,230,597** (real count, re-ingested 2026-06-26) | full corpus; mojibake fixed (`utf-8-sig`), garbage dates nulled — 70 rows (0.001%) still carry genuine *upstream* double-encoded names, accepted not fixed (see §5) | 🟢 Loaded | ❌ last run 2026-06-15 (1 ok / 1 error), cron path unproven | re-ingest run 2026-06-26 |
| Grants & contributions (`grants_quarterly`) | 1,148,041 ✱ | 2005–2026; ⚠️ `agreement_start` corrupted | 🟢 Loaded | ❌ last run 2026-06-22 (manual backfill) | scheduler_log |
| OCL lobbying — communications (`ocl_monthly`) | **362,805** (real count) | 2008–2026 | 🟢 Loaded | ❌ never logged on the scheduled path | count(*) |
| OCL lobbying — registrations (`ocl_registrations`) | 166,564 | 1996–2026 | 🟢 Loaded | ❌ last run 2026-06-22; status/benefits fields still empty | count(*) |
| Bills — LEGISinfo (`bills_daily`) | 185 | current Parliament only | 🟢 Loaded | ❌ daily job **stopped firing after 2026-06-19** | LEGISinfo live 200 ✅ + scheduler_log |
| Canada Gazette RSS (`gazette_weekly`) | 638 | recent window | 🟢 Loaded | ❌ last run 2026-06-15 | RSS live 200 ✅ |
| MPs / parliamentarians (`parliament_seed`) | 343 | current | 🟢 Loaded | ❌ ad-hoc seed, never on a real cron | openparliament live 200 ✅ |
| Hansard keyword mentions (`hansard_search`) | 217 | current Parliament | 🟡 Partial — third-party keyword sweep, kept separate from transcripts below | ❌ last run 2026-06-19 | count(*) |
| **Hansard full transcripts (`hansard_transcripts`, new `hansard_speeches` table)** | **639,695** (real count) | **2004-10-04 to 2026-06-18** (38th Parliament onward), all 13 real sessions: (38,1),(39,1),(39,2),(40,1),(40,2),(40,3),(41,1),(41,2),(42,1),(43,1),(43,2),(44,1),(45,1); pre-2004 Hansard is PDF-only, confirmed out of scope | 🟢 Loaded — full historical backfill complete | ✅ new `pipeline/connector_hansard_transcripts.py` — first-party ourcommons.ca per-sitting XML, every Intervention's full text; SQL-only (not embedded), same class as contracts/donations/NPRI | full backfill run 2026-06-26 (1,234s, 2,266 sittings, 0 gaps, 0 errors, `stopped_reason="exhausted"` on every session) via `scripts/run_ingest.py hansard_transcripts`; count(*) verified; `record_links` now connects 210,519 speech rows to MPs and 6,445 speech rows to bills where the seeded MP/bill rows exist |
| GIC Appointments (`appointments_weekly`) | **9,825** (fixed 2026-06-26) | 1990s–present, derived from `orders_in_council` précis text | 🟢 Loaded | ✅ re-derives from already-ingested data, no network call | real run 2026-06-26, ISO dates verified |
| CRTC tribunal decisions (`tribunal_decisions`) | **13,827** (fixed 2026-06-26) | 1995–2026 | 🟢 Loaded | ✅ new `pipeline/connector_crtc_decisions.py` reads CRTC's per-year decision index (RSS feeds confirmed still dead) | real run 2026-06-26: 14,619 parsed, outcome recovered for years where the source embeds it inline |

### 3.2 Tier 2 — breadth (`source_records`, 278,495 real `count(*)`, re-verified 2026-06-26 — the prior "381,665 ✱" figure here was stale/wrong, caught while reconciling house_votes)

| Source | Rows | Status | Refreshing? | Notes |
|---|---|---|---|---|
| NPRI pollutant releases (`npri`) | 181,780 | 🟡 Partial | ❌ last run 2026-06-22 | 2022–2024 only; full history deferred to Postgres |
| Orders in Council (`orders_in_council`) | 20,304 | 🟢 Loaded | ❌ last run 2026-06-22 | 1990–present; also the real GIC-appointment source |
| GC News (`gc_news`) | 20,134 | ✅ **Live** | ✅ every 4h (current) | snippet-only (Crown copyright) |
| Gazette per-instrument notices (`gazette_notices`) | 12,527 | ✅ **Live** | ✅ every 4h (current) | regulator announcements + OICs |
| Govt dept RSS feeds (`gac_news`, `nrcan_news`, `ised_news`, `eccc_news`, `transport_news`, `health_news`, `competition_news`, `crtc_news`, `boc_news`, `pmo_news`, `cer_news`) | ~13,500 combined | 🟢 Loaded | ❌ **all last fired 2026-06-22** (one manual burst) | one connector (`pipeline/feeds.py`), 320-char snippets |
| CER pipeline incidents (`cer`) | 2,008 | 🟢 Loaded | ❌ last run 2026-06-16 | date format fixed 2026-06-26 (`M/D/YYYY`→ISO), re-run verified 0 malformed dates |
| IAAC projects (`iaac`) | 376 | 🟡 Partial | ❌ last run 2026-06-22 | ~300/6,389 projects (~5%); 5s crawl-delay → accrues slowly |
| StatCan catalogue (`statcan`) | 300 | 🟡 Partial — **metadata only** | ❌ last run 2026-06-15 | real cubes downloaded — **15 of 16 ingested into `statcan_observations` 2026-06-26**, see §7 |
| Transport / Geospatial catalogues (`transport`, `geospatial`) | 300 each | 🟡 Partial — metadata only | ❌ | dataset metadata, no row-level |
| CER applications/proceedings (`cer_applications`) | 110 | 🟢 Loaded | ❌ last run 2026-06-22 | www host (not REGDOCS) |
| The Conversation Canada (`conversation_ca_politics`) | 28 | ✅ **Live** | ✅ every 4h (current) | only licensed commercial news |
| StatCan discovery layer (`catalogue_entries` table) | 11,581 | 🟡 Partial | n/a | full 8,213-cube list + relevance classification (Goal 5); not reconciled into `source_records` |
| **BC lobbyist registry (`bc_lobbyist_registry`)** | **26,357** (new 2026-06-26) | 🟢 Loaded — first provincial source | ✅ weekly | `province="BC"`; consultant + in-house registrations; ON/QC/AB have no bulk channel today, see §6.2 |
| House of Commons recorded votes (`house_votes`) | **2,182** (new 2026-06-26) | 🟢 Loaded | ✅ daily | sessions (42,1)–(45,1); per-division yea/nay/paired tallies, not free text — `embed=False` by design, same SQL-only class as contracts/donations/NPRI; backfill initially returned 0 rows due to stale checkpoints from a pre-wiring standalone test, fixed by deleting them and re-walking live |
| StatCan cube observations (`statcan_observations`, new typed table) | **521,367** (15 cubes, new 2026-06-26) | 🟢 Loaded | n/a (one-time backfill, `scripts/ingest_statcan_cubes.py`) | `statcan_36100608` (61.4M rows/14G) deliberately deferred — see §7 |


### 3.3 Cross-record link graph (`record_links`, new 2026-06-26)

`record_links` materializes high-confidence edges that cannot be expressed by the
older shared-`canonical_name` relation alone. It is rebuilt idempotently with
`scripts/link_records.py` after large imports. Verified 2026-06-26 against
`polaris.db`: **589,836 links** total — **210,519** `hansard_speeches` →
`politicians` (`spoken_by`), **6,445** `hansard_speeches` → `bills`
(`mentions_bill`), and **372,872** `source_records`/`house_votes` →
`politicians` (`mp_voted`) from archived vote-participant XML. API record detail
and `/api/graph/record/{table}/{pk}` now expose these links under
`relations.explicit_links`.

Caveat: `politicians` currently contains the current 343-MP roster, not every
historical MP since 2004. Historical Hansard and vote records therefore link to
MPs only when the person is in that seeded roster. A historical MP roster import
is the next cleaning step to close that gap.

### 3.4 Archive-only (📦 fetched, no queryable rows yet)

| Source | Status | What's needed |
|---|---|---|
| `canadabuys_tenders` | 📦 crawler runs every 4h (live), raw JSON only | map tender-notice JSON → `source_records` |
| `bank_of_canada` | 📦 ~15,642 Valet series walked, raw only | map series → rows; fix the "no per-series since-param" staleness (CLAUDE.md) |

### 3.5 Built, never wired in (⬜ cheapest real wins)

| Source | What exists |
|---|---|
| `ocl_legacy_scraper` | old `scrapers/ocl.py` live-search path — confirmed this session it is **not** dead: still a live fallback in `pipeline/gather.py` and `api/routes/lobbying.py`. Not retiring. |

---

## 4. In progress now

- **This session (2026-06-25):** consolidated the four data docs into this SSOT;
  recovered 22G of orphaned raw/extracted data from `OLD NESSUS/` (§7); re-verified
  live status of all non-bulk sources.
- **Open from prior goals:** IAAC project crawl still accruing (~5% done); CanadaBuys &
  Bank of Canada archive→rows mapping; StatCan catalogue reconciliation.

---

## 5. Known data-quality bugs (distinct from missing sources)

All five items below were **fixed and verified 2026-06-26** (see GAMEPLAN.md for the
session-by-session execution log). Kept here as a permanent record of root cause, not
as an open punch list.

1. ~~**`contracts.contract_date` is corrupted**~~ — root cause: `pipeline/ingest.py:
   stream_csv_rows` split raw text on `\n` *before* CSV-aware parsing, so embedded
   newlines in quoted fields shifted every column after them (explains both the
   1899-Excel-epoch placeholder min and the French-prose max). Fixed: parse with
   `csv.reader` over the whole decoded stream. Corrupted rows purged.
2. ~~**`grants.agreement_start` is corrupted**~~ — same root cause and fix as #1
   (`iter_grant_rows` shares `stream_csv_rows`).
3. ~~**`donations.received_date` has garbage years**~~ — two separate bugs, both fixed:
   (a) the file is UTF-8 with a BOM but was force-decoded as `latin-1`, mangling every
   accented name — fixed (`utf-8-sig`), full re-ingest landed 6,230,597 clean rows; (b)
   ~43 rows with literal garbage years (`0025`/`4002`) in the *source* data — a sane-year
   guard now nulls them instead of storing nonsense. **Residual, accepted, not a bug**:
   70 rows (0.001%) carry a genuine upstream double-encoded name baked into the
   government's own CSV — confirmed via raw byte inspection, three different
   byte-level encodings of the same name across different rows in *their* file. Not
   worth per-row repair on a 6.2M-row hot path.
4. ~~**`cer` dates stored `M/D/YYYY`**~~ — `pipeline/breadth.py:_cer_date()` now parses
   `strptime("%m/%d/%Y %I:%M:%S %p")` → ISO. Re-ran the connector; 0 malformed dates in
   the live table.
5. ~~**Doc/code id drift**~~ — yaml's `the_conversation_ca` renamed to match the
   scheduler's actual job id `conversation_ca_politics`.
6. **New, found during this pass's verification, also fixed**: `parse_appointments_from_
   precis()`'s "effective DATE" regex captured the précis's raw textual date
   ("December 2, 2002") instead of normalizing it, while the `date_made` fallback was
   already ISO — 36.7% of the 9,825 derived appointments had inconsistent date formats.
   Fixed: `datetime.strptime(..., "%B %d, %Y")` → ISO before storing. Re-ran; 0 malformed
   dates in the live table. Caught by spot-checking sample rows after the "real run,"
   not by the row count alone — a reminder that landing the expected row count doesn't
   mean every field in those rows is correct.

---

## 6. Future sources

Ordered within each group by value. Effort: Low (hours) · Med (1–3 days) · High (1+ week).

### 6.1 Federal gaps (no new jurisdiction, real product value)

| Source | Priority | Effort | Notes |
|---|---|---|---|
| **StatCan series observations** (real GDP/CPI/employment numbers) | P1 | Med–High | 16 cubes already downloaded (§7) — first step is *ingest what we have*, not re-download |
| **Entity graph** (subsidiaries/officers/parent-co) | P1 | High | the multiplier on every other source; today resolution is name-matching only |
| `committee_evidence` (House committee membership/witnesses) | P1 | High | needs `parl.gc.ca` committee data |
| ~~Full Hansard transcripts~~ | ~~P1~~ | ~~High~~ | **Shipped 2026-06-26** — see §3.1 (`hansard_transcripts`) |
| `competition_bureau` enforcement actions | P1 | Med | |
| `public_accounts` + `gc_infobase` (who got paid, by dept) | P2–P3 | Med–High | beyond proactive disclosure |
| `osfi` (financial regulator) | P2 | Med | no RSS; subscribe page email-only |
| `cnsc` (nuclear), `cfia_recalls` (food), `transport_row_level` (TSB/recalls) | P3 | Med | sector-specific |
| `scc_official` (Supreme Court) | deferred | High | first-party scraper handling publication bans |
| `canlii` | blocked | Low once unblocked | pending API key |

### 6.2 Provincial — the biggest blind spot (build all four)

**Status update, 2026-06-26:** live-verified (direct fetch, not just search results) that
of the original ON→QC→BC→AB priority order, only **BC** currently has a real bulk/API
channel for its lobbyist registry — built and shipped, 26,357 rows in `source_records`
(see §3.2). The other three are confirmed interactive-search-only with no export and no
mirror on their provincial open-data portals:

| Province | First-wave source checked | Live finding | Status |
|---|---|---|---|
| **British Columbia** | BC Lobbyists Registry | Real ZIP bulk export, monthly, no UA/key required (`lobbyistsregistrar.bc.ca`) | ✅ **Shipped** — `pipeline/connector_bc_lobbyist_registry.py` |
| **Ontario** | ON Lobbyists Registry (`lobbyist.oico.on.ca`) | Interactive search UI only, no export/API; data.ontario.ca doesn't mirror it | ⬜ Blocked |
| **Quebec** | Registre des lobbyistes (now `carrefourlobby.quebec`) | Angular SPA, no documented public API; companion site `lobbyisme.quebec` explicitly blocks AI crawlers via robots.txt | ⬜ Blocked |
| **Alberta** | AB Lobbyist Registry | Oracle APEX search app, no export/API; open.alberta.ca doesn't mirror it | ⬜ Blocked |

**BC second source type checked 2026-06-26** (procurement, political finance — the two most
relevant second-wave targets): both blocked. **BC Bid** (`bcbid.gov.bc.ca`, procurement) and
**Elections BC** (`elections.bc.ca`, political finance/contributions) both use the standard
gov.bc.ca robots.txt template — `Disallow: /` for all generic agents, only Googlebot/bingbot/
BCGovSearch excepted. No workaround via BC's general open-data catalogue either: a real
"Ministry Contract Awards" dataset exists there, but `catalogue.data.gov.bc.ca`'s own
robots.txt disallows `/api/` and `/client-api/` (unlike `open.canada.ca`, which only blocks
CMS internals and explicitly permits its CKAN API) — and its dataset pages are a bare
`<div id="app">` SPA shell with no static resource links, entirely dependent on that
disallowed API. Same failure shape as Quebec's lobbyist SPA. Stays blocked; revisit if BC
opens its catalogue API or either site's robots.txt changes.

Remaining per-province second-wave targets (legislature/Hansard, orders/appointments) are
still entirely unscoped — research them with the same live-fetch-first discipline before
writing any connector. Don't assume a portal exists just because the source's federal
analogue does.

> Provincial is **High effort** — it's four jurisdictions' worth of sources, not one
> connector. ON/QC/AB stay blocked until those registries publish a bulk channel, or until
> an interactive-form scrape is explicitly approved (none of the three has a confirmed
> ToS/ToU position on bulk redistribution, and Quebec's posture is actively unfriendly).

### 6.3 Municipal — future backlog (not now)

On the radar, explicitly **after** federal-fix and the four provinces: Toronto /
Montreal / Vancouver **lobbyist registries** and **big-city procurement & council
agendas**. Don't start until provincial is underway.

### 6.4 Licence-review debt (governance, not engineering)

Live sources without a confirmed commercial-reuse review: donations, OCL lobbying
(comms + registrations), LEGISinfo bills, openparliament (MPs + Hansard), CRTC. These
need a terms review on file (P1 governance). See `config/data-sources.yaml`
`commercial_reuse_reviewed: false` rows.

### 6.5 Needs a decision before building

- `cmhc_housing` — overlaps StatCan's housing-construction series; pick one source of truth.
- `social_statements` — no authoritative source (X/LinkedIn APIs gated); press-release RSS unconfirmed.

---

## 7. Raw-archive & data-recovery note

**2026-06-25:** the canonical working copy was missing ~22G of raw/extracted source
payloads that had been left behind in `~/Documents/OLD NESSUS/` during the repo merge
(`data/` is gitignored, so git never carried it). **Recovered** via no-clobber copy;
canonical `data/` went 901M → 24G. The live `polaris.db` was already current (newer than
the old copy) and was **not** touched.

What was recovered and why it matters:

| Recovered | Size | Value |
|---|---|---|
| `data/extracted/statcan` (16 full data cubes) | 14G | **15 of 16 ingested 2026-06-26** into the new `statcan_observations` typed table (521,367 rows, `scripts/ingest_statcan_cubes.py`, `pipeline/connector_statcan_cubes.py`). `statcan_36100608` (61.4M rows, 14G alone — a narrow infrastructure-asset table) deliberately **deferred**, not silently skipped: disk/time cost isn't justified by the table's narrow product value relative to the other 15. |
| `data/raw/proactive-disclosure` | 2.7G | contracts/grants source CSVs — re-ingest-from-local for the Postgres move (no re-download) |
| `data/raw/{open-government, parliament, transport, statcan, orders-in-council, iaac, bank-of-canada, lobbying, …}` | ~3.5G | provenance/audit chain + re-ingest source |
| `data/extracted/{elections-canada, lobbying}` | ~2.7G | regenerable from cache zips (low unique value, kept for completeness) |

`OLD NESSUS/` is retained as a safety backup until the recovered data is verified in use
(e.g. a successful StatCan-cube ingest). After that it can be deleted.

---

## 8. Roadmap (sequenced)

**Phase 0 — Trust the current state** ✅ *done 2026-06-26 (see §5, GAMEPLAN.md)*
1. ✅ Fixed the data-quality bugs in §5 (contracts/grants/donations date columns, cer
   format, plus the appointment-date bug found during verification).
2. ✅ Wired `house_votes` into the scheduler; confirmed `ocl_legacy_scraper` is a live
   fallback, not dead code — not retiring it.
3. ✅ Fixed GIC Appointments (derives from already-ingested `orders_in_council` précis
   text — no dead CKAN dataset call) and CRTC (new per-year decision-index connector,
   RSS confirmed permanently dead).
4. ✅ Reconciled the yaml id drift. StatCan catalogue vs `catalogue_entries`
   reconciliation still open (low priority — `catalogue_entries` is discovery-layer
   metadata, not blocking the cube ingestion that mattered).

**Phase 1 — The refresh loop** *(the #1 problem — still open)*
5. **Migrate to Postgres** (`scripts/migrate_to_postgres.py`, resumable). Gating step.
6. Turn on the standalone scheduler; prove each Tier-1 job on its *scheduled* path.
7. Map the two archive-only sources (`canadabuys_tenders`, `bank_of_canada`) into rows.

**Phase 2 — Deepen federal**
8. ✅ **Ingested 15 of 16 recovered StatCan cubes** (2026-06-26, 521,367 rows,
   `statcan_observations`) — `statcan_36100608` (61.4M rows/14G) deliberately deferred.
9. **Entity graph** (subsidiaries/officers) — the moat multiplier. Still open.
10. ✅ **Full Hansard transcripts shipped** (2026-06-26, `hansard_transcripts` job, new
    `hansard_speeches` table) — first-party ourcommons.ca per-sitting XML, 13 sessions
    (38th Parliament onward). Committee evidence; competition_bureau; public_accounts/
    gc_infobase still open.

**Phase 3 — Provincial** *(biggest blind spot; in progress)*
11. ✅ **British Columbia shipped** (26,357 rows, lobbyist registry) — the only one of the
    four with a real bulk channel as of 2026-06-26 (live-verified). Ontario, Quebec,
    Alberta confirmed blocked (interactive-search-only registries, no export) — see §6.2.
    Revisit if any of the three publishes a bulk channel.

**Phase 4 — Municipal** *(backlog)*
12. Toronto / Montreal / Vancouver lobbying + procurement.

---

## Verification snapshot (2026-06-25)

How each claim above was checked this session:

- **DB counts:** real `count(*)` for `contracts` (1,155,000) and `lobbying_records`
  (362,805) — both have delete/reinsert history that inflates `max(id)`. `max(id)` proxy
  (✱) for append-only big tables. `count(*)` for all small tables.
- **Scheduler reality:** `scheduler_log` per-job last-run + status. Only `gc_news`,
  `gazette_notices`, `conversation_ca_politics`, `canadabuys_tenders` have fired since
  2026-06-22; the rest are stale or manual-only. `contracts_monthly` and
  `appointments_weekly` have only ever logged **errors** on the scheduled path.
- **Live HTTP probes (200 = reachable):** LEGISinfo bills JSON ✅, Gazette p1 RSS ✅,
  GC News API ✅, StatCan getAllCubesListLite ✅ (5MB / 8,213 cubes), openparliament ✅,
  orders-in-council portal ✅. **CRTC BroadcastDecisions RSS ❌** returns HTML, not XML
  (confirms the tribunal breakage).
- **Data-quality:** min/max on date columns surfaced the contracts/grants/donations
  corruption in §5.
- **Data recovery:** `du`/`cp -an` against `OLD NESSUS/`; canonical `data/` 901M → 24G,
  disk 164G free (filesystem reflinked the copy).
