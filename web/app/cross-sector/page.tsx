"use client";

import Link from "next/link";
import { Fragment, useMemo } from "react";
import type { ReactNode } from "react";
import { useApi } from "@/lib/use-api";
import type { EvidenceRef, FindingsResponse, GraphFinding, SectorsResponse, SectorSummary } from "@/lib/api";
import { evidenceHref, findingHref, sectorHref, typeLabel } from "@/lib/navigation";

type SectorNode = { slug: string; name: string };
type ConvergencePair = {
  key: string;
  a: SectorNode;
  b: SectorNode;
  findings: GraphFinding[];
  references: EvidenceRef[];
  severity: number;
};

export default function CrossSector() {
  const { data: sectorData, loading: sectorsLoading, error: sectorsError } = useApi<SectorsResponse>("/api/sectors");
  const { data: findingData, loading: findingsLoading, error: findingsError } = useApi<FindingsResponse>("/api/graph/findings");

  const sectors = useMemo(() => (sectorData?.sectors ?? []).slice().sort((a, b) => (b.entity_count ?? 0) - (a.entity_count ?? 0)), [sectorData]);
  const findings = findingData?.findings ?? [];
  const pairs = useMemo(() => buildConvergencePairs(findings), [findings]);
  const topPairs = pairs.slice(0, 8);
  const matrixSectors = sectors.slice(0, 6);
  const loading = sectorsLoading || findingsLoading;
  const error = sectorsError || findingsError;

  return (
    <div className="animate-rise">
      <div className="mb-gutter pb-density-comfortable border-b border-outline-variant">
        <Link href="/sectors" className="font-label-caps text-label-caps text-on-surface-variant uppercase hover:text-primary inline-flex items-center gap-1 mb-3 focus-ring rounded">
          <span className="material-symbols-outlined text-[16px]">arrow_back</span> Sectors
        </Link>
        <div className="flex flex-wrap justify-between items-end gap-4">
          <div>
            <h1 className="font-display-lg text-display-lg text-primary">Cross-Sector Convergence</h1>
            <p className="font-body-lg text-body-lg text-on-surface-variant mt-unit max-w-2xl">
              Live overlap between sector findings, connected evidence records, and regulatory files.
            </p>
          </div>
          <Link href="/explorer" className="px-3 py-2 border border-outline-variant rounded text-on-surface-variant text-body-md flex items-center gap-2 hover:bg-surface-container-low transition-colors focus-ring">
            <span className="material-symbols-outlined text-[18px]">hub</span>
            Evidence graph
          </Link>
        </div>
      </div>

      {error ? <Message tone="error">{error}</Message> : null}

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-gutter mb-gutter">
        <div className="lg:col-span-8">
          <section className="card-level-1 rounded-lg overflow-hidden h-full">
            <div className="bg-surface-container-low px-density-comfortable py-density-compact border-b border-outline-variant flex justify-between items-center gap-3">
              <h2 className="font-headline-sm text-headline-sm text-primary">Convergence Heatmap</h2>
              <span className="font-label-caps text-label-caps text-on-surface-variant uppercase bg-surface-variant px-2 py-1 rounded">Live graph</span>
            </div>
            <div className="p-density-comfortable">
              {loading ? (
                <div className="skeleton h-80" />
              ) : matrixSectors.length ? (
                <ConvergenceMatrix sectors={matrixSectors} pairs={pairs} />
              ) : (
                <EmptyState title="No sectors loaded yet." body="Ingest source data to populate the sector catalogue and convergence matrix." />
              )}
            </div>
          </section>
        </div>

        <div className="lg:col-span-4">
          <section className="card-level-1 rounded-lg overflow-hidden h-full">
            <div className="bg-surface-container-low px-density-comfortable py-density-compact border-b border-outline-variant">
              <h2 className="font-headline-sm text-headline-sm text-primary">Synthesis</h2>
            </div>
            <div className="p-density-comfortable space-y-4">
              <p className="font-memo-body text-[16px] text-on-surface leading-relaxed">
                {summaryText(pairs, findings.length)}
              </p>
              {topPairs.slice(0, 2).map((pair) => (
                <Link key={pair.key} href={findingHref(pair.findings[0]?.title) ?? sectorHref(pair.a.slug) ?? "/signals"} className="block bg-surface-container-low border-l-2 border-primary rounded-r px-4 py-3 hover:bg-surface-container transition-colors focus-ring">
                  <span className="font-label-caps text-label-caps text-primary uppercase">Key driver - {pair.a.name} + {pair.b.name}</span>
                  <p className="font-body-md text-body-md text-on-surface mt-1 line-clamp-3">{pair.findings[0]?.summary || "Shared sector signal supported by internal evidence records."}</p>
                </Link>
              ))}
              {!loading && !topPairs.length ? (
                <EmptyState title="No cross-sector findings yet." body="Single-sector findings are still available in the live feed and sector pages." compact />
              ) : null}
            </div>
          </section>
        </div>
      </div>

      <section className="card-level-1 rounded-lg overflow-hidden">
        <div className="bg-surface-container-low px-density-comfortable py-density-comfortable border-b border-outline-variant flex flex-wrap justify-between items-center gap-3">
          <div>
            <h2 className="font-headline-sm text-headline-sm text-primary">Shared Regulatory Files</h2>
            <p className="text-body-md text-on-surface-variant mt-1">Findings with more than one affected sector, opening into internal evidence.</p>
          </div>
          <Link href="/signals" className="px-3 py-1.5 border border-outline-variant rounded text-on-surface-variant text-body-md flex items-center gap-2 hover:bg-surface-container-low transition-colors focus-ring">
            <span className="material-symbols-outlined text-[18px]">rss_feed</span> Live feed
          </Link>
        </div>
        {loading ? (
          <div className="p-density-comfortable space-y-3">{[0, 1, 2].map((i) => <div key={i} className="skeleton h-16" />)}</div>
        ) : topPairs.length ? (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse min-w-[780px]">
              <thead>
                <tr className="border-b border-outline-variant">
                  <th className="py-3 px-density-comfortable font-label-caps text-label-caps text-on-surface-variant uppercase tracking-wider">Finding / File</th>
                  <th className="py-3 px-density-comfortable font-label-caps text-label-caps text-on-surface-variant uppercase tracking-wider">Affected Sectors</th>
                  <th className="py-3 px-density-comfortable font-label-caps text-label-caps text-on-surface-variant uppercase tracking-wider">Connected Evidence</th>
                  <th className="py-3 px-density-comfortable font-label-caps text-label-caps text-on-surface-variant uppercase tracking-wider text-right">Source</th>
                </tr>
              </thead>
              <tbody className="font-data-tabular text-data-tabular text-on-surface">
                {topPairs.map((pair) => <ConvergenceRow key={pair.key} pair={pair} />)}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="p-density-comfortable">
            <EmptyState title="No shared files detected." body="Current findings do not yet contain enough overlapping sector tags to calculate convergence." />
          </div>
        )}
      </section>
    </div>
  );
}

function ConvergenceMatrix({ sectors, pairs }: { sectors: SectorSummary[]; pairs: ConvergencePair[] }) {
  const byKey = new Map(pairs.map((pair) => [pair.key, pair]));
  return (
    <div className="overflow-x-auto">
      <div className="grid min-w-[520px]" style={{ gridTemplateColumns: `120px repeat(${sectors.length}, minmax(64px, 1fr))` }}>
        <div />
        {sectors.map((sector) => (
          <Link key={sector.slug} href={sectorHref(sector.slug) ?? "/sectors"} className="px-2 py-2 text-center font-label-caps text-label-caps text-on-surface-variant uppercase hover:text-primary focus-ring rounded">
            {sector.name}
          </Link>
        ))}
        {sectors.map((row) => (
          <Fragment key={`${row.slug}-row`}>
            <Link key={`${row.slug}-label`} href={sectorHref(row.slug) ?? "/sectors"} className="px-2 py-3 font-label-caps text-label-caps text-on-surface-variant uppercase hover:text-primary focus-ring rounded">
              {row.name}
            </Link>
            {sectors.map((col) => {
              const pair = row.slug === col.slug ? null : byKey.get(pairKey(row, col));
              const intensity = row.slug === col.slug ? 0.08 : Math.min(0.9, 0.12 + (pair?.findings.length ?? 0) * 0.18 + (pair?.severity ?? 0) * 0.08);
              const href = pair ? findingHref(pair.findings[0]?.title) : sectorHref(col.slug);
              return (
                <Link
                  key={`${row.slug}-${col.slug}`}
                  href={href ?? "/sectors"}
                  title={pair ? `${pair.findings.length} shared finding(s)` : row.slug === col.slug ? row.name : "No shared findings yet"}
                  className="m-1 aspect-square rounded-sm border border-outline-variant/40 hover:border-primary focus-ring"
                  style={{ background: `rgba(4,22,50,${intensity})` }}
                >
                  <span className="sr-only">{row.name} and {col.name}: {pair?.findings.length ?? 0} shared findings</span>
                </Link>
              );
            })}
          </Fragment>
        ))}
      </div>
      <p className="font-data-tabular text-data-tabular text-on-surface-variant mt-3 text-center">Sector x sector evidence overlap intensity</p>
    </div>
  );
}

function ConvergenceRow({ pair }: { pair: ConvergencePair }) {
  const finding = pair.findings[0];
  const evidence = pair.references[0];
  return (
    <tr className="border-b border-outline-variant zebra-row hover:bg-surface-container-low transition-colors">
      <td className="py-4 px-density-comfortable">
        <Link href={findingHref(finding?.title) ?? "/signals"} className="font-medium text-primary hover:underline focus-ring rounded">
          {finding?.title ?? `${pair.a.name} / ${pair.b.name}`}
        </Link>
        <p className="text-[12px] text-on-surface-variant mt-1 line-clamp-2">{finding?.summary ?? "Shared signal derived from connected sector records."}</p>
      </td>
      <td className="py-4 px-density-comfortable">
        <span className="flex flex-wrap gap-1">
          {[pair.a, pair.b].map((sector) => (
            <Link key={sector.slug} href={sectorHref(sector.slug) ?? "/sectors"} className="px-2 py-0.5 bg-secondary-container text-on-secondary-container rounded text-[11px] hover:underline focus-ring">
              {sector.name}
            </Link>
          ))}
        </span>
      </td>
      <td className="py-4 px-density-comfortable">
        {evidence ? (
          <Link href={evidenceHref(evidence) ?? "/records"} className="text-primary hover:underline focus-ring rounded">
            {evidence.title}
          </Link>
        ) : (
          <span className="text-on-surface-variant">No evidence reference attached</span>
        )}
      </td>
      <td className="py-4 px-density-comfortable text-right">
        <span className="text-primary font-medium">{evidence ? typeLabel(evidence.table) : "Graph"}</span>
      </td>
    </tr>
  );
}

function buildConvergencePairs(findings: GraphFinding[]): ConvergencePair[] {
  const pairs = new Map<string, ConvergencePair>();
  for (const finding of findings) {
    const sectors = uniqueSectors([finding.sector, ...(finding.related_sectors ?? [])]);
    if (sectors.length < 2) continue;
    for (let i = 0; i < sectors.length; i += 1) {
      for (let j = i + 1; j < sectors.length; j += 1) {
        const a = sectors[i];
        const b = sectors[j];
        const key = pairKey(a, b);
        const existing = pairs.get(key) ?? { key, a, b, findings: [], references: [], severity: 0 };
        existing.findings.push(finding);
        existing.references.push(...(finding.references ?? []));
        existing.severity = Math.max(existing.severity, severityScore(finding.severity));
        pairs.set(key, existing);
      }
    }
  }
  return Array.from(pairs.values())
    .map((pair) => ({ ...pair, references: dedupeRefs(pair.references).slice(0, 5) }))
    .sort((a, b) => b.severity - a.severity || b.findings.length - a.findings.length || a.key.localeCompare(b.key));
}

function uniqueSectors(items: ({ slug: string; name: string } | null | undefined)[]): SectorNode[] {
  const seen = new Map<string, SectorNode>();
  for (const item of items) {
    if (item?.slug && !seen.has(item.slug)) seen.set(item.slug, { slug: item.slug, name: item.name || item.slug });
  }
  return Array.from(seen.values());
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

function pairKey(a: { slug: string }, b: { slug: string }) {
  return [a.slug, b.slug].sort().join("__");
}

function severityScore(severity: string) {
  if (severity === "high") return 4;
  if (severity === "elevated") return 3;
  if (severity === "watch") return 2;
  return 1;
}

function summaryText(pairs: ConvergencePair[], findingCount: number) {
  if (!findingCount) return "Nessus is waiting for graph findings before calculating cross-sector convergence.";
  if (!pairs.length) return `${findingCount} live finding${findingCount === 1 ? "" : "s"} loaded, but none currently span multiple sectors.`;
  const top = pairs[0];
  return `${pairs.length} cross-sector relationship${pairs.length === 1 ? "" : "s"} detected. The strongest current overlap connects ${top.a.name} and ${top.b.name} through ${top.findings.length} finding${top.findings.length === 1 ? "" : "s"}.`;
}

function EmptyState({ title, body, compact = false }: { title: string; body: string; compact?: boolean }) {
  return (
    <div className={`rounded border border-outline-variant bg-surface-container-low ${compact ? "px-3 py-2" : "px-4 py-5"}`}>
      <div className="font-headline-sm text-[18px] text-primary">{title}</div>
      <p className="text-body-md text-on-surface-variant mt-1">{body}</p>
    </div>
  );
}

function Message({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "error" }) {
  return (
    <div className={`mb-gutter rounded border px-4 py-3 font-body-md text-body-md ${tone === "error" ? "border-error/30 bg-error/10 text-error" : "border-outline-variant bg-surface-container-low text-on-surface-variant"}`}>
      {children}
    </div>
  );
}
