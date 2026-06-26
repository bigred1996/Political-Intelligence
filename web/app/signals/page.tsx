"use client";

import Link from "next/link";
import { RelatedItems, type RelatedItem } from "@/components/intelligence";
import { useApi } from "@/lib/use-api";
import type { FindingsResponse, GraphFinding } from "@/lib/api";
import { evidenceHref, findingHref, findingSlug, sectorHref, typeLabel } from "@/lib/navigation";

export default function LiveFeed() {
  const { data, loading, error } = useApi<FindingsResponse>("/api/graph/findings");
  const findings = data?.findings ?? [];

  return (
    <div className="animate-rise">
      <div className="flex flex-wrap justify-between items-end gap-4 mb-gutter border-b border-outline-variant pb-density-comfortable">
        <div>
          <h1 className="font-display-lg text-display-lg text-primary">Intelligence Live Feed</h1>
          <p className="font-data-tabular text-data-tabular text-on-surface-variant mt-1 flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-green-600 inline-block" />
            Stream Health: {error ? "Degraded" : "Live"} · {findings.length} connected finding{findings.length === 1 ? "" : "s"}
          </p>
        </div>
        <Link href="/sources" className="px-3 py-1.5 border border-outline-variant rounded text-on-surface-variant font-body-md text-body-md flex items-center gap-2 hover:bg-surface-container-low transition-colors focus-ring">
          <span className="material-symbols-outlined text-[18px]">dataset</span>
          Source coverage
        </Link>
      </div>

      <div className="grid grid-cols-12 gap-gutter">
        <div className="col-span-12 lg:col-span-8 space-y-density-comfortable">
          {loading ? <LoadingFeed /> : null}
          {error ? (
            <div className="card-level-1 rounded-lg border-l-4 border-error p-density-comfortable text-error">{error}</div>
          ) : null}
          {!loading && !error && !findings.length ? (
            <div className="card-level-1 rounded-lg p-density-comfortable text-on-surface-variant">No live findings yet. Ingest source data, then refresh this feed.</div>
          ) : null}
          {findings.map((finding, index) => <FindingFeedCard key={findingSlug(finding) ?? `${finding.title}-${index}`} finding={finding} />)}
        </div>

        <aside className="col-span-12 lg:col-span-4 space-y-gutter">
          <FilterCard
            title="Signal Strength"
            items={[
              { label: "High / Elevated", on: true },
              { label: "Watch", on: true },
              { label: "Low / contextual", on: true },
            ]}
          />
          <FilterCard
            title="Investigation Links"
            items={[
              { label: "Findings open internally", on: true },
              { label: "Evidence opens in /records", on: true },
              { label: "Original source is secondary", on: true },
            ]}
          />
        </aside>
      </div>
    </div>
  );
}

function FindingFeedCard({ finding }: { finding: GraphFinding }) {
  const href = findingHref(finding) ?? "/signals";
  const evidenceItems = finding.references.slice(0, 4).map((ref): RelatedItem => ({
    id: `${ref.table}-${ref.pk ?? ref.id}`,
    title: ref.title,
    type: typeLabel(ref.table),
    href: evidenceHref(ref),
    description: ref.date ?? null,
    meta: ref.source,
    relationship: "finding supported by record",
    strength: "supported",
  }));

  return (
    <article className="card-level-1 card-level-2 rounded-lg p-density-comfortable">
      <Link href={href} className="block focus-ring rounded">
        <div className="flex justify-between items-center mb-3 gap-3">
          <span className="font-label-caps text-label-caps text-on-surface-variant uppercase">{finding.type.replace(/_/g, " ")}</span>
          <span className={severityClass(finding.severity)}>{finding.severity}</span>
        </div>
        <h2 className="font-headline-sm text-[20px] font-semibold text-primary leading-tight mb-2">{finding.title}</h2>
        <p className="font-body-md text-body-md text-on-surface-variant leading-relaxed mb-4">{finding.summary || "Connected evidence available for analyst review."}</p>
      </Link>
      <div className="bg-surface-container-low border-l-2 border-primary rounded-r px-4 py-3 mb-4">
        <span className="font-label-caps text-label-caps text-primary uppercase">Why It Matters</span>
        <p className="font-body-md text-body-md text-on-surface mt-1">
          This signal is generated from internal evidence. Review the records before treating the relationship as causal.
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2 pt-3 border-t border-outline-variant">
        <span className="font-label-caps text-label-caps text-on-surface-variant uppercase">Affected sectors:</span>
        {dedupeSectors([finding.sector, ...finding.related_sectors]).slice(0, 4).map((sector) => (
          <Link key={sector.slug} href={sectorHref(sector.slug) ?? "/sectors"} className="text-xs bg-surface-container px-2 py-1 rounded text-secondary border border-outline-variant hover:border-primary focus-ring">
            {(sector as { name: string }).name}
          </Link>
        ))}
      </div>
      <details className="mt-4">
        <summary className="font-data-tabular text-data-tabular text-on-surface-variant cursor-pointer hover:text-primary focus-ring rounded">Supporting evidence</summary>
        <div className="mt-3">
          <RelatedItems items={evidenceItems} empty="No evidence references attached." />
        </div>
      </details>
    </article>
  );
}

function FilterCard({ title, items }: { title: string; items: { label: string; on: boolean }[] }) {
  return (
    <div className="card-level-1 rounded-lg overflow-hidden">
      <div className="bg-surface-bright px-density-comfortable py-density-compact border-b border-outline-variant">
        <h3 className="font-label-caps text-label-caps text-on-surface-variant uppercase tracking-wider">{title}</h3>
      </div>
      <div className="p-density-comfortable space-y-3">
        {items.map((it) => (
          <div key={it.label} className="flex items-center gap-3 text-body-md font-body-md text-on-surface">
            <span className={`w-4 h-4 rounded-sm border flex items-center justify-center ${it.on ? "bg-primary border-primary text-on-primary" : "border-outline-variant"}`}>
              {it.on && <span className="material-symbols-outlined text-[14px]">check</span>}
            </span>
            {it.label}
          </div>
        ))}
      </div>
    </div>
  );
}

function LoadingFeed() {
  return <div className="space-y-density-comfortable">{[0, 1, 2].map((i) => <div key={i} className="skeleton h-44" />)}</div>;
}

function dedupeSectors(sectors: ({ slug: string; name: string } | null | undefined)[]): { slug: string; name: string }[] {
  const unique = new Map<string, { slug: string; name: string }>();
  for (const sector of sectors) {
    if (sector?.slug && !unique.has(sector.slug)) unique.set(sector.slug, sector);
  }
  return [...unique.values()];
}

function severityClass(severity: string) {
  if (severity === "high" || severity === "elevated") return "font-label-caps text-label-caps status-chip-red px-2 py-1 rounded-full uppercase";
  if (severity === "watch") return "font-label-caps text-label-caps status-chip-amber px-2 py-1 rounded-full uppercase";
  return "font-label-caps text-label-caps status-chip-green px-2 py-1 rounded-full uppercase";
}
