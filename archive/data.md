# data.md — Source Completeness & Roadmap

Standalone living reference for "what do we have, what's partial, what's not built, and what's it worth to fix" — a personal checklist, separate from `DATA_CHECKLIST.md` (narrative build log), `DATA_CATALOG.md` (full source universe writeup), and `config/data-sources.yaml` (machine-readable registry). Those keep doing their own job; this doc isn't auto-generated and won't update itself — re-check against the registry/audit CLI (`scripts/nessus.py data inventory`) before trusting an old row.

Last assembled: 2026-06-22 (resuming a session that hit the Claude Code usage limit mid-build; real counts below come from a live audit against the canonical copy plus this session's own verified runs).

**Legend** — Status: ✅ live · 🟡 partial · 🔴 broken · ⬜ not started · 🚫 blocked (licensing/legal) · 📦 raw-archive only (fetched, not yet queryable rows)
**Difficulty**: Low / Medium / High · **Time**: hours / 1 day / 2-3 days / 1+ week

---

## ✅ Live and working

| Source | Rows | Coverage | Notes |
|---|---|---|---|
| Federal contracts >$10k (`contracts_monthly`) | 1,269,298 | full corpus | **Scheduled path verified this session (Goal 13)** — previously only a one-off manual backfill had ever succeeded; the actual cron-equivalent function now runs clean end-to-end (364s) |
| Political donations — Elections Canada (`donations_quarterly`) | 6,230,381 (prior run; re-verifying) | full corpus | Scheduled path being re-verified this session (Goal 13) — same fix as contracts |
| Grants & contributions (`grants_quarterly`) | 1,148,041 (prior run; re-verifying) | 1899*–2026 | *1899 is a known bad-data artifact, not real data — see Known bugs below |
| Lobbying communications (`ocl_monthly`) | 362,805 | 2008–2026 | |
| Lobbying registrations (`ocl_registrations`) | 166,564 | 1996–2026 | |
| NPRI pollutant releases (`npri`) | 181,780 | 2022–2024 only | One recent year; full history deferred to Postgres move |
| Orders in Council (`orders_in_council`) | 20,304 | 1990–2026 | |
| Canada Gazette (`gazette_weekly` + `gazette_notices`) | 13,165 | 2007–2026 | RSS entries + per-instrument notices |
| Bills (`bills_daily`) | 185 | current Parliament | LEGISinfo |
| MPs (`parliament_seed`) | 343 | current | openparliament, enriched w/ photos |
| Hansard keyword mentions (`hansard_search`) | 217 | current Parliament | **Not transcripts** — see Known gaps below |
| IAAC projects + CER incidents/applications (`iaac`, `cer`, `cer_applications`) | ~2,400 | thin, growing | IAAC accrues ~300 projects/run toward 6,389 total |
| 11 government dept RSS feeds (`pmo_news`,`boc_news`,`nrcan_news`,`eccc_news`,`ised_news`,`gac_news`,`transport_news`,`health_news`,`competition_news`,`crtc_news`,`cer_news`) + `gc_news` | ~30,600 | mostly 2017–2026 | One generic connector (`pipeline/feeds.py`), 320-char snippets only (Crown-copyright commercial-reuse cap) |
| The Conversation Canada politics (`the_conversation_ca`) | 25 | rolling | Only licensed commercial news source; ⚠️ yaml id `the_conversation_ca` vs actual scheduler/connector id `conversation_ca_politics` — same source, drifted doc id, never fixed (Low / hours) |
| StatCan, Transport, Geospatial catalogues (`statcan`, `transport`, `geospatial`) | ~900 | dataset *metadata* only | Not real numbers — see `statcan_series_observations` below |

## 📦 Built and scheduled, but archive-only (no queryable rows yet)

| Source | Status | Difficulty | Time | Notes |
|---|---|---|---|---|
| `canadabuys_tenders` | Resumable crawler runs every 4h | Medium | 2-3 days | Map raw tender-notice JSON into `source_records` |
| `bank_of_canada` | Resumable crawler runs every business day | Medium | 2-3 days | ~15,642 series; also has the unresolved "no per-series since-param" staleness issue (see CLAUDE.md) |

## 🟡🔴 Partial / broken — needs a fix, not a new build

| Source | Issue | Difficulty | Time |
|---|---|---|---|
| `appointments_weekly` (GIC Appointments) | `"No CSV resource found in GIC appointments dataset"` — CKAN dataset URL/shape rotated | Low | hours |
| `tribunal_decisions` (CRTC) | Feed URL now returns HTML, not RSS — runs "successfully" but silently loads 0 rows every time | Medium | 1 day |
| `ckan_catalogue` | Wired into the scheduler, has just never actually run (0 rows) | Low | hours |
| `grants_quarterly` date corruption | Some rows have description text shifted into the date column (`latest_date` returned French prose, not a date) | Medium | 1 day |
| `cer` date format | Dates stored `M/D/YYYY` instead of `YYYY-MM-DD`, silently breaks year-gap detection | Low | hours |

## ⬜ Built, never wired in (cheapest real wins)

| Source | What exists | Difficulty | Time |
|---|---|---|---|
| `house_votes` | `pipeline/connector_house_votes.py` — complete, working per-MP yea/nay-per-division connector, just never added to the scheduler | Low | hours |
| `iaac_project_registry` (yaml entry) | Stale doc only — this "follow-up" already shipped under the live `iaac` connector (Goal 8, 310+ rows). Delete the registry row, not a real gap | Low | hours |
| `ocl_legacy_scraper` | Old `scrapers/ocl.py` live-search path, superseded by the bulk-ZIP ingest, not wired into the scheduler. Likely safe to retire — confirm nothing else imports it first | Low | hours |

## ⬜ Not started — backlog only, no real blocker

| Source | Priority | Difficulty | Time |
|---|---|---|---|
| `statcan_series_observations` (real GDP/CPI/employment numbers) | P1 | High | 1+ week |
| `competition_bureau` enforcement actions | P1 | Medium | 2-3 days |
| `committee_evidence` (House committee membership/witnesses/evidence) | P1 | High | 1+ week |
| `gc_infobase` (federal spending/performance) | P3 | Medium-High | 2-3 days–1 week |
| `public_accounts` | P4 | Medium | 2-3 days |
| `osfi` | P2 | Medium | 2-3 days — confirmed no RSS; subscribe page is email-only |
| `cnsc` (nuclear regulator proceedings) | P3 | Medium | 1-2 days |
| `cfia_recalls` (food recalls) | P3 | Low-Medium | 1 day |
| `transport_row_level` (TSB occurrences/vehicle recalls) | P3 | Medium | 2-3 days |
| Full Hansard transcripts (real per-sitting-day text, not the keyword-excerpt sweep) | — | High | 1+ week — needs `parl.gc.ca` per-sitting-day Hansard XML, nothing here touches it today; UI mockup already exists (`New DESIGN INSTRUCTIONS/nessus_hansard_transcript_detail`) with no connector behind it |

## ⬜ Needs a decision before building (not just effort)

| Source | Decision needed |
|---|---|
| `cmhc_housing` | Overlaps StatCan's own housing-construction series — pick one source of truth before building both |
| `social_statements` | No single authoritative source (X/LinkedIn APIs are access-gated); press-release RSS suggested but unconfirmed |
| `regional_and_trade_press_placeholder` | Tasks.md names the category generically without naming actual outlets — nothing concrete to review yet |

## ⬜ Harder / legally distinct — deliberately deferred

| Source | Why it's harder |
|---|---|
| `scc_official` (Supreme Court decisions) | Needs a dedicated first-party scraper (not CanLII) that handles publication bans and corrected judgments — real design work, High / 1+ week |
| `canlii` | Blocked on a pending API key, not a difficulty problem — Low/hours once the key arrives |

## 🚫 Blocked on licensing (17 registry rows, grouped)

CBC, CTV, Globe and Mail, Toronto Star, Financial Post, National Post, La Presse, Le Devoir, The Logic, The Narwhal, Canadian Press, iPolitics, Hill Times, Policy Options, Global News — all reviewed live and confirmed to need a paid/negotiated licence Nessus doesn't hold. Plus `licensed_news_api_vendors` (Factiva, LexisNexis, Meltwater, NewsAPI.ai — paid, not reviewed individually) and `regional_and_trade_press_placeholder`. Not an engineering task — needs a licensing/business decision first.

## 🚫 Provincial (4 registry rows, grouped)

`provincial_placeholder_{on,qc,bc,ab}` — entirely absent. Everything in the product today is federal. Largest single blind spot if clients care about regional plays — High difficulty, 1+ week, since it's 4 new jurisdictions' worth of sources, not one connector.

---

## Known data-quality bugs (separate from missing sources)

1. **`grants_quarterly`**: some rows have description text shifted into the date column instead of a real date (on top of the 1899 placeholder issue above).
2. **`cer`**: dates stored as `M/D/YYYY`, not `YYYY-MM-DD` — breaks year-gap detection silently.
3. **Doc/code id drift**: yaml's `the_conversation_ca` vs the scheduler's actual `conversation_ca_politics` — same source, two ids (caught by Goal 12's audit engine).

## Recommended next priorities

**Quick wins (hours each, do these first):** wire `house_votes`, delete the stale `iaac_project_registry` entry, fix the GIC appointments dataset URL, run `ckan_catalogue` once, fix the `cer` date format.

**Highest product value (bigger lifts, biggest payoff):**
- `statcan_series_observations` — real GDP/CPI/employment numbers, the actual "economic context" the platform only gestures at today via a dataset list. Flagged P1, still untouched — most defensible "build next."
- **Entity graph** (subsidiaries/officers) — called out repeatedly elsewhere in this project's own notes as the multiplier on every other source; entity resolution today is name-matching only.
- `public_accounts` + `gc_infobase` — "who got paid how much, by which department," beyond proactive disclosure.
- **Provincial expansion** — the single largest blind spot if regional coverage matters to clients, not a connector bug.
