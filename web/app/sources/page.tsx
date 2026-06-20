"use client";

import Link from "next/link";
import { CoverageBadge, PageHeader } from "@/components/ui";
import { num, type SourceCoverageItem, type SourceStatusResponse } from "@/lib/api";
import { sourceHref, typeLabel } from "@/lib/navigation";
import { useApi } from "@/lib/use-api";

export default function SourcesIndex() {
  const { data, loading, error } = useApi<SourceStatusResponse>("/api/sources/status");
  const sources = data?.sources ?? [];
  const quality = data?.quality;

  return (
    <div className="animate-rise">
      <PageHeader
        title="Data Sources"
        subtitle="Provenance, freshness, confidence, and known gaps for every federal source feeding the intelligence graph."
        action={<Link href="/records" className="px-4 py-2 rounded border border-outline-variant text-body-md font-medium text-on-surface hover:bg-surface-container-low transition-colors focus-ring">Record catalogue</Link>}
      />

      <div className="grid grid-cols-1 sm:grid-cols-4 gap-gutter mb-gutter">
        <Metric label="Live" value={num(data?.summary.live)} />
        <Metric label="Partial" value={num(data?.summary.partial)} />
        <Metric label="Empty" value={num(data?.summary.empty)} />
        <Metric label="Planned" value={num(data?.summary.planned)} />
      </div>

      {quality?.explicit_gaps?.length ? (
        <div className="mb-gutter rounded border border-outline-variant bg-surface-container-lowest px-4 py-3 text-body-md text-on-surface-variant">
          <span className="font-medium text-on-surface">{quality.explicit_gaps.length} source gap{quality.explicit_gaps.length === 1 ? "" : "s"} tracked.</span>{" "}
          Open a source profile to inspect missing coverage and supported evidence records.
        </div>
      ) : null}

      {error ? <Message tone="error">{error}</Message> : null}
      {loading ? <SourcesSkeleton /> : null}

      {!loading && !error ? (
        <section className="card-level-1 rounded-lg overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse min-w-[760px]">
              <thead>
                <tr className="bg-surface-container-low border-b border-outline-variant">
                  <th className="py-3 px-density-comfortable font-label-caps text-label-caps text-on-surface-variant uppercase tracking-wider">Source</th>
                  <th className="py-3 px-density-comfortable font-label-caps text-label-caps text-on-surface-variant uppercase tracking-wider text-right">Records</th>
                  <th className="py-3 px-density-comfortable font-label-caps text-label-caps text-on-surface-variant uppercase tracking-wider">Coverage</th>
                  <th className="py-3 px-density-comfortable font-label-caps text-label-caps text-on-surface-variant uppercase tracking-wider">Freshness</th>
                  <th className="py-3 px-density-comfortable font-label-caps text-label-caps text-on-surface-variant uppercase tracking-wider text-right">Confidence</th>
                </tr>
              </thead>
              <tbody className="font-data-tabular text-data-tabular text-on-surface">
                {sources.map((source) => (
                  <SourceRow key={source.id} source={source} />
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
    </div>
  );
}

function SourceRow({ source }: { source: SourceCoverageItem }) {
  const href = sourceHref(source.id) ?? "/sources";
  const rows = source.status === "planned" ? "Planned" : `${num(source.rows)}${source.approximate ? " approx." : ""}`;
  const table = source.table ? typeLabel(source.table, true) : "Source planned";
  const freshness = source.latest_record_date ?? source.freshness ?? "unknown";
  const confidence = source.confidence ?? "low";

  return (
    <tr className="border-b border-outline-variant zebra-row hover:bg-surface-container-low transition-colors">
      <td className="py-3.5 px-density-comfortable">
        <Link href={href} className="font-medium text-primary hover:underline focus-ring rounded">{source.label}</Link>
        <div className="text-on-surface-variant mt-1">{table}</div>
      </td>
      <td className="py-3.5 px-density-comfortable text-right">{rows}</td>
      <td className="py-3.5 px-density-comfortable"><CoverageBadge status={source.status} /></td>
      <td className="py-3.5 px-density-comfortable text-on-surface-variant">{freshnessLabel(freshness)}</td>
      <td className="py-3.5 px-density-comfortable text-right text-on-surface-variant">{confidenceLabel(confidence)}</td>
    </tr>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-outline-variant bg-surface-container-lowest px-4 py-3">
      <div className="font-label-caps text-label-caps text-on-surface-variant uppercase">{label}</div>
      <div className="font-data-tabular text-[24px] leading-tight text-primary mt-1">{value}</div>
    </div>
  );
}

function SourcesSkeleton() {
  return <div className="skeleton h-72" />;
}

function Message({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "neutral" | "error" }) {
  return (
    <div className={`rounded border px-4 py-3 font-body-md text-body-md mb-gutter ${tone === "error" ? "border-error/30 bg-error/10 text-error" : "border-outline-variant bg-surface-container-low text-on-surface-variant"}`}>
      {children}
    </div>
  );
}

function freshnessLabel(value?: string | null): string {
  if (!value || value === "unknown") return "Unknown";
  if (value === "planned") return "Planned";
  if (/^\d{4}/.test(value)) return value;
  return `${value.charAt(0).toUpperCase()}${value.slice(1)}`;
}

function confidenceLabel(value: string): string {
  if (value === "planned") return "Planned";
  return `${value.charAt(0).toUpperCase()}${value.slice(1)}`;
}
