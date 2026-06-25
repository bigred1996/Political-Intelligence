"use client";

import Link from "next/link";
import { use, useMemo, useState } from "react";
import {
  type ReviewWorkspaceResponse,
  type SynthesisItem,
  type WorkspaceFinding,
} from "@/lib/api";
import { useApi } from "@/lib/use-api";
import {
  ConfidenceBadge,
  EmptyState,
  InterpretationBadge,
  PageHeader,
  Panel,
  Pill,
  SeverityBadge,
} from "@/components/ui";
import { BarList, HeatMatrix, RadialNetwork, TrendBars } from "@/components/dataviz";
import {
  categorySeverityMatrix,
  connectedNetwork,
  findingsByYear,
  riskDistribution,
  sectorExposure,
  sourceCoverageBars,
} from "@/lib/workspace-charts";

/* Goal B4 — the persistent diligence workspace. READS one stored B3 run
   (via /api/reviews/{id}); it never re-runs the loop or calls a model. The run
   is arranged into the standard diligence sections; client-side filters narrow
   the findings with no server round-trip. Empty sections say so explicitly —
   nothing is fabricated. Every evidence item links to its real /records page. */

type Filters = {
  sector: string; jurisdiction: string; source_type: string; risk_level: string;
  confidence: string; signal_type: string; entity: string; interpretation_type: string;
  date_from: string; date_to: string;
};
const EMPTY_FILTERS: Filters = {
  sector: "", jurisdiction: "", source_type: "", risk_level: "", confidence: "",
  signal_type: "", entity: "", interpretation_type: "", date_from: "", date_to: "",
};

const STATUS_CHIP: Record<string, string> = {
  researching: "status-chip-amber", ready: "status-chip-green", failed: "status-chip-red",
};

export default function WorkspacePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data, loading, error } = useApi<ReviewWorkspaceResponse>(`/api/reviews/${id}`);
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);

  const findings = useMemo(() => data?.workspace.findings ?? [], [data]);
  const filtered = useMemo(() => findings.filter((f) => matches(f, filters)), [findings, filters]);

  // Chart series — derived in code from the SAME filtered array the lists render,
  // so a chart can never drift from the findings beneath it. Empty series fall
  // through to each primitive's "No data" insufficient-data state.
  const riskBars = useMemo(() => riskDistribution(filtered), [filtered]);
  const sectorBars = useMemo(() => sectorExposure(filtered), [filtered]);
  const yearBars = useMemo(() => findingsByYear(filtered), [filtered]);
  const heatMatrix = useMemo(() => categorySeverityMatrix(filtered), [filtered]);
  // Source coverage + connections are run-level overviews (full run, like a legend).
  const coverageBars = useMemo(() => sourceCoverageBars(data?.workspace.source_coverage ?? []), [data]);
  const netNodes = useMemo(() => connectedNetwork(data?.workspace.connected ?? []), [data]);

  // Drill-down: a chart click toggles the matching FilterBar facet (reusing the
  // exact same filter logic the lists already obey). Clicking an active bar clears.
  const toggle = (k: keyof Filters, v: string) =>
    setFilters({ ...filters, [k]: filters[k] === v ? "" : v });
  const toggleYear = (year: string) => {
    const on = filters.date_from === year && filters.date_to === `${year}-12-31`;
    setFilters({ ...filters, date_from: on ? "" : year, date_to: on ? "" : `${year}-12-31` });
  };
  const activeYear = /^\d{4}$/.test(filters.date_from) ? filters.date_from : null;

  if (loading) return <div className="p-6 text-on-surface-variant">Loading workspace…</div>;
  if (error) return <div className="p-6 text-on-error-container">{error}</div>;
  if (!data) return <EmptyState>Review not found.</EmptyState>;

  const { review, run, workspace } = data;
  const s = run?.synthesis;

  return (
    <div className="animate-rise space-y-gutter pb-16">
      <PageHeader
        title={review.company || "Diligence workspace"}
        subtitle={subtitle(review)}
        action={
          <div className="flex items-center gap-2">
            {run && review.status !== "failed" && (
              <>
                <a href={`/memo/${review.id}`} target="_blank" rel="noopener noreferrer"
                  className="text-[12px] px-3 py-1.5 rounded border border-primary text-primary hover:bg-primary/10 transition-colors focus-ring">
                  View memo
                </a>
                <a href={`/memo/${review.id}/pdf`} target="_blank" rel="noopener noreferrer"
                  className="text-[12px] px-3 py-1.5 rounded border border-primary text-primary hover:bg-primary/10 transition-colors focus-ring">
                  Download PDF
                </a>
              </>
            )}
            <Link href="/reviews" className="text-[12px] px-3 py-1.5 rounded border border-outline-variant text-on-surface-variant hover:border-primary transition-colors focus-ring">
              + New review
            </Link>
          </div>
        }
      />

      {/* Run meta */}
      <Panel bodyClass="p-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className={`mono text-[10px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded ${STATUS_CHIP[review.status] ?? "status-chip-amber"}`}>
            {review.status}
          </span>
          <Pill>tier: {review.depth_tier}</Pill>
          {run && <Pill>rounds {run.rounds_used}/{run.max_rounds}</Pill>}
          {run && <Pill>findings {workspace.findings.length}</Pill>}
          {run && <Pill>model calls {run.model_call_count}</Pill>}
          {run && <Pill>{run.provider} · {run.model}</Pill>}
          {review.created_at && <Pill>{new Date(review.created_at).toLocaleString()}</Pill>}
        </div>
      </Panel>

      {/* Failed / no-run guard */}
      {review.status === "failed" && (
        <Panel title="Research run failed" bodyClass="p-4">
          <p className="text-[13px] text-on-surface">
            This review’s research run did not complete. No findings are available.
          </p>
          {review.error && <p className="mono text-[11px] text-on-surface-variant mt-2">{review.error}</p>}
        </Panel>
      )}

      {run && (
        <>
          {/* 1. Executive summary — coverage narrative + "what we found" themes,
              mirroring the memo's lead section. */}
          <Section title="Executive summary" empty={!s?.coverage_summary && (s?.themes.length ?? 0) === 0}>
            <div className="p-4 space-y-4">
              <div className="flex flex-wrap items-center gap-2">
                {s && <ConfidenceBadge value={s.overall_confidence} />}
                {s && <Pill>synthesis: {s.generated_by}</Pill>}
                <Pill>{run.rounds_used} round(s)</Pill>
                <Pill>{workspace.findings.length} finding(s)</Pill>
                <Pill>{workspace.source_coverage.length} source(s)</Pill>
              </div>
              {s?.coverage_summary && (
                <p className="font-body-md text-body-md text-on-surface leading-relaxed">{s.coverage_summary}</p>
              )}
              {s && s.themes.length > 0 && (
                <div className="divide-y divide-outline-variant/40 border-t border-outline-variant/40">
                  {s.themes.map((t, i) => <SynthRow key={i} item={t} heading={t.title} />)}
                </div>
              )}
            </div>
          </Section>

          {/* Filter bar — narrows every list + chart below with no server round-trip. */}
          <FilterBar facets={workspace.facets} filters={filters} setFilters={setFilters}
            shown={filtered.length} total={findings.length} />

          {/* 2. Risk snapshot — the memo's signature exhibit. Stat band + category ×
              severity heat matrix + the supporting charts, all reacting to the filter
              above; a chart/cell click drills the matching filter. */}
          <Panel title="Risk snapshot · where the exposure concentrates" bodyClass="p-4 space-y-5">
            <StatBand
              findings={filtered.length}
              sources={workspace.source_coverage.length}
              period={periodLabel(yearBars)}
              topRisk={riskBars[0]?.label ?? "None"}
              confidence={s?.overall_confidence ?? "—"}
            />
            <HeatMatrix matrix={heatMatrix} onSelect={(k) => setFilters({ ...filters, risk_level: k ?? "" })} activeKey={filters.risk_level || null} />
            <div className="flex flex-wrap gap-x-4 gap-y-1.5 text-[12px] text-on-surface-variant items-center">
              <span>Declared scope:</span>
              {(review.sectors ?? []).length
                ? review.sectors.map((s2) => <Pill key={s2}>{s2}</Pill>)
                : <span>none declared</span>}
            </div>
            <div className="grid md:grid-cols-3 gap-5">
              <MiniChart label="Severity mix">
                <BarList items={riskBars} color="var(--color-risk-high)" onSelect={(k) => toggle("risk_level", k)} activeKey={filters.risk_level || null} />
              </MiniChart>
              <MiniChart label="Activity over time">
                <TrendBars data={yearBars} onSelect={toggleYear} activeYear={activeYear} />
              </MiniChart>
              <MiniChart label="Sector exposure">
                <BarList items={sectorBars} onSelect={(k) => toggle("sector", k)} activeKey={filters.sector || null} />
              </MiniChart>
            </div>
          </Panel>

          {/* 3. Material developments — the interactive findings list (the analyst's
              working core; every card drills to its /records page). */}
          <Section title={`Material developments (${filtered.length})`} empty={filtered.length === 0}>
            <div className="divide-y divide-outline-variant/40">
              {timelineItems(filtered).concat(filtered.filter((f) => !f.meta.date))
                .map((f) => <FindingCard key={`${f.table}:${f.pk}`} f={f} />)}
            </div>
          </Section>

          {/* 4. Material risks & opportunities — side by side, mirroring the memo. */}
          <div className="grid md:grid-cols-2 gap-gutter">
            <Section title={`Material risks (${s?.material_risks.length ?? 0})`} empty={!s?.material_risks.length}>
              <div className="divide-y divide-outline-variant/40">
                {s?.material_risks.map((r, i) => <SynthRow key={i} item={r} />)}
              </div>
            </Section>
            <Section title={`Opportunities (${s?.opportunities.length ?? 0})`} empty={!s?.opportunities.length}>
              <div className="divide-y divide-outline-variant/40">
                {s?.opportunities.map((o, i) => <SynthRow key={i} item={o} />)}
              </div>
            </Section>
          </div>

          {/* 5. Stakeholders & connections — radial map + the exhaustive linkable list. */}
          <Section title={`Political stakeholders & connections (${workspace.connected.length})`}
            empty={workspace.connected.length === 0}>
            <div className="p-4 space-y-4">
              {workspace.connected.length > 0 && (
                <div className="max-w-sm mx-auto">
                  <RadialNetwork center={review.company || "Subject"} nodes={netNodes} />
                </div>
              )}
              <div className="flex flex-wrap gap-2">
                {workspace.connected.map((c) => (
                  <LinkChip key={`${c.table}:${c.pk}`} href={c.internal_url} title={c.title}>
                    <span className="material-symbols-outlined text-[14px]">
                      {c.kind === "politicians" ? "account_balance" : c.kind === "committees" ? "groups" : "corporate_fare"}
                    </span>
                    {c.title}
                  </LinkChip>
                ))}
              </div>
            </div>
          </Section>

          {/* 6. Diligence actions — questions for management + further-research gaps. */}
          <Section title="Diligence actions"
            empty={!(s?.diligence_questions.length ?? 0) && workspace.further_research.length === 0}>
            <div className="p-4 space-y-4">
              {(s?.diligence_questions.length ?? 0) > 0 && (
                <div>
                  <div className="font-label-caps text-label-caps text-on-surface-variant uppercase mb-2">Questions for management</div>
                  <ol className="list-decimal pl-6 space-y-1.5">
                    {s?.diligence_questions.map((q, i) => (
                      <li key={i} className="text-[13px] text-on-surface leading-snug">{q}</li>
                    ))}
                  </ol>
                </div>
              )}
              {workspace.further_research.length > 0 && (
                <div>
                  <div className="font-label-caps text-label-caps text-on-surface-variant uppercase mb-2">Lines to pursue</div>
                  <div className="flex flex-wrap gap-2">
                    {workspace.further_research.map((g, i) => (
                      g.internal_url ? (
                        <LinkChip key={i} href={g.internal_url} title={g.title}>
                          {g.type.replace(/_/g, " ")}{g.table ? ` · ${g.table}:${g.pk}` : ""}
                        </LinkChip>
                      ) : (
                        <span key={i} className="text-[11px] px-1.5 py-0.5 rounded status-chip-amber">
                          {g.type.replace(/_/g, " ")}
                        </span>
                      )
                    ))}
                  </div>
                </div>
              )}
            </div>
          </Section>

          {/* 7. Evidence appendix — source coverage + the full linkable record list. */}
          <Section title={`Evidence appendix (${filtered.length})`} empty={filtered.length === 0}>
            <div className="p-4 space-y-4">
              {workspace.source_coverage.length > 0 && (
                <MiniChart label="Source coverage">
                  <BarList items={coverageBars} onSelect={(k) => toggle("source_type", k)} activeKey={filters.source_type || null} />
                </MiniChart>
              )}
              <div className="divide-y divide-outline-variant/40 border-t border-outline-variant/40">
                {filtered.map((f) => (
                  <Link key={`${f.table}:${f.pk}`} href={f.internal_url ?? "#"}
                    className="flex items-center gap-3 py-2 hover:bg-surface-container-high transition-colors focus-ring">
                    <SeverityBadge severity={f.meta.risk_level} />
                    <span className="font-label-caps text-label-caps text-on-surface-variant uppercase shrink-0">{f.meta.source_label}</span>
                    <span className="text-[13px] text-on-surface truncate flex-1">{f.title}</span>
                    {f.meta.date && <span className="font-data-tabular text-[11px] text-on-surface-variant">{f.meta.date}</span>}
                  </Link>
                ))}
              </div>
            </div>
          </Section>
        </>
      )}
    </div>
  );
}

// ── filtering ─────────────────────────────────────────────────────────
function matches(f: WorkspaceFinding, fl: Filters): boolean {
  const m = f.meta;
  if (fl.sector && m.sector_slug !== fl.sector) return false;
  if (fl.jurisdiction && m.jurisdiction !== fl.jurisdiction) return false;
  if (fl.source_type && m.source_type !== fl.source_type) return false;
  if (fl.risk_level && m.risk_level !== fl.risk_level) return false;
  if (fl.confidence && m.confidence !== fl.confidence) return false;
  if (fl.signal_type && m.signal_type !== fl.signal_type) return false;
  if (fl.entity && m.entity !== fl.entity) return false;
  if (fl.interpretation_type && !m.interpretation_types.includes(fl.interpretation_type)) return false;
  if (fl.date_from || fl.date_to) {
    if (!m.date) return false;
    const d = String(m.date);
    if (fl.date_from && d < fl.date_from) return false;
    if (fl.date_to && d > fl.date_to) return false;
  }
  return true;
}

function timelineItems(items: WorkspaceFinding[]): WorkspaceFinding[] {
  return items.filter((f) => f.meta.date).sort((a, b) => String(b.meta.date).localeCompare(String(a.meta.date)));
}

function periodLabel(yearBars: { year: string }[]): string {
  if (yearBars.length === 0) return "—";
  if (yearBars.length === 1) return yearBars[0].year;
  return `${yearBars[0].year}–${yearBars[yearBars.length - 1].year}`;
}

// The memo's at-a-glance strip — the answer in five numbers — ported to the workspace.
function StatBand({ findings, sources, period, topRisk, confidence }: {
  findings: number; sources: number; period: string; topRisk: string; confidence: string;
}) {
  const stats: [string, string][] = [
    [String(findings), "Findings"],
    [String(sources), "Sources"],
    [period, "Period"],
    [topRisk, "Top risk band"],
    [confidence.charAt(0).toUpperCase() + confidence.slice(1), "Confidence"],
  ];
  return (
    <div className="grid grid-cols-2 sm:grid-cols-5 divide-x divide-outline-variant/40 rounded-sm border border-outline-variant/40 overflow-hidden">
      {stats.map(([n, l]) => (
        <div key={l} className="px-3 py-2.5">
          <div className="font-data-tabular text-[20px] font-bold text-on-surface leading-none">{n}</div>
          <div className="font-label-caps text-label-caps text-on-surface-variant uppercase mt-1">{l}</div>
        </div>
      ))}
    </div>
  );
}

// ── sub-components ──────────────────────────────────────────────────────
function subtitle(review: ReviewWorkspaceResponse["review"]): string {
  const bits = [
    review.transaction_type, review.jurisdiction,
    review.date_from || review.date_to ? `${review.date_from ?? "…"}–${review.date_to ?? "…"}` : null,
    review.research_question,
  ].filter(Boolean);
  return bits.length ? bits.join(" · ") : "Persistent diligence workspace over internal records.";
}

function Section({ title, empty, children }: { title: string; empty: boolean; children: React.ReactNode }) {
  return (
    <Panel title={title} bodyClass="p-0">
      {empty ? <Insufficient /> : children}
    </Panel>
  );
}

// A labeled chart cell for the Risk-snapshot / appendix grids.
function MiniChart({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <div className="font-label-caps text-label-caps text-on-surface-variant uppercase">{label}</div>
      {children}
    </div>
  );
}

function Insufficient({ note }: { note?: string }) {
  return (
    <p className="p-4 text-[12px] text-on-surface-variant italic">
      {note ?? "Insufficient evidence in this run for this section."}
    </p>
  );
}

function FindingCard({ f }: { f: WorkspaceFinding }) {
  return (
    <div className="p-4 space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <SeverityBadge severity={f.meta.risk_level} />
        <ConfidenceBadge value={f.confidence} />
        {f.meta.interpretation_types.map((t) => <InterpretationBadge key={t} value={t} />)}
        <span className="font-label-caps text-label-caps text-on-surface-variant uppercase ml-auto">{f.meta.source_label}</span>
        {f.internal_url && (
          <Link href={f.internal_url} className="text-[11px] px-1.5 py-0.5 rounded border border-outline-variant text-on-surface-variant hover:border-primary hover:text-on-surface transition-colors focus-ring">
            {f.table}:{f.pk}
          </Link>
        )}
      </div>
      <p className="text-[13px] text-on-surface leading-snug"><span className="text-on-surface-variant">Fact: </span>{f.source_fact}</p>
      {f.interpretation && <p className="text-[13px] text-on-surface leading-snug"><span className="text-on-surface-variant">Interpretation: </span>{f.interpretation}</p>}
      {f.impact && <p className="text-[13px] text-on-surface leading-snug"><span className="text-on-surface-variant">Impact: </span>{f.impact}</p>}
      {f.recommendation && <p className="text-[13px] text-on-surface leading-snug"><span className="text-on-surface-variant">Recommended: </span>{f.recommendation}</p>}
      {f.evidence_limitations && <p className="text-[12px] text-on-surface-variant italic">Limitations: {f.evidence_limitations}</p>}
    </div>
  );
}

function SynthRow({ item, heading }: { item: SynthesisItem; heading?: string }) {
  return (
    <div className="p-3 space-y-2">
      <div className="flex items-start gap-3">
        <InterpretationBadge value={item.label} />
        <div className="min-w-0">
          {heading && <p className="font-label-caps text-label-caps text-on-surface-variant uppercase">{heading}</p>}
          <p className="text-[13px] text-on-surface leading-snug">{item.text}</p>
        </div>
      </div>
      {item.findings.length > 0 && (
        <div className="flex flex-wrap gap-1.5 pl-8">
          {item.findings.map((fd) => (
            <LinkChip key={`${fd.table}:${fd.pk}`} href={fd.internal_url} title={fd.title}>
              {fd.table}:{fd.pk}
            </LinkChip>
          ))}
        </div>
      )}
    </div>
  );
}

function LinkChip({ href, title, children }: { href: string | null; title?: string; children: React.ReactNode }) {
  const cls = "inline-flex items-center gap-1 text-[11px] px-1.5 py-0.5 rounded border border-outline-variant text-on-surface-variant";
  return href ? (
    <Link href={href} title={title} className={`${cls} hover:border-primary hover:text-on-surface transition-colors focus-ring`}>
      {children}
    </Link>
  ) : (
    <span className={cls} title={title}>{children}</span>
  );
}

function FilterBar({ facets, filters, setFilters, shown, total }: {
  facets: ReviewWorkspaceResponse["workspace"]["facets"];
  filters: Filters; setFilters: (f: Filters) => void; shown: number; total: number;
}) {
  const set = (k: keyof Filters, v: string) => setFilters({ ...filters, [k]: v });
  const active = Object.values(filters).some(Boolean);
  return (
    <Panel title="Filters" bodyClass="p-4">
      <div className="flex flex-wrap gap-2 items-end">
        <Select label="Sector" value={filters.sector} onChange={(v) => set("sector", v)}
          options={facets.sectors.map((s) => ({ value: s.slug, label: s.name }))} />
        <Select label="Source" value={filters.source_type} onChange={(v) => set("source_type", v)}
          options={facets.source_types.map((s) => ({ value: s.key, label: s.label }))} />
        <Select label="Risk" value={filters.risk_level} onChange={(v) => set("risk_level", v)}
          options={facets.risk_levels.map((r) => ({ value: r, label: r }))} />
        <Select label="Confidence" value={filters.confidence} onChange={(v) => set("confidence", v)}
          options={facets.confidences.map((c) => ({ value: c, label: c }))} />
        <Select label="Signal" value={filters.signal_type} onChange={(v) => set("signal_type", v)}
          options={facets.signal_types.map((c) => ({ value: c, label: c }))} />
        <Select label="Interpretation" value={filters.interpretation_type} onChange={(v) => set("interpretation_type", v)}
          options={facets.interpretation_types.map((c) => ({ value: c, label: c }))} />
        <Select label="Jurisdiction" value={filters.jurisdiction} onChange={(v) => set("jurisdiction", v)}
          options={facets.jurisdictions.map((c) => ({ value: c, label: c }))} />
        <Select label="Entity" value={filters.entity} onChange={(v) => set("entity", v)}
          options={facets.entities.map((c) => ({ value: c, label: c }))} />
        <div className="flex flex-col gap-1">
          <label className="font-label-caps text-label-caps text-on-surface-variant uppercase">Date from</label>
          <input value={filters.date_from} onChange={(e) => set("date_from", e.target.value)} placeholder={facets.date_min ?? "YYYY"}
            className="bg-surface-container-lowest border border-outline-variant rounded px-2 py-1 text-[12px] text-on-surface focus-ring w-24" />
        </div>
        <div className="flex flex-col gap-1">
          <label className="font-label-caps text-label-caps text-on-surface-variant uppercase">Date to</label>
          <input value={filters.date_to} onChange={(e) => set("date_to", e.target.value)} placeholder={facets.date_max ?? "YYYY"}
            className="bg-surface-container-lowest border border-outline-variant rounded px-2 py-1 text-[12px] text-on-surface focus-ring w-24" />
        </div>
        <div className="ml-auto flex items-center gap-3">
          <span className="font-data-tabular text-[12px] text-on-surface-variant">{shown} / {total} findings</span>
          {active && (
            <button onClick={() => setFilters(EMPTY_FILTERS)}
              className="text-[12px] px-2.5 py-1 rounded border border-outline-variant text-on-surface-variant hover:border-primary transition-colors focus-ring">
              Clear
            </button>
          )}
        </div>
      </div>
    </Panel>
  );
}

function Select({ label, value, onChange, options }: {
  label: string; value: string; onChange: (v: string) => void; options: { value: string; label: string }[];
}) {
  if (options.length === 0) return null;
  return (
    <div className="flex flex-col gap-1">
      <label className="font-label-caps text-label-caps text-on-surface-variant uppercase">{label}</label>
      <select value={value} onChange={(e) => onChange(e.target.value)}
        className="bg-surface-container-lowest border border-outline-variant rounded px-2 py-1 text-[12px] text-on-surface focus-ring max-w-[160px]">
        <option value="">All</option>
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>
  );
}
