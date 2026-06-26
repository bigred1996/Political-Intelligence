# Connected Intelligence Audit

Last updated: 2026-06-20 (frontend/route content re-verified 2026-06-21 — still accurate, no drift found)

Canonical working copy (real data + API key):

`~/Documents/Nessus Intelligence` (this repo, cloned from `bigred1996/Political-Intelligence`)

The `/Users/codymcmullen/...` path previously listed here was a stale reference
from when this project lived on a different machine/user account — corrected
2026-06-21.

This audit captures the current connected-intelligence foundation for Nessus. It documents the frontend routes, backend routes, database tables, source types, record pages, search behavior, and internal linking rules now used by the customer-interview prototype.

**Ingestion-layer companion audit:** this document covers the frontend/graph/
record-page layer, which a 2026-06-21 pass confirmed is accurate (all 25 routes
listed below were verified to exist as real files, no discrepancies). The
*data-ingestion* side (connector reliability, incremental fetch, raw storage,
revision history, test coverage) is audited separately in `DATA_CHECKLIST.md`
("Ingestion audit — 2026-06-21") and `DATA_CATALOG.md`, with the machine-readable
per-source registry in `config/data-sources.yaml`. Headline: the record/entity/
graph pages here are in good shape; the connectors feeding them are not yet
incremental, have no revision history, and two (`grants_quarterly`,
`appointments_weekly`) have a live duplicate-accumulation bug that hasn't fired
yet only because they've never been triggered.

## Frontend Routes

| Route | Purpose | Internal navigation status |
|---|---|---|
| `/` | Morning intelligence brief with priority findings, watchlist sectors, actor movement, and review queues | Findings link to internal signal detail pages. |
| `/dashboard` | Operational intelligence dashboard | Live `/api/overview` view with material developments, sector heatmap, regulatory movement, source-stream status, and internal links to findings, evidence records, sectors, sources, and graph explorer. |
| `/signals` | Findings/signals index | Live graph findings from `/api/graph/findings`; finding cards link to `/signals/{slug}` and evidence opens internally. |
| `/signals/[slug]` | Finding detail | Shows interpretation, why it matters, sectors, supporting evidence, connected people/orgs, connected bills/lobbying/regulations/sources, and reports including the finding. Evidence-derived bills and source records preserve `from=finding` context. |
| `/records` | Record explorer/list page | Live `/api/sources/status` record-discovery surface with source profile links and source-scoped search links; no guessed sample record IDs. |
| `/records/[table]/[pk]` | Universal evidence record detail | Reused for contracts, donations, grants, lobbying, registrations, bills, Gazette, tribunals, appointments, Hansard, source records, and public statements via `/records/social_statements/{id}` alias. Shows context, related findings, graph links, players, relations, timeline, and original source as secondary action. |
| `/meetings/[id]` | Meeting/contact detail | Connected internal detail view over lobbying communication records with preserved context, participants, findings, sectors, source groups, timeline, evidence record, and secondary original-source action. |
| `/search` | Plain-English search | Results use internal record detail as the primary action and preserve `from=search&q=...` context. |
| `/watchlists` | Watchlist management | Live `/api/sectors` + `/api/graph/findings` monitoring workspace with internal finding, sector, evidence-record, live-feed, search, and graph links; push alerts remain planned. |
| `/sectors` | Sector list | Links to sector detail pages. |
| `/cross-sector` | Cross-sector convergence | Live `/api/sectors` + `/api/graph/findings` view showing sector-overlap heatmap, cross-sector synthesis, internal finding links, sector links, and supporting evidence records. |
| `/sectors/[slug]` | Sector intelligence | Live sector overview from `/api/sectors/{slug}/overview`; shows risk profile, findings, evidence, connected people, companies, regulators, committee links, source coverage, suggested questions, and preserves `from=sector&sector=...` context into findings, evidence records, people, entities, regulators, and committees. |
| `/entities` | Entity lookup | Live `/api/graph/findings` directory of observed companies/organizations with internal profile, finding, sector, evidence, and search links. |
| `/entities/[canonical]` | Company/organization profile | Live `/api/entities/{name}` profile with shared logo fallback, source coverage, risk scores, cross-source patterns, departments, bills, lobbying/regulatory records, and internal evidence links. |
| `/organizations/[kind]/[name]` | Department/regulator/organization profile | Live `/api/organizations/{kind}/{name}` profile with shared mark fallback, metrics, sectors, findings, source groups, timeline, and internal evidence links. |
| `/committees/[slug]` | Committee profile | Live `/api/parliament/committee/{slug}` profile with shared committee mark fallback, Hansard, bills, lobbying, source records, findings, people, sectors, source groups, timeline, evidence as internal links, and preserved search/sector/finding context. |
| `/explorer` | Evidence graph explorer | Live graph workspace from `/api/graph/findings`; renders findings, actors, sectors, and evidence-record nodes with internal links. |
| `/politicians` | Political player directory | Links to politician pages with image fallbacks and portrait attribution when photos exist. |
| `/politicians/[slug]` | Political figure profile | Live `/api/politicians/{slug}` profile with MP/speaker details, sectors, sponsored bills, Hansard interventions, portrait attribution, and internal bill/speech evidence links. |
| `/senators/[slug]` | Senator profile graceful state | Internal search/graph-backed investigation page for senator references while Senate ingestion is planned; avoids unsourced chamber facts. |
| `/ministers/[slug]` | Minister profile graceful state | Internal search/graph-backed investigation page for minister/portfolio references while richer cabinet ingestion is planned; avoids unsourced portfolio facts. |
| `/briefings` | Reports hub | Live `/api/reports` hub with report status, scores, graceful empty/error states, and internal links to `/briefings/{id}` report detail pages. |
| `/briefings/[id]` | Briefing detail | Internal report view with connected findings, supporting evidence, and secondary original-source actions. |
| `/sources` | Source coverage/status | Live `/api/sources/status` table showing source quality, gaps, freshness, confidence, and internal source-detail links. |
| `/sources/[id]` | Source detail | Internal source profile with normalized coverage, why it matters, affected sectors, related findings, connected records, gaps, timeline, and evidence links. |

## Backend Routes

Core internal-navigation APIs:

| Route | Purpose |
|---|---|
| `/api/overview` | Dashboard findings, sector watchlist, actor movement, source status. |
| `/api/search` | Structured/semantic search with linkable table/pk results. |
| `/api/search/sources` | Search-source coverage counts. |
| `/api/records/{table}/{pk}` | Universal record detail and cross-source entity relations. |
| `/api/graph/findings` | Global deterministic graph findings. |
| `/api/graph/actors` | Actor-focused findings. |
| `/api/graph/actor/{slug}` | Political actor graph. |
| `/api/graph/sector/{slug}` | Sector graph. |
| `/api/graph/record/{table}/{pk}` | Record graph with related findings and relationship strength. |
| `/api/sectors` and `/api/sectors/{slug}/overview` | Sector list and sector overview. |
| `/api/entities/{name}` | Entity profile. |
| `/api/organizations/{kind}/{name}` | Department/regulator/organization profile assembled from existing source records. |
| `/api/parliament/committee/{slug}` | Committee profile assembled from existing Hansard, bills, lobbying, source records, and graph findings. |
| `/api/politicians` and `/api/politicians/{slug}` | Political figure list/detail. |
| `/api/sources/status` | Source coverage, freshness, gaps. |
| `/api/sources/{source_id}` | Source detail assembled from source-status metadata, recent internal records, sectors, and graph findings. |
| `/api/reports`, `/api/reports/{id}`, `/api/reports/by-finding/{slug}`, `/api/report/{id}` | Report list/detail, finding back-links, and export surfaces. |
| `/api/scheduler/*` | Ingestion scheduler status/history/trigger. |

Source-specific APIs remain in place for ingestion/search/stats: contracts, grants, lobbying, OCL registrations, appointments, regulations, parliament, donations/bills through sources, and reports/requests.

## Database Tables and Record Support

| Table | Model | Internal detail URL | Status |
|---|---|---|---|
| `contracts` | `Contract` | `/records/contracts/{id}` | Supported. |
| `donations` | `Donation` | `/records/donations/{id}` | Supported. |
| `grants` | `Grant` | `/records/grants/{id}` | Supported. |
| `lobbying_records` | `LobbyingRecord` | `/records/lobbying/{id}` or alias `/records/lobbying_records/{id}` | Supported via alias. |
| `ocl_registrations` | `OCLRegistration` | `/records/ocl_registrations/{id}` | Supported. |
| `bills` | `Bill` | `/records/bills/{id}` | Supported. |
| `gazette_entries` | `GazetteEntry` | `/records/gazette/{id}` or alias `/records/gazette_entries/{id}` | Supported via alias. |
| `tribunal_decisions` | `TribunalDecision` | `/records/tribunal/{id}` or alias `/records/tribunal_decisions/{id}` | Supported via alias. |
| `appointments` | `Appointment` | `/records/appointments/{id}` | Supported. |
| `hansard_mentions` | `HansardMention` | `/records/hansard_mentions/{id}` | Supported. |
| `source_records` | `SourceRecord` | `/records/source_records/{id}` | Supported as generic breadth/source record. |
| `social_statements` | `SourceRecord` | `/records/social_statements/{id}` or `/records/source_records/{id}` | Supported as a public-statement alias over rows in `source_records`; source profile is `/sources/social_statements`. |
| `politicians` | `Politician` | `/politicians/{slug}` | Dedicated person page. |
| `reports` | `Report` | `/briefings/{id}` and `/api/reports/{id}` surfaces | Internal report detail with graph findings and source references surfaced. |
| `report_requests` | `ReportRequestRow` | Request/admin API only | No primary UI detail page yet. |
| `scheduler_log` | `SchedulerLog` | Scheduler API only | No user-facing diligence detail page needed. |

## Source Types

Live or partial source surfaces currently represented in app/source status:

- Federal contracts
- Political donations
- Bills and legislation
- Canada Gazette
- MP profiles
- Hansard mentions
- Operations breadth records in `source_records` for CER, NPRI, GC News, StatCan, IAAC, Transport, and geospatial/catalogue records
- Government publications & RSS in `source_records` (Goal 9): PMO, Bank of Canada, NRCan, ECCC, ISED, GAC, Transport Canada, Health Canada, Competition Bureau and CRTC news/publications via a generic RSS/Atom/RDF connector (`pipeline/feeds.py`)
- Public statements/social signals in `source_records` under `social_statements` or `public_statements`, with internal detail URLs and a source profile even while ingestion is not active
- Grants and contributions
- Governor in Council appointments
- Lobbying registrations
- Tribunal/regulatory decisions

`DATA_CATALOG.md` remains the broader source universe and ingestion-priority tracker.

## Central Navigation Registry

The frontend registry lives in:

`web/lib/navigation.ts`

It owns:

- supported type labels and plural labels
- canonical table aliases
- source labels
- internal record URLs through `recordHref(table, pk)`, with meeting-like records delegated to `/meetings/{id}`
- evidence URLs through `evidenceHref(ref)`
- entity, sector, person, finding, source, and report URLs
- report URLs through `reportHref(id)` to `/briefings/{id}`
- finding slug generation

Current URL rules:

| Type | URL rule |
|---|---|
| Finding | `/signals/{slugified-title}` |
| Evidence record | `/records/{canonical-table}/{pk}` |
| Meeting/contact | `/meetings/{id}` backed by `/records/lobbying/{id}` |
| Sector | `/sectors/{slug}` |
| Entity/company/org | `/entities/{canonical-or-name}` |
| Department/regulator/org body | `/organizations/{department|regulator|organization}/{name}` |
| Political figure | `/politicians/{slug}` |
| Senator | `/senators/{slug}` |
| Minister | `/ministers/{slug}` |
| Committee | `/committees/{slug}` |
| Report/briefing | `/briefings/{id}` |
| Source | `/sources/{id}` |
| Sources/status | `/sources` |
| Original source | External link only as secondary `View original source` action rendered through `OriginalSourceLink`. |

## Source Detail Logic

`/api/sources/{source_id}` makes source coverage rows clickable internal Nessus objects. It reuses the existing source-status metadata and current tables, samples recent records as `/records/{table}/{pk}` evidence, infers affected sectors from source/evidence text, and links graph findings that cite the same source table. Planned or empty sources still return graceful internal states with known gaps instead of dead links.

`/records` and `/sources` both read `/api/sources/status`. `/records` uses source cards as the primary way into internal source profiles and source-scoped search; it does not fabricate `/records/{table}/1` links. `/sources` shows the same live coverage contract as an operator table with freshness, confidence, and tracked gaps.

`/sources/[id]` shows title/type, normalized coverage data, concise interpretation, why the source matters, affected sectors, related findings, connected evidence records, known gaps, and a timeline. Original external URLs remain on the individual evidence records as secondary actions.

## Record and Graph Linking Logic

`/api/records/{table}/{pk}` resolves supported source tables through the SQL search specs and aliases. It returns:

- normalized title/source/type/date/amount/url; full normalized fields (internal-only columns `id`/`ingested_at`/`canonical_name` hidden); full untruncated `body` text for text-bearing sources; raw source data where available
- resolved entity/canonical name
- **confidence-tiered industry**: entity-roster match → `confirmed`; keyword match (≥2 corroborating hits) → `likely`; otherwise no sector is asserted (cross-government). This kills the prior false positives (a PSPC road contract no longer reads "Aerospace & Defence" off a single "procurement" keyword or the generic buyer name).
- **`signal`**: a calibrated Strong/Moderate/Low signal (replaces the old miscalibrated per-type severity), blended from cross-source footprint, connection volume, dollar materiality, record-type weight, and sector confidence — returned with the drivers that produced it so the score is legible.
- **`assessment`**: the deterministic five-beat reading (`means` / `matters` / `impact` / `strategic_read`) from `pipeline/record_lens.py` — no API calls, instant, identical every load.
- **`people`** — genuinely-linked people only: bill sponsor, Hansard speaker (`spoken_by`), recorded vote participants (`mp_voted`), and the GIC appointee. The old keyword-Hansard sweep (any MP who once said a sector keyword, including procedural names like "The Speaker") was removed as noise.
- **`governing_regulators`** — the sector's federal regulators, surfaced as institutional context separate from "people on this record".
- **cross-source connections** sharing the same canonical entity, plus a `cross_source_signature` distilling the "so what" pattern (lobbied AND won contracts AND donated…), plus per-type `lateral` "records like this" (indexed lookups: same department / body / sponsor) for one-off records with no entity graph.
- sector peers and a chronological timeline of related entity activity.

`/api/graph/record/{table}/{pk}` overlays graph findings and labels the relationship `supported` (direct evidence) or `inferred` (sector-contextual).

**Record detail UI — the adaptive two-column dossier (`web/components/record-dossier.tsx`, shared by the record and meeting pages).** It is built on one editorial spine — *What does it mean? Why does it matter? How does it connect? What is the impact? Strategic assessment* — and adapts to data richness. The left column is the narrative ("tell me"): a verdict-first **Strategic Read** (with the signal's drivers), then an **Analysis** card carrying the *What this means / Why it matters / Impact on {sector}* beats, then any directly-supported findings, then **Full Text** (real `record.body`, never a placeholder), then **Record Details**. The right rail is the evidence ("show me"): **How It Connects** (the cross-source signature + grouped connections on rich records; honest "no cross-source activity" + lateral "records sharing context" on one-offs), **People On This Record** (genuine links only — hidden when there are none), **Who Governs This** (regulators), and an **Activity Timeline**. `OriginalSourceLink` stays the one secondary, explicit, new-tab action.

## Record Browse Logic

`/records` source cards' "Open records" action opens `/records/{source_id}`, a paginated browse of that source's individual rows — staying inside the platform instead of bouncing into `/search`. It's backed by `GET /api/sources/{source_id}/records` (cursor-paginated on `id < cursor`, newest-ingested first, so even the million-row tables like contracts/donations stay an indexed primary-key lookup regardless of page depth). Each row links to `/records/{table}/{pk}?from=records&source={source_id}`, and the record detail page recognizes `from=records` as a return-context the same way it does `from=search`/`from=sector`/`from=finding`.

## Meeting Detail Logic

`/meetings/[id]` is a semantic internal view over `/records/lobbying/{id}` and `/api/graph/record/lobbying/{id}`. The central `recordHref` registry delegates `meetings`, `communications`, and `contacts` aliases to this page instead of the generic record shell. It is now a thin wrapper over the shared `RecordDossier` (`web/components/record-dossier.tsx`): a meeting-specific "Registered Communication" lead card (stating the record marks contact, not proven influence) sits above the same verdict-first dossier the record page uses, so a lobbying communication reads consistently whether reached as a record or a meeting. It preserves `from=search`/`from=sector`/`from=finding` context through every connected link.

## Search Linking Logic

`/search` treats internal links as primary:

- Search title link: `/records/{table}/{pk}?from=search&q={query}`
- Secondary action: `View original source` via `OriginalSourceLink`
- Source labels use the central registry where possible.

Original-source URLs are resolved per `TableSpec.url_fn`. Gazette, tribunal, Hansard, and breadth/source records carry a stored URL; bill records derive the canonical LEGISinfo URL deterministically from `parliament` + `bill_number` (`https://www.parl.ca/legisinfo/en/bill/{parliament}/{bill_number}`) so the prioritized dashboard→finding→bill→original-source flow terminates at the live LEGISinfo page instead of a missing link. Records with no resolvable URL omit the secondary action rather than rendering a dead link.

`/records/{table}/{pk}` reads navigation context and displays a return path for:

- `from=search&q=...`
- `from=sector&sector=...`
- `from=finding&finding=...`

Dashboard/Morning Brief finding cards preserve context with `from=dashboard` or `from=briefing`. Finding-detail supporting-evidence, sector, committee, report, company/entity, and political-figure links append `from=finding&finding=...` before opening `/records/{table}/{pk}`, `/sectors/{slug}`, `/committees/{slug}`, `/briefings/{id}`, `/entities/{name}`, or `/politicians/{slug}`.

When `from=search`, `from=sector`, or `from=finding` context exists, timeline, supporting-evidence, connected-source, related-finding, sector, entity-profile evidence links, finding report/committee links, meeting finding/sector links, committee evidence links, organization finding/source-group links, and politician sector/committee/bill/Hansard links preserve it where practical so an analyst can step through related evidence and still return to the original search, sector, or finding investigation. The prioritized prototype path is now: dashboard finding → finding detail → connected bill/person/company → evidence record → original source as a secondary action; the search path is search result → evidence record → connected entity/person/organization → related records; the sector path is sector → finding or connected bill/person/company/committee → related records.

## Organization Detail Logic

`/api/organizations/{kind}/{name}` turns text-only departments and regulators into clickable internal Nessus objects. It currently aggregates records from existing tables without creating new infrastructure:

- contracts and grants by `owner_org_title`
- Gazette entries by `department`
- tribunal decisions by `body`
- GIC appointments by `organization`
- lobbying communications by `institutions`

`/organizations/[kind]/[name]` shows title/type, summary, why it matters, metrics, affected sectors, related findings, connected records, source groups, timeline, and all evidence links as internal `/records/{table}/{pk}` links. It uses the shared organization/department/regulator fallback mark until official mark URL/source/attribution fields exist.

`/entities/[canonical]` shows a source-backed entity profile from `/api/entities/{name}` with risk scores, source coverage, reports including the entity, connected departments, connected bills, lobbying/regulatory records, supporting evidence, and the shared company fallback logo until official logo URL/source/attribution fields exist.


## Committee Detail Logic

`/api/parliament/committee/{slug}` turns committee references into clickable internal Nessus objects without adding a new ingestion pipeline. It currently searches existing Hansard mentions, bills, lobbying communications, and source records by committee code/name, resolves mentioned political people where possible, infers affected sectors from evidence text, and links matching graph findings.

`/committees/[slug]` shows title/type, summary, why it matters, affected sectors, related findings, connected people, connected records, source groups, and timeline. Evidence opens through `/records/{table}/{pk}`; original-source URLs remain secondary on the evidence records. It uses the shared committee/organization fallback mark until official committee mark URL/source/attribution fields exist.

## Senator and Minister Graceful Detail Logic

`/senators/[slug]` and `/ministers/[slug]` reuse `PlannedPoliticalProfile` rather than inventing static facts. They decode the route slug into a person label, query `/api/search?q={name}&answer=false` for internal matching records, query `/api/graph/findings` for related graph findings, group matched evidence by source type, infer affected sectors only from related findings, and render official-portrait/source-coverage gaps explicitly. Evidence opens through `/records/{table}/{pk}` and original-source URLs remain secondary on the evidence records.

These pages are intentionally marked as graceful states until dedicated Senate/cabinet feeds exist. They keep the analyst inside Polaris and avoid implying committee membership, portfolios, voting, attendance, mandate-letter, or statement coverage that has not been ingested.

## Report Linking Logic

`/api/reports/{id}` now exposes existing report evidence as:

- `graph_findings`: normalized findings included in the report
- `source_references`: normalized internal evidence records used by the report
- `/api/reports/by-finding/{slug}`: reports that include a specific finding title slug
- entity profiles include reports matching their canonical company name as internal `/briefings/{id}` links through `reportHref(id)`

`/briefings/[id]` renders these as:

- `report includes finding` relationship links to `/signals/{slug}`
- supporting evidence links to `/records/{table}/{pk}`
- `View original source` links only as secondary actions

Report detail preserves incoming search, sector, or finding context into connected findings and supporting evidence records.

`/entities/[canonical]` renders matching reports as `report covers entity` direct relationship links through `reportHref(id)` to `/briefings/{id}`.

## Shared Components

| Component | File | Purpose |
|---|---|---|
| `RecordDossier` | `web/components/record-dossier.tsx` | The adaptive two-column record dossier (verdict-first narrative + adaptive evidence rail) shared by the record and meeting pages. |
| `SignalBadge` | `web/components/nessus.tsx` | Calibrated Strong/Moderate/Low signal-strength chip (replaces the old miscalibrated severity badge). |
| `Beat` | `web/components/nessus.tsx` | One labelled narrative beat (What this means / Why it matters / Impact). |
| `AvatarLogo` | `web/components/intelligence.tsx` | Official image when present, otherwise initials or neutral type fallback; accepts image source/attribution metadata. |
| `PartyBadge` | `web/components/intelligence.tsx` | Generated party visual identity fallback for political pages; explicitly notes that official party logos are not stored. |
| `JurisdictionBadge` | `web/components/intelligence.tsx` | Generated jurisdiction symbol fallback for province/territory recognition; explicitly notes that official flags/symbols are not stored. |
| `RelationshipBadge` | `web/components/intelligence.tsx` | Displays `Direct`, `Supported`, or `Inferred`. |
| `RelatedItems` | `web/components/intelligence.tsx` | Reusable typed relationship list. |
| `EvidenceRows` | `web/components/ui.tsx` | Compact internal evidence-link list. |
| `OriginalSourceLink` | `web/components/ui.tsx` | Shared secondary external-source action so original URLs are labelled consistently and never become the primary investigation path. |
| `FindingCard` | `web/components/ui.tsx` | Finding summary card with evidence expansion. |
| `SourceTag`, badges, panels | `web/components/ui.tsx` | Consistent detail-page metadata and graceful states. |

## Relationship Vocabulary

- `finding supported by record`
- `finding supported by source`
- `finding spans sectors`
- `sector finding related to record`
- `record affects sector`
- `record names organization`
- `person connected to finding`
- `person connected to record`
- `person mentioned bill or sector`
- `person mentioned committee`
- `senator mentioned in record`
- `minister mentioned in record`
- `organization registered lobbying activity`
- `meeting supported by record`
- `organization has federal activity`
- `bill affects sector`
- `regulator opened consultation`
- `committee connected to finding`
- `shared entity evidence`
- `report covers entity`

Relationship strength labels are explicit: `direct`, `supported`, or `inferred`. The UI should not imply causation unless a direct evidence reference exists.

## Unsupported or Partial Entity Types

| Entity/type | Current handling | Gap |
|---|---|---|
| Senators | Internal `/senators/{slug}` graceful profile page available for references, backed by search and graph findings where matching records exist. | Needs Senate profile/source ingestion, committee/vote activity, portraits, and source attribution. |
| Ministers/cabinet portfolios | Internal `/ministers/{slug}` graceful profile page available for references, backed by search and graph findings where matching records exist; MP role text may also appear on politician records. | Needs explicit minister portfolio model, mandate/department links, statements, portraits, and source attribution. |
| Committees | Internal `/committees/{slug}` page available from existing Hansard, bill, lobbying, source-record, finding, and resolved-person evidence; uses fallback mark. | Needs richer committee directory, member/witness relationships, Senate committees, and official mark metadata. |
| Meetings | Internal `/meetings/{id}` view available for lobbying communications. | Needs richer meeting/contact semantics if future data separates meetings from communication returns. |
| Departments | Internal `/organizations/department/{name}` page now available when matching records exist. | Needs richer canonical directory, images/marks, and stronger aliases. |
| Regulators | Internal `/organizations/regulator/{name}` page now available when matching records exist. | Needs regulator directory, remit metadata, images/marks, and consultation-specific ingestion. |
| Social posts/public statements | Internal public-statement source profile and `/records/social_statements/{id}` alias are available over `source_records`; labels render as public statements when `source`/`record_type` identifies them. | Need dedicated ingestion, richer speaker/account metadata, platform/source attribution, and relationship extraction. |
| Company/organization logos | Entity pages use `AvatarLogo` initials fallback and explicitly state official logos are not stored. | Need logo source metadata and attribution fields when logos are introduced. |
| Department/regulator marks | Organization pages use `AvatarLogo` department/regulator fallback and explicitly state official marks are not stored. | Need image URL/source/attribution metadata if used. |
| Party logos | Political pages use `PartyBadge` generated party symbols/color fallbacks with explicit non-official-source notes. | Official party logo assets/source metadata still require an asset/source decision. |
| Jurisdiction flags/symbols | Political pages use `JurisdictionBadge` generated province/territory symbols for recognition with explicit non-official-source notes. | Official jurisdiction flags/symbol source metadata still require an asset/source decision. |

## Remaining Gaps

- Enrich first-class regulator/department pages with canonical directories, aliases, official marks, remit metadata, and stronger source coverage.
- Enrich committee pages with canonical member/witness data, stronger aliases, Senate committee coverage, and official marks only where they improve recognition.
- Add report inclusion counts on entity pages and report filters by company/sector.
- Extend media attribution/source metadata beyond MP portraits and generated party/jurisdiction fallbacks to logos, department/regulator marks, official party logos, and official jurisdiction symbols when those assets are introduced.
- Keep non-core investigation context on more internal links beyond search, sector, dashboard, briefing, and finding-to-record paths.
- Expand graph relationships beyond deterministic sector/entity links where evidence exists.
- Replace senator/minister graceful search-backed pages with first-class source-backed profiles when those ingestion feeds are added.
- Extend social/public statement ingestion beyond the internal placeholder source profile.
- Add official source-home links only where they can be labelled as secondary original-source actions.
- Add tests specifically covering navigation URL generation and record graph relationship-strength behavior.
