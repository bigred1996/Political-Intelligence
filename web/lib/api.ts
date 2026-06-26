export { recordHref } from "@/lib/navigation";

// Typed client for the Nessus FastAPI backend. All calls go through relative
// /api paths, which next.config rewrites proxy to the backend (same-origin in dev).

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { cache: "no-store", ...init });
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText} — ${path}`);
  }
  return res.json() as Promise<T>;
}

// ── Formatting helpers ────────────────────────────────────────────────
export function money(n: number | null | undefined): string {
  if (!n) return "$0";
  if (n >= 1_000_000_000) return `$${(n / 1_000_000_000).toFixed(1)}B`;
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(0)}K`;
  return `$${Math.round(n).toLocaleString()}`;
}

export function moneyFull(n: number | null | undefined): string {
  return `$${Math.round(n ?? 0).toLocaleString()}`;
}

export function num(n: number | null | undefined): string {
  return (n ?? 0).toLocaleString();
}

export type RiskBand = "low" | "medium" | "high";
export function riskBand(score: number): RiskBand {
  return score >= 7 ? "high" : score >= 4 ? "medium" : "low";
}
export function riskColorVar(score: number): string {
  const b = riskBand(score);
  return b === "high" ? "var(--color-risk-high)" : b === "medium" ? "var(--color-risk-med)" : "var(--color-risk-low)";
}

// ── Response types ────────────────────────────────────────────────────
export interface SectorSummary {
  slug: string;
  name: string;
  blurb: string;
  description?: string;
  status?: string;
  parent?: string | null;
  subsectors?: string[];
  topics?: string[];
  associated_topics?: string[];
  organizations?: string[];
  associated_organizations?: string[];
  departments?: string[];
  associated_government_departments?: string[];
  associated_regulators?: string[];
  keywords?: string[];
  associated_keywords?: string[];
  enabled?: boolean;
  display_priority?: number;
  entity_count: number;
  regulators: string[];
}
export interface Province { code: string; name: string }
export interface SectorsResponse {
  count: number;
  sectors: SectorSummary[];
  provinces: Province[];
}

export interface Scores {
  regulatory_risk: number;
  policy_volatility: number;
  election_sensitivity: number;
  lobbying_intensity: number;
  overall: number;
  drivers: Record<string, string>;
}
export interface Connection {
  title: string;
  detail: string;
  sources: string[];
  severity: "high" | "elevated" | "watch";
  references?: EvidenceRef[];
}
export interface SignalMetric {
  label: string;
  value: number;
  format?: "money";
}
export interface SectorSignal {
  theme: string;
  title: string;
  summary: string;
  severity: "high" | "elevated" | "watch";
  why: string;
  metrics: SignalMetric[];
  sources: string[];
  references: EvidenceRef[];
}
export interface EvidenceRef {
  table: string;
  id: number;
  pk?: number;
  source: string;
  title: string;
  date?: string | null;
  url?: string | null;
  record_type?: string | null;
  entity?: string | null;
  amount?: number | null;
}
export interface SourceRecordsPage {
  id: string;
  label: string;
  table: string;
  total_rows: number;
  approximate: boolean;
  records: EvidenceRef[];
  next_cursor: number | null;
  has_more: boolean;
}
export interface MovementWindow {
  window_days: 7 | 30 | 90;
  status: "changed" | "unchanged" | "insufficient_history";
  direction: "increasing" | "decreasing" | "stable" | "unclear";
  current?: number | null;
  previous?: number | null;
  delta?: number | null;
  note: string;
}
export interface IntelligenceEvidence {
  source_name: string;
  source_type: string;
  title: string;
  publication_date?: string | null;
  ingestion_date?: string | null;
  coverage_status: "strong" | "partial" | "weak" | "unknown";
  confidence: "low" | "medium" | "high";
  table: string;
  pk: number | string;
  internal_url: string;
  external_url?: string | null;
}
export interface IntelligenceFinding {
  title: string;
  concise_summary: string;
  why_it_matters: string;
  primary_sector: { slug: string; name: string } | null;
  related_sectors: { slug: string; name: string }[];
  signal_type: string;
  risk_direction: "increasing" | "decreasing" | "stable" | "unclear";
  risk_level: "low" | "moderate" | "elevated" | "high" | "unknown" | "insufficient evidence";
  confidence: "low" | "medium" | "high";
  source_coverage: "strong" | "partial" | "weak" | "unknown";
  recency: "fresh" | "aging" | "stale";
  interpretation_type: "observed" | "inferred" | "speculative";
  evidence_references: IntelligenceEvidence[];
  related_records: EvidenceRef[];
  related_people?: Record<string, unknown>[];
  related_organizations?: Record<string, unknown>[];
  related_bills?: Record<string, unknown>[];
  related_committees?: Record<string, unknown>[];
  related_lobbying_activity?: Record<string, unknown>[];
  related_regulatory_events?: Record<string, unknown>[];
  suggested_questions: string[];
}
export interface FindingMetric {
  label: string;
  value?: number | string | null;
  format?: string | null;
}
export interface GraphFinding {
  title: string;
  summary: string;
  severity: "high" | "elevated" | "watch" | "low";
  type: string;
  sector?: { slug: string; name: string } | null;
  related_sectors: { slug: string; name: string }[];
  actors: Record<string, unknown>[];
  references: EvidenceRef[];
  metrics: FindingMetric[];
  confidence: string;
  relationship_strength?: "direct" | "supported" | "inferred";
}
export interface EvidenceGraphResponse {
  sector?: Record<string, unknown> | null;
  actor?: Record<string, unknown> | null;
  record?: Record<string, unknown> | null;
  industry?: { slug?: string; name?: string; blurb?: string; matched_by?: string } | null;
  entity?: { canonical?: string | null; name?: string | null } | null;
  findings: GraphFinding[];
  nodes: { id: string; type: string; label: string; meta?: Record<string, unknown> }[];
  edges: { from: string; to: string; type: string; strength?: "direct" | "supported" | "inferred" }[];
  relations: Record<string, unknown>;
}
export interface FindingsResponse {
  count: number;
  findings: GraphFinding[];
}
export interface CommitteeProfile {
  slug: string;
  name: string;
  chamber: string;
  summary: string;
  why_it_matters: string;
  affected_sectors: { slug: string; name: string }[];
  related_findings: GraphFinding[];
  connected_people: Record<string, unknown>[];
  connected_organizations: Record<string, unknown>[];
  connected_records: EvidenceRef[];
  groups: { table: string; label: string; count: number; records: EvidenceRef[]; partial: boolean }[];
  timeline: EvidenceRef[];
}
export interface OrganizationProfile {
  kind: "department" | "regulator" | "organization" | string;
  name: string;
  title: string;
  summary: string;
  why_it_matters: string;
  metrics: { label: string; value: number | string }[];
  affected_sectors: { slug: string; name: string }[];
  related_findings: GraphFinding[];
  connected_people: Record<string, unknown>[];
  connected_organizations: Record<string, unknown>[];
  connected_records: EvidenceRef[];
  groups: { table: string; source: string; label: string; count: number; records: EvidenceRef[]; partial: boolean }[];
  timeline: EvidenceRef[];
}
export interface SourceCoverageItem {
  id: string;
  label: string;
  status: "live" | "partial" | "empty" | "planned";
  rows: number;
  row_count_method?: "exact" | "max_id" | "planned" | "unavailable";
  source_id?: string | null;
  sector_rows?: number;
  sector_status?: "live" | "partial" | "empty" | "planned" | "no_sector_hits";
  global_rows?: number;
  global_status?: "live" | "partial" | "empty" | "planned";
  freshness?: "current" | "stale" | "unknown" | "missing" | "planned";
  confidence?: "high" | "medium" | "low" | "planned";
  known_gaps?: string[];
  latest_record_date?: string | null;
  table?: string | null;
  approximate?: boolean;
  description?: string;
}
export interface SourceDetail {
  id: string;
  label: string;
  type: string;
  status: string;
  freshness: string;
  confidence: string;
  summary: string;
  why_it_matters: string;
  important_data: Record<string, unknown>;
  affected_sectors: { slug: string; name: string }[];
  related_findings: GraphFinding[];
  connected_people: Record<string, unknown>[];
  connected_organizations: Record<string, unknown>[];
  connected_records: EvidenceRef[];
  groups: { table: string; label: string; count: number; records: EvidenceRef[]; partial: boolean }[];
  timeline: EvidenceRef[];
  known_gaps: string[];
  original_source_url?: string | null;
}
export interface SourceStatusResponse {
  sources: SourceCoverageItem[];
  counts: Record<string, number>;
  breadth_sources: { source: string; rows: number; min_date: string | null; max_date: string | null; status: string }[];
  summary: { live: number; partial: number; empty: number; planned: number };
  quality?: {
    approximate_sources: string[];
    stale_sources: string[];
    unknown_freshness_sources: string[];
    empty_sources: string[];
    planned_sources: string[];
    explicit_gaps: { id: string; label: string; gaps: string[] }[];
    confidence: "high" | "medium" | "low";
  };
}
export interface ProvinceRow { code: string; province: string; records: number; amount: number }
export interface TrendPoint { year: string; value?: number; count?: number }
export interface Trends { contracts: TrendPoint[]; lobbying: TrendPoint[]; donations: TrendPoint[] }
export interface SectorOverview {
  sector: SectorSummary;
  province: string | null;
  province_name: string | null;
  scores: Scores;
  risk_band: "low" | "moderate" | "elevated" | "high" | "unknown" | "insufficient evidence";
  movement: MovementWindow[];
  connections: Connection[];
  signals: SectorSignal[];
  findings: IntelligenceFinding[];
  suggested_questions: string[];
  intelligence_brief: {
    title: string;
    risk_summary: string;
    what_changed: string;
    top_findings: IntelligenceFinding[];
    confidence_and_limits: SourceCoverageItem[];
    suggested_questions: string[];
  };
  narrative: string;
  trends: Trends;
  top_entities: { entity: string; contracts: number; lobbying: number }[];
  province_breakdown: ProvinceRow[];
  source_coverage: SourceCoverageItem[];
  source_status?: SourceStatusResponse;
  graph?: EvidenceGraphResponse;
  evidence: {
    contracts: { count: number; total_value: number; by_department: { dept: string; value: number; count: number }[]; by_entity: { entity: string; value: number; count: number }[]; records: (EvidenceRef & { department: string; value: number; description: string })[] };
    donations: { count: number; total_value: number; by_party: { party: string; value: number; count: number }[]; records: (EvidenceRef & { party: string; amount: number; province: string })[] };
    lobbying: { count: number; institutions: string[]; top_institutions: { institution: string; count: number }[]; by_entity: { entity: string; count: number }[]; records: (EvidenceRef & { registrant: string; institutions: string[]; subjects: string[] })[] };
    bills: { count: number; records: (EvidenceRef & { bill_number: string; title_en: string; status: string; sponsor: string; latest_activity: string })[] };
    regulations: { count: number; records: (EvidenceRef & { gazette_part: string; published_date: string; department: string; url: string })[] };
    tribunal_decisions: { count: number; records: (EvidenceRef & { body: string; decision_number: string; decision_date: string; outcome: string; url: string })[] };
    appointments: { count: number; records: (EvidenceRef & { appointee_name: string; position_title: string; organization: string; appointment_date: string })[] };
    breadth: { count: number; records: (EvidenceRef & { summary: string; event_date: string; province: string; url: string })[] };
  };
}

export interface EntityProfile {
  company: string;
  canonical: string;
  sector: SectorSummary | null;
  scores: Scores;
  connections: Connection[];
  narrative: string;
  trends: Trends;
  source_coverage: SourceCoverageItem[];
  reports: ReportSummary[];
  evidence: SectorOverview["evidence"];
}

export interface OverviewResponse {
  regional_exposure: { code: string; province: string; records: number; score: number }[];
  regulatory_movement: { title: string; body: string; date: string | null; impact: string; kind: string; url: string | null; meta: string; table?: string; pk?: number; source?: string }[];
  activity: { source: string; count: number }[];
  signals: { title: string; category: string; impact: string; meta: string }[];
  dashboard_signals: {
    title: string;
    theme: string;
    impact: string;
    summary: string;
    why: string;
    sectors: { slug: string; name: string }[];
    references: EvidenceRef[];
  }[];
  intelligence_findings: IntelligenceFinding[];
  sector_watchlist: {
    sector: { slug: string; name: string };
    score: number;
    risk_band: string;
    impact: string;
    summary: string;
    movement: MovementWindow[];
    metrics: {
      contracts: number;
      contract_value: number;
      lobbying: number;
      bills: number;
      gazette: number;
      operations: number;
      hansard: number;
    };
    references: EvidenceRef[];
  }[];
  sector_comparison: {
    sector: { slug: string; name: string };
    risk_band: string;
    movement: MovementWindow[];
    political_attention: number;
    regulatory_activity: number;
    lobbying_intensity: number;
    evidence_volume: number;
    source_coverage: string;
    confidence: string;
    note: string;
  }[];
  actor_movement: {
    actor: string;
    role: string | null;
    party: string | null;
    politician_slug: string | null;
    date: string | null;
    keyword: string;
    excerpt: string;
    sectors: { slug: string; name: string }[];
    reference: EvidenceRef;
  }[];
  ticker: { house_status: string; next_item: string; bills_in_motion: number; gazette_entries: number; contracts: number; operations: number };
  what_changed: { summary?: string; movement_status?: string; requires_attention?: { slug: string; name: string }[]; source_limits?: string };
  source_status?: SourceStatusResponse;
  cache?: { status: "hit" | "miss" | "refresh"; ttl_seconds: number };
}

export interface FeedItem { kind: string; label: string; title: string; meta: string; date: string | null; url: string | null }
export interface BriefingResponse {
  sectors: SectorSummary[];
  streams: { legislation: FeedItem[]; regulation: FeedItem[]; operations: FeedItem[] };
}

export interface SearchHit {
  source: string; title: string; snippet?: string; date?: string;
  amount?: number; url?: string; match: "both" | "semantic" | "exact";
  table?: string; pk?: number; // present → links to the in-app record detail page
}

// ── Universal record detail ───────────────────────────────────────────
export interface RecordRef {
  table: string; pk: number; source: string; record_type: string;
  type_label?: string | null; title: string; date?: string | null; amount?: number | null;
  entity?: string | null; current?: boolean;
}
export interface RelationGroup {
  table: string; source: string; label: string; count: number;
  records: RecordRef[]; partial: boolean;
}
export interface PlayerRef {
  type: "politician" | "regulator" | "appointee";
  name: string; slug: string | null; party: string | null;
  role: string | null; photo_url: string | null; why: string;
  photo_source?: string | null; photo_attribution?: string | null; photo_source_url?: string | null;
}
export type SignalLevel = "strong" | "moderate" | "low";
export interface RecordSignal {
  level: SignalLevel;
  score: number;
  drivers: { label: string; detail: string }[];
}
export interface RecordAssessment {
  means: string;
  matters: string;
  impact: string;
  what_to_watch?: string;
  strategic_read: string;
}
export interface CrossSourceSignature {
  sources: string[];
  distinct: number;
  insight: string | null;
}
export interface LateralGroup {
  label: string;
  basis: string;
  records: RecordRef[];
}
export interface ExplicitRecordLink extends RecordRef {
  relationship: string;
  confidence: number;
  direction: "in" | "out";
  evidence?: Record<string, unknown> | null;
}
export interface ExplicitLinkGroup {
  relationship: string;
  count: number;
  records: ExplicitRecordLink[];
}

export interface RecordDetail {
  table: string;
  pk: number;
  record: {
    title: string; source: string; record_type: string; type_label?: string | null;
    entity: string | null; canonical: string | null;
    date: string | null; amount: number | null; url: string | null;
    fields: { key: string; label: string; value: string }[];
    body?: string | null;
    raw: Record<string, unknown> | null;
  };
  entity: { canonical: string | null; name: string | null };
  industry: { name: string; slug: string; blurb: string; matched_by: string; confidence: "confirmed" | "likely" | "" } | null;
  signal: RecordSignal | null;
  assessment: RecordAssessment | null;
  governing_regulators: string[];
  people: PlayerRef[];
  // Back-compat (page reads signal/assessment/people instead).
  impact: {
    industry: string | null; severity: string; meaning: string; regulators: string[];
  };
  players: PlayerRef[];
  relations: {
    by_source: RelationGroup[];
    total: number;
    sector: { slug: string; name: string; blurb: string } | null;
    sector_peers: { canonical: string; name: string }[];
    timeline: RecordRef[];
    lateral?: LateralGroup[];
    cross_source_signature?: CrossSourceSignature;
    explicit_links?: {
      total: number;
      groups: ExplicitLinkGroup[];
      records: ExplicitRecordLink[];
    };
  };
}

// ── Politicians / political players ───────────────────────────────────
export interface PoliticianCard {
  slug: string; name: string; party: string | null; riding: string | null;
  province: string | null; role: string | null; photo_url: string | null;
  photo_source?: string | null; photo_attribution?: string | null; photo_source_url?: string | null;
}
export interface PoliticiansResponse {
  count: number;
  politicians: PoliticianCard[];
  parties: { party: string; count: number }[];
  provinces: { province: string; count: number }[];
}
export interface PoliticianDetail extends PoliticianCard {
  email: string | null; since_date: string | null; commons_url: string | null;
  openparliament_url: string | null; summary: string;
  industries: { slug: string; name: string }[];
  bills: { table: string; pk: number; bill_number: string; title: string; status: string; date: string }[];
  speeches: { table: string; pk: number; keyword: string; date: string; excerpt: string; url: string | null }[];
}

// Party → accent color (var defined in globals or inline fallback).
export function partyColor(party: string | null | undefined): string {
  const p = (party || "").toLowerCase();
  if (p.includes("liberal")) return "#d71920";
  if (p.includes("conservative")) return "#1a4782";
  if (p.includes("bloc")) return "#0098d4";
  if (p.includes("ndp") || p.includes("democratic")) return "#f37021";
  if (p.includes("green")) return "#3d9b35";
  return "var(--color-fg-dim)";
}

export interface SearchResponse {
  query: string;
  plan: { planner?: string; sources?: string[]; min_amount?: number; date_from?: string; date_to?: string; entity_text?: string };
  counts: { structured: number; semantic: number; returned: number; by_source: Record<string, number> };
  answer: string | null;
  results: SearchHit[];
}

// ── Internal-records retrieval (no AI prose — transparent, citation-safe) ──
export interface RetrievalHit {
  id: string; table: string; pk: number | string; record_type: string;
  source: string; title: string; snippet: string; score: number;
  match: "structured" | "semantic" | "both" | "deterministic";
  date?: string | null; amount?: number | null;
  internal_url: string | null; external_url: string | null;
}
export interface RetrievalResponse {
  query: string;
  plan: { planner?: string; sources?: string[]; min_amount?: number; date_from?: string; date_to?: string };
  retrieval_set_id: string;
  generated_at: string;
  embedding_model: string;
  empty: boolean;
  counts: { returned: number; structured: number; semantic: number; deterministic: number; by_type: Record<string, number> };
  results: RetrievalHit[];
  by_type: Record<string, RetrievalHit[]>;
}

// ── Single-finding AI interpretation (Goal B2) — citation-safe, no report ──
export interface InterpretationClaim {
  text: string;
  label: "observed" | "inferred" | "speculative";
  cited_record_ids: { table: string; pk: number | string }[];
}
export interface CitedRecord {
  table: string; pk: number | string; title: string; internal_url: string | null;
}
export interface InterpretationResponse {
  id: string;
  retrieval_set_id: string;
  table: string;
  pk: number | string;
  status: "ok" | "degraded" | "rejected";
  rejection_reason: string | null;
  model: string;
  provider: string;
  contract_version: string;
  created_at: string;
  from_cache: boolean;
  source_fact: string;
  interpretation: string;
  impact: string;
  recommendation: string;
  confidence: "high" | "medium" | "low";
  evidence_limitations: string;
  cited_record_ids: { table: string; pk: number | string }[];
  cited_records: CitedRecord[];
  claims: InterpretationClaim[];
  generated_by: string;
}

// ── Research runs (Goal B3 — multi-step deep research) ──────────────────
export interface ResearchFindingRef {
  table: string; pk: number | string; title: string; internal_url: string | null;
}
export interface SynthesisItem {
  title?: string;
  text: string;
  label: "observed" | "inferred" | "speculative";
  finding_ids: { table: string; pk: number | string }[];
  findings: ResearchFindingRef[];
}
export interface ResearchSynthesis {
  themes: SynthesisItem[];
  material_risks: SynthesisItem[];
  opportunities: SynthesisItem[];
  diligence_questions: string[];
  overall_confidence: "high" | "medium" | "low";
  coverage_summary: string;
  generated_by: string;
}
export interface ResearchCoverageGap {
  type: string; table?: string; pk?: string; title?: string;
}
export interface ResearchRound {
  round: number;
  queries: string[];
  retrieval_sets: { id: string; query: string | null; result_count: number }[];
  interpretations: InterpretationResponse[];
  coverage_gaps: ResearchCoverageGap[];
  gap_assessment: { material_gaps_remain?: boolean };
}
export interface ResearchRunResponse {
  id: string;
  topic: string;
  depth_tier: "brief" | "standard" | "deep";
  status: "running" | "complete" | "insufficient_evidence" | "degraded" | "error";
  contract_version: string;
  max_rounds: number;
  max_interpretations: number;
  rounds_used: number;
  interpretations_used: number;
  model: string;
  provider: string;
  model_call_count: number;
  created_at: string | null;
  completed_at: string | null;
  rounds: ResearchRound[];
  synthesis: ResearchSynthesis;
}
export interface ResearchRunSummary {
  id: string; topic: string; depth_tier: string; status: string;
  rounds_used: number; max_rounds: number; interpretations_used: number;
  model_call_count: number; created_at: string | null;
}

// ── Diligence reviews + workspace (Goal B4) ─────────────────────────────
export interface ReviewInputs {
  id: string;
  company: string;
  sectors: string[];
  transaction_type: string | null;
  jurisdiction: string | null;
  date_from: string | null;
  date_to: string | null;
  key_concerns: string | null;
  keywords: string[];
  research_question: string | null;
  depth_tier: "brief" | "standard" | "deep";
  research_run_id: string | null;
  status: "researching" | "ready" | "failed";
  error: string | null;
  created_at: string | null;
  updated_at: string | null;
}
export interface WorkspaceFindingMeta {
  date: string | null;
  sector_slug: string | null;
  sector_name: string | null;
  jurisdiction: string;
  source_type: string;
  source_label: string;
  risk_level: string;
  signal_type: string;
  entity: string | null;
  confidence: "high" | "medium" | "low";
  interpretation_types: string[];
}
export interface WorkspaceFinding {
  interpretation_id: string;
  table: string;
  pk: string;
  title: string;
  internal_url: string | null;
  source_fact: string;
  interpretation: string;
  impact: string;
  recommendation: string;
  evidence_limitations: string;
  confidence: "high" | "medium" | "low";
  claims: InterpretationClaim[];
  generated_by: string;
  category: string;
  meta: WorkspaceFindingMeta;
}
export interface WorkspaceConnected {
  table: string; pk: string; kind: string; title: string; internal_url: string | null;
}
export interface WorkspaceGap {
  type: string; table: string | null; pk: string | null; title: string; internal_url: string | null;
}
export interface WorkspaceSourceCoverage {
  source_type: string; label: string; count: number;
}
export interface WorkspaceFacets {
  sectors: { slug: string; name: string }[];
  jurisdictions: string[];
  source_types: { key: string; label: string }[];
  risk_levels: string[];
  confidences: string[];
  signal_types: string[];
  entities: string[];
  interpretation_types: string[];
  date_min: string | null;
  date_max: string | null;
}
export interface Workspace {
  findings: WorkspaceFinding[];
  connected: WorkspaceConnected[];
  further_research: WorkspaceGap[];
  source_coverage: WorkspaceSourceCoverage[];
  facets: WorkspaceFacets;
}
export interface ReviewWorkspaceResponse {
  review: ReviewInputs;
  run: ResearchRunResponse | null;
  workspace: Workspace;
}
export interface ReviewsListResponse { reviews: ReviewInputs[] }

export interface SearchSourcesResponse {
  sources: Record<string, number>;
  total_records: number;
  approximate_sources: string[];
  row_count_methods: Record<string, string>;
}

export interface ReportSummary {
  id: string; company_name: string; report_type: string; status: string;
  generated_by: string; overall: number | null; created_at: string; approved_at?: string | null;
}
export interface ReportsResponse { count: number; reports: ReportSummary[] }
export interface ReportDetail extends ReportSummary {
  risk_scores: Scores;
  evidence: Record<string, unknown>;
  graph_findings: GraphFinding[];
  source_references: EvidenceRef[];
  analyst_notes: string | null;
  sections: { key: string; title: string; html: string }[];
}

export interface ContractSearch {
  company: string; canonical_name: string; count: number; total_value: number;
  contracts: { vendor_name: string; description: string; contract_value: number; contract_date: string; owner_org_title: string }[];
}
export interface LobbyingRecords {
  count: number;
  records: { client: string; canonical_name: string; registrant: string; institutions: string[]; communication_date: string; source: string }[];
}
