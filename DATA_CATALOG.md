# Polaris — Master Data Catalog

Every candidate source, with access method, product priority, and status.
This supersedes the source table in `DATA_CHECKLIST.md` (that file stays as the
short build tracker; this is the full universe).

**Status:** ✅ live · 🟡 partial/stub · ⬜ planned · 🔴 blocked
**Access:** `API` (JSON/REST) · `BULK` (CSV/ZIP download) · `SCRAPE` (HTML/XML) · `3P` (third-party API) · `KEY` (needs credential)
**Priority** (for political-risk DD on a company/sector):
**P1** core to the 9 report sections · **P2** strong enhancer · **P3** breadth / later

Last updated: 2026-06-15

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
| Federal lobbyist registry (OCL) | BULK | P1 | 🔴 | gov media ZIP blocked → currently sample. Try CKAN `70ef2117`, browser-UA, or mirror |
| Active lobbyists database | BULK | P1 | 🔴 | within OCL registry |
| Lobbying activity / monthly communication returns | BULK | P1 | 🔴 | CKAN `a34eb330` (Monthly Communication Reports) — **try this first, separate from blocked ZIP** |
| Designated public office holder (DPOH) contacts | BULK | P1 | 🔴 | in communications data — drives revolving-door flags |
| Lobbying subject-matter classifications | BULK | P2 | 🔴 | maps lobbying → sector/bill |
| Client registries (companies, assns, NGOs) | BULK | P1 | 🔴 | core entity links |
| Lobbying firm registrations | BULK | P2 | 🔴 | consultant lobbyists |
| Lobbyist code-of-conduct disclosures | SCRAPE | P3 | ⬜ | OCL site |

## 5. Political Finance & Donations

| Source | Access | Priority | Status | Notes / next step |
|---|---|---|---|---|
| Contributions database (individual donors) | BULK | P1 | ✅ | Elections Canada ZIP — live in DB (80k loaded, uncap pending) |
| Corporate donation records (historical) | BULK | P2 | 🟡 | same dataset pre-2007 ban; flag historical only |
| Party financial returns | BULK/SCRAPE | P2 | ⬜ | elections.ca financial returns |
| Riding association financial reports | BULK/SCRAPE | P3 | ⬜ | elections.ca |
| Election campaign spending reports | BULK/SCRAPE | P2 | ⬜ | elections.ca |
| Leadership contest finances | BULK/SCRAPE | P3 | ⬜ | elections.ca |
| Third-party advertising spending (EFA) | BULK/SCRAPE | P2 | ⬜ | elections.ca — relevant to sector advocacy |

## 6. Government Spending & Procurement

| Source | Access | Priority | Status | Notes / next step |
|---|---|---|---|---|
| Federal procurement contracts (>$10k) | BULK | P1 | ✅ | open.canada.ca CSV — live in DB |
| Contract award notices / tenders (CanadaBuys) | API | P2 | ⬜ | canadabuys.canada.ca (replaced Buyandsell) — has open data/API |
| Vendor registry | BULK | P2 | ⬜ | within procurement data |
| PSPC spending reports | BULK | P3 | ⬜ | open.canada.ca |
| Departmental expenditures | BULK/API | P3 | ⬜ | GC InfoBase API |
| MP office budgets / expenses | SCRAPE | P3 | ⬜ | ourcommons.ca proactive disclosure |
| Travel & hospitality disclosures | BULK | P2 | ⬜ | open.canada.ca proactive disclosure datasets (confirmed reachable) |
| Grants & contribution programs (recipients) | BULK | P2 | ⬜ | open.canada.ca dataset `432527ab` (confirmed reachable) |
| Crown corporation financial disclosures | SCRAPE | P3 | ⬜ | varies per Crown corp |

## 7. Regulation & Policy Output

| Source | Access | Priority | Status | Notes / next step |
|---|---|---|---|---|
| Federal regulations (SOR/SI) | SCRAPE/BULK | P1 | ⬜ | laws-lois.justice.gc.ca (Justice Laws) — feeds Regulatory Landscape |
| Regulatory Impact Analysis Statements (RIAS) | SCRAPE | P2 | ⬜ | published in Canada Gazette Part II |
| Canada Gazette (Part I proposed / Part II registered) | SCRAPE | P1 | ⬜ | gazette.gc.ca — early-warning on sector regulation |
| Treasury Board directives | SCRAPE | P3 | ⬜ | canada.ca |
| Departmental policy instruments | SCRAPE | P3 | ⬜ | canada.ca |
| Consultation papers + public submissions | SCRAPE | P2 | ⬜ | consultations registry on canada.ca |
| Regulatory amendments tracking | SCRAPE | P2 | ⬜ | Gazette diffing |

## 8. Courts & Legal Interpretation

| Source | Access | Priority | Status | Notes / next step |
|---|---|---|---|---|
| Supreme Court of Canada decisions | SCRAPE | P2 | ⬜ | scc-csc.lexum.com |
| Federal Court rulings | SCRAPE | P2 | ⬜ | decisions.fct-cf.gc.ca |
| Provincial court decisions | SCRAPE | P3 | ⬜ | varies; Phase 2 (provincial) |
| CanLII case database | API+KEY | P2 | ⬜ | CanLII API requires approved key; broad coverage |
| Charter challenge rulings | SCRAPE | P3 | ⬜ | subset of above |
| Administrative tribunals (CRTC, Competition Bureau, IRB, CER) | SCRAPE | P1 | ⬜ | **sector-critical** regulatory-risk signal; per-tribunal sites |

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
| GC InfoBase (budget + performance) | API | P3 | ⬜ | budget/spending context |
| Statistics Canada datasets | API | P2 | ⬜ | StatCan WDS API — sector/economic context |
| Geo data (GeoBase, boundaries) | BULK(GEO) | P3 | ⬜ | riding mapping |
| Environmental registry datasets (IAAC) | API/BULK | P2 | ⬜ | see §11 |

## 11. Environmental, Energy & Industry Regulation

| Source | Access | Priority | Status | Notes / next step |
|---|---|---|---|---|
| Impact assessment project registry (IAAC) | API/BULK | P1* | ⬜ | *P1 for energy/infra/mining deals — project-level political risk |
| Environmental compliance reports | BULK | P2 | ⬜ | ECCC |
| GHG emissions reporting (federal) | BULK | P2 | ⬜ | open.canada.ca |
| National Pollutant Release Inventory (NPRI) | BULK/API | P2 | ⬜ | open data |
| Energy regulation filings (CER) | SCRAPE/API | P1* | ⬜ | Canada Energy Regulator — *P1 for energy sector |
| Mining permits/licences | BULK | P2 | ⬜ | federal/provincial split |
| Fisheries & ocean permits | BULK | P3 | ⬜ | DFO |
| Transport Canada enforcement / TSB | BULK/SCRAPE | P3 | ⬜ | sector-specific |

---

## Strategic read

**Already live (✅):** procurement contracts, individual donations, bills (LEGISinfo), CKAN discovery. That's 4 real feeds powering the report today.

**Fastest high-value wins (clean API/bulk, P1):**
1. **OCL Monthly Communication Reports** via CKAN `a34eb330` — sidesteps the blocked ZIP and unlocks the moat (lobbying contacts + DPOH/revolving-door).
2. **House voting records + Hansard + committee witnesses** via **openparliament.ca** third-party API — one integration covers MP profiles, speeches, and votes cleanly.
3. **Canada Gazette + Justice Laws** for the Regulatory Landscape section (currently inferred only from contracts).
4. **Administrative tribunals** (CRTC, Competition Bureau, CER) — the sharpest sector regulatory-risk signal.

**Scrape-heavy / slower (budget accordingly):** Senate, provincial courts, per-Crown-corp disclosures, org charts, tribunal sites without bulk export.

**Needs a credential:** CanLII API (approval), any X/LinkedIn social access.

**Sector-conditional P1:** IAAC project registry + CER filings become top priority specifically for energy / infrastructure / mining deals.

> Note: access methods marked SCRAPE/API are best-known starting points; each needs a
> reachability probe before committing (same discipline that caught the blocked OCL ZIP
> and the LEGISinfo field names). Don't trust the label until a probe confirms it.
