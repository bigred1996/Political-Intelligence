"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, use, useState } from "react";
import { money, moneyFull, num, recordHref, riskBand, type SectorOverview } from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { ConnectionCard, RiskGauge, Scorecard } from "@/components/charts";
import { BarList, CanadaMap, TrendArea, TrendBars } from "@/components/dataviz";
import { Eyebrow, Panel, SkeletonBlock, SourceTag } from "@/components/ui";

const BAND_LABEL: Record<string, string> = { high: "ELEVATED", medium: "MODERATE", low: "CONTAINED" };
const BAND_COLOR: Record<string, string> = { high: "var(--color-risk-high)", medium: "var(--color-risk-med)", low: "var(--color-risk-low)" };

export default function SectorPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  return (
    <Suspense fallback={<Loading />}>
      <SectorView slug={slug} />
    </Suspense>
  );
}

function SectorView({ slug }: { slug: string }) {
  const search = useSearchParams();
  const router = useRouter();
  const province = search.get("province");
  const [mapMetric, setMapMetric] = useState<"records" | "amount">("records");
  const path = `/api/sectors/${slug}/overview${province ? `?province=${province}` : ""}`;
  const { data, loading, error } = useApi<SectorOverview>(path);

  if (error) return <ErrorState msg={error} />;
  if (loading || !data) return <Loading />;

  const { scores, evidence, connections, trends } = data;
  const band = riskBand(scores.overall);

  function selectProvince(code: string | null) {
    router.push(`/sectors/${slug}${code ? `?province=${code}` : ""}`, { scroll: false });
  }

  const KPIS = [
    { label: "Overall Risk", value: scores.overall.toFixed(1), tone: BAND_COLOR[band] },
    { label: "Contract $", value: money(evidence.contracts.total_value) },
    { label: "Contracts", value: num(evidence.contracts.count) },
    { label: "Lobbying", value: num(evidence.lobbying.count) },
    { label: "Bills", value: num(evidence.bills.count) },
    { label: "Gazette", value: num(evidence.regulations.count) },
    { label: "Donations", value: num(evidence.donations.count) },
    { label: "Departments", value: num(evidence.contracts.by_department.length) },
  ];

  return (
    <div className="animate-rise">
      {/* Header strip */}
      <section className="bg-panel border-b border-line map-grid">
        <div className="mx-auto max-w-[1320px] px-4 py-5">
          <div className="mono text-xs text-fg-dim mb-3 flex items-center gap-2">
            <Link href="/sectors" className="hover:text-brass">SECTORS</Link>
            <span className="text-line">/</span>
            <span className="text-fg uppercase">{data.sector.name}</span>
            {data.province_name && <><span className="text-line">/</span><span className="text-brass-bright uppercase">{data.province_name}</span></>}
          </div>

          <div className="grid lg:grid-cols-[1fr_auto] gap-6 items-start">
            <div>
              <Eyebrow>Sector Intelligence</Eyebrow>
              <h1 className="text-3xl font-semibold text-fg-bright mt-1.5 leading-tight">{data.sector.name}</h1>
              <p className="text-fg/80 mt-2 max-w-3xl text-sm leading-relaxed">{data.narrative}</p>
            </div>
            <div className="flex items-center gap-4 panel bg-panel-2 px-5 py-3">
              <RiskGauge score={scores.overall} size={120} />
              <div>
                <div className="eyebrow !text-fg-dim">Risk Band</div>
                <div className="mono text-lg font-semibold" style={{ color: BAND_COLOR[band] }}>{BAND_LABEL[band]}</div>
              </div>
            </div>
          </div>

          {/* KPI ticker */}
          <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-px bg-line mt-5 border border-line rounded overflow-hidden">
            {KPIS.map((k) => (
              <div key={k.label} className="bg-panel px-3 py-2.5">
                <div className="eyebrow !text-fg-dim !text-[9px] mb-1 truncate">{k.label}</div>
                <div className="mono text-lg font-semibold" style={{ color: k.tone || "var(--color-fg-bright)" }}>{k.value}</div>
              </div>
            ))}
          </div>

          {/* Province filter */}
          <div className="flex flex-wrap items-center gap-1.5 mt-4">
            <span className="eyebrow !text-fg-dim mr-1">Region</span>
            <Chip active={!province} onClick={() => selectProvince(null)}>All Canada</Chip>
            {data.province_breakdown.slice(0, 10).map((p) => (
              <Chip key={p.code} active={province === p.code} onClick={() => selectProvince(p.code)}>{p.code}</Chip>
            ))}
          </div>
        </div>
      </section>

      <div className="mx-auto max-w-[1320px] px-4 py-4 grid grid-cols-12 gap-3">
        {/* Map */}
        <Panel
          className="col-span-12 lg:col-span-4 row-span-2"
          title="Regional Footprint"
          right={
            <div className="flex gap-1 mono text-[10px]">
              {(["records", "amount"] as const).map((m) => (
                <button
                  key={m}
                  onClick={() => setMapMetric(m)}
                  className={`px-1.5 py-0.5 rounded cursor-pointer ${mapMetric === m ? "text-brass-bright bg-panel-2" : "text-fg-dim hover:text-fg"}`}
                >
                  {m === "records" ? "VOL" : "$"}
                </button>
              ))}
            </div>
          }
          bodyClass="p-3"
        >
          <CanadaMap rows={data.province_breakdown} selected={province} onSelect={selectProvince} metric={mapMetric} />
          <p className="mono text-[10px] text-fg-dim mt-1 text-center">Click a province to filter · darker brass = higher {mapMetric === "amount" ? "value" : "volume"}</p>
        </Panel>

        {/* Trends */}
        <Panel className="col-span-12 sm:col-span-6 lg:col-span-4" title="Federal Contract Spend / yr" right={<span className="mono text-[10px] text-brass">$</span>}>
          <TrendArea data={trends.contracts} asMoney color="var(--color-brass)" />
        </Panel>
        <Panel className="col-span-12 sm:col-span-6 lg:col-span-4" title="Lobbying Cadence / yr" right={<span className="mono text-[10px] text-up">COMMS</span>}>
          <TrendBars data={trends.lobbying} color="var(--color-up)" />
        </Panel>

        {/* Top entities + departments */}
        <Panel className="col-span-12 sm:col-span-6 lg:col-span-4" title="Top Players · Contract $">
          <BarList items={evidence.contracts.by_entity.slice(0, 6).map((e) => ({ label: e.entity, value: e.value }))} asMoney />
        </Panel>
        <Panel className="col-span-12 sm:col-span-6 lg:col-span-4" title="Contracting Departments">
          <BarList items={evidence.contracts.by_department.slice(0, 6).map((d) => ({ label: d.dept || "—", value: d.value }))} asMoney color="var(--color-warn)" />
        </Panel>

        {/* Connections */}
        <Panel className="col-span-12 lg:col-span-8" title="Key Connections — cross-source signals">
          {connections.length ? (
            <div className="grid sm:grid-cols-2 gap-2.5">
              {connections.map((c, i) => <ConnectionCard key={i} c={c} />)}
            </div>
          ) : (
            <p className="text-sm text-fg-dim">No notable cross-source patterns at current data depth.</p>
          )}
        </Panel>

        {/* Scorecard */}
        <Panel className="col-span-12 lg:col-span-4" title="Risk Scorecard">
          <Scorecard scores={scores} />
        </Panel>

        {/* Lobbying institutions */}
        <Panel className="col-span-12 lg:col-span-4" title="Institutions Lobbied">
          <BarList items={evidence.lobbying.top_institutions.slice(0, 7).map((t) => ({ label: t.institution, value: t.count }))} />
        </Panel>

        {/* Bills */}
        <Panel className="col-span-12 sm:col-span-6 lg:col-span-4" title={`Legislation · ${evidence.bills.count}`}>
          <DataList
            rows={evidence.bills.records.slice(0, 5).map((b) => ({ tag: b.bill_number, title: b.title_en, sub: b.status, href: recordHref(b.table, b.id) }))}
            empty="No sector-relevant bills."
          />
        </Panel>

        {/* Regulation */}
        <Panel className="col-span-12 sm:col-span-6 lg:col-span-4" title={`Regulation · ${evidence.regulations.count}`}>
          <DataList
            rows={evidence.regulations.records.slice(0, 5).map((r) => ({ tag: `P${r.gazette_part}`, title: r.title, sub: r.department, href: recordHref(r.table, r.id) }))}
            empty="No sector-relevant regulatory items."
          />
        </Panel>

        {/* Operations */}
        <Panel className="col-span-12 lg:col-span-8" title={`Operations & Environment · ${evidence.breadth.count}`}>
          {evidence.breadth.records.length ? (
            <div className="grid sm:grid-cols-2 gap-x-5 gap-y-2">
              {evidence.breadth.records.slice(0, 8).map((e, i) => (
                <Link key={i} href={recordHref(e.table, e.id) || "#"} className="group flex items-start gap-2 border-b border-line/60 pb-2 hover:bg-panel-2 -mx-1 px-1 rounded">
                  <SourceTag>{e.source}</SourceTag>
                  <span className="text-[13px] text-fg group-hover:text-brass-bright leading-snug flex-1 transition-colors">
                    {e.title}
                  </span>
                  {e.province && <span className="mono text-[10px] text-fg-dim shrink-0">{e.province}</span>}
                </Link>
              ))}
            </div>
          ) : (
            <p className="text-sm text-fg-dim">No operational records.</p>
          )}
        </Panel>

        {/* Donations by party */}
        <Panel className="col-span-12 lg:col-span-4" title="Contributions by Party">
          <BarList items={evidence.donations.by_party.slice(0, 6).map((p) => ({ label: p.party, value: p.value }))} asMoney color="var(--color-down)" />
        </Panel>
      </div>
    </div>
  );
}

function DataList({ rows, empty }: { rows: { tag: string; title: string; sub?: string; url?: string; href?: string | null }[]; empty: string }) {
  if (!rows.length) return <p className="text-sm text-fg-dim">{empty}</p>;
  return (
    <div className="space-y-2.5">
      {rows.map((r, i) => {
        const body = (
          <>
            <div className="mono text-[10px] text-brass-bright">{r.tag}</div>
            <div className="text-[13px] text-fg leading-snug group-hover:text-brass-bright transition-colors">{r.title}</div>
            {r.sub && <div className="text-xs text-fg-dim mt-0.5">{r.sub}</div>}
          </>
        );
        const cls = "group block border-b border-line/60 last:border-0 pb-2.5 last:pb-0";
        if (r.href) return <Link key={i} href={r.href} className={`${cls} hover:bg-panel-2 -mx-1 px-1 rounded`}>{body}</Link>;
        if (r.url) return <a key={i} href={r.url} target="_blank" rel="noopener noreferrer" className={cls}>{body}</a>;
        return <div key={i} className={cls}>{body}</div>;
      })}
    </div>
  );
}

function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={`mono text-xs px-2.5 py-1 rounded border transition-colors duration-200 cursor-pointer ${
        active ? "bg-brass text-canvas border-brass font-semibold" : "border-line text-fg-dim hover:text-fg hover:border-brass/50"
      }`}
    >
      {children}
    </button>
  );
}

function Loading() {
  return (
    <div>
      <div className="bg-panel border-b border-line"><div className="mx-auto max-w-[1320px] px-4 py-5 space-y-3">
        <SkeletonBlock className="h-4 w-40" /><SkeletonBlock className="h-8 w-72" /><SkeletonBlock className="h-16 w-full" />
      </div></div>
      <div className="mx-auto max-w-[1320px] px-4 py-4 grid grid-cols-12 gap-3">
        {Array.from({ length: 8 }).map((_, i) => <SkeletonBlock key={i} className="h-40 rounded col-span-12 sm:col-span-6 lg:col-span-4" />)}
      </div>
    </div>
  );
}

function ErrorState({ msg }: { msg: string }) {
  return (
    <div className="mx-auto max-w-[1320px] px-4 py-20 text-center text-fg-dim">
      Couldn&rsquo;t load this sector. {msg}
      <div className="mt-3"><Link href="/sectors" className="text-brass-bright underline">← All sectors</Link></div>
    </div>
  );
}
