"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import { RelatedItems, type RelatedItem } from "@/components/intelligence";
import { useApi } from "@/lib/use-api";
import type { EvidenceRef, FindingsResponse, GraphFinding, SectorsResponse } from "@/lib/api";
import { evidenceHref, findingHref, findingSlug, sectorHref, typeLabel } from "@/lib/navigation";

type Watchlist = {
  id: string;
  name: string;
  description: string;
  freq: string;
  status: "MONITORING" | "READY" | "EMPTY";
  targets: RelatedItem[];
};

export default function WatchlistsPage() {
  const [selected, setSelected] = useState(0);
  const { data: sectorData, loading: sectorsLoading, error: sectorsError } = useApi<SectorsResponse>("/api/sectors");
  const { data: findingData, loading: findingsLoading, error: findingsError } = useApi<FindingsResponse>("/api/graph/findings");
  const findings = useMemo(() => findingData?.findings ?? [], [findingData]);
  const sectors = useMemo(() => sectorData?.sectors ?? [], [sectorData]);
  const watchlists = useMemo(() => buildWatchlists(sectors, findings), [sectors, findings]);
  const selectedIndex = Math.min(selected, Math.max(0, watchlists.length - 1));
  const wl = watchlists[selectedIndex];
  const loading = sectorsLoading || findingsLoading;
  const error = sectorsError || findingsError;
  const activeTargets = watchlists.reduce((sum, list) => sum + list.targets.length, 0);

  return (
    <div className="animate-rise">
      <div className="flex flex-wrap items-start justify-between gap-4 mb-gutter">
        <div>
          <h1 className="font-display-lg text-display-lg text-primary">Watchlist Management</h1>
          <p className="font-body-lg text-body-lg text-on-surface-variant mt-unit max-w-2xl">
            Monitor live findings, sectors, and evidence records without leaving Polaris.
          </p>
        </div>
        <form className="flex items-center gap-2" action="/search">
          <label className="sr-only" htmlFor="watchlist-search">Search target</label>
          <input
            id="watchlist-search"
            name="q"
            placeholder="Search entity or file"
            className="px-3 py-2 bg-surface-container-low border border-outline-variant rounded text-body-md text-on-surface placeholder:text-on-surface-variant focus:border-primary focus:ring-1 focus:ring-primary outline-none w-56"
          />
          <button className="px-4 py-2 rounded bg-primary text-on-primary text-body-md font-medium hover:bg-primary-container transition-colors focus-ring">Search</button>
        </form>
      </div>

      {error ? <Message tone="error">{error}</Message> : null}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-gutter items-start">
        <section className="lg:col-span-2 card-level-1 rounded-lg overflow-hidden">
          <div className="bg-surface-container-low px-density-comfortable py-density-compact border-b border-outline-variant flex justify-between items-center gap-3">
            <h2 className="font-headline-sm text-headline-sm text-primary">Active Watchlists</h2>
            <span className="font-label-caps text-label-caps text-on-surface-variant uppercase">{activeTargets} live targets</span>
          </div>
          {loading ? (
            <div className="p-density-comfortable space-y-3">{[0, 1, 2].map((i) => <div key={i} className="skeleton h-16" />)}</div>
          ) : (
            <div className="p-2">
              <div className="grid grid-cols-[1.5fr_0.8fr_1fr_0.8fr] gap-3 px-3 py-2 font-label-caps text-label-caps text-on-surface-variant uppercase border-b border-outline-variant">
                <span>Name</span><span>Targets</span><span>Source</span><span className="text-right">Status</span>
              </div>
              {watchlists.map((w, i) => (
                <button
                  key={w.id}
                  onClick={() => setSelected(i)}
                  className={`w-full text-left grid grid-cols-[1.5fr_0.8fr_1fr_0.8fr] gap-3 items-center px-3 py-3.5 rounded transition-colors cursor-pointer focus-ring ${
                    i === selectedIndex ? "bg-primary-container/10" : "hover:bg-surface-container-low"
                  }`}
                >
                  <span className="flex items-center gap-2 min-w-0">
                    <span className="material-symbols-outlined text-[18px] text-on-surface-variant">visibility</span>
                    <span className="min-w-0">
                      <span className="block text-body-md font-bold text-primary truncate">{w.name}</span>
                      <span className="block text-[11px] text-on-surface-variant truncate">{w.description}</span>
                    </span>
                  </span>
                  <span className="font-data-tabular text-data-tabular text-on-surface-variant">{w.targets.length}</span>
                  <span className="font-data-tabular text-data-tabular text-on-surface-variant">{w.freq}</span>
                  <span className="text-right">
                    <span className={`font-label-caps text-label-caps px-2 py-0.5 rounded ${w.status === "MONITORING" ? "status-chip-green" : w.status === "READY" ? "status-chip-amber" : "bg-surface-container-high text-on-surface-variant"}`}>
                      {w.status}
                    </span>
                  </span>
                </button>
              ))}
            </div>
          )}
        </section>

        <aside className="card-level-1 rounded-lg p-density-comfortable h-fit">
          <div className="font-label-caps text-label-caps text-on-surface-variant uppercase">Configuration</div>
          <h2 className="font-headline-sm text-headline-sm text-primary mt-1 mb-2">{wl.name}</h2>
          <p className="text-body-md text-on-surface-variant mb-5">{wl.description}</p>

          <div className="mb-5">
            <div className="flex items-center gap-2 mb-2 text-body-md font-bold text-on-surface">
              <span className="material-symbols-outlined text-[18px] text-on-surface-variant">notifications_active</span> Alert Configuration
            </div>
            <div className="rounded border border-primary bg-primary-container/10 px-3 py-3 mb-2">
              <span className="flex items-center gap-2 text-body-md font-medium text-primary">
                <span className="material-symbols-outlined text-[18px]">radio_button_checked</span> Internal workspace monitoring
              </span>
            </div>
            <div className="rounded border border-outline-variant px-3 py-3 text-body-md text-on-surface-variant">
              Push alerts are a planned workflow; current prototype keeps watch targets inside Polaris.
            </div>
          </div>

          <RelatedItems title="Watch targets" items={wl.targets.slice(0, 8)} empty="No live watch targets match this group yet." />

          <div className="flex justify-end gap-2 mt-6">
            <Link href="/signals" className="px-4 py-2 rounded border border-outline-variant text-body-md font-medium text-on-surface hover:bg-surface-container-low transition-colors focus-ring">Live feed</Link>
            <Link href="/explorer" className="px-4 py-2 rounded bg-primary text-on-primary text-body-md font-medium hover:bg-primary-container transition-colors focus-ring">Open graph</Link>
          </div>
        </aside>
      </div>
    </div>
  );
}

function buildWatchlists(sectors: SectorsResponse["sectors"], findings: GraphFinding[]): Watchlist[] {
  const highFindings = findings.filter((finding) => finding.severity === "high" || finding.severity === "elevated");
  const sectorTargets = sectors
    .slice()
    .sort((a, b) => (b.entity_count ?? 0) - (a.entity_count ?? 0))
    .slice(0, 8)
    .map((sector): RelatedItem => ({
      id: `sector-${sector.slug}`,
      title: sector.name,
      type: "Sector",
      href: sectorHref(sector.slug),
      description: sector.blurb || sector.description || "Sector intelligence profile",
      meta: `${sector.entity_count ?? 0} entities`,
      relationship: "company belongs to sector",
      strength: "inferred",
    }));
  const findingTargets = highFindings.slice(0, 8).map((finding, index): RelatedItem => ({
    id: `finding-${findingSlug(finding) ?? `${finding.title}-${index}`}`,
    title: finding.title,
    type: "Finding",
    href: findingHref(finding),
    description: finding.summary,
    meta: `${finding.severity} severity`,
    relationship: "finding spans sectors",
    strength: finding.relationship_strength ?? "supported",
  }));
  const evidenceTargets = dedupeRefs(findings.flatMap((finding) => finding.references ?? [])).slice(0, 8).map((ref): RelatedItem => ({
    id: `evidence-${ref.table}-${ref.pk ?? ref.id}`,
    title: ref.title,
    type: typeLabel(ref.table),
    href: evidenceHref(ref),
    description: ref.date ?? null,
    meta: ref.source,
    relationship: "finding supported by record",
    strength: "supported",
  }));

  return [
    {
      id: "material-findings",
      name: "Material Findings",
      description: "High and elevated graph findings requiring review.",
      freq: "/api/graph/findings",
      status: findingTargets.length ? "MONITORING" : "EMPTY",
      targets: findingTargets,
    },
    {
      id: "sector-watch",
      name: "Sector Watch",
      description: "Highest-activity sectors from the live sector catalogue.",
      freq: "/api/sectors",
      status: sectorTargets.length ? "MONITORING" : "EMPTY",
      targets: sectorTargets,
    },
    {
      id: "evidence-records",
      name: "Evidence Records",
      description: "Recent records supporting live graph findings.",
      freq: "/records",
      status: evidenceTargets.length ? "READY" : "EMPTY",
      targets: evidenceTargets,
    },
  ];
}

function dedupeRefs(refs: EvidenceRef[]): EvidenceRef[] {
  const seen = new Set<string>();
  return refs.filter((ref) => {
    const key = `${ref.table}:${ref.pk ?? ref.id}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function Message({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "error" }) {
  return (
    <div className={`mb-gutter rounded border px-4 py-3 font-body-md text-body-md ${tone === "error" ? "border-error/30 bg-error/10 text-error" : "border-outline-variant bg-surface-container-low text-on-surface-variant"}`}>
      {children}
    </div>
  );
}
