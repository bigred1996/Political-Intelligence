"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useApi } from "@/lib/use-api";
import type {
  EvidenceRef,
  IntelligenceFinding,
  MovementWindow,
  OverviewResponse,
  SourceStatusResponse,
} from "@/lib/api";
import { money, num } from "@/lib/api";
import {
  evidenceHref,
  findingHref,
  personHref,
  recordHref,
  sectorHref,
} from "@/lib/navigation";
import { CanadaMap } from "@/components/dataviz";
import { SourceCoverageList } from "@/components/ui";
import {
  ConfidenceDot,
  ConnectionChain,
  DashSection,
  FilterSelect,
  MetricTile,
  MovementPips,
  Segmented,
  WatchStar,
  useWatchlist,
  type ChainNode,
} from "@/components/dashboard";

const ALL = "ALL";
const RISK_WEIGHT: Record<string, number> = { high: 4, elevated: 3, moderate: 2, low: 1 };

export default function IntelligenceDashboard() {
  const { data, loading, error } = useApi<OverviewResponse>("/api/overview");
  const { data: sourceStatus } = useApi<SourceStatusResponse>("/api/sources/status");
  const { watched, toggle, isWatched, ready: watchReady } = useWatchlist();

  const [region, setRegion] = useState<string>(ALL);
  const [sector, setSector] = useState<string>(ALL);
  const [windowDays, setWindowDays] = useState<7 | 30 | 90>(30);

  // ── Filter option sources (honest: only provinces/sectors with data) ──
  const regionOptions = useMemo(() => [
    { value: ALL, label: "All Canada" },
    ...(data?.regional_exposure ?? []).map((r) => ({ value: r.code, label: r.province })),
  ], [data]);
  const sectorOptions = useMemo(() => [
    { value: ALL, label: "All sectors" },
    ...(data?.sector_watchlist ?? []).map((s) => ({ value: s.sector.slug, label: s.sector.name })),
  ], [data]);

  const provinceQs = region !== ALL ? `?province=${region}` : "";
  const sLink = (slug?: string | null) => slug ? `${sectorHref(slug)}${provinceQs}` : "/sectors";

  // ── Sector-scoped finding filter ──
  const matchesSector = (f: IntelligenceFinding) =>
    sector === ALL ||
    f.primary_sector?.slug === sector ||
    (f.related_sectors ?? []).some((s) => s.slug === sector);

  const findings = useMemo(() => {
    const list = (data?.intelligence_findings ?? []).filter(matchesSector);
    return [...list].sort((a, b) =>
      (RISK_WEIGHT[b.risk_level] ?? 0) - (RISK_WEIGHT[a.risk_level] ?? 0) ||
      (b.evidence_references?.length ?? 0) - (a.evidence_references?.length ?? 0)
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, sector]);

  const highFindings = findings.filter((f) => f.risk_level === "high" || f.risk_level === "elevated");
  const risks = findings.filter((f) => f.risk_direction === "increasing" || f.risk_level === "high" || f.risk_level === "elevated");
  const opportunities = findings.filter((f) => f.risk_direction === "decreasing" || f.signal_type?.toLowerCase().includes("opportunit"));

  // ── Sector comparison (filtered + normalized) ──
  const comparison = useMemo(() => {
    const rows = (data?.sector_comparison ?? []).filter((c) => sector === ALL || c.sector.slug === sector);
    return rows;
  }, [data, sector]);

  const watchlistMeta = useMemo(() =>
    (data?.sector_watchlist ?? []).reduce((m, s) => { m[s.sector.slug] = s; return m; }, {} as Record<string, OverviewResponse["sector_watchlist"][number]>),
  [data]);

  // ── Cross-source connection chains (real linked records only) ──
  const chains = useMemo(() => buildChains(findings), [findings]);

  // ── Priority metric distributions (current distributions, not trends) ──
  const wl = data?.sector_watchlist ?? [];
  const sectorScores = wl.map((s) => s.score);
  const sectorLobby = wl.map((s) => s.metrics.lobbying);
  const findingsEvidence = highFindings.map((f) => f.evidence_references?.length ?? f.related_records?.length ?? 0);
  const lobbyTotal = wl.reduce((sum, s) => sum + (s.metrics.lobbying || 0), 0);
  const topLobbySector = [...wl].sort((a, b) => b.metrics.lobbying - a.metrics.lobbying)[0]?.sector.slug;
  const regulatory = data?.regulatory_movement ?? [];
  const actors = data?.actor_movement ?? [];
  const activeSectors = wl.filter((s) => s.score >= 4).length;

  const srcSummary = sourceStatus?.summary;
  const liveCount = srcSummary?.live ?? 0;
  const totalSources = srcSummary ? srcSummary.live + srcSummary.partial + srcSummary.empty + srcSummary.planned : 0;
  const staleSources = sourceStatus?.quality?.stale_sources?.length ?? 0;

  if (error) {
    return (
      <div className="animate-rise">
        <PageHead cache={data?.cache?.status} />
        <ErrorState error={error} />
      </div>
    );
  }

  return (
    <div className="animate-rise space-y-gutter">
      <PageHead cache={data?.cache?.status} ttl={data?.cache?.ttl_seconds} />

      {/* ── Filter bar ── */}
      <div className="card-level-1 rounded-lg px-4 py-3 flex flex-wrap items-center gap-x-5 gap-y-3 sticky top-0 z-20">
        <FilterSelect label="Region" icon="public" value={region} onChange={setRegion} options={regionOptions} />
        <FilterSelect label="Sector" icon="category" value={sector} onChange={setSector} options={sectorOptions} />
        <div className="flex items-center gap-2">
          <span className="font-label-caps text-label-caps text-on-surface-variant uppercase">Window</span>
          <Segmented<7 | 30 | 90>
            ariaLabel="Movement window"
            value={windowDays}
            onChange={setWindowDays}
            options={[{ value: 7, label: "7D" }, { value: 30, label: "30D" }, { value: 90, label: "90D" }]}
          />
        </div>
        {(region !== ALL || sector !== ALL) && (
          <button
            onClick={() => { setRegion(ALL); setSector(ALL); }}
            className="font-data-tabular text-data-tabular text-primary hover:underline focus-ring rounded px-1 cursor-pointer"
          >
            Clear filters
          </button>
        )}
        {region !== ALL && (
          <span className="font-data-tabular text-[11px] text-on-surface-variant ml-auto inline-flex items-center gap-1">
            <span className="material-symbols-outlined text-[14px]">info</span>
            Region scopes the map &amp; sector drill-downs; cross-source findings remain Canada-wide.
          </span>
        )}
      </div>

      {/* ── Watchlist strip ── */}
      {watchReady && watched.length > 0 && (
        <div className="card-level-1 rounded-lg px-4 py-3 flex flex-wrap items-center gap-2">
          <span className="font-label-caps text-label-caps text-on-surface-variant uppercase mr-1 inline-flex items-center gap-1">
            <span className="material-symbols-outlined text-[16px] text-warn" style={{ fontVariationSettings: "'FILL' 1" }}>star</span>
            Your watchlist
          </span>
          {watched.map((slug) => {
            const meta = watchlistMeta[slug];
            return (
              <span key={slug} className="inline-flex items-center gap-1 rounded-full border border-outline-variant bg-surface-container-lowest pl-3 pr-1 py-1">
                <Link href={sLink(slug)} className="font-body-md text-[13px] text-primary hover:underline focus-ring rounded">
                  {meta?.sector.name ?? slug}
                </Link>
                <WatchStar active onToggle={() => toggle(slug)} label={meta?.sector.name ?? slug} />
              </span>
            );
          })}
        </div>
      )}

      <div className="grid grid-cols-12 gap-gutter">
        {/* ════════ Main column ════════ */}
        <div className="col-span-12 lg:col-span-8 space-y-gutter">
          {/* Intelligence summary */}
          <IntelligenceSummary
            loading={loading}
            data={data}
            sourceStatus={sourceStatus}
            highCount={highFindings.length}
            activeSectors={wl.length}
            windowDays={windowDays}
            scope={{ region, sector, regionLabel: regionOptions.find((o) => o.value === region)?.label, sectorLabel: sectorOptions.find((o) => o.value === sector)?.label }}
          />

          {/* Priority metrics */}
          <DashSection title="Priority metrics" caption="Each tile opens a filtered internal view." icon="speed">
            {loading ? (
              <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">{Array.from({ length: 6 }).map((_, i) => <div key={i} className="skeleton h-[112px] rounded-lg" />)}</div>
            ) : (
              <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
                <MetricTile label="Material findings" value={num(highFindings.length)} sub="high / elevated" tone={highFindings.length ? "down" : "neutral"} icon="warning" href="/signals" bars={findingsEvidence} />
                <MetricTile label="Sectors active" value={num(activeSectors)} sub={`of ${wl.length} tracked`} tone="neutral" icon="category" href="/sectors" bars={sectorScores} />
                <MetricTile label="Regulatory developments" value={num(regulatory.length)} sub="bills + Gazette" tone="neutral" icon="gavel" href="/records" bars={regulatory.map((r) => ({ High: 3, Medium: 2, Low: 1 }[r.impact] ?? 1))} />
                <MetricTile label="Political attention" value={num(actors.length)} sub="House interventions" tone="neutral" icon="campaign" href="/politicians" />
                <MetricTile label="Lobbying activity" value={num(lobbyTotal)} sub="communications, tracked sectors" tone="neutral" icon="record_voice_over" href={sLink(topLobbySector)} bars={sectorLobby} />
                <MetricTile
                  label="Source coverage"
                  value={srcSummary ? `${liveCount}/${totalSources}` : "—"}
                  sub={srcSummary ? `${srcSummary.partial} partial · ${srcSummary.planned} planned` : "loading"}
                  tone={staleSources ? "warn" : "neutral"}
                  icon="dataset"
                  href="/sources"
                  caution={staleSources ? `${staleSources} stale source${staleSources > 1 ? "s" : ""}` : undefined}
                />
              </div>
            )}
          </DashSection>

          {/* What changed — primary ranked findings */}
          <DashSection
            title="What changed"
            icon="bolt"
            caption="Ranked cross-source findings — commercial interpretation, affected sectors, confidence and evidence."
            action={<Link href="/signals" className="font-label-caps text-label-caps text-primary uppercase hover:underline focus-ring rounded inline-flex items-center gap-1">Live feed <span className="material-symbols-outlined text-[16px]">arrow_forward</span></Link>}
          >
            {loading ? (
              <div className="space-y-3">{[0, 1, 2].map((i) => <div key={i} className="skeleton h-28 rounded-lg" />)}</div>
            ) : findings.length ? (
              <div className="space-y-3">
                {findings.slice(0, 5).map((f) => <ChangedRow key={f.title} finding={f} />)}
              </div>
            ) : (
              <EmptyState>
                {sector !== ALL
                  ? "No connected findings for this sector at current data depth. Clear the sector filter or ingest more source data."
                  : "No connected findings yet. Ingest source data, then refresh the workspace."}
              </EmptyState>
            )}
          </DashSection>

          {/* Sector comparison */}
          <DashSection
            title="Sector comparison"
            icon="bar_chart"
            caption="Evidence-normalized — raw source volume is not treated as risk by itself."
            action={<Link href="/sectors" className="font-label-caps text-label-caps text-primary uppercase hover:underline focus-ring rounded inline-flex items-center gap-1">All sectors <span className="material-symbols-outlined text-[16px]">arrow_forward</span></Link>}
          >
            {loading ? (
              <div className="space-y-2">{[0, 1, 2, 3].map((i) => <div key={i} className="skeleton h-20 rounded-lg" />)}</div>
            ) : comparison.length ? (
              <SectorComparison rows={comparison} windowDays={windowDays} sLink={sLink} isWatched={isWatched} toggle={toggle} />
            ) : (
              <EmptyState>No sector comparison available.</EmptyState>
            )}
          </DashSection>

          {/* Cross-source connections */}
          <DashSection
            title="Cross-source connections"
            icon="account_tree"
            caption="Readable relationship chains across sources. Every node opens its record."
            action={<Link href="/explorer" className="font-label-caps text-label-caps text-primary uppercase hover:underline focus-ring rounded inline-flex items-center gap-1">Evidence graph <span className="material-symbols-outlined text-[16px]">arrow_forward</span></Link>}
          >
            {loading ? (
              <div className="space-y-2">{[0, 1].map((i) => <div key={i} className="skeleton h-16 rounded-lg" />)}</div>
            ) : chains.length ? (
              <div className="space-y-3">
                {chains.map((c, i) => (
                  <div key={i} className="card-level-1 rounded-lg p-4">
                    <p className="font-body-md text-body-md text-on-surface mb-2.5 leading-snug">{c.summary}</p>
                    <ConnectionChain nodes={c.nodes} />
                  </div>
                ))}
              </div>
            ) : (
              <EmptyState>No multi-source chains at current data depth. Chains appear once a finding links two or more sources.</EmptyState>
            )}
          </DashSection>

          {/* Risks & opportunities */}
          <DashSection title="Risks &amp; opportunities" icon="balance" caption="Separated by detected risk direction, with recommended diligence questions.">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-gutter">
              <RiskOppColumn kind="risk" findings={risks} loading={loading} />
              <RiskOppColumn kind="opportunity" findings={opportunities} loading={loading} />
            </div>
          </DashSection>
        </div>

        {/* ════════ Aside ════════ */}
        <aside className="col-span-12 lg:col-span-4 space-y-gutter">
          <div className="lg:sticky lg:top-16 space-y-gutter">
            {/* Investigation */}
            <div className="card-level-1 rounded-lg p-5">
              <h3 className="font-label-caps text-label-caps text-on-surface-variant uppercase mb-3">Investigation</h3>
              <div className="space-y-2.5">
                <Link href="/search" className="w-full bg-primary text-on-primary py-2.5 px-4 rounded font-body-md text-body-md font-bold flex items-center justify-between hover:bg-primary-container transition-colors focus-ring">
                  <span>Ask Nessus</span><span className="material-symbols-outlined text-[20px]">forum</span>
                </Link>
                <Link href="/explorer" className="w-full bg-surface text-primary border border-outline-variant py-2.5 px-4 rounded font-body-md text-body-md font-bold flex items-center justify-between hover:bg-surface-container-low transition-colors focus-ring">
                  <span>Open evidence graph</span><span className="material-symbols-outlined text-[20px]">hub</span>
                </Link>
              </div>
            </div>

            {/* Regional exposure map */}
            <div className="card-level-1 rounded-lg overflow-hidden">
              <div className="panel-head"><span className="eyebrow !text-on-surface-variant flex-1">Regional exposure</span>
                {region !== ALL && <button onClick={() => setRegion(ALL)} className="font-data-tabular text-[11px] text-primary hover:underline focus-ring rounded cursor-pointer">Reset</button>}
              </div>
              <div className="p-3">
                {data?.regional_exposure?.length ? (
                  <>
                    <CanadaMap rows={data.regional_exposure.map((r) => ({ ...r, amount: 0 }))} selected={region === ALL ? null : region} onSelect={(c) => setRegion(c ?? ALL)} metric="records" />
                    <p className="font-data-tabular text-[11px] text-on-surface-variant mt-1 text-center">Operational/source records by province. Click a province to filter.</p>
                  </>
                ) : <EmptyState>No province-tagged records yet.</EmptyState>}
              </div>
            </div>

            {/* Regulatory timeline */}
            <div className="card-level-1 rounded-lg overflow-hidden">
              <div className="panel-head"><span className="eyebrow !text-on-surface-variant flex-1">Regulatory timeline</span></div>
              <div className="p-4">
                <RegulatoryTimeline items={regulatory} loading={loading} />
                <p className="font-data-tabular text-[11px] text-on-surface-variant mt-3 pt-3 border-t border-outline-variant">
                  Dated legislative &amp; regulatory activity. Forward consultation deadlines &amp; committee calendars are planned, not yet ingested.
                </p>
              </div>
            </div>

            {/* Source health */}
            <div className="card-level-1 rounded-lg overflow-hidden">
              <div className="panel-head">
                <span className="eyebrow !text-on-surface-variant flex-1">Source health</span>
                <Link href="/sources" className="font-label-caps text-label-caps text-primary uppercase hover:underline focus-ring rounded">All</Link>
              </div>
              <div className="p-4">
                {sourceStatus ? (
                  <>
                    <div className="flex items-center gap-2 mb-3 flex-wrap font-data-tabular text-[11px]">
                      <HealthPill tone="up" label={`${srcSummary?.live ?? 0} live`} />
                      <HealthPill tone="warn" label={`${srcSummary?.partial ?? 0} partial`} />
                      <HealthPill tone="neutral" label={`${srcSummary?.empty ?? 0} empty`} />
                      <HealthPill tone="muted" label={`${srcSummary?.planned ?? 0} planned`} />
                    </div>
                    <SourceCoverageList items={sourceStatus.sources} limit={7} />
                    {sourceStatus.quality?.explicit_gaps?.length ? (
                      <p className="font-data-tabular text-[11px] text-on-surface-variant mt-3 pt-3 border-t border-outline-variant">
                        Coverage gaps in {sourceStatus.quality.explicit_gaps.slice(0, 3).map((g) => g.label).join(", ")}
                        {sourceStatus.quality.explicit_gaps.length > 3 ? " and others" : ""} can affect cross-source analysis.
                      </p>
                    ) : null}
                  </>
                ) : (
                  <div className="space-y-2">{[0, 1, 2, 3].map((i) => <div key={i} className="skeleton h-7 rounded" />)}</div>
                )}
              </div>
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}

// ════════ Sub-components ════════

function PageHead({ cache, ttl }: { cache?: string; ttl?: number }) {
  return (
    <div className="flex flex-wrap justify-between items-end gap-4 border-b border-outline-variant pb-3">
      <div>
        <h1 className="font-sans font-semibold text-headline-md md:text-display-lg text-primary leading-tight tracking-tight">Intelligence Dashboard</h1>
        <p className="font-body-lg text-body-lg text-on-surface-variant mt-1">What changed, what matters commercially, and what to investigate next — across Canadian political &amp; regulatory sources.</p>
      </div>
      <div className="text-right shrink-0">
        <span className="font-label-caps text-label-caps bg-primary-container/10 text-primary px-2 py-1 rounded inline-flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-up" /> LIVE WORKSPACE
        </span>
        {cache ? <div className="font-data-tabular text-[11px] text-on-surface-variant mt-1.5">Cache: {cache}{ttl ? ` · ${Math.round(ttl / 60)}-min refresh` : ""}</div> : null}
      </div>
    </div>
  );
}

function IntelligenceSummary({
  loading, data, sourceStatus, highCount, activeSectors, windowDays, scope,
}: {
  loading: boolean;
  data: OverviewResponse | null;
  sourceStatus: SourceStatusResponse | null;
  highCount: number;
  activeSectors: number;
  windowDays: number;
  scope: { region: string; sector: string; regionLabel?: string; sectorLabel?: string };
}) {
  const confidence = sourceStatus?.quality?.confidence;
  const scoped = scope.region !== ALL || scope.sector !== ALL;
  return (
    <section aria-label="Intelligence summary" className="card-level-1 rounded-lg p-5 relative overflow-hidden">
      <div className="absolute right-0 top-0 w-56 h-full bg-gradient-to-l from-surface-container-low to-transparent pointer-events-none opacity-60" />
      <div className="relative">
        <div className="flex items-center justify-between gap-3 mb-3">
          <h2 className="font-sans text-[18px] font-semibold tracking-tight text-primary flex items-center gap-2">
            <span className="material-symbols-outlined text-[19px] text-on-surface-variant">summarize</span> Intelligence summary
          </h2>
          <span className="font-data-tabular text-[11px] text-on-surface-variant">{windowDays}-day movement window</span>
        </div>

        {loading ? (
          <div className="space-y-2"><div className="skeleton h-4 w-full rounded" /><div className="skeleton h-4 w-5/6 rounded" /><div className="skeleton h-4 w-2/3 rounded" /></div>
        ) : (
          <>
            <p className="font-body-lg text-body-lg leading-relaxed text-on-surface max-w-2xl">
              {data?.what_changed?.summary ?? "Nessus is waiting for enough source history to calculate period-over-period movement."}
            </p>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-4">
              <SummaryStat label="Material changes" value={num(highCount)} tone={highCount ? "down" : "neutral"} />
              <SummaryStat label="Active sector lenses" value={num(activeSectors)} tone="neutral" />
              <SummaryStat label="Movement status" value="Insufficient history" small tone="warn" />
              <SummaryStat label="Confidence" value={confidence ? confidence[0].toUpperCase() + confidence.slice(1) : "—"} small tone={confidence === "high" ? "up" : confidence === "low" ? "down" : "warn"} />
            </div>

            {(data?.what_changed?.requires_attention?.length ?? 0) > 0 && (
              <div className="mt-4 flex flex-wrap items-center gap-2">
                <span className="font-label-caps text-label-caps text-on-surface-variant uppercase">Requires attention</span>
                {data!.what_changed!.requires_attention!.map((s) => (
                  <Link key={s.slug} href={sectorHref(s.slug) ?? "/sectors"} className="font-data-tabular text-data-tabular text-primary border border-outline-variant rounded-full px-2.5 py-0.5 hover:border-primary transition-colors focus-ring">
                    {s.name}
                  </Link>
                ))}
              </div>
            )}

            <p className="font-data-tabular text-[12px] text-on-surface-variant mt-4 pt-3 border-t border-outline-variant leading-relaxed">
              <span className="material-symbols-outlined text-[14px] align-middle mr-1">info</span>
              {data?.what_changed?.source_limits ?? "Unequal source coverage can explain apparent sector differences."}
              {scoped ? ` Scope: ${scope.regionLabel ?? "All Canada"} · ${scope.sectorLabel ?? "All sectors"}.` : ""}
            </p>
          </>
        )}
      </div>
    </section>
  );
}

function SummaryStat({ label, value, tone = "neutral", small }: { label: string; value: string; tone?: string; small?: boolean }) {
  const color = tone === "down" ? "var(--color-down)" : tone === "up" ? "var(--color-up)" : tone === "warn" ? "var(--color-warn)" : "var(--color-fg-bright)";
  return (
    <div className="rounded border border-outline-variant bg-surface-container-lowest px-3 py-2.5">
      <div className="font-label-caps text-[10px] text-on-surface-variant uppercase leading-tight">{label}</div>
      <div className={`mono ${small ? "text-[14px]" : "text-[24px]"} font-bold leading-tight mt-1`} style={{ color }}>{value}</div>
    </div>
  );
}

function ChangedRow({ finding }: { finding: IntelligenceFinding }) {
  const href = `${findingHref(finding) ?? "/signals"}?from=dashboard`;
  const evidenceCount = finding.evidence_references?.length ?? finding.related_records?.length ?? 0;
  const accent = finding.risk_level === "high" || finding.risk_level === "elevated" ? "var(--color-down)" : finding.risk_level === "moderate" ? "var(--color-warn)" : "var(--color-outline-variant)";
  const dirGlyph = { increasing: "trending_up", decreasing: "trending_down", stable: "trending_flat", unclear: "help" }[finding.risk_direction] ?? "trending_flat";
  return (
    <article className="card-level-1 card-level-2 rounded-lg p-4 border-l-[3px]" style={{ borderLeftColor: accent }}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-1.5 mb-1.5">
            <RiskChip level={finding.risk_level} />
            <ConfidenceDot value={finding.confidence} />
            <span className="font-label-caps text-[9px] uppercase tracking-wide text-on-surface-variant border border-outline-variant rounded px-1.5 py-0.5">{finding.interpretation_type}</span>
            {finding.primary_sector && (
              <Link href={sectorHref(finding.primary_sector.slug) ?? "/sectors"} className="font-label-caps text-[9px] uppercase tracking-wide text-primary bg-primary/5 rounded px-1.5 py-0.5 hover:underline focus-ring">{finding.primary_sector.name}</Link>
            )}
          </div>
          <Link href={href} className="font-sans text-[17px] font-semibold leading-snug text-primary hover:underline focus-ring rounded block">{finding.title}</Link>
          <p className="font-body-md text-body-md text-on-surface-variant mt-1 leading-snug line-clamp-2">{finding.concise_summary || finding.why_it_matters}</p>
        </div>
        <div className="flex flex-col items-end gap-1 shrink-0">
          <span className="material-symbols-outlined text-[20px] text-on-surface-variant" title={`Risk direction: ${finding.risk_direction}`}>{dirGlyph}</span>
          <span className="font-data-tabular text-[11px] text-on-surface-variant">{finding.recency}</span>
        </div>
      </div>
      <div className="flex items-center justify-between gap-3 mt-3 pt-2.5 border-t border-outline-variant">
        <div className="flex items-center gap-3 min-w-0 flex-wrap">
          {(finding.related_sectors ?? []).slice(0, 3).map((s) => (
            <Link key={s.slug} href={sectorHref(s.slug) ?? "/sectors"} className="font-data-tabular text-[11px] text-on-surface-variant hover:text-primary focus-ring rounded">#{s.name}</Link>
          ))}
        </div>
        <div className="flex items-center gap-3 shrink-0">
          <span className="font-data-tabular text-[11px] text-on-surface-variant inline-flex items-center gap-1"><span className="material-symbols-outlined text-[14px]">database</span>{evidenceCount} evidence</span>
          <Link href={href} className="font-label-caps text-label-caps text-primary uppercase hover:underline focus-ring rounded inline-flex items-center gap-0.5">Open <span className="material-symbols-outlined text-[15px]">arrow_forward</span></Link>
        </div>
      </div>
    </article>
  );
}

function SectorComparison({
  rows, windowDays, sLink, isWatched, toggle,
}: {
  rows: OverviewResponse["sector_comparison"];
  windowDays: 7 | 30 | 90;
  sLink: (slug?: string | null) => string;
  isWatched: (slug: string) => boolean;
  toggle: (slug: string) => void;
}) {
  const maxReg = Math.max(1, ...rows.map((r) => r.regulatory_activity));
  const maxPol = Math.max(1, ...rows.map((r) => r.political_attention));
  const maxLob = Math.max(1, ...rows.map((r) => r.lobbying_intensity));
  return (
    <div className="space-y-2.5">
      {rows.map((r) => (
        <div key={r.sector.slug} className="card-level-1 card-level-2 rounded-lg p-4">
          <div className="flex items-center justify-between gap-3 mb-2.5">
            <div className="flex items-center gap-2 min-w-0">
              <WatchStar active={isWatched(r.sector.slug)} onToggle={() => toggle(r.sector.slug)} label={r.sector.name} />
              <Link href={sLink(r.sector.slug)} className="font-sans text-[15px] font-semibold text-primary hover:underline focus-ring rounded truncate">{r.sector.name}</Link>
              <RiskChip level={r.risk_band} />
            </div>
            <div className="flex items-center gap-3 shrink-0">
              <MovementPips windows={r.movement as MovementWindow[]} active={windowDays} />
              <ConfidenceDot value={r.confidence} />
            </div>
          </div>
          <div className="grid grid-cols-3 gap-3">
            <IntensityBar label="Regulatory" value={r.regulatory_activity} max={maxReg} href={sLink(r.sector.slug)} />
            <IntensityBar label="Political" value={r.political_attention} max={maxPol} href={sLink(r.sector.slug)} />
            <IntensityBar label="Lobbying" value={r.lobbying_intensity} max={maxLob} href={sLink(r.sector.slug)} />
          </div>
          <div className="flex items-center justify-between gap-2 mt-2.5">
            <span className="font-data-tabular text-[11px] text-on-surface-variant capitalize inline-flex items-center gap-1">
              <span className="material-symbols-outlined text-[13px]">dataset</span>{r.source_coverage} coverage
            </span>
            <Link href={sLink(r.sector.slug)} className="font-label-caps text-label-caps text-primary uppercase hover:underline focus-ring rounded">Open sector</Link>
          </div>
        </div>
      ))}
    </div>
  );
}

function IntensityBar({ label, value, max, href }: { label: string; value: number; max: number; href: string }) {
  return (
    <Link href={href} className="block focus-ring rounded group">
      <div className="flex items-baseline justify-between mb-1">
        <span className="font-label-caps text-[10px] text-on-surface-variant uppercase">{label}</span>
        <span className="font-data-tabular text-[12px] text-on-surface group-hover:text-primary">{num(value)}</span>
      </div>
      <div className="h-2 rounded-full bg-surface-variant overflow-hidden">
        <div className="h-full rounded-full" style={{ width: `${Math.max(4, (value / max) * 100)}%`, background: "var(--color-primary)", transition: "width .5s ease" }} />
      </div>
    </Link>
  );
}

function RiskOppColumn({ kind, findings, loading }: { kind: "risk" | "opportunity"; findings: IntelligenceFinding[]; loading: boolean }) {
  const isRisk = kind === "risk";
  const color = isRisk ? "var(--color-down)" : "var(--color-up)";
  return (
    <div className="card-level-1 rounded-lg overflow-hidden">
      <div className="panel-head" style={{ borderTop: `2px solid ${color}` }}>
        <span className="eyebrow flex-1 flex items-center gap-1.5" style={{ color }}>
          <span className="material-symbols-outlined text-[16px]">{isRisk ? "trending_up" : "trending_down"}</span>
          {isRisk ? "Risks" : "Opportunities"}
        </span>
        <span className="font-data-tabular text-[11px] text-on-surface-variant">{findings.length}</span>
      </div>
      <div className="p-4 space-y-3">
        {loading ? (
          <><div className="skeleton h-20 rounded" /><div className="skeleton h-20 rounded" /></>
        ) : findings.length ? (
          findings.slice(0, 3).map((f) => {
            const ev = (f.related_records ?? [])[0];
            const evHref = ev ? evidenceHref(ev) : f.evidence_references?.[0]?.internal_url;
            return (
              <div key={f.title} className="rounded border border-outline-variant bg-surface-container-lowest p-3">
                <Link href={`${findingHref(f) ?? "/signals"}?from=dashboard`} className="font-body-md text-body-md font-bold text-primary leading-snug hover:underline focus-ring rounded block">{f.title}</Link>
                <p className="font-body-md text-[13px] text-on-surface-variant mt-1 leading-snug line-clamp-2">{f.concise_summary || f.why_it_matters}</p>
                {f.suggested_questions?.[0] && (
                  <div className="mt-2 flex items-start gap-1.5">
                    <span className="material-symbols-outlined text-[14px] text-on-surface-variant mt-0.5">help</span>
                    <span className="font-body-md text-[12px] text-on-surface italic leading-snug">{f.suggested_questions[0]}</span>
                  </div>
                )}
                {evHref && (
                  <Link href={evHref} className="font-label-caps text-label-caps text-primary uppercase mt-2 inline-flex items-center gap-1 hover:underline focus-ring rounded">
                    <span className="material-symbols-outlined text-[14px]">database</span>Evidence
                  </Link>
                )}
              </div>
            );
          })
        ) : (
          <EmptyState>
            {isRisk
              ? "No increasing-risk findings in scope."
              : "Polaris has not detected decreasing-risk or opportunity signals at current data depth."}
          </EmptyState>
        )}
      </div>
    </div>
  );
}

function RegulatoryTimeline({ items, loading }: { items: OverviewResponse["regulatory_movement"]; loading: boolean }) {
  const dated = items.filter((i) => i.date).slice(0, 6);
  if (loading) return <div className="space-y-3">{[0, 1, 2, 3].map((i) => <div key={i} className="skeleton h-10 rounded" />)}</div>;
  if (!dated.length) return <EmptyState>No dated regulatory activity available.</EmptyState>;
  return (
    <div className="relative pl-4">
      <span className="absolute left-[5px] top-1 bottom-1 w-px bg-outline-variant" aria-hidden="true" />
      {dated.map((item) => {
        const href = recordHref(item.table, item.pk) ?? item.url ?? "/records";
        const tone = item.impact === "High" ? "var(--color-down)" : item.impact === "Medium" ? "var(--color-warn)" : "var(--color-on-surface-variant)";
        return (
          <Link key={`${item.table}-${item.pk ?? item.title}`} href={href} className="relative block py-2 pl-3 hover:bg-surface-container-low rounded -ml-1 focus-ring">
            <span className="absolute -left-[3px] top-3.5 w-2 h-2 rounded-full" style={{ background: tone }} aria-hidden="true" />
            <div className="flex items-center justify-between gap-2">
              <span className="font-data-tabular text-[11px] text-on-surface-variant">{item.date}</span>
              <span className="font-label-caps text-[9px] uppercase tracking-wide" style={{ color: tone }}>{item.impact} · {item.kind}</span>
            </div>
            <p className="font-body-md text-[13px] text-primary leading-snug line-clamp-2 mt-0.5">{item.title}</p>
            <span className="font-data-tabular text-[11px] text-on-surface-variant">{item.body}</span>
          </Link>
        );
      })}
    </div>
  );
}

// ════════ helpers ════════

interface Chain { summary: string; nodes: ChainNode[] }

function tableKind(table?: string): ChainNode["kind"] {
  switch (table) {
    case "bills": case "gazette": case "tribunal": case "tribunal_decisions": return "regulatory";
    case "lobbying": case "lobbying_records": return "lobbying";
    case "hansard_mentions": return "actor";
    default: return "record";
  }
}

function buildChains(findings: IntelligenceFinding[]): Chain[] {
  const out: Chain[] = [];
  for (const f of findings) {
    const recs = (f.related_records ?? []).filter((r) => r.table && (r.pk ?? r.id) != null);
    const distinctTables = new Set(recs.map((r) => r.table));
    if (recs.length < 2 || distinctTables.size < 2) continue;
    const nodes: ChainNode[] = recs.slice(0, 3).map((r: EvidenceRef) => ({
      label: r.title,
      sub: r.source,
      href: recordHref(r.table, r.pk ?? r.id),
      kind: tableKind(r.table),
    }));
    if (f.primary_sector) {
      nodes.push({ label: f.primary_sector.name, sub: "affected sector", href: sectorHref(f.primary_sector.slug), kind: "sector" });
    }
    out.push({ summary: f.concise_summary || f.title, nodes });
    if (out.length >= 4) break;
  }
  return out;
}

function RiskChip({ level }: { level?: string | null }) {
  const l = (level ?? "unknown").toLowerCase();
  const cls = l.includes("high") || l.includes("elevated")
    ? "status-chip-red"
    : l.includes("moderate") || l.includes("medium") || l.includes("watch")
    ? "status-chip-amber"
    : "status-chip-green";
  return <span className={`font-label-caps text-label-caps ${cls} px-2 py-0.5 rounded-full uppercase`}>{level ?? "unknown"}</span>;
}

function HealthPill({ tone, label }: { tone: "up" | "warn" | "neutral" | "muted"; label: string }) {
  const color = tone === "up" ? "var(--color-up)" : tone === "warn" ? "var(--color-warn)" : tone === "muted" ? "var(--color-on-surface-variant)" : "var(--color-on-surface-variant)";
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-outline-variant px-2 py-0.5">
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: color }} />{label}
    </span>
  );
}

function EmptyState({ children }: { children: ReactNode }) {
  return <div className="rounded border border-outline-variant bg-surface-container-low px-4 py-4 font-body-md text-body-md text-on-surface-variant text-center">{children}</div>;
}

function ErrorState({ error }: { error: string }) {
  return (
    <div className="rounded-lg border border-error/30 bg-error/10 px-4 py-4 mt-gutter">
      <div className="flex items-center gap-2 text-error font-body-md text-body-md font-bold"><span className="material-symbols-outlined">error</span>Workspace data unavailable</div>
      <p className="font-data-tabular text-data-tabular text-error/80 mt-1">{error}</p>
      <p className="font-body-md text-body-md text-on-surface-variant mt-2">The FastAPI backend may be offline. Start it on :8077 and refresh.</p>
    </div>
  );
}
