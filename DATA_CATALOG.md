# Nessus — Master Data Catalog

Every candidate source, with access method, product priority, and status.
This supersedes the source table in `DATA_CHECKLIST.md` (that file stays as the
short build tracker; this is the full universe).

**Status:** ✅ live · 🟡 partial/stub · ⬜ planned · 🔴 blocked
**Access:** `API` (JSON/REST) · `BULK` (CSV/ZIP download) · `SCRAPE` (HTML/XML) · `3P` (third-party API) · `KEY` (needs credential)
**Priority** (for political-risk DD on a company/sector):
**P1** core to the 9 report sections · **P2** strong enhancer · **P3** breadth / later

Last updated: 2026-06-21 — reconciled against `config/data-sources.yaml` and a
live audit of `polaris.db` + `scheduler_log` (see `DATA_CHECKLIST.md`
"Ingestion audit — 2026-06-21" for the systemic findings: no connector does
true incremental fetch, no raw storage/revision history exists, two wired-but-
dormant jobs have duplicate-accumulation bugs). Rows below marked "✅(2026-06-21)"
were corrected this pass — the prior status was stale.

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
| Bank of Canada announcements / RSS | RSS | P2 | ⬜ | not started |
| Department of Finance releases + Fiscal Monitor | RSS/BULK | P2 | ⬜ | not started |
| OSFI guidance, announcements, financial data | SCRAPE/BULK | P2 | ⬜ | not started |
| CMHC housing starts, building permits, rental market data | BULK/API | P2 | ⬜ | not started; StatCan also publishes overlapping series |
| Competition Bureau decisions, enforcement, guidance | SCRAPE | P1 | ⬜ | sector-critical for any merger/competition political-risk read; not started |
| Canadian Nuclear Safety Commission proceedings/decisions | SCRAPE | P2 | ⬜ | not started |
| Canadian Food Inspection Agency recalls/notices | RSS/API | P2 | ⬜ | not started |
| Health Canada recalls/advisories/compliance notices | RSS | P2 | ⬜ | not started |
| Canadian International Trade Tribunal decisions | SCRAPE | P3 | ⬜ | not started |
| Canadian Transportation Agency decisions | SCRAPE | P3 | ⬜ | not started |

## 13. Approved News & Publications (added 2026-06-21)

Per the ingestion spec's news policy — full-text copyrighted news stays
disabled pending licensing review. Headline/summary/link metadata under fair
use from official feeds is fine to enable now.

| Source | Access | Priority | Status | Notes / next step |
|---|---|---|---|---|
| GC departmental news RSS (PMO, Finance, GAC, NRCan, ECCC, ISED, TC, Health, Public Safety, IRCC, CRA, Competition Bureau, CER, IAAC, CNSC, CRTC, OSFI) | RSS | P1 | 🟡 | `gc_news` breadth connector already covers "all departments" via the IO news API — confirm it's a superset of these specific department feeds before building per-department RSS separately |
| Global News RSS (Canada, Politics, Money, Environment) | RSS | P3 | ⬜ | publisher-provided feed, terms permit headline/summary/link use — reviewable, not yet built |
| CBC, CTV, Financial Post, National Post, Globe and Mail, Toronto Star, La Presse, Le Devoir, The Logic, The Narwhal, Canadian Press, iPolitics, Hill Times, Policy Options | — | P5 | 🔴 | **disabled candidates pending licensing/terms review** per spec — do not enable without a reviewed agreement |
| Licensed news APIs (CP, Factiva/Dow Jones, LexisNexis, Meltwater, Event Registry/NewsAPI.ai) | 3P/KEY | P5 | 🔴 | do not activate on key availability alone — needs commercial storage/display/caching/redistribution review first |

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
