"use client";

import Link from "next/link";
import { use } from "react";
import { money, num, recordHref, riskBand, type EntityProfile } from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { ConnectionCard, RiskGauge, Scorecard } from "@/components/charts";
import { BarList, TrendArea, TrendBars } from "@/components/dataviz";
import { Eyebrow, Panel, SkeletonBlock, SourceTag } from "@/components/ui";

const BAND_LABEL: Record<string, string> = { high: "ELEVATED", medium: "MODERATE", low: "CONTAINED" };
const BAND_COLOR: Record<string, string> = { high: "var(--color-risk-high)", medium: "var(--color-risk-med)", low: "var(--color-risk-low)" };

export default function EntityPage({ params }: { params: Promise<{ canonical: string }> }) {
  const { canonical } = use(params);
  const name = decodeURIComponent(canonical);
  const { data, loading, error } = useApi<EntityProfile>(`/api/entities/${encodeURIComponent(name)}`);

  if (error) {
    return (
      <div className="mx-auto max-w-[1320px] px-4 py-20 text-center text-fg-dim">
        Couldn&rsquo;t load this entity. {error}
        <div className="mt-3"><Link href="/entities" className="text-brass-bright underline">← Entity lookup</Link></div>
      </div>
    );
  }
  if (loading || !data) {
    return (
      <div>
        <div className="bg-panel border-b border-line"><div className="mx-auto max-w-[1320px] px-4 py-5 space-y-3">
          <SkeletonBlock className="h-4 w-40" /><SkeletonBlock className="h-8 w-72" /><SkeletonBlock className="h-16 w-full" />
        </div></div>
        <div className="mx-auto max-w-[1320px] px-4 py-4 grid grid-cols-12 gap-3">
          {Array.from({ length: 6 }).map((_, i) => <SkeletonBlock key={i} className="h-40 rounded col-span-12 sm:col-span-6 lg:col-span-4" />)}
        </div>
      </div>
    );
  }

  const { scores, evidence, connections, trends } = data;
  const band = riskBand(scores.overall);
  const KPIS = [
    { label: "Overall Risk", value: scores.overall.toFixed(1), tone: BAND_COLOR[band] },
    { label: "Contract $", value: money(evidence.contracts.total_value) },
    { label: "Contracts", value: num(evidence.contracts.count) },
    { label: "Lobbying", value: num(evidence.lobbying.count) },
    { label: "Bills", value: num(evidence.bills.count) },
    { label: "Donations", value: num(evidence.donations.count) },
  ];

  return (
    <div className="animate-rise">
      <section className="bg-panel border-b border-line map-grid">
        <div className="mx-auto max-w-[1320px] px-4 py-5">
          <div className="mono text-xs text-fg-dim mb-3 flex items-center gap-2">
            <Link href="/entities" className="hover:text-brass">ENTITIES</Link>
            <span className="text-line">/</span>
            <span className="text-fg uppercase">{data.canonical}</span>
          </div>
          <div className="grid lg:grid-cols-[1fr_auto] gap-6 items-start">
            <div>
              <Eyebrow>Entity Intelligence{data.sector ? ` · ${data.sector.name}` : ""}</Eyebrow>
              <h1 className="text-3xl font-semibold text-fg-bright mt-1.5 capitalize leading-tight">{data.canonical}</h1>
              <p className="text-fg/80 mt-2 max-w-3xl text-sm leading-relaxed">{data.narrative}</p>
              {data.sector && (
                <Link href={`/sectors/${data.sector.slug}`} className="inline-flex items-center gap-1.5 mt-3 mono text-xs text-brass-bright hover:text-fg transition-colors">
                  → {data.sector.name} sector intelligence
                </Link>
              )}
            </div>
            <div className="flex items-center gap-4 panel bg-panel-2 px-5 py-3">
              <RiskGauge score={scores.overall} size={120} />
              <div>
                <div className="eyebrow !text-fg-dim">Risk Band</div>
                <div className="mono text-lg font-semibold" style={{ color: BAND_COLOR[band] }}>{BAND_LABEL[band]}</div>
              </div>
            </div>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-px bg-line mt-5 border border-line rounded overflow-hidden">
            {KPIS.map((k) => (
              <div key={k.label} className="bg-panel px-3 py-2.5">
                <div className="eyebrow !text-fg-dim !text-[9px] mb-1 truncate">{k.label}</div>
                <div className="mono text-lg font-semibold" style={{ color: k.tone || "var(--color-fg-bright)" }}>{k.value}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <div className="mx-auto max-w-[1320px] px-4 py-4 grid grid-cols-12 gap-3">
        <Panel className="col-span-12 sm:col-span-6" title="Federal Contract Spend / yr" right={<span className="mono text-[10px] text-brass">$</span>}>
          <TrendArea data={trends.contracts} asMoney color="var(--color-brass)" />
        </Panel>
        <Panel className="col-span-12 sm:col-span-6" title="Lobbying Cadence / yr" right={<span className="mono text-[10px] text-up">COMMS</span>}>
          <TrendBars data={trends.lobbying} color="var(--color-up)" />
        </Panel>

        <Panel className="col-span-12 lg:col-span-8" title="Key Connections — cross-source signals">
          {connections.length ? (
            <div className="grid sm:grid-cols-2 gap-2.5">{connections.map((c, i) => <ConnectionCard key={i} c={c} />)}</div>
          ) : (
            <p className="text-sm text-fg-dim">No notable cross-source patterns for this entity.</p>
          )}
        </Panel>
        <Panel className="col-span-12 lg:col-span-4" title="Risk Scorecard">
          <Scorecard scores={scores} />
        </Panel>

        <Panel className="col-span-12 sm:col-span-6" title="Contracting Departments">
          <BarList items={evidence.contracts.by_department.slice(0, 6).map((d) => ({ label: d.dept || "—", value: d.value }))} asMoney color="var(--color-warn)" />
        </Panel>
        <Panel className="col-span-12 sm:col-span-6" title="Institutions Lobbied">
          <BarList items={evidence.lobbying.top_institutions.slice(0, 6).map((t) => ({ label: t.institution, value: t.count }))} />
        </Panel>

        <Panel className="col-span-12 sm:col-span-6 lg:col-span-4" title={`Legislation · ${evidence.bills.count}`}>
          {evidence.bills.records.length ? (
            <div className="space-y-2.5">
              {evidence.bills.records.slice(0, 5).map((b, i) => (
                <Link key={i} href={recordHref(b.table, b.id) || "#"} className="group block border-b border-line/60 last:border-0 pb-2.5 last:pb-0 hover:bg-panel-2 -mx-1 px-1 rounded">
                  <div className="mono text-[10px] text-brass-bright">{b.bill_number}</div>
                  <div className="text-[13px] text-fg leading-snug group-hover:text-brass-bright transition-colors">{b.title_en}</div>
                  {b.status && <div className="text-xs text-fg-dim mt-0.5">{b.status}</div>}
                </Link>
              ))}
            </div>
          ) : <p className="text-sm text-fg-dim">No related bills.</p>}
        </Panel>

        <Panel className="col-span-12 sm:col-span-6 lg:col-span-4" title="Contributions">
          <div className="mono text-3xl font-semibold text-fg-bright">{num(evidence.donations.count)}</div>
          <p className="text-sm text-fg-dim mt-1">{money(evidence.donations.total_value)} in political contributions on file.</p>
        </Panel>

        {evidence.breadth.records.length > 0 && (
          <Panel className="col-span-12 lg:col-span-4" title={`Operations · ${evidence.breadth.count}`}>
            <div className="space-y-2">
              {evidence.breadth.records.slice(0, 5).map((e, i) => (
                <Link key={i} href={recordHref(e.table, e.id) || "#"} className="group flex items-start gap-2 border-b border-line/60 last:border-0 pb-2 last:pb-0 hover:bg-panel-2 -mx-1 px-1 rounded">
                  <SourceTag>{e.source}</SourceTag>
                  <span className="text-[13px] text-fg group-hover:text-brass-bright leading-snug flex-1 transition-colors">{e.title}</span>
                </Link>
              ))}
            </div>
          </Panel>
        )}
      </div>
    </div>
  );
}
