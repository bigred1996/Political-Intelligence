"use client";

import Link from "next/link";
import { useState } from "react";
import { num, type EntityProfile, type OverviewResponse, type ReportsResponse, type SectorsResponse } from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { BarList, CanadaMap, RadialNetwork } from "@/components/dataviz";
import { Panel, RiskBadge, SkeletonBlock } from "@/components/ui";

const IMPACT_CLS: Record<string, string> = {
  High: "bg-down/15 text-down border-down/40",
  Medium: "bg-warn/15 text-warn border-warn/40",
  Low: "bg-fg-dim/15 text-fg-dim border-fg-dim/30",
};
function Impact({ v }: { v: string }) {
  return <span className={`mono text-[9px] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded border ${IMPACT_CLS[v] ?? IMPACT_CLS.Low}`}>{v}</span>;
}

const FEATURED = ["enbridge", "telus", "royal bank of", "loblaw", "bombardier", "barrick gold"];

export default function Overview() {
  const { data: ov, loading } = useApi<OverviewResponse>("/api/overview");
  const { data: sectors } = useApi<SectorsResponse>("/api/sectors");
  const { data: reports } = useApi<ReportsResponse>("/api/reports");
  const [featured, setFeatured] = useState(FEATURED[0]);
  const { data: ent } = useApi<EntityProfile>(`/api/entities/${encodeURIComponent(featured)}`);

  const networkNodes = ent
    ? [
        ...ent.evidence.lobbying.top_institutions.slice(0, 3).map((t) => ({ label: t.institution, sub: "Regulator", type: "regulatory" as const })),
        ...ent.evidence.contracts.by_department.slice(0, 2).map((d) => ({ label: d.dept || "—", sub: "Funder", type: "funding" as const })),
        ...ent.evidence.bills.records.slice(0, 2).map((b) => ({ label: b.bill_number, sub: "Policy", type: "policy" as const })),
      ]
    : [];

  return (
    <div className="p-3 sm:p-4">
      {/* Title bar */}
      <div className="flex flex-wrap items-end justify-between gap-3 mb-3">
        <div>
          <h1 className="text-xl font-semibold text-fg-bright">Canadian Political Landscape</h1>
          <p className="text-sm text-fg-dim">Decode the landscape — by sector, region and entity.</p>
        </div>
        <div className="mono text-[11px] text-fg-dim flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-up animate-pulse" /> Live · {sectors?.count ?? "—"} sectors · 14 sources
        </div>
      </div>

      <div className="grid grid-cols-12 gap-3 auto-rows-min">
        {/* Regional exposure */}
        <Panel className="col-span-12 lg:col-span-5" title="Sector Exposure by Region" bodyClass="p-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              {ov ? <CanadaMap rows={ov.regional_exposure.map((r) => ({ ...r, amount: 0 }))} metric="records" /> : <SkeletonBlock className="h-64" />}
            </div>
            <div>
              <div className="grid grid-cols-[1fr_auto] text-[10px] mono uppercase text-fg-dim border-b border-line pb-1 mb-1">
                <span>Region</span><span>Exposure</span>
              </div>
              <div className="space-y-1">
                {(ov?.regional_exposure ?? []).slice(0, 9).map((r) => (
                  <div key={r.code} className="grid grid-cols-[1fr_auto] items-center gap-2 text-[13px]">
                    <span className="text-fg truncate">{r.province}</span>
                    <span className="flex items-center gap-2">
                      <span className="w-14 h-1 rounded-full bg-panel-2 overflow-hidden inline-block">
                        <span className="block h-full rounded-full" style={{ width: `${r.score}%`, background: "var(--color-brass)" }} />
                      </span>
                      <span className="mono text-fg-bright w-7 text-right">{r.score}</span>
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </Panel>

        {/* Regulatory movement */}
        <Panel className="col-span-12 sm:col-span-6 lg:col-span-4" title="Regulatory Movement" bodyClass="p-0">
          <div className="max-h-[320px] overflow-y-auto no-scrollbar divide-y divide-line/60">
            {loading
              ? <div className="p-4"><SkeletonBlock className="h-40" /></div>
              : (ov?.regulatory_movement ?? []).map((r, i) => (
                <div key={i} className="px-3 py-2.5 hover:bg-panel-2/50 transition-colors">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      {r.url ? (
                        <a href={r.url} target="_blank" rel="noopener noreferrer" className="text-[13px] text-fg hover:text-brass-bright leading-snug line-clamp-2">{r.title}</a>
                      ) : (
                        <span className="text-[13px] text-fg leading-snug line-clamp-2">{r.title}</span>
                      )}
                      <div className="mono text-[10px] text-fg-dim mt-0.5 uppercase">{r.meta || r.body}</div>
                    </div>
                    <Impact v={r.impact} />
                  </div>
                </div>
              ))}
          </div>
        </Panel>

        {/* Signal monitor */}
        <Panel className="col-span-12 sm:col-span-6 lg:col-span-3" title="Activity Monitor" bodyClass="p-3">
          <div className="space-y-2.5">
            {(ov?.activity ?? []).map((a) => {
              const max = Math.max(...(ov?.activity ?? []).map((x) => x.count));
              return (
                <div key={a.source} className="text-[12px]">
                  <div className="flex justify-between mb-0.5"><span className="text-fg-dim">{a.source}</span><span className="mono text-fg-bright">{num(a.count)}</span></div>
                  <div className="h-1.5 bg-panel-2 rounded-full overflow-hidden"><div className="h-full rounded-full" style={{ width: `${(a.count / max) * 100}%`, background: "var(--color-up)" }} /></div>
                </div>
              );
            })}
          </div>
          <div className="eyebrow !text-fg-dim mt-4 mb-2">Signals</div>
          <div className="space-y-2">
            {(ov?.signals ?? []).slice(0, 5).map((s, i) => (
              <div key={i} className="flex items-start gap-2 text-[12px]">
                <span className="w-1.5 h-1.5 rounded-full mt-1.5 shrink-0" style={{ background: s.impact === "High" ? "var(--color-down)" : s.impact === "Medium" ? "var(--color-warn)" : "var(--color-fg-dim)" }} />
                <span className="text-fg leading-snug">{s.title}<span className="mono text-[10px] text-fg-dim ml-1 uppercase">· {s.category}</span></span>
              </div>
            ))}
          </div>
        </Panel>

        {/* Cross-source network */}
        <Panel
          className="col-span-12 lg:col-span-5"
          title="Cross-Source Connections"
          right={
            <div className="flex gap-1 mono text-[10px]">
              {FEATURED.slice(0, 4).map((f) => (
                <button key={f} onClick={() => setFeatured(f)} className={`px-1.5 py-0.5 rounded capitalize cursor-pointer ${featured === f ? "text-brass-bright bg-panel-2" : "text-fg-dim hover:text-fg"}`}>
                  {f.split(" ")[0]}
                </button>
              ))}
            </div>
          }
          bodyClass="p-2"
        >
          {ent ? <RadialNetwork center={ent.canonical} nodes={networkNodes} /> : <SkeletonBlock className="h-[340px]" />}
          <div className="flex flex-wrap gap-3 px-2 pb-1 mono text-[10px] text-fg-dim">
            <Legend c="#e3a93a" l="Regulator" /><Legend c="#3ecf8e" l="Funder" /><Legend c="#5b8def" l="Policy" />
            <Link href={`/entities/${encodeURIComponent(featured)}`} className="ml-auto text-brass-bright hover:underline">Open profile →</Link>
          </div>
        </Panel>

        {/* Latest briefings */}
        <Panel className="col-span-12 sm:col-span-6 lg:col-span-4" title="Latest Briefings" right={<Link href="/briefings" className="mono text-[10px] text-brass-bright hover:underline">ALL →</Link>} bodyClass="p-0">
          <div className="divide-y divide-line/60">
            {(reports?.reports ?? []).slice(0, 6).map((r) => (
              <Link key={r.id} href={`/briefings/${r.id}`} className="flex items-center justify-between gap-2 px-3 py-2.5 hover:bg-panel-2/50 transition-colors">
                <div className="min-w-0">
                  <div className="text-[13px] text-fg truncate">{r.company_name}</div>
                  <div className="mono text-[10px] text-fg-dim uppercase">{r.report_type.replace(/_/g, " ")}</div>
                </div>
                {r.overall != null && <RiskBadge score={r.overall} />}
              </Link>
            ))}
            {!reports?.count && <div className="px-3 py-4 text-sm text-fg-dim">No briefings yet.</div>}
          </div>
        </Panel>

        {/* Sector launchpad */}
        <Panel className="col-span-12 sm:col-span-6 lg:col-span-3" title="Sectors" right={<Link href="/sectors" className="mono text-[10px] text-brass-bright hover:underline">ALL →</Link>} bodyClass="p-2">
          <div className="grid grid-cols-1 gap-1">
            {(sectors?.sectors ?? []).map((s) => (
              <Link key={s.slug} href={`/sectors/${s.slug}`} className="flex items-center justify-between px-2 py-1.5 rounded hover:bg-panel-2 transition-colors text-[13px]">
                <span className="text-fg truncate">{s.name}</span>
                <span className="mono text-[10px] text-fg-dim shrink-0">{s.entity_count}</span>
              </Link>
            ))}
          </div>
        </Panel>
      </div>
    </div>
  );
}

function Legend({ c, l }: { c: string; l: string }) {
  return <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full inline-block" style={{ background: c }} /> {l}</span>;
}
