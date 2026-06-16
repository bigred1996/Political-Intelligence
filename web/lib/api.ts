// Typed client for the Polaris FastAPI backend. All calls go through relative
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
}
export interface ProvinceRow { code: string; province: string; records: number; amount: number }
export interface TrendPoint { year: string; value?: number; count?: number }
export interface Trends { contracts: TrendPoint[]; lobbying: TrendPoint[]; donations: TrendPoint[] }
export interface SectorOverview {
  sector: SectorSummary;
  province: string | null;
  province_name: string | null;
  scores: Scores;
  connections: Connection[];
  narrative: string;
  trends: Trends;
  top_entities: { entity: string; contracts: number; lobbying: number }[];
  province_breakdown: ProvinceRow[];
  evidence: {
    contracts: { count: number; total_value: number; by_department: { dept: string; value: number; count: number }[]; by_entity: { entity: string; value: number; count: number }[] };
    donations: { count: number; total_value: number; by_party: { party: string; value: number; count: number }[] };
    lobbying: { count: number; institutions: string[]; top_institutions: { institution: string; count: number }[]; by_entity: { entity: string; count: number }[] };
    bills: { count: number; records: { id: number; table: string; bill_number: string; title_en: string; status: string; sponsor: string; latest_activity: string }[] };
    regulations: { count: number; records: { id: number; table: string; gazette_part: string; title: string; published_date: string; department: string; url: string }[] };
    tribunal_decisions: { count: number; records: { id: number; table: string; body: string; decision_number: string; title: string; decision_date: string; outcome: string; url: string }[] };
    appointments: { count: number; records: { id: number; table: string; appointee_name: string; position_title: string; organization: string; appointment_date: string }[] };
    breadth: { count: number; records: { id: number; table: string; source: string; title: string; summary: string; event_date: string; province: string; url: string }[] };
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
  evidence: SectorOverview["evidence"];
}

export interface OverviewResponse {
  regional_exposure: { code: string; province: string; records: number; score: number }[];
  regulatory_movement: { title: string; body: string; date: string | null; impact: string; kind: string; url: string | null; meta: string }[];
  activity: { source: string; count: number }[];
  signals: { title: string; category: string; impact: string; meta: string }[];
  ticker: { house_status: string; next_item: string; bills_in_motion: number; gazette_entries: number; contracts: number; operations: number };
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
  title: string; date?: string | null; amount?: number | null;
  entity?: string | null; current?: boolean;
}
export interface RelationGroup {
  table: string; source: string; label: string; count: number;
  records: RecordRef[]; partial: boolean;
}
export interface PlayerRef {
  type: "politician" | "regulator";
  name: string; slug: string | null; party: string | null;
  role: string | null; photo_url: string | null; why: string;
}
export interface RecordDetail {
  table: string;
  pk: number;
  record: {
    title: string; source: string; record_type: string;
    entity: string | null; canonical: string | null;
    date: string | null; amount: number | null; url: string | null;
    fields: { key: string; label: string; value: string }[];
    raw: Record<string, unknown> | null;
  };
  entity: { canonical: string | null; name: string | null };
  industry: { name: string; slug: string; blurb: string; matched_by: string } | null;
  impact: {
    industry: string | null; industry_slug: string | null; how: string;
    severity: "high" | "elevated" | "watch"; meaning: string; regulators: string[];
  };
  players: PlayerRef[];
  relations: {
    by_source: RelationGroup[];
    total: number;
    sector: { slug: string; name: string; blurb: string } | null;
    sector_peers: { canonical: string; name: string }[];
    timeline: RecordRef[];
  };
}

// ── Politicians / political players ───────────────────────────────────
export interface PoliticianCard {
  slug: string; name: string; party: string | null; riding: string | null;
  province: string | null; role: string | null; photo_url: string | null;
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
  speeches: { keyword: string; date: string; excerpt: string; url: string }[];
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

// Build the in-app detail href for any record reference.
export function recordHref(table: string | undefined, pk: number | undefined): string | null {
  if (!table || pk == null) return null;
  return `/records/${encodeURIComponent(table)}/${pk}`;
}
export interface SearchResponse {
  query: string;
  plan: { planner?: string; sources?: string[]; min_amount?: number; date_from?: string; date_to?: string; entity_text?: string };
  counts: { structured: number; semantic: number; returned: number; by_source: Record<string, number> };
  answer: string | null;
  results: SearchHit[];
}

export interface ReportSummary {
  id: string; company_name: string; report_type: string; status: string;
  generated_by: string; overall: number | null; created_at: string;
}
export interface ReportsResponse { count: number; reports: ReportSummary[] }
export interface ReportDetail extends ReportSummary {
  risk_scores: Scores;
  evidence: Record<string, { count?: number; total_value?: number }>;
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
