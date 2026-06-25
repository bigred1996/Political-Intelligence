/* Goal B5 — tests for the deterministic chart-series derivation. Run with the
   repo's Node (≥23 strips TS types natively, no new dependency):

     ~/.lmstudio/.internal/utils/node --test web/lib/workspace-charts.test.ts

   Covers: every series renders from real run data; empty input → empty series
   (the primitives' insufficient-data state, never a fabricated trend); chart
   numbers match the underlying findings (no drift); the drill-down keys a chart
   emits are valid filter values. */
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  categorySeverityMatrix,
  connectedNetwork,
  findingsByYear,
  riskDistribution,
  sectorExposure,
  sourceCoverageBars,
  yearOf,
} from "./workspace-charts.ts";

// ── fixtures: shaped exactly like pipeline.diligence build_workspace output ──
type F = Record<string, unknown>;
function finding(meta: Partial<Record<string, unknown>>): F {
  return {
    table: "contracts", pk: String(Math.random()), title: "t", internal_url: "/x",
    source_fact: "", interpretation: "", impact: "", recommendation: "",
    evidence_limitations: "", confidence: "low", claims: [], generated_by: "", category: "other",
    meta: {
      date: null, sector_slug: null, sector_name: null, jurisdiction: "Federal",
      source_type: "contracts", source_label: "Federal contracts", risk_level: "watch",
      signal_type: "record", entity: null, confidence: "low", interpretation_types: [],
      ...meta,
    },
  };
}

const SAMPLE = [
  finding({ risk_level: "high", sector_slug: "energy", sector_name: "Energy", source_type: "contracts", source_label: "Federal contracts", date: "2021-03-15" }),
  finding({ risk_level: "high", sector_slug: "energy", sector_name: "Energy", source_type: "lobbying", source_label: "Lobbying", date: "2021-09-01" }),
  finding({ risk_level: "elevated", sector_slug: "telecom", sector_name: "Telecom", source_type: "bills", source_label: "Bills", date: "2023" }),
  finding({ risk_level: "watch", sector_slug: null, sector_name: null, source_type: "gazette", source_label: "Gazette", date: null }),
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
] as any[];

// ── renders from real data ──────────────────────────────────────────────
test("riskDistribution: counts by level, severity order, no empty buckets", () => {
  const bars = riskDistribution(SAMPLE);
  assert.deepEqual(bars, [
    { key: "high", label: "High", value: 2 },
    { key: "elevated", label: "Elevated", value: 1 },
    { key: "watch", label: "Watch", value: 1 },
  ]);
});

test("categorySeverityMatrix: grids present categories × severity, lists absent ones", () => {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const withCat = (category: string, risk_level: string) => ({ ...finding({ risk_level }), category }) as any;
  const m = categorySeverityMatrix([
    withCat("political_attention", "elevated"),
    withCat("political_attention", "watch"),
    withCat("legislative_regulatory", "high"),
  ]);
  // Present categories follow CAT_ORDER (political before legislative); cols are high→watch.
  assert.deepEqual(m.rows, ["Political & reputational", "Legislative & regulatory"]);
  assert.deepEqual(m.colKeys, ["high", "elevated", "watch"]);
  assert.deepEqual(m.values, [
    [0, 1, 1], // political: 0 high, 1 elevated, 1 watch
    [1, 0, 0], // legislative: 1 high
  ]);
  // Tracked-but-unobserved categories are reported, never rendered as empty rows.
  assert.deepEqual(m.absentRows, ["Government support", "Lobbying & stakeholders"]);
});

test("categorySeverityMatrix: empty input yields an empty grid (no fabricated rows)", () => {
  const m = categorySeverityMatrix([]);
  assert.equal(m.rows.length, 0);
  assert.equal(m.values.length, 0);
});

test("sectorExposure: counts by resolved sector, busiest first, untracked excluded", () => {
  const bars = sectorExposure(SAMPLE);
  assert.deepEqual(bars, [
    { key: "energy", label: "Energy", value: 2 },
    { key: "telecom", label: "Telecom", value: 1 },
  ]);
});

test("findingsByYear: buckets by year ascending with interior gaps filled at 0", () => {
  const bars = findingsByYear(SAMPLE);
  assert.deepEqual(bars, [
    { year: "2021", count: 2 },
    { year: "2022", count: 0 }, // gap-filled, honest quiet year
    { year: "2023", count: 1 },
  ]);
});

test("sourceCoverageBars: maps aggregated coverage rows 1:1", () => {
  const bars = sourceCoverageBars([
    { source_type: "contracts", label: "Federal contracts", count: 1 },
    { source_type: "lobbying", label: "Lobbying", count: 1 },
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ] as any);
  assert.deepEqual(bars, [
    { key: "contracts", label: "Federal contracts", value: 1 },
    { key: "lobbying", label: "Lobbying", value: 1 },
  ]);
});

test("connectedNetwork: maps kinds to edge types and caps node count", () => {
  const connected = [
    { table: "politicians", pk: "1", kind: "politicians", title: "MP A", internal_url: "/p/1" },
    { table: "organizations", pk: "2", kind: "organizations", title: "Org B", internal_url: "/o/2" },
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ] as any;
  const nodes = connectedNetwork(connected);
  assert.deepEqual(nodes, [
    { label: "MP A", sub: "politicians", type: "policy" },
    { label: "Org B", sub: "organizations", type: "partnership" },
  ]);
  // cap
  const many = Array.from({ length: 30 }, (_, i) => ({ table: "entities", pk: String(i), kind: "entities", title: `E${i}`, internal_url: null }));
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  assert.equal(connectedNetwork(many as any).length, 14);
});

// ── empty series → insufficient-data state (no crash, no fabrication) ────
test("empty input yields empty series for every chart (no fabricated trend)", () => {
  assert.deepEqual(riskDistribution([]), []);
  assert.deepEqual(sectorExposure([]), []);
  assert.deepEqual(findingsByYear([]), []);
  assert.deepEqual(sourceCoverageBars([]), []);
  assert.deepEqual(connectedNetwork([]), []);
});

test("findings with no dates yield an empty timeline, not a flat fake line", () => {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const noDates = [finding({ date: null }), finding({ date: undefined as any })] as any[];
  assert.deepEqual(findingsByYear(noDates), []);
});

// ── no drift: chart totals equal the underlying finding count ────────────
test("no drift: risk + year bars each sum to the dated/total finding count", () => {
  const riskTotal = riskDistribution(SAMPLE).reduce((n, b) => n + b.value, 0);
  assert.equal(riskTotal, SAMPLE.length); // every finding has a risk level

  const dated = SAMPLE.filter((f) => yearOf((f.meta as F).date as string)).length;
  const yearTotal = findingsByYear(SAMPLE).reduce((n, b) => n + b.count, 0);
  assert.equal(yearTotal, dated); // gap years are 0, so the sum still equals dated findings
});

// ── drill-down keys are valid filter values ─────────────────────────────
test("drill-down: emitted keys match the meta fields the FilterBar filters on", () => {
  // sector bar key === meta.sector_slug → FilterBar 'sector' compares m.sector_slug
  assert.equal(sectorExposure(SAMPLE)[0].key, "energy");
  // risk bar key === meta.risk_level → FilterBar 'risk_level' compares m.risk_level
  assert.equal(riskDistribution(SAMPLE)[0].key, "high");
  // source bar key === source_type → FilterBar 'source_type' compares m.source_type
  assert.equal(sourceCoverageBars([{ source_type: "bills", label: "Bills", count: 3 }] as never)[0].key, "bills");
});

// ── yearOf robustness across date granularities ─────────────────────────
test("yearOf: handles bare year, ISO date, timestamp; rejects junk + out-of-range", () => {
  assert.equal(yearOf("2021"), "2021");
  assert.equal(yearOf("2021-03-15"), "2021");
  assert.equal(yearOf("2021-03-15T00:00:00Z"), "2021");
  assert.equal(yearOf(null), null);
  assert.equal(yearOf(""), null);
  assert.equal(yearOf("not-a-date"), null);
  assert.equal(yearOf("4043-01-01"), null); // the openparliament bogus-year case
});
