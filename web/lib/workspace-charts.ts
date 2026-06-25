/* Goal B5 — deterministic chart-series derivation for the diligence workspace.
   Every number here is COMPUTED IN CODE from the stored B3 run's findings — no
   model is ever called and no value is fabricated. The workspace page feeds the
   *currently-filtered* findings array into these functions so the charts and the
   findings lists are always computed from the same source (they cannot drift).
   An empty input yields an empty series, which the SVG primitives render as their
   "No data" / insufficient-data state. Pure + side-effect-free so they unit-test
   without a browser or a DB. */
import type { WorkspaceConnected, WorkspaceFinding, WorkspaceSourceCoverage } from "./api";

/** A categorical bar with the filter `key` it drills into. */
export type ChartBar = { key: string; label: string; value: number };
/** A year bucket for the timeline column chart. */
export type YearBar = { year: string; count: number };
/** A node for the connected-entities radial map. */
export type NetNode = { label: string; sub?: string; type: "regulatory" | "funding" | "policy" | "partnership" };

// Risk buckets in severity order (matches pipeline.impact severities + the
// SeverityBadge vocabulary). Anything unrecognized collapses into "watch".
const RISK_ORDER = ["high", "elevated", "watch"] as const;
const RISK_LABEL: Record<string, string> = { high: "High", elevated: "Elevated", watch: "Watch" };

/** Findings counted by risk level, high→watch, omitting empty buckets. */
export function riskDistribution(findings: WorkspaceFinding[]): ChartBar[] {
  const counts = new Map<string, number>();
  for (const f of findings) {
    const lvl = RISK_ORDER.includes(f.meta.risk_level as (typeof RISK_ORDER)[number]) ? f.meta.risk_level : "watch";
    counts.set(lvl, (counts.get(lvl) ?? 0) + 1);
  }
  return RISK_ORDER.filter((lvl) => counts.has(lvl)).map((lvl) => ({
    key: lvl,
    label: RISK_LABEL[lvl] ?? lvl,
    value: counts.get(lvl) ?? 0,
  }));
}

/** Findings counted by resolved sector, busiest first. Findings whose record did
    not resolve to a tracked sector are excluded (no fabricated "unknown" bar). */
export function sectorExposure(findings: WorkspaceFinding[]): ChartBar[] {
  const counts = new Map<string, number>();
  const names = new Map<string, string>();
  for (const f of findings) {
    const slug = f.meta.sector_slug;
    if (!slug) continue;
    counts.set(slug, (counts.get(slug) ?? 0) + 1);
    names.set(slug, f.meta.sector_name ?? slug);
  }
  return [...counts.entries()]
    .map(([slug, value]) => ({ key: slug, label: names.get(slug) ?? slug, value }))
    .sort((a, b) => b.value - a.value || a.label.localeCompare(b.label));
}

/** A clean 4-digit year from a date string of any granularity ("2021",
    "2021-03-15", ISO timestamps). Returns null for missing/implausible dates. */
export function yearOf(date: string | null | undefined): string | null {
  if (!date) return null;
  const m = String(date).match(/^(\d{4})/);
  if (!m) return null;
  const y = Number(m[1]);
  return y >= 1900 && y <= 2100 ? m[1] : null;
}

/** Findings bucketed by year, ascending, with interior gap years filled at 0 so
    the time axis is honest (a quiet year reads as quiet, not as missing). */
export function findingsByYear(findings: WorkspaceFinding[]): YearBar[] {
  const counts = new Map<string, number>();
  for (const f of findings) {
    const y = yearOf(f.meta.date);
    if (!y) continue;
    counts.set(y, (counts.get(y) ?? 0) + 1);
  }
  if (counts.size === 0) return [];
  const years = [...counts.keys()].map(Number).sort((a, b) => a - b);
  const out: YearBar[] = [];
  for (let y = years[0]; y <= years[years.length - 1]; y++) {
    out.push({ year: String(y), count: counts.get(String(y)) ?? 0 });
  }
  return out;
}

/** Source-coverage rows (already aggregated server-side) as drillable bars. */
export function sourceCoverageBars(coverage: WorkspaceSourceCoverage[]): ChartBar[] {
  return coverage.map((c) => ({ key: c.source_type, label: c.label, value: c.count }));
}

// Diligence category → human label / display order. Mirrors pipeline.diligence
// CATEGORY + pipeline.memo_builder.CAT_LABEL so the web heat matrix and the PDF
// memo's signature exhibit read identically.
const CAT_LABEL: Record<string, string> = {
  political_attention: "Political & reputational",
  legislative_regulatory: "Legislative & regulatory",
  govt_support: "Government support",
  lobbying_stakeholders: "Lobbying & stakeholders",
  other: "Other signals",
};
const CAT_ORDER = ["political_attention", "legislative_regulatory", "govt_support", "lobbying_stakeholders", "other"];

/** The category × severity heat matrix — the memo's signature exhibit, ported
    to the workspace. `rows`/`cols`/`values` form the grid (count per cell);
    `keys` carry the category slug per row so a cell click can drill to a filter;
    `absentRows` are the tracked categories with zero findings (shown as one
    muted line, never empty rows). */
export type HeatMatrix = {
  rows: string[];
  keys: string[];
  cols: string[];
  colKeys: string[];
  values: number[][];
  absentRows: string[];
};

export function categorySeverityMatrix(findings: WorkspaceFinding[]): HeatMatrix {
  const grid = new Map<string, Record<string, number>>();
  for (const f of findings) {
    const cat = f.category || "other";
    const lvl = RISK_ORDER.includes(f.meta.risk_level as (typeof RISK_ORDER)[number]) ? f.meta.risk_level : "watch";
    const row = grid.get(cat) ?? { high: 0, elevated: 0, watch: 0 };
    row[lvl] = (row[lvl] ?? 0) + 1;
    grid.set(cat, row);
  }
  const present = CAT_ORDER.filter((c) => grid.has(c));
  const absent = CAT_ORDER.filter((c) => !grid.has(c) && c !== "other").map((c) => CAT_LABEL[c]);
  return {
    rows: present.map((c) => CAT_LABEL[c] ?? c),
    keys: present,
    cols: RISK_ORDER.map((r) => RISK_LABEL[r]),
    colKeys: [...RISK_ORDER],
    values: present.map((c) => RISK_ORDER.map((lvl) => grid.get(c)?.[lvl] ?? 0)),
    absentRows: absent,
  };
}

// Connected-entity kind → network edge colour bucket. The radial primitive only
// knows four edge types; this maps the directory tables onto them deterministically.
const KIND_TO_TYPE: Record<string, NetNode["type"]> = {
  politicians: "policy",
  committees: "policy",
  organizations: "partnership",
  entities: "partnership",
};

/** Connected people/orgs as radial nodes. Capped for legibility (the section's
    chip list below the chart remains the exhaustive, linkable enumeration). */
export function connectedNetwork(connected: WorkspaceConnected[], cap = 14): NetNode[] {
  return connected.slice(0, cap).map((c) => ({
    label: c.title || `${c.table}:${c.pk}`,
    sub: c.kind,
    type: KIND_TO_TYPE[c.kind] ?? "partnership",
  }));
}
