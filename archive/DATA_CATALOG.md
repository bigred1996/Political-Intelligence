# Nessus — Master Data Catalog

Every candidate source, with access method, product priority, and status.
This supersedes the source table in `DATA_CHECKLIST.md` (that file stays as the
short build tracker; this is the full universe).

**Status:** ✅ live · 🟡 partial/stub · ⬜ planned · 🔴 blocked
**Access:** `API` (JSON/REST) · `BULK` (CSV/ZIP download) · `SCRAPE` (HTML/XML) · `3P` (third-party API) · `KEY` (needs credential)
**Priority** (for political-risk DD on a company/sector):
**P1** core to the 9 report sections · **P2** strong enhancer · **P3** breadth / later

Last updated: 2026-06-22 (Goal 9 — generic RSS/Atom/RDF government-publication
connector, 11 feeds live; see §12/§13) — reconciled against
`config/data-sources.yaml` and a live audit of `polaris.db` + `scheduler_log`
(see `DATA_CHECKLIST.md` "Ingestion audit — 2026-06-21" for the systemic
findings: no connector does true incremental fetch, no raw storage/revision
history exists, two wired-but-dormant jobs have duplicate-accumulation bugs).
Rows below marked "✅(2026-06-21)" were corrected that pass; "✅(2026-06-22)"
rows are Goal 9 — the prior status was stale.

---

## 1. Parliament & Legislative Process

| Source | Access | Priority | Status | Notes / next step |
|---|---|---|---|---|
| Bills + proposed legislation (LEGISinfo) | API | P1 | ✅ | `parl.ca/legisinfo/en/bills/json` — live in DB |
| Bill status tracking (stages, amendments, royal assent) | API | P1 | 🟡 | same feed has stage fields; expand parse into a status timeline |
| Voting records — House divisions | API/SCRAPE | P1 | ⬜ | ourcommons.ca votes XML; or openparliament.ca `3P` API |
| Senate voting records | SCRAPE | P2 | ⬜ | sencanada.ca — scrape |
| Hansard — House debates | SCRAPE(XML) | P1 | 🟡(stub) | ourcommons.ca publishes per-sitting XML; openparliament.ca `3P` has clean speeches API |
| Senate debates (Senate Hansard) | SCRAPE | P2 | ⬜ | sencanada.ca |
| House committee transcripts | SCRAPE(XML) | P1 | ⬜ | ourcommons.ca committee evidence XML |
| Senate committee transcripts | SCRAPE | P2 | ⬜ | sencanada.ca |
| Committee reports | SCRAPE | P2 | ⬜ | ourcommons.ca |
| Committee witness testimony records | SCRAPE | P1 | ⬜ | high value — who testified for/against (maps to stakeholders + lobbying) |
| Order papers / notices of motion | SCRAPE | P3 | ⬜ | ourcommons.ca |
| Parliamentary petitions | API/SCRAPE | P3 | ⬜ | petitions.ourcommons.ca |

## 2. Members of Parliament / Political Actors

| Source | Access | Priority | Status | Notes / next step |
|---|---|---|---|---|
| MP profiles (bio, riding, party, roles) | SCRAPE/3P | P1 | 🟡(seed) | ourcommons.ca members XML; openparliament.ca `3P` API is cleanest |
| Ministerial portfolios / cabinet composition | SCRAPE | P1 | 🟡(seed) | canada.ca cabinet; pm.gc.ca |
| Party affiliation history | 3P | P2 | ⬜ | openparliament.ca |
| Parliamentary roles (whip, chair, etc.) | SCRAPE/3P | P2 | ⬜ | feeds committee-jurisdiction stakeholder mapping |
| Electoral district representation history | BULK/3P | P3 | ⬜ | Elections Canada + openparliament |
| Attendance records | SCRAPE | P3 | ⬜ | partial availability |

## 3. Elections & Democracy Data

| Source | Access | Priority | Status | Notes / next step |
|---|---|---|---|---|
| Federal election results (Elections Canada) | BULK | P2 | ⬜ | elections.ca open data / CKAN bulk CSV |
| Riding-level vote breakdowns | BULK | P2 | ⬜ | same — feeds "election sensitivity" by riding |
| Candidate lists | BULK | P3 | ⬜ | elections.ca |
| Voter turnout statistics | BULK | P3 | ⬜ | elections.ca |
| Registered political parties | BULK | P3 | ⬜ | elections.ca |
| Electoral district boundaries (redistribution) | BULK(GEO) | P3 | ⬜ | maps donors/contracts to ridings |
| By-election results | BULK | P3 | ⬜ | elections.ca |
| Referendum results (historical) | BULK | P3 | ⬜ | elections.ca |

## 4. Lobbying & Influence  ← **moat**

| Source | Access | Priority | Status | Notes / next step |
|---|---|---|---|---|
| Federal lobbyist registry (OCL) — communications | BULK | P1 | ✅(2026-06-21) | **Unblocked.** Browser-UA on the Monthly Communications ZIP works — 362,805 rows live by real `count(*)` (corrected 2026-06-21; the "694,152" figure cited everywhere previously was `max(id)`, inflated because this table's full delete-then-reinsert cycle doesn't reuse SQLite autoincrement ids). Stale 🔴 corrected this pass. |
| Active lobbyists database | BULK | P1 | ✅(2026-06-21) | within OCL communications data above |
| Lobbying activity / monthly communication returns | BULK | P1 | ✅(2026-06-21) | same ZIP as above; always full delete-then-reinsert, no incremental fetch yet |
| Lobbying registrations (versioned) | BULK | P1 | 🔴 | connector built (`fetch_ocl_registration_rows`), job wired (`ocl_registrations`), **table empty — never triggered**; no version-history preservation yet (spec wants registration versions kept, not overwritten) |
| Designated public office holder (DPOH) contacts | BULK | P1 | ✅(2026-06-21) | in communications data, stored as `raw` JSON per record — drives revolving-door flags (not yet surfaced as a UI flag) |
| Lobbying subject-matter classifications | BULK | P2 | 🟡 | subject codes stored raw; no code→human-label lookup yet |
| Client registries (companies, assns, NGOs) | BULK | P1 | ✅(2026-06-21) | core entity links, resolved via `entity_resolver.normalize()` |
| Lobbying firm registrations | BULK | P2 | 🔴 | within the untriggered registrations job above |
| Lobbyist code-of-conduct disclosures | SCRAPE | P3 | ⬜ | OCL site |

## 5. Political Finance & Donations

| Source | Access | Priority | Status | Notes / next step |
|---|---|---|---|---|
| Contributions database (individual donors) | BULK | P1 | ✅(2026-06-21) | Elections Canada ZIP — full corpus live, **6,230,381 rows** (was 80k pending uncap; now uncapped, but scheduled quarterly cron is unproven — see checklist) |
| Corporate donation records (historical) | BULK | P2 | 🟡 | same dataset pre-2007 ban; flag historical only |
| Party financial returns | BULK/SCRAPE | P2 | ⬜ | elections.ca financial returns |
| Riding association financial reports | BULK/SCRAPE | P3 | ⬜ | elections.ca |
| Election campaign spending reports | BULK/SCRAPE | P2 | ⬜ | elections.ca |
| Leadership contest finances | BULK/SCRAPE | P3 | ⬜ | elections.ca |
| Third-party advertising spending (EFA) | BULK/SCRAPE | P2 | ⬜ | elections.ca — relevant to sector advocacy |

## 6. Government Spending & Procurement

| Source | Access | Priority | Status | Notes / next step |
|---|---|---|---|---|
| Federal procurement contracts (>$10k) | BULK | P1 | ✅(2026-06-21) | open.canada.ca CSV — **1,155,000 rows** live; *but* the scheduled monthly cron has only been attempted once and failed (see checklist) — only the manual backfill is proven |
| Contract award notices / tenders (CanadaBuys) | API | P2 | ⬜ | canadabuys.canada.ca (replaced Buyandsell) — has open data/API; not started |
| Contract award notices (CanadaBuys awards) | API | P2 | ⬜ | same portal, awarded-contract feed; not started |
| Vendor registry | BULK | P2 | ⬜ | within procurement data |
| PSPC spending reports | BULK | P3 | ⬜ | open.canada.ca |
| Departmental expenditures | BULK/API | P3 | ⬜ | GC InfoBase API |
| Public Accounts of Canada | BULK | P2 | ⬜ | tpsgc-pwgsc.gc.ca; not started |
| MP office budgets / expenses | SCRAPE | P3 | ⬜ | ourcommons.ca proactive disclosure |
| Travel & hospitality disclosures | BULK | P2 | ⬜ | open.canada.ca proactive disclosure datasets (confirmed reachable) |
| Grants & contribution programs (recipients) | BULK | P2 | 🔴 | connector built (`fetch_grant_rows`), job wired (`grants_quarterly`), **table empty, never triggered, and has a duplicate-accumulation bug** — fix before triggering (see checklist) |
| Crown corporation financial disclosures | SCRAPE | P3 | ⬜ | varies per Crown corp |

## 7. Regulation & Policy Output

| Source | Access | Priority | Status | Notes / next step |
|---|---|---|---|---|
| Federal regulations (SOR/SI) | SCRAPE/BULK | P1 | ⬜ | laws-lois.justice.gc.ca (Justice Laws) — feeds Regulatory Landscape |
| Regulatory Impact Analysis Statements (RIAS) | SCRAPE | P2 | ⬜ | published in Canada Gazette Part II |
| Canada Gazette (Part I proposed / Part II registered) | RSS | P1 | ✅(2026-06-21) | `gazette.gc.ca/rss/p1-eng.xml` + `/p2-eng.xml` — **638 entries** live, upsert-by-`guid`. Stale ⬜ corrected this pass. |
| Treasury Board directives | SCRAPE | P3 | ⬜ | canada.ca |
| Departmental policy instruments | SCRAPE | P3 | ⬜ | canada.ca |
| Forward Regulatory Plans | SCRAPE | P3 | ⬜ | canada.ca; not started |
| Orders in Council | BULK | P2 | ⬜ | orders-in-council.canada.ca has a search/export; not started |
| Consultation papers + public submissions | SCRAPE | P2 | ⬜ | consultations registry on canada.ca |
| Regulatory amendments tracking | SCRAPE | P2 | ⬜ | Gazette diffing — blocked on the revision-history mechanism not existing yet (see checklist) |

## 8. Courts & Legal Interpretation

| Source | Access | Priority | Status | Notes / next step |
|---|---|---|---|---|
| Supreme Court of Canada decisions | SCRAPE | P2 | 🔴 | **Blocked by design, not technical.** Spec requires first-party court sources only; SCC needs a dedicated scraper against scc-csc.lexum.com (official) — not built. Do not substitute CanLII for this. |
| Federal Court rulings | SCRAPE | P2 | ⬜ | decisions.fct-cf.gc.ca |
| Provincial court decisions | SCRAPE | P3 | ⬜ | varies; Phase 2 (provincial) |
| CanLII case database | API+KEY | P2 | 🔴 | **Permission-gated by product decision** — needs an approved CanLII API key + confirmed commercial-reuse terms before any bulk use. Until then: citations/links only, no full-text mirroring. |
| Charter challenge rulings | SCRAPE | P3 | ⬜ | subset of above |
| Administrative tribunals — CRTC decisions | RSS | P1 | 🔴 | connector built (`fetch_crtc_decisions`), job wired (`tribunal_decisions`), upsert-by-`(decision_number, body)` already implemented, **table empty — never triggered** |
| Administrative tribunals — Competition Bureau, IRB, CER proceedings | SCRAPE | P1 | ⬜ | **sector-critical** regulatory-risk signal; per-tribunal sites, not started beyond CRTC |

## 9. Government Structure & Administration

| Source | Access | Priority | Status | Notes / next step |
|---|---|---|---|---|
| Department & agency directories (GEDS) | API/BULK | P2 | ⬜ | open.canada.ca org data — stakeholder reference table |
| Org charts (federal departments) | SCRAPE | P3 | ⬜ | canada.ca |
| Senior public servant / GIC appointments | SCRAPE | P2 | ⬜ | GIC appointments + Orders in Council search (revolving-door context) |
| Treasury Board classification data | BULK | P3 | ⬜ | open.canada.ca |
| Federal public service employment data | BULK | P3 | ⬜ | open.canada.ca / StatCan |
| Staffing & hiring statistics | BULK | P3 | ⬜ | PSC reports |

## 10. Open Data Infrastructure

| Source | Access | Priority | Status | Notes / next step |
|---|---|---|---|---|
| Open Government Portal (CKAN) | API | P1 | ✅ | `open.canada.ca/data/api/3/action` — our dataset-discovery backbone |
| Federal dataset API catalogs | API | P2 | ✅ | via CKAN |
| GC InfoBase (budget + performance) | API | P3 | ⬜ | budget/spending context; not started |
| Statistics Canada datasets — cube catalogue | API | P2 | 🟡(2026-06-21) | live — **300 cube metadata rows**, no row-level series values yet. Stale ⬜ corrected this pass. |
| Statistics Canada datasets — series observations (GDP, CPI, employment, etc.) | API(SDMX/WDS) | P1 | ⬜ | the actual numbers behind the catalogue — not yet ingested; this is what the political/sector-intelligence framing needs, not the catalogue alone |
| Geo data (GeoBase, boundaries) | BULK(GEO) | P3 | 🟡(2026-06-21) | NRCan/GeoGratis catalogue live (300 dataset records); no boundary files actually downloaded/queryable yet |
| Environmental registry datasets (IAAC) | API/BULK | P2 | 🟡(2026-06-21) | catalogue live (200 records); row-level project registry still needs a dedicated connector — see §11 |

## 11. Environmental, Energy & Industry Regulation

| Source | Access | Priority | Status | Notes / next step |
|---|---|---|---|---|
| Impact assessment project registry (IAAC) | API/BULK | P1* | 🟡(2026-06-21) | *P1 for energy/infra/mining deals. Catalogue live (200 dataset records via CKAN); the actual per-project registry (proponents, status, decisions, conditions) needs the IAAC registry API specifically — not built |
| Environmental compliance reports | BULK | P2 | ⬜ | ECCC |
| GHG emissions reporting (federal) | BULK | P2 | ⬜ | open.canada.ca |
| National Pollutant Release Inventory (NPRI) | BULK/API | P2 | ✅(2026-06-21) | **60,202 facility-level releases** live (most recent reporting year only; capped at `max_rows=200000` by design). Multi-year history not yet loaded — disk-pressure rationale for deferring it may no longer apply on this host (246 GB free vs the ~13 GB this was designed around). |
| Energy regulation filings (CER) | SCRAPE/API | P1* | ✅(2026-06-21) | *P1 for energy sector. **2,008 pipeline incidents** live, by company/substance/location. Applications/hearings/decisions/conditions not yet ingested — only incident data so far. |
| Mining permits/licences | BULK | P2 | ⬜ | federal/provincial split |
| Fisheries & ocean permits | BULK | P3 | ⬜ | DFO |
| Transport Canada enforcement / TSB | BULK/SCRAPE | P3 | 🟡(2026-06-21) | dataset catalogue live (300 records via CKAN org query); row-level TSB occurrences / vehicle recalls need a dedicated connector — catalogue only today |

## 12. Macroeconomic & Financial Regulators (added 2026-06-21, from ingestion spec)

| Source | Access | Priority | Status | Notes / next step |
|---|---|---|---|---|
| Bank of Canada policy rate, FX rates, market data | API | P2 | ⬜ | Bank of Canada Valet API (open, no key) — not started |
| Bank of Canada announcements / RSS | RSS | P2 | ✅(2026-06-22) | Goal 9: `boc_news` — 10 items live, 2026-01-28..2026-06-10 (RSS 1.0/RDF; feed window is thin, no deeper archive at this URL) |
| Department of Finance releases + Fiscal Monitor | RSS/BULK | P2 | 🟡(2026-06-22) | Goal 9 investigated: no dedicated departmental RSS/Atom feed found (the IO News API's `dept=` slug for Finance could not be discovered — tried 3 legal-name variants, all 0 results). Already captured via the existing `gc_news` connector instead (`entity_name = "Department of Finance Canada"`, ~117 items in a `pick=3000` window) — not duplicated as a separate connector. Fiscal Monitor/budget documents themselves still not started. |
| OSFI guidance, announcements, financial data | SCRAPE/BULK | P2 | 🔴(2026-06-22) | Goal 9 investigated: OSFI publishes no RSS/Atom feed at all — its "Stay Connected" page is email-only notifications, no feed references found. No connector built. |
| CMHC housing starts, building permits, rental market data | BULK/API | P2 | ⬜ | not started; StatCan also publishes overlapping series |
| Competition Bureau decisions, enforcement, guidance | SCRAPE | P1 | 🟡(2026-06-22) | Goal 9 added the news/announcements side (`competition_news` — 495 items, 2016-11-21..2026-06-22, deepest dept-filtered feed found); formal decisions/enforcement-action registry (distinct from news releases) still not ingested |
| Canadian Nuclear Safety Commission proceedings/decisions | SCRAPE | P2 | 🔴(2026-06-22) | Goal 9 investigated: both documented RSS subscribe URLs (`cnsc-ccsn.gc.ca` and `nuclearsafety.gc.ca` `/eng/get-involved/subscribe-rss/`) return HTTP 404 — CNSC appears to have discontinued RSS without removing the link from its own news-room page. No connector built; revisit periodically. |
| Canadian Food Inspection Agency recalls/notices | RSS/API | P2 | ⬜ | not started |
| Health Canada recalls/advisories/compliance notices | RSS | P2 | 🟡(2026-06-22) | Goal 9 added general news (`health_news` — 1,159 items, 2017-05-17..2026-06-16); recall/advisory/compliance-specific feeds (`canada.ca/en/health-canada/services/rss-feeds.html`) are a separate, more granular source not yet ingested |
| Canadian International Trade Tribunal decisions | SCRAPE | P3 | ⬜ | not started |
| Canadian Transportation Agency decisions | SCRAPE | P3 | ⬜ | not started |

## 13. Government Publications (added 2026-06-21; itemized 2026-06-22 — Goal 9)

Per the ingestion spec's news policy — full-text copyrighted news stays
disabled pending licensing review. Headline/summary/link metadata under fair
use from official feeds is fine to enable now.

**Goal 9 (2026-06-22) built a single generic RSS/Atom/RDF connector
(`pipeline/feeds.py`) serving 11 government feeds** — see
`config/data-sources.yaml` for full per-source detail (licensing,
backfill/incremental strategy, known limitations). All 11 are `enabled: true`,
checkpointed via upsert-by-GUID, and registered as daily scheduler jobs.
**License finding:** Canada.ca's Terms and Conditions permit reproduction for
non-commercial use only ("you may not reproduce materials for the purposes of
commercial redistribution... without prior written permission") — Nessus is
commercial, so every one of these 11 stores/displays only a ~320-char
publisher-supplied snippet per item (never the full release body, and
`<content:encoded>`/Atom `<content>` are never even parsed), with the complete
raw feed XML retained separately via `pipeline/raw_storage.py` for internal
provenance only (not a public display surface).

| Source | Access | Priority | Status | Notes / next step |
|---|---|---|---|---|
| PMO news | RSS | P2 | ✅(2026-06-22) | `pmo_news` — 10 items, 2026-06-17..2026-06-22 (thin RSS window, no deeper archive) |
| Global Affairs Canada news | API (IO News, dept-filtered) | P2 | ✅(2026-06-22) | `gac_news` — 3,620 items, 2018-03-13..2026-06-22 (deepest dept-filtered feed) |
| Natural Resources Canada news | API (IO News, dept-filtered) | P2 | ✅(2026-06-22) | `nrcan_news` — 1,862 items, 2017-10-13..2026-06-22 |
| Environment and Climate Change Canada news | API (IO News, dept-filtered) | P2 | ✅(2026-06-22) | `eccc_news` — 1,522 items, 2018-02-01..2026-06-22 |
| ISED news | API (IO News, dept-filtered) | P2 | ✅(2026-06-22) | `ised_news` — 1,857 items, 2017-03-16..2026-06-22 |
| Transport Canada news | API (IO News, dept-filtered) | P2 | ✅(2026-06-22) | `transport_news` — 1,220 items, 2017-05-12..2026-06-22; distinct from the existing `transport` open-data-catalogue connector |
| CRTC news & speeches | Atom | P3 | ✅(2026-06-22) | `crtc_news` — 28 items, 2025-11-18..2026-06-16; distinct from the existing `tribunal_decisions` job (structured CRTC decision rows) |
| Canada Energy Regulator news releases | Atom | P3 | ✅(2026-06-22) | `cer_news` — 3 items, 2026-01-30..2026-03-17 (very thin feed); distinct from the existing `cer` (incidents) and `cer_applications` (proceedings) connectors |
| Finance Canada, OSFI, CNSC, IAAC | — | P2 | see §12 | no dedicated RSS/Atom feed exists for these four — see §12 rows above for what was tried and why each is unbuilt rather than ✅ |
| Public Safety Canada, IRCC, CRA | RSS | P2 | ⬜ | named in the ingestion spec's §13 priority list but out of Goal 9's explicit scope ("Start with" 17 named sources) — not investigated this pass |

## 13b. Canadian News — separate connector category (added 2026-06-22 — Goal 10)

Goal 9's `pipeline/feeds.py` connectors above are all official government
departments/agencies — a blanket Crown-copyright/canada.ca-Terms review covers
all 11 at once. Actual commercial/independent news publishers are a different
risk category (each carries its own, individually-negotiated licence), so
Goal 10 split them into a **separate connector category, "Canadian News"**
(`pipeline/news_feeds.py`), with two real terms-of-use reviews done live
this session rather than assumed from the spec's own optimistic framing:

- **Global News (Corus Entertainment) — REJECTED.** corusent.com's Terms of
  Use (which the spec named as a "starting approved" source) state content
  may be downloaded/printed/viewed "for non-commercial use only", with a
  separate paid licensing-request page for anything else. No RSS/syndication
  carve-out exists. Stays disabled.
- **The Conversation Canada — APPROVED, and now live.** Every Atom entry
  carries a per-item `<rights>` tag reading "Licensed as Creative Commons –
  attribution, no derivatives" (CC BY-ND 4.0); their republishing guidelines
  confirm commercial use is fine. `fetch_news_feed_records` additionally
  verifies that per-item rights string before accepting any row, rather than
  trusting the feed-level review for every item. Full text is still never
  stored (their own guidelines forbid "systematically republish[ing] ALL of
  our articles", which a recurring connector does by nature, and full
  republication separately needs a pageview-counter script not implemented
  here) — same headline/excerpt/author/canonical-link shape as the Goal 9
  government feeds.

| Source | Access | Priority | Status | Notes / next step |
|---|---|---|---|---|
| The Conversation Canada — Politics | Atom | P3 | ✅(2026-06-22) | `the_conversation_ca` — CC BY-ND 4.0, reviewed and enabled; 25 items live, 2026-05-24..2026-06-22, all 25 passing the per-item `<rights>` check; headline/excerpt only, full text deliberately withheld (see above) |
| Global News RSS (Canada, Politics, Money, Environment) | RSS | P5 | 🔴 | **REVIEWED 2026-06-22 and blocked** — corusent.com ToU is non-commercial-use-only; was previously listed as "reviewable", now confirmed blocked |
| The Narwhal | — | P5 | 🔴 | **REVIEWED 2026-06-22 and blocked** — their republishing page requires case-by-case email approval per story, prohibits ads on republished stories and systematic republication, and offers no RSS at all; initially guessed to resemble The Conversation Canada's open licence, that guess was wrong |
| CBC, CTV, Financial Post, National Post, Globe and Mail, Toronto Star, La Presse, Le Devoir, The Logic, iPolitics, Hill Times, Policy Options | RSS | P5 | 🔴 | **disabled candidates pending licensing/terms review** — each now has its own row in `config/data-sources.yaml` (split out of one bundled placeholder) so a future review can track each negotiation separately; not individually reviewed this session |
| The Canadian Press (wire) | 3P/KEY | P5 | 🔴 | wire-service access requires a paid commercial licensing agreement, not a public feed |
| Licensed news APIs (Factiva/Dow Jones, LexisNexis, Meltwater, Event Registry/NewsAPI.ai) | 3P/KEY | P5 | 🔴 | do not activate on key availability alone — needs commercial storage/display/caching/redistribution review first |
| Regional business & energy/mining trade press (Business in Vancouver, etc.) | RSS | P5 | ⬜ | Tasks.md names this generically rather than by specific outlet — needs a real candidate list before any review |

## 14. Provincial Sources (placeholders only, per spec — Phase 2)

| Source | Access | Priority | Status | Notes / next step |
|---|---|---|---|---|
| Provincial legislatures (bills, Hansard, committees) | varies | P4 | ⬜ | placeholder — ON/QC/BC/AB highest value |
| Provincial gazettes | varies | P4 | ⬜ | placeholder |
| Provincial lobbying registries | varies | P4 | ⬜ | placeholder — ON has its own registry today |
| Provincial procurement | varies | P4 | ⬜ | placeholder |
| Provincial budgets | varies | P4 | ⬜ | placeholder |
| Provincial energy boards / securities regulators / impact-assessment registries | varies | P4 | ⬜ | placeholder |

---

## Strategic read (revised 2026-06-21)

**Already live with real rows:** contracts (1.15M), donations (6.2M), lobbying
communications (694k), bills (185), Gazette (638), CER incidents (2,008), NPRI
releases (60,202), GC News (20,034), MPs (343), CKAN discovery, StatCan/IAAC/
Transport/Geospatial catalogues (~300 each). That's the real foundation — the
gap is no longer "do we have data," it's "is the *refresh* path proven, and is
there any change-history."

**Fastest wins now — fixing/triggering what's already built, not new connectors:**
1. **Trigger the 3 wired-but-dormant jobs** — `ocl_registrations`, `tribunal_decisions`
   (CRTC), and `grants_quarterly` (after fixing its dup-accumulation bug) — code
   exists, nobody has ever run them.
2. **Fix `appointments_weekly` and `grants_quarterly`'s duplicate-accumulation bug**
   before triggering — both insert with no delete-first and no dedup key.
3. **Prove the scheduled (cron) paths for `contracts_monthly` and `donations_quarterly`
   actually complete** — both live datasets came from one-off manual/standalone
   runs; the one logged scheduled `contracts_monthly` attempt failed.
4. **Statistics Canada row-level series** (GDP, CPI, employment) — the catalogue
   is live but it's metadata only; the political/sector-intelligence framing
   needs actual observations, not a list of 300 table names.

**Genuinely net-new (not yet started, real engineering):**
- Administrative tribunals beyond CRTC (Competition Bureau, CER hearings/decisions, IRB)
- IAAC and Transport row-level connectors (currently catalogue-only)
- House voting records / individual MP votes (Hansard speeches are live; votes are not)
- Bank of Canada, OSFI, CMHC, CFIA, Health Canada recalls (§12 above)
- Raw-file storage + revision history + checkpoint/ETag support — a cross-cutting
  gap affecting every connector, not a per-source task (see `DATA_CHECKLIST.md`)

**Scrape-heavy / slower (budget accordingly):** Senate, provincial courts, per-Crown-corp disclosures, org charts, tribunal sites without bulk export.

**Permission-gated, do not bypass:** CanLII (needs an approved API key + reviewed
commercial-reuse terms — citations/links only until then), SCC (needs a first-party
scraper, not CanLII), any X/LinkedIn social access, all named-publisher news beyond
official government RSS (§13).

**Sector-conditional P1:** IAAC project registry + CER filings become top priority specifically for energy / infrastructure / mining deals.

> Note: access methods marked SCRAPE/API are best-known starting points; each needs a
> reachability probe before committing (same discipline that caught the blocked OCL ZIP
> and the LEGISinfo field names). Don't trust the label until a probe confirms it.
