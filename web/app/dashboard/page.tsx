"use client";

import Link from "next/link";
import { useApi } from "@/lib/use-api";
import type { IntelligenceFinding, OverviewResponse } from "@/lib/api";
import { money, num } from "@/lib/api";
import { evidenceHref, findingHref, recordHref, sectorHref, sourceHref } from "@/lib/navigation";

export default function Dashboard() {
  const { data, loading, error } = useApi<OverviewResponse>("/api/overview");
  const findings = data?.intelligence_findings ?? [];
  const sectors = data?.sector_watchlist ?? [];
  const highFindings = findings.filter((finding) => ["high", "elevated"].includes(finding.risk_level));
  const evidenceCount = findings.reduce((sum, finding) => sum + (finding.related_records?.length ?? finding.evidence_references?.length ?? 0), 0);
  const firstBill = (data?.regulatory_movement ?? []).find((item) => item.kind === "bill" && item.table && item.pk);
  const firstBillHref = recordHref(firstBill?.table, firstBill?.pk) ?? "/records";

  return (
    <div className="animate-rise">
      <div className="mb-gutter">
        <h1 className="font-display-lg text-display-lg text-primary">Intelligence Brief</h1>
        <p className="font-body-lg text-body-lg text-on-surface-variant mt-unit">
          Live operational view across the Canadian regulatory landscape.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-gutter mb-gutter">
        <StatCard label="Active Legislative Items" value={num(data?.ticker?.bills_in_motion)} delta={`${num(data?.ticker?.gazette_entries)} Gazette entries`} tone="up" icon="gavel" href={firstBillHref} />
        <StatCard label="Material Risks Detected" value={num(highFindings.length)} delta="Requires review" tone="warn" icon="warning" href="/signals" />
        <StatCard label="Linked Evidence" value={num(evidenceCount)} delta={`${num(findings.length)} findings`} tone="neutral" icon="monitoring" href="/explorer" />
      </div>

      <div className="grid grid-cols-12 gap-gutter">
        <div className="col-span-12 lg:col-span-8">
          <section className="card-level-1 rounded-lg overflow-hidden">
            <div className="px-density-comfortable py-density-comfortable border-b border-outline-variant flex justify-between items-center">
              <h2 className="font-headline-sm text-headline-sm text-primary flex items-center gap-2">
                <span className="material-symbols-outlined text-primary">bolt</span> Material Developments
              </h2>
              <Link href="/signals" className="px-3 py-1.5 border border-outline-variant rounded text-on-surface-variant text-body-md flex items-center gap-2 hover:bg-surface-container-low transition-colors focus-ring">
                <span className="material-symbols-outlined text-[18px]">rss_feed</span> Live feed
              </Link>
            </div>
            <div className="divide-y divide-outline-variant">
              {loading ? <LoadingRows /> : null}
              {error ? <div className="p-density-comfortable text-error">{error}</div> : null}
              {!loading && !error && findings.length === 0 ? <div className="p-density-comfortable text-on-surface-variant">No material developments available yet.</div> : null}
              {findings.slice(0, 6).map((finding) => <Development key={finding.title} finding={finding} />)}
            </div>
          </section>
        </div>

        <div className="col-span-12 lg:col-span-4 space-y-gutter">
          <section className="card-level-1 rounded-lg overflow-hidden">
            <div className="bg-surface-bright px-density-comfortable py-density-compact border-b border-outline-variant">
              <h3 className="font-label-caps text-label-caps text-on-surface-variant uppercase tracking-wider">Sector Activity Heatmap</h3>
            </div>
            <div className="p-density-comfortable space-y-4">
              {sectors.slice(0, 6).map((sector) => (
                <Link key={sector.sector.slug} href={sectorHref(sector.sector.slug) ?? "/sectors"} className="block focus-ring rounded">
                  <div className="flex justify-between text-body-md mb-1">
                    <span className="text-on-surface font-medium">{sector.sector.name}</span>
                    <span className="font-medium text-primary capitalize">{sector.risk_band}</span>
                  </div>
                  <div className="h-2 w-full bg-surface-variant rounded-full overflow-hidden">
                    <div className="h-full rounded-full" style={{ width: `${Math.min(100, Math.max(8, sector.score * 10))}%`, background: riskColor(sector.risk_band) }} />
                  </div>
                </Link>
              ))}
              {!sectors.length && <div className="text-body-md text-on-surface-variant">No sector activity yet.</div>}
            </div>
          </section>

          <section className="card-level-1 rounded-lg overflow-hidden">
            <div className="bg-surface-bright px-density-comfortable py-density-compact border-b border-outline-variant">
              <h3 className="font-label-caps text-label-caps text-on-surface-variant uppercase tracking-wider">Regulatory Movement</h3>
            </div>
            <div className="p-density-comfortable space-y-4">
              {(data?.regulatory_movement ?? []).slice(0, 4).map((item) => {
                const href = recordHref(item.table, item.pk);
                return (
                  <Link key={`${item.table}-${item.pk ?? item.title}`} href={href ?? "/records"} className="flex gap-3 items-start rounded hover:bg-surface-container-low transition-colors p-1 -m-1 focus-ring">
                    <div className="flex flex-col items-center min-w-[44px]">
                      <span className="font-label-caps text-label-caps text-error">{item.date?.slice(5, 7) ?? "--"}</span>
                      <span className="font-headline-sm text-headline-sm font-bold text-primary">{item.date?.slice(8, 10) ?? "--"}</span>
                    </div>
                    <div className="border-l-2 border-outline-variant pl-3 min-w-0">
                      <p className="font-body-md text-body-md font-bold text-primary leading-tight line-clamp-2">{item.title}</p>
                      <p className="text-xs text-on-surface-variant mt-1">{item.body} · {item.impact}</p>
                    </div>
                  </Link>
                );
              })}
              <Link href="/records" className="block text-center font-label-caps text-label-caps text-primary uppercase pt-2 hover:underline focus-ring rounded">View all records</Link>
            </div>
          </section>

          <section className="card-level-1 rounded-lg overflow-hidden">
            <div className="bg-surface-bright px-density-comfortable py-density-compact border-b border-outline-variant">
              <h3 className="font-label-caps text-label-caps text-on-surface-variant uppercase tracking-wider">Stream Status</h3>
            </div>
            <div className="p-density-comfortable space-y-3">
              {(data?.activity ?? []).slice(0, 6).map((source) => (
                <Link key={source.source} href={sourceHref(source.source) ?? "/sources"} className="flex justify-between items-center rounded hover:bg-surface-container-low transition-colors p-1 -m-1 focus-ring">
                  <span className="text-body-md text-on-surface">{source.source}</span>
                  <span className="flex items-center gap-1.5 text-green-600 font-data-tabular text-data-tabular">
                    <span className="w-2 h-2 rounded-full bg-green-600" /> {num(source.count)}
                  </span>
                </Link>
              ))}
              <div className="pt-2 border-t border-outline-variant font-data-tabular text-data-tabular text-on-surface-variant">
                Cache: {data?.cache?.status ?? "unknown"}
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}

function StatCard({ label, value, delta, tone, icon, href }: { label: string; value: string; delta: string; tone: "up" | "warn" | "neutral"; icon: string; href: string }) {
  return (
    <Link href={href} className="card-level-1 card-level-2 rounded-lg p-density-comfortable focus-ring">
      <div className="flex justify-between items-start">
        <span className="font-label-caps text-label-caps text-on-surface-variant uppercase">{label}</span>
        <span className={`material-symbols-outlined text-[20px] ${tone === "warn" ? "text-error" : "text-on-surface-variant"}`}>{icon}</span>
      </div>
      <div className="font-display-lg text-headline-md text-primary leading-none mt-3 mb-2">{value}</div>
      <span className={`font-data-tabular text-data-tabular ${tone === "up" ? "text-green-600" : tone === "warn" ? "text-error" : "text-on-surface-variant"}`}>{delta}</span>
    </Link>
  );
}

function Development({ finding }: { finding: IntelligenceFinding }) {
  const baseHref = findingHref(finding.title) ?? "/signals";
  const href = `${baseHref}${baseHref.includes("?") ? "&" : "?"}from=dashboard`;
  const evidence = finding.related_records?.[0];
  const evidenceUrl = evidence ? evidenceHref(evidence) : finding.evidence_references?.[0]?.internal_url;
  return (
    <article className="p-density-comfortable">
      <Link href={href} className="block focus-ring rounded">
        <div className="flex items-center gap-2 mb-3 flex-wrap">
          <span className="font-label-caps text-label-caps bg-surface-variant text-on-surface px-2 py-1 rounded uppercase">{finding.primary_sector?.name ?? "Cross-sector"}</span>
          <span className={riskClass(finding.risk_level)}>{finding.risk_level}</span>
          <span className="ml-auto font-data-tabular text-data-tabular text-on-surface-variant">{finding.recency}</span>
        </div>
        <h3 className="font-headline-sm text-[20px] font-semibold text-primary leading-tight mb-2">{finding.title}</h3>
      </Link>
      <div className="bg-surface-container-low border-l-2 border-primary rounded-r px-4 py-3 mb-3">
        <span className="font-label-caps text-label-caps text-primary uppercase">Why It Matters</span>
        <p className="font-body-md text-body-md text-on-surface mt-1">{finding.why_it_matters || finding.concise_summary}</p>
      </div>
      <div className="flex items-center gap-2 flex-wrap">
        <span className="flex items-center gap-1 text-xs bg-surface-container px-2 py-1 rounded text-secondary border border-outline-variant">
          <span className="material-symbols-outlined text-[14px]">description</span>{finding.source_coverage}
        </span>
        {evidenceUrl && (
          <Link href={evidenceUrl} className="flex items-center gap-1 text-xs bg-primary/10 px-2 py-1 rounded text-primary border border-primary/20 hover:underline focus-ring">
            <span className="material-symbols-outlined text-[14px]">database</span>Open evidence
          </Link>
        )}
      </div>
    </article>
  );
}

function LoadingRows() {
  return <div className="p-density-comfortable space-y-3">{[0, 1, 2].map((i) => <div key={i} className="skeleton h-28" />)}</div>;
}

function riskColor(level: string) {
  const l = level.toLowerCase();
  if (l.includes("high") || l.includes("elevated")) return "#ba1a1a";
  if (l.includes("moderate") || l.includes("watch")) return "#d97706";
  return "#041632";
}

function riskClass(level?: string | null) {
  const l = (level ?? "unknown").toLowerCase();
  if (l.includes("high") || l.includes("elevated")) return "font-label-caps text-label-caps status-chip-red px-2 py-1 rounded uppercase";
  if (l.includes("moderate") || l.includes("watch")) return "font-label-caps text-label-caps status-chip-amber px-2 py-1 rounded uppercase";
  return "font-label-caps text-label-caps status-chip-green px-2 py-1 rounded uppercase";
}
