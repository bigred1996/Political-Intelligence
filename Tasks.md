

Nessus is a Canadian political, regulatory, economic and sector intelligence platform. It connects government records, legislation, lobbying, regulatory activity, projects, economic indicators and news so users can understand how political developments affect sectors, markets and investment decisions.

Some data connectors, database tables, pages and ingestion logic may already exist.

Do not assume this is a greenfield project.

PRIMARY OBJECTIVE

Build or complete the local-first data ingestion system so that relevant Canadian government, political, regulatory, economic, legal, project, environmental and licensed news data flows reliably into Nessus.

Every imported source record must:

1. Be stored with full provenance.
2. Have a viewable page or dynamic application route.
3. Be searchable.
4. Be linked to canonical people, organizations, government bodies, projects, sectors, geographic areas, legislation and other related records.
5. Be refreshed automatically at an appropriate frequency.
6. Retain its original source URL and raw source data.
7. Record when it was first seen, last checked and last changed.

Work with the existing architecture and coding language wherever reasonable. Do not replace working systems merely because another stack might be preferable.

PHASE 1: AUDIT THE EXISTING SYSTEM

Before making major changes, inspect:

- Existing database schema and migrations
- Existing source connectors
- Existing API clients
- Existing scheduled jobs
- Existing data folders
- Existing entity and relationship models
- Existing search implementation
- Existing record detail pages
- Existing environment variables
- Existing Docker or development configuration
- Existing tests
- Any remaining references to Polaris that should now say Nessus

Create a concise audit document at:

docs/data-ingestion-audit.md

For every requested source, classify it as:

- Working
- Working but incomplete
- Present but broken
- Missing
- Blocked by licensing or access
- Requires manual investigation

Document:

- What is already implemented
- What data is currently imported
- Whether incremental updates work
- Known errors
- Missing fields
- Missing relationships
- Whether pages exist
- Whether the connector is covered by tests

Do not delete, duplicate or rewrite a working connector without a clear reason.

SOURCE REGISTRY

Create a machine-readable source registry, preferably:

config/data-sources.yaml

Use the existing project format if an equivalent registry already exists.

Each source must include:

- Stable source ID
- Source name
- Jurisdiction
- Department or publisher
- Category
- Base URL
- API, RSS, Atom, CSV, JSON, XML, SDMX, CKAN, OData, GeoJSON, shapefile, bulk download or approved HTML access
- License
- Terms URL
- Robots URL where applicable
- Whether commercial reuse has been reviewed
- Whether full text may be stored
- Attribution requirements
- Enabled status
- Connector name
- Existing implementation status
- Backfill strategy
- Incremental update strategy
- Check frequency
- Last checked time
- Last successful import
- Last source change
- Cursor, page or checkpoint state
- Rate limit
- Local raw-data path
- Known limitations
- Priority
- Responsible parser
- Health status

A source must not be enabled until its access method and reuse conditions have been documented.

CORE SOURCES TO AUDIT AND COMPLETE

1. Open Government Canada

Use the federal Open Government CKAN API as both:

- A catalogue of government datasets
- A source of individual downloadable resources

Import metadata for relevant federal datasets.

Do not immediately download every resource in the catalogue. First create catalogue records and classify resources by:

- Department
- Subject
- Sector
- Geography
- File format
- Update frequency
- Relevance to Nessus
- Data size
- License
- Last modified date

Create a controlled materialization process that downloads the most relevant resources first.

Relevant topics include:

- Legislation
- Regulation
- Lobbying
- Procurement
- Grants
- Contributions
- Federal spending
- Energy
- Mining
- Natural resources
- Environment
- Infrastructure
- Transportation
- Housing
- Finance
- Banking
- Telecommunications
- Agriculture
- Health regulation
- Immigration
- Trade
- Industry
- Competition
- Indigenous affairs
- Major projects
- Employment
- Economic development

2. House of Commons and Parliament

Audit and complete ingestion for:

- Current and former MPs
- Constituencies
- Political parties
- Parliamentary sessions
- Bills
- Bill stages
- Bill sponsors
- Votes
- Individual MP votes
- Debates and Hansard
- Statements
- Questions
- Committee meetings
- Committee membership
- Committee evidence
- Witnesses
- Committee reports
- Notices
- Journals
- Order Papers
- Parliamentary publications

Support the official JSON and XML formats where available.

Do not create duplicate English and French records. Model them as language variants of the same canonical record.

3. Elections Canada

Import where available and legally permitted:

- Electoral districts
- Election results
- Candidates
- Registered parties
- Registered associations
- Political financing
- Contributions
- Financial returns
- Leadership contests
- Nomination contests
- Third-party reporting
- Regulated fundraising events
- By-elections
- Voter turnout
- Historical election data

Normal schedule: weekly.

During a federal election or by-election period: daily or more frequently when official data changes.

4. Office of the Commissioner of Lobbying

Audit and complete:

- Lobbying registrations
- Registration versions
- Consultant lobbyists
- In-house organizations
- In-house corporations
- Clients
- Parent companies
- Subsidiaries
- Government institutions
- Subject matters
- Communication techniques
- Government funding disclosures
- Monthly communication reports
- Designated public office holders
- Communication dates
- Registrant information

Preserve historical registration versions rather than overwriting them.

Connect lobbying records to:

- Companies
- Associations
- Lobbying firms
- Lobbyists
- Government departments
- Ministers
- MPs
- Public office holders
- Policy topics
- Bills
- Regulations
- Projects
- Sectors
- News stories

Check for new or changed data daily.

Run a more complete reconciliation after the monthly communication-report deadline.

5. Statistics Canada

Support the Web Data Service and SDMX services where appropriate.

Do not ingest every StatCan series immediately.

Start with indicators relevant to sector and political intelligence:

- GDP
- GDP by industry
- CPI
- Employment
- Unemployment
- Wages
- Labour productivity
- Business investment
- Capital expenditure
- International trade
- Imports and exports
- Commodity trade
- Population
- Immigration
- Housing construction
- Building permits
- Industrial production
- Manufacturing
- Energy production
- Mining production
- Government finances
- Corporate profits
- Bankruptcy and insolvency indicators
- Regional and provincial economic indicators

Create:

- Economic series records
- Observation records
- Release records
- Revision history
- Geography records
- Industry classification records
- Unit and seasonal-adjustment metadata

Check release metadata every business day.

Only update individual series when their source data changes.

6. Impact Assessment Agency of Canada

Import:

- Projects
- Project reference numbers
- Proponents
- Project descriptions
- Project status
- Assessment type
- Responsible authorities
- Locations
- Coordinates
- Provinces and territories
- Indigenous communities named in public records
- Public notices
- Comment periods
- Documents
- Decisions
- Conditions
- Ministerial decisions
- Timelines
- Project updates

Connect projects to:

- Proponents
- Parent companies
- Regulators
- Geographic areas
- Indigenous communities
- Commodities
- Infrastructure types
- Sectors
- Environmental records
- Government announcements
- News coverage

Check active projects daily.

Check inactive or completed projects weekly.

7. Canada Energy Regulator

Import legally available structured data and downloadable datasets covering:

- Applications
- Hearings
- Decisions
- Regulatory documents
- Pipelines
- Pipeline operators
- Incidents
- Project conditions
- Energy production
- Energy demand
- Imports
- Exports
- Commodity flows
- Energy prices
- Provincial energy profiles
- Energy outlooks
- Market snapshots
- Safety and environmental data
- News and publications

Do not scrape regulatory-document systems if automated access is not permitted. Mark unavailable sources as blocked and document the required permission or alternative official dataset.

Check regulatory notices and active proceedings daily.

Check analytical datasets weekly or based on their release schedule.

8. National Pollutant Release Inventory

Import:

- Facilities
- Facility operators
- Parent companies
- NAICS industries
- Locations
- Coordinates
- Pollutants
- Releases to air
- Releases to water
- Releases to land
- Disposals
- Transfers
- Recycling
- Reporting year
- Reporting status
- Pollution-prevention information

Connect facilities to:

- Companies
- Projects
- Municipalities
- Provinces
- Federal ridings
- Sectors
- Nearby regulated assets
- IAAC projects
- CER projects
- Enforcement or regulatory records

Use bulk files where available.

Check catalogue metadata weekly.

Download changed annual or bulk datasets only when their metadata or checksum changes.

9. Transport Canada

Identify and integrate relevant official datasets concerning:

- Rail
- Marine
- Aviation
- Road transportation
- Dangerous-goods incidents
- Transportation infrastructure
- Ports
- Airports
- Rail crossings
- Vehicle recalls
- Safety notices
- Enforcement
- Transportation statistics
- Infrastructure projects

Use official APIs or downloadable resources where available.

10. Federal spending and proactive disclosure

Import:

- Contracts
- Contract amendments
- Grants
- Contributions
- Travel
- Hospitality
- Government spending
- Departmental plans
- Departmental results
- Public Accounts
- Authorities
- Expenditures
- Programs
- Full-time-equivalent counts
- Transfer payments
- Recipient organizations

Connect recipients and suppliers to canonical organizations.

Check current disclosure files weekly.

Check active procurement opportunities daily.

11. Supreme Court of Canada and legal data

Prefer first-party court sources for Supreme Court records.

Import:

- Cases
- Docket numbers
- Parties
- Counsel
- Judges
- Hearing dates
- Leave decisions
- Appeal decisions
- Reasons
- Citations
- Case summaries
- Referenced legislation
- Referenced cases

CanLII must be permission-gated.

Do not perform bulk scraping of CanLII unless the terms, API agreement or written authorization clearly permit the intended commercial use.

Until permission is confirmed:

- Store CanLII links and citations only
- Use official court sources where possible
- Mark the CanLII connector as blocked or limited
- Do not mirror full decisions from CanLII
- Do not circumvent technical restrictions

Account for publication bans, redactions and corrected judgments.

12. Federal geospatial data

Audit:

- NRCan
- GeoGratis
- GeoDiscover
- Open Maps
- Administrative boundaries
- Federal electoral districts
- Resource projects
- Mines
- Energy infrastructure
- Transportation infrastructure
- Indigenous lands and public boundary datasets
- Environmental areas
- Watersheds
- Census geographies

Support:

- GeoJSON
- Shapefile
- KML
- WMS
- WFS
- ESRI REST
- CSV coordinates

Store geospatial files locally when necessary, but do not duplicate large unchanged datasets on every run.

13. Government of Canada news and publications

Create a reusable Canada.ca news connector rather than writing a separate scraper for every department.

Capture:

- Headline
- Summary
- Department
- Minister
- Content type
- Publication date
- Updated date
- Location
- Original URL
- Language
- Named entities
- Topics
- Related documents

Relevant content types include:

- News releases
- Statements
- Speeches
- Readouts
- Backgrounders
- Media advisories
- Publications
- Reports
- Consultations
- Regulatory announcements

Use official RSS or structured data where available.

Prioritize feeds from:

- Prime Minister’s Office
- Department of Finance
- Global Affairs Canada
- Natural Resources Canada
- Environment and Climate Change Canada
- Innovation, Science and Economic Development Canada
- Transport Canada
- Health Canada
- Public Safety Canada
- Immigration, Refugees and Citizenship Canada
- Canada Revenue Agency
- Competition Bureau
- Canada Energy Regulator
- Impact Assessment Agency
- Canadian Nuclear Safety Commission
- Canadian Radio-television and Telecommunications Commission
- Office of the Superintendent of Financial Institutions

ADDITIONAL HIGH-VALUE SOURCES TO ADD

Add these to the source registry and implement them in priority order after auditing existing work.

Regulation and policy:

- Canada Gazette Parts I, II and III
- Proposed regulations
- Final regulations
- Public notices
- Regulatory consultations
- Forward Regulatory Plans
- Orders in Council
- Governor in Council appointments
- Consulting with Canadians
- Regulatory impact analysis statements
- Treasury Board policy publications
- Departmental plans and departmental results reports

Government organization and spending:

- GC InfoBase
- Inventory of Federal Organizations and Interests
- Public Accounts
- Main Estimates
- Supplementary Estimates
- Departmental expenditures
- Programs
- Results indicators
- Grants and contributions
- CanadaBuys tender notices
- CanadaBuys contract awards

Economic and financial:

- Bank of Canada data services
- Bank of Canada rates, exchange rates and market data
- Bank of Canada announcements and RSS
- Department of Finance releases and publications
- Fiscal Monitor
- Federal budgets and economic statements
- OSFI financial data
- OSFI guidance and announcements
- CMHC housing data
- Housing starts
- Rental markets
- Mortgage and debt data
- Canadian international trade data
- OECD data for international comparisons
- World Bank data for international comparisons
- IMF data where licensing permits

Industry and regulatory:

- Competition Bureau decisions, enforcement and guidance
- CRTC decisions, consultations and notices
- Canadian Nuclear Safety Commission proceedings and decisions
- Canadian Food Inspection Agency recalls and notices
- Health Canada recalls, advisories and compliance notices
- Fisheries and Oceans notices and project data
- Agriculture and Agri-Food Canada market information
- Global Affairs sanctions, trade notices and treaty information
- Canadian International Trade Tribunal decisions
- Canadian Transportation Agency decisions
- Corporations Canada public information where automated use is allowed
- Patents, trademarks and intellectual-property datasets where relevant
- Natural Resources Canada mining, forestry and critical-minerals data

Future provincial expansion:

Create source-registry placeholders for:

- Provincial legislatures
- Provincial gazettes
- Provincial lobbying registries
- Provincial procurement
- Provincial budgets
- Provincial regulators
- Provincial energy boards
- Provincial securities regulators
- Provincial impact-assessment registries

Do not implement all provincial sources during this task unless existing code already supports them.

NEWS AND RSS POLICY

News ingestion must be legally conservative.

Automatically enable only:

1. Official government RSS or Atom feeds.
2. Publisher-provided feeds whose terms permit Nessus’s intended use.
3. Paid or licensed news APIs covered by an active agreement.
4. Feeds explicitly approved in the source registry.

Starting approved or reviewable sources should include:

- Global News official RSS feeds, especially Canada, Politics, Money and Environment
- Government of Canada departmental RSS feeds
- Canada Gazette RSS
- Bank of Canada RSS
- Prime Minister’s Office RSS
- Global Affairs Canada RSS
- Department of Finance RSS
- Natural Resources Canada RSS
- Relevant regulator RSS feeds

Add the following as disabled candidates pending terms or licensing review:

- CBC News and Radio-Canada
- CTV News
- Financial Post
- National Post
- The Globe and Mail
- Toronto Star
- La Presse
- Le Devoir
- The Logic
- The Narwhal
- Canadian Press
- iPolitics
- The Hill Times
- Policy Options
- Business in Vancouver
- Regional business publications
- Energy and mining trade publications

Also evaluate licensed API options such as:

- Canadian Press licensing
- Factiva or Dow Jones
- LexisNexis
- Meltwater
- Event Registry or NewsAPI.ai
- Other vendors with clear Canadian coverage and commercial terms

Do not activate an API simply because a developer key is available. Review commercial storage, display, caching and redistribution rights first.

For unlicensed news and RSS:

Store only:

- Headline
- Publisher
- Author where supplied
- Publication timestamp
- Short publisher-supplied description
- Canonical URL
- Image URL only where reuse is permitted
- Feed tags
- Extracted named entities
- Nessus-generated classification
- Nessus-generated summary only where legally appropriate

Do not store or display full copyrighted article text unless licensed.

Do not bypass paywalls.

Do not make unauthorized copies of article images.

Always link users to the original publication.

INGESTION ARCHITECTURE

Create a shared connector interface.

Each connector should implement equivalents of:

- discover()
- backfill()
- fetch_incremental()
- normalize()
- validate()
- persist()
- link_entities()
- checkpoint()
- health_check()

Adapt these names to the existing codebase.

Connectors must be:

- Idempotent
- Restartable
- Paginated
- Rate-limited
- Observable
- Testable
- Capable of resuming from checkpoints
- Resistant to duplicate records
- Able to detect updated and deleted source records

Support:

- ETag
- Last-Modified
- Conditional requests
- Source cursors
- Updated-since parameters
- Checksums
- Content hashes
- Retry with exponential backoff
- Jitter
- Timeout handling
- Circuit breaking
- Schema-change detection

Do not silently ignore errors.

LOCAL STORAGE

Use the existing database if suitable.

If no suitable local database exists, prefer a local PostgreSQL instance, potentially through Docker. Add PostGIS if geospatial querying is required.

Do not introduce a graph database yet unless one is already in use. Represent the graph through entity and relationship tables that can later be exported to a graph database.

Store immutable raw files on the local hard drive.

Suggested structure:

data/
  raw/
    [source_id]/
      [year]/
        [month]/
          [day]/
            [run_id]/
  normalized/
  documents/
  geospatial/
  indexes/
  checkpoints/
  quarantine/
  exports/
  logs/

Raw source files must never be silently modified.

For large text or structured files:

- Compress older raw files
- Avoid keeping identical duplicates
- Record checksums
- Maintain references to the original import run
- Keep enough information to reproduce a normalized record

Do not store large binary files directly in database rows unless the existing architecture requires it.

CANONICAL DATA MODEL

Use or adapt the existing data model.

At minimum, support:

Source
SourceRun
SourceRecord
SourceRecordRevision
Document
Entity
EntityAlias
Relationship
RelationshipEvidence
Event
EconomicSeries
EconomicObservation
Geography
Sector
Topic
ImportError
ImportCheckpoint

SourceRecord should include:

- Internal ID
- Source ID
- External source ID
- Record type
- Title
- Summary
- Language
- Publication date
- Effective date
- Updated date
- First seen date
- Last seen date
- Last changed date
- Original URL
- Raw-data path
- Content hash
- Source metadata
- Normalized metadata
- Status
- Current revision
- Attribution
- License information

Use a stable uniqueness rule such as:

source_id + external_id + record_type

Do not rely on titles as unique identifiers.

CANONICAL ENTITY TYPES

Support at least:

- Person
- Organization
- Company
- Association
- Lobbying firm
- Government department
- Government agency
- Regulator
- Political party
- Electoral district
- Committee
- Bill
- Regulation
- Act
- Policy
- Program
- Consultation
- Government announcement
- Lobbying registration
- Lobbying communication
- Parliamentary debate
- Committee meeting
- Vote
- Contract
- Grant
- Contribution
- Procurement opportunity
- Project
- Facility
- Infrastructure asset
- Court case
- Court decision
- Economic indicator
- Economic release
- Dataset
- Document
- News article
- Geographic location
- Sector
- Industry
- Commodity
- Topic

RELATIONSHIP MODEL

Relationships must be explicit records, not unexplained JSON embedded inside entities.

Each relationship should include:

- From entity
- Relationship type
- To entity
- Direction
- Valid-from date
- Valid-to date
- First observed date
- Last observed date
- Source record
- Relationship evidence
- Match method
- Confidence score
- Review status
- Created date
- Updated date

Example relationship types:

- sponsored_by
- member_of
- chaired_by
- voted_for
- voted_against
- abstained_on
- spoke_about
- appeared_before
- employed_by
- represented_by
- lobbied
- communicated_with
- regulates
- regulated_by
- owns
- subsidiary_of
- parent_of
- operates
- proposed
- funds
- funded_by
- awarded_to
- located_in
- affects
- concerns
- implements
- amends
- cites
- mentioned_in
- reported_by
- published_by
- related_to
- competes_with
- supplies
- consulted_on
- subject_to_assessment
- associated_with_sector

ENTITY RESOLUTION

Build conservative entity resolution.

Use:

- Exact identifiers
- Government organization IDs
- Business numbers only where public and appropriate
- Lobby registry organization identifiers
- Parliamentary member identifiers
- Electoral district identifiers
- Project reference numbers
- Court citations
- Bill numbers combined with parliamentary session
- Normalized names
- Known aliases
- Parent and subsidiary data
- Postal addresses
- Domains
- Geographic coordinates
- Dates and contextual evidence

Do not automatically merge entities solely because their normalized names match.

Use confidence levels:

- 1.00: shared authoritative identifier
- 0.90 to 0.99: very strong deterministic match
- 0.75 to 0.89: probable match requiring supporting evidence
- Below 0.75: suggestion or manual-review queue

Maintain a manual merge and split mechanism.

Every inferred relationship must retain evidence explaining why it exists.

BILINGUAL DATA

Treat English and French versions as language variants, not separate real-world entities.

Store:

- Original language
- Alternate-language title
- Alternate-language summary
- Alternate-language URL
- Shared canonical entity or record ID

Do not machine-translate official titles when an official translation exists.

RECORD AND ENTITY PAGES

Every source record needs a dynamic, addressable page.

Do not generate millions of static files.

Use routes similar to:

/records/[source]/[external-id]
/entities/[entity-type]/[entity-id]
/sources/[source-id]
/datasets/[dataset-id]
/projects/[project-id]
/bills/[bill-id]
/companies/[company-id]

Adapt routes to the existing application.

A source-record page should show:

- Title
- Record type
- Source
- Original source link
- Attribution
- Publication and update dates
- Current status
- Summary
- Structured fields
- Related entities
- Related records
- Source documents
- Record revisions
- Raw import information
- Last synchronization time

An entity page should aggregate:

- Canonical name
- Aliases
- Entity type
- Description
- Identifiers
- Parent or subsidiary relationships
- Sector classifications
- Geographic exposure
- Related lobbying
- Related bills and regulations
- Related projects
- Related contracts and grants
- Related parliamentary mentions
- Related court decisions
- Related government announcements
- Related news
- Timeline
- Relationship graph
- Source provenance

Create a data-source administration page showing:

- Source status
- Last check
- Last success
- Last failure
- Records imported
- Records updated
- Errors
- Current checkpoint
- Next scheduled check
- License status
- Connector health

SCHEDULING

Use the project’s existing scheduler where possible.

Otherwise use an appropriate local scheduler such as cron, APScheduler, a worker queue or the framework’s existing job system.

Recommended default checks:

Every 2 to 6 hours:

- Approved news RSS
- Government news feeds
- Active parliamentary publications when Parliament is sitting
- Active major-project updates
- CanadaBuys active tenders

Daily:

- Bills and bill stages
- Votes
- Hansard
- Committee activity
- Lobbying updates
- Canada Gazette feed checks
- Government announcements
- CER active proceedings and notices
- IAAC active projects
- Court decisions
- Regulatory notices
- Bank of Canada announcements

Every business day:

- Statistics Canada release metadata
- Bank of Canada economic series
- Major financial-regulator announcements

Weekly:

- Elections Canada outside election periods
- Proactive disclosure
- Contracts, grants and contributions
- Transport Canada datasets
- Open Government catalogue reconciliation
- Geospatial metadata
- Inactive IAAC and CER projects
- Legal-source reconciliation
- OSFI datasets
- CMHC release checks where no release calendar is available

Monthly or release-driven:

- Large economic datasets
- Housing datasets
- Public Accounts and expenditure datasets
- NPRI bulk data
- Large geospatial files
- Annual facility datasets

Schedules must be configurable in the source registry.

Prefer release-driven checks, ETags, Last-Modified headers and source metadata over unnecessary full downloads.

BACKFILL AND INCREMENTAL IMPORTS

Separate initial backfills from ongoing incremental jobs.

All connectors must support:

- Date-range backfills
- Source-specific backfills
- Dry runs
- Limited test imports
- Resume after interruption
- Reprocessing normalized data without downloading raw data again
- Rebuilding relationships without refetching records

Provide CLI or equivalent commands such as:

nessus data sources
nessus data audit
nessus data backfill [source]
nessus data sync [source]
nessus data sync-all
nessus data health
nessus data retry-failures
nessus data rebuild-links
nessus data reprocess [source]
nessus data validate

Adapt naming to the existing application.

CHANGE TRACKING

Do not overwrite meaningful source changes.

For changed records:

- Save a new revision
- Calculate field-level differences
- Record when the change was detected
- Preserve the previous revision
- Update the current record
- Generate timeline events for meaningful changes

Examples:

- Bill stage changed
- Project status changed
- Lobbying registration amended
- New government institution added to a registration
- Contract value changed
- Regulation published
- Economic observation revised
- Court judgment corrected

SEARCH

Ensure records are searchable by:

- Title
- Full permitted text
- Summary
- Person
- Organization
- Department
- Bill number
- Regulation
- Project
- Sector
- Geography
- Date
- Source
- Record type
- Keyword
- Industry code
- Commodity
- Lobbying subject
- Court citation

Use the existing search service if present.

Do not introduce a second search stack unless necessary.

DATA QUALITY

Add validation for:

- Missing required identifiers
- Invalid dates
- Broken source URLs
- Duplicate records
- Unexpected language variants
- Invalid coordinates
- Unrecognized enum values
- Schema changes
- Empty bulk files
- Sudden record-count changes
- Source responses replaced by login pages or error pages

Quarantine invalid records instead of discarding them.

OBSERVABILITY

Each run should record:

- Start and finish time
- Connector version
- Source
- Request count
- Response status counts
- Bytes downloaded
- Records discovered
- Records created
- Records updated
- Records unchanged
- Records rejected
- Relationships created
- Errors
- Retry count
- Checkpoint
- Duration

Create clear logs and a human-readable failure report.

TESTING

Add:

- Unit tests for normalization
- Connector tests with saved fixtures
- Idempotency tests
- Duplicate-prevention tests
- Entity-resolution tests
- Relationship-evidence tests
- Page tests
- Migration tests
- Scheduler tests
- Bilingual-record tests

Do not make live third-party requests during normal unit tests.

Save small, legally permitted source fixtures.

IMPLEMENTATION PRIORITY

After the audit, implement in this order unless working code makes a different order more efficient:

Priority 1:

- Repair existing broken connectors
- Source registry
- Shared connector interface
- Checkpointing
- Raw storage
- Import logs
- Record pages
- Entity pages

Priority 2:

- Parliament
- Lobby Canada
- Government of Canada news
- Canada Gazette
- Open Government catalogue
- Statistics Canada
- Bank of Canada

Priority 3:

- IAAC
- CER
- CanadaBuys
- Proactive disclosure
- GC InfoBase
- NPRI

Priority 4:

- Elections Canada
- Transport Canada
- NRCan geospatial data
- OSFI
- CMHC
- Supreme Court official data

Priority 5:

- Approved news RSS
- Licensed news API
- Remaining regulators
- Provincial source placeholders

FIRST WORKING MILESTONE

Deliver a functioning local pipeline that proves the complete flow:

source
to raw storage
to normalized record
to canonical entity
to relationship
to searchable page
to scheduled incremental update

The milestone should include at least:

- One parliamentary source
- Lobby Canada
- Government news
- Canada Gazette
- One economic source
- One project or regulatory source
- One approved publisher RSS feed

Demonstrate connections such as:

- Company to lobbying registration
- Lobbying registration to department
- Department to government announcement
- Announcement to bill or regulation
- Project to proponent
- Project to geographic area
- Company to contract or grant
- Economic indicator to sector
- News story to company, project or policy
- MP to bill, vote, speech and committee

EXPECTED OUTPUT

Do not only return an architecture proposal.

Inspect the repository and begin implementing the system.

Produce:

1. docs/data-ingestion-audit.md
2. docs/data-architecture.md
3. docs/source-licensing.md
4. config/data-sources.yaml or the project equivalent
5. Database migrations
6. Shared connector framework
7. Repaired existing connectors
8. Missing high-priority connectors
9. Scheduled incremental jobs
10. Raw local storage structure
11. Record and entity pages
12. Data-source health page
13. Tests
14. Setup and operating instructions
15. A concise list of blocked sources and what permission is required

Keep changes incremental.

Reuse working code.

Do not hide failures.

Do not invent undocumented APIs.

Do not scrape a source when an official API, RSS feed or bulk download exists.

Do not ingest copyrighted full-text news without permission.

Do not merge uncertain entities without preserving confidence and evidence.

Begin by auditing the existing Nessus repository, then implement the highest-priority missing or broken pieces.
```

[1]: https://open.canada.ca/data/en/dataset/2d90548d-50ef-4802-91f8-c59c5cf68251?utm_source=chatgpt.com "Open Government API - Open Government Portal - Canada.ca"
[2]: https://gazette.gc.ca/rss/sc-rb-eng.html?utm_source=chatgpt.com "Receive updates by RSS feed"
[3]: https://globalnews.ca/pages/feeds/?utm_source=chatgpt.com "Global News RSS feeds"


