"use client";

import Link from "next/link";
import { useApi } from "@/lib/use-api";
import type { IntelligenceFinding, OverviewResponse } from "@/lib/api";
import { money, num } from "@/lib/api";
import { evidenceHref, findingHref, recordHref, sectorHref } from "@/lib/navigation";

export default function Briefing() {
  const { data, loading, error } = useApi<OverviewResponse>("/api/overview");
  const findings = data?.intelligence_findings ?? [];
  const topFindings = findings.slice(0, 3);
  const watchlist = data?.sector_watchlist ?? [];
  const bills = (data?.regulatory_movement ?? []).filter((r) => r.kind === "bill").slice(0, 4);
  const firstBillHref = bills.find((bill) => bill.table && bill.pk)
    ? recordHref(bills.find((bill) => bill.table && bill.pk)?.table, bills.find((bill) => bill.table && bill.pk)?.pk)
    : null;

  return (
    <div className="grid grid-cols-12 gap-gutter animate-rise">
      <div className="col-span-12 lg:col-span-8 space-y-8">
        <section>
          <div className="flex flex-wrap justify-between items-end gap-4 mb-4 border-b border-outline-variant pb-2">
            <div>
              <h1 className="font-display-lg text-display-lg text-primary mb-1">Morning Intelligence Brief</h1>
              <p className="font-body-lg text-body-lg text-on-surface-variant">Live connected intelligence across Canadian political and regulatory sources</p>
            </div>
            <span className="font-label-caps text-label-caps bg-primary-container text-on-primary-container px-2 py-1 rounded">
              {data?.cache?.status ? `CACHE: ${data.cache.status.toUpperCase()}` : "LIVE WORKSPACE"}
            </span>
          </div>

          <div className="card-level-1 card-level-2 rounded-lg p-6 relative overflow-hidden">
            <div className="absolute right-0 top-0 w-64 h-full bg-gradient-to-l from-surface-container-low to-transparent pointer-events-none opacity-50" />
            <h2 className="font-headline-sm text-headline-sm text-primary mb-4 flex items-center gap-2">
              <span className="material-symbols-outlined text-error">warning</span>
              Material Changes Detected
            </h2>
            {loading ? <LoadingRows /> : error ? <ErrorState error={error} /> : (
              <div className="space-y-6">
                {topFindings.length ? topFindings.map((finding) => (
                  <FindingCard key={finding.title} finding={finding} />
                )) : (
                  <EmptyState>No connected findings are available yet. Ingest source data, then refresh the workspace.</EmptyState>
                )}
              </div>
            )}
          </div>
        </section>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
          <section className="card-level-1 card-level-2 rounded-lg flex flex-col overflow-hidden">
            <div className="bg-surface-container-lowest border-b border-outline-variant p-4 flex justify-between items-center rounded-t-lg">
              <h3 className="font-headline-sm text-[18px] text-primary">Active Legislative Movement</h3>
              <Link href={firstBillHref ?? "/records"} className="text-on-surface-variant hover:text-primary focus-ring rounded" aria-label="Open bill records">
                <span className="material-symbols-outlined text-[20px]">open_in_new</span>
              </Link>
            </div>
            <div className="p-4 flex-1">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="border-b border-outline-variant">
                    <th className="py-2 font-label-caps text-label-caps text-on-surface-variant">FILE</th>
                    <th className="py-2 font-label-caps text-label-caps text-on-surface-variant">STATUS</th>
                    <th className="py-2 font-label-caps text-label-caps text-on-surface-variant text-right">IMPACT</th>
                  </tr>
                </thead>
                <tbody className="font-data-tabular text-data-tabular">
                  {bills.length ? bills.map((bill, i) => {
                    const href = recordHref(bill.table, bill.pk);
                    const target = href ?? "/records";
                    const row = [
                      <td key="title" className="py-3 pr-2 text-primary font-bold truncate max-w-[180px]">{bill.title}</td>,
                      <td key="status" className="py-3 text-on-surface-variant">{bill.meta || "Active"}</td>,
                      <td key="impact" className="py-3 text-right text-error font-bold">{bill.impact}</td>,
                    ];
                    const linkedRow = (
                      <>
                        <td className="py-3 pr-2 text-primary font-bold truncate max-w-[180px]"><Link href={target} className="hover:underline focus-ring rounded">{bill.title}</Link></td>
                        <td className="py-3 text-on-surface-variant"><Link href={target} className="focus-ring rounded">{bill.meta || "Active"}</Link></td>
                        <td className="py-3 text-right text-error font-bold"><Link href={target} className="focus-ring rounded">{bill.impact}</Link></td>
                      </>
                    );
                    return (
                      <tr key={`${bill.table}-${bill.pk ?? bill.title}`} className={`${i < bills.length - 1 ? "border-b border-outline-variant" : ""} hover:bg-primary/[0.02] transition-colors`}>
                        {href ? linkedRow : row}
                      </tr>
                    );
                  }) : (
                    <tr><td colSpan={3} className="py-4 text-on-surface-variant">No bill movement available.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>

          <section className="card-level-1 card-level-2 rounded-lg flex flex-col overflow-hidden">
            <div className="bg-surface-container-lowest border-b border-outline-variant p-4 flex justify-between items-center rounded-t-lg">
              <h3 className="font-headline-sm text-[18px] text-primary">Political Actor Movement</h3>
              <Link href="/politicians" className="font-label-caps text-label-caps text-on-surface-variant hover:text-primary focus-ring rounded">PLAYERS</Link>
            </div>
            <div className="p-4 flex-1 space-y-4">
              {(data?.actor_movement ?? []).slice(0, 4).map((actor) => (
                <Link key={`${actor.actor}-${actor.date}-${actor.keyword}`} href={evidenceHref(actor.reference) ?? "/politicians"} className="flex gap-4 items-start rounded p-2 -m-2 hover:bg-surface-container-low transition-colors focus-ring">
                  <div className="font-data-tabular text-data-tabular text-on-surface-variant w-20 pt-1">{actor.date ?? "No date"}</div>
                  <div className="flex-1 min-w-0">
                    <p className="font-body-md text-body-md font-bold text-primary truncate">{actor.actor}</p>
                    <p className="font-data-tabular text-data-tabular text-on-surface-variant line-clamp-2">{actor.keyword} - {actor.excerpt}</p>
                  </div>
                </Link>
              ))}
              {!data?.actor_movement?.length && <EmptyState>No actor movement available.</EmptyState>}
            </div>
          </section>
        </div>

        <section className="card-level-1 card-level-2 rounded-lg overflow-hidden">
          <div className="bg-surface-container-lowest border-b border-outline-variant p-4 rounded-t-lg">
            <h3 className="font-headline-sm text-[18px] text-primary">Sector Watchlist</h3>
          </div>
          <div className="p-4 grid grid-cols-1 md:grid-cols-2 gap-3">
            {watchlist.slice(0, 6).map((sector) => (
              <Link key={sector.sector.slug} href={sectorHref(sector.sector.slug) ?? "/sectors"} className="rounded border border-outline-variant bg-surface-container-lowest p-3 hover:border-primary transition-colors focus-ring">
                <div className="flex items-center justify-between gap-2">
                  <h4 className="font-body-md text-body-md font-bold text-primary">{sector.sector.name}</h4>
                  <span className={riskChip(sector.risk_band)}>{sector.risk_band}</span>
                </div>
                <p className="font-body-md text-body-md text-on-surface-variant mt-2 line-clamp-2">{sector.summary}</p>
                <div className="mt-3 grid grid-cols-3 gap-2 font-data-tabular text-data-tabular text-on-surface-variant">
                  <span>{num(sector.metrics.lobbying)} lobbying</span>
                  <span>{num(sector.metrics.bills + sector.metrics.gazette)} regulatory</span>
                  <span>{money(sector.metrics.contract_value)}</span>
                </div>
              </Link>
            ))}
          </div>
        </section>
      </div>

      <aside className="col-span-12 lg:col-span-4">
        <div className="glass-panel p-6 rounded-lg lg:sticky lg:top-6">
          <h3 className="font-label-caps text-label-caps text-on-surface-variant mb-4">INVESTIGATION</h3>
          <div className="space-y-4">
            <Link href="/search" className="w-full bg-primary text-on-primary py-3 px-4 rounded font-body-md text-body-md font-bold flex items-center justify-between hover:bg-primary-container transition-colors shadow-sm focus-ring">
              <span>Ask Nessus</span>
              <span className="material-symbols-outlined text-[20px]">forum</span>
            </Link>
            <Link href="/explorer" className="w-full bg-surface text-primary border border-outline-variant py-3 px-4 rounded font-body-md text-body-md font-bold flex items-center justify-between hover:bg-surface-container-low transition-colors focus-ring">
              <span>Open Evidence Graph</span>
              <span className="material-symbols-outlined text-[20px]">hub</span>
            </Link>
          </div>

          <hr className="my-6 border-outline-variant" />

          <h3 className="font-label-caps text-label-caps text-on-surface-variant mb-4">WHAT CHANGED</h3>
          <p className="font-body-md text-body-md text-on-surface-variant leading-relaxed">
            {data?.what_changed?.summary ?? "Nessus is waiting for enough source history to calculate period-over-period movement."}
          </p>
          <div className="mt-4 space-y-2">
            {(data?.what_changed?.requires_attention ?? []).map((sector) => (
              <Link key={sector.slug} href={sectorHref(sector.slug) ?? "/sectors"} className="flex items-center justify-between rounded border border-outline-variant bg-surface-container-lowest px-3 py-2 hover:border-primary transition-colors focus-ring">
                <span className="font-body-md text-body-md text-primary">{sector.name}</span>
                <span className="material-symbols-outlined text-[18px] text-on-surface-variant">chevron_right</span>
              </Link>
            ))}
          </div>
        </div>
      </aside>
    </div>
  );
}

function FindingCard({ finding }: { finding: IntelligenceFinding }) {
  const baseHref = findingHref(finding) ?? "/signals";
  const href = `${baseHref}${baseHref.includes("?") ? "&" : "?"}from=briefing`;
  const evidence = finding.related_records?.[0] ? evidenceHref(finding.related_records[0]) : finding.evidence_references?.[0]?.internal_url;
  return (
    <Link href={href} className="block pl-4 border-l-2 border-error hover:bg-surface-container-low/60 rounded-r p-2 -m-2 transition-colors focus-ring">
      <div className="flex flex-wrap items-center gap-2 mb-2">
        <span className={riskChip(finding.risk_level)}>{finding.risk_level}</span>
        <span className="font-label-caps text-label-caps bg-surface-container-highest text-on-surface-variant px-2 py-1 rounded-full uppercase">{finding.confidence} confidence</span>
        {finding.primary_sector && <span className="font-label-caps text-label-caps bg-primary/10 text-primary px-2 py-1 rounded-full uppercase">{finding.primary_sector.name}</span>}
      </div>
      <h3 className="font-headline-md text-[20px] leading-tight text-primary mb-1">{finding.title}</h3>
      <p className="font-memo-body text-memo-body text-on-surface-variant mb-2">{finding.concise_summary || finding.why_it_matters}</p>
      <div className="flex items-center gap-2 font-data-tabular text-data-tabular text-on-surface-variant">
        <span>Open finding</span>
        {evidence && <span> - evidence available</span>}
      </div>
    </Link>
  );
}

function LoadingRows() {
  return <div className="space-y-3">{[0, 1, 2].map((i) => <div key={i} className="skeleton h-24" />)}</div>;
}

function EmptyState({ children }: { children: React.ReactNode }) {
  return <div className="rounded border border-outline-variant bg-surface-container-low px-4 py-3 text-body-md text-on-surface-variant">{children}</div>;
}

function ErrorState({ error }: { error: string }) {
  return <div className="rounded border border-error/30 bg-error/10 px-4 py-3 text-body-md text-error">{error}</div>;
}

function riskChip(level?: string | null) {
  const l = (level ?? "unknown").toLowerCase();
  if (l.includes("high") || l.includes("elevated")) return "font-label-caps text-label-caps status-chip-red px-2 py-1 rounded-full uppercase";
  if (l.includes("moderate") || l.includes("medium") || l.includes("watch")) return "font-label-caps text-label-caps status-chip-amber px-2 py-1 rounded-full uppercase";
  return "font-label-caps text-label-caps status-chip-green px-2 py-1 rounded-full uppercase";
}
