"use client";

import Link from "next/link";
import { PageHeader, CoverageBadge } from "@/components/ui";
import { num, type SourceCoverageItem, type SourceStatusResponse } from "@/lib/api";
import { sourceHref, typeLabel } from "@/lib/navigation";
import { useApi } from "@/lib/use-api";

const ICON_BY_SOURCE: Record<string, string> = {
  bills: "gavel",
  lobbying_communications: "groups",
  ocl_registrations: "assignment_ind",
  contracts: "receipt_long",
  donations: "volunteer_activism",
  hansard_mentions: "record_voice_over",
  hansard_transcripts: "record_voice_over",
  gazette_entries: "menu_book",
  appointments: "badge",
  tribunal_decisions: "balance",
  grants: "payments",
  operations: "dataset_linked",
  politicians: "account_circle",
  social_statements: "campaign",
};

export default function RecordsIndex() {
  const { data, loading, error } = useApi<SourceStatusResponse>("/api/sources/status");
  const sources = data?.sources ?? [];
  const supportedRows = sources.reduce((sum, source) => sum + (source.status === "planned" ? 0 : source.rows), 0);
  const liveCount = data?.summary.live ?? 0;
  const partialCount = data?.summary.partial ?? 0;
  const plannedCount = data?.summary.planned ?? 0;

  return (
    <div className="animate-rise">
      <PageHeader
        title="Records"
        subtitle="Source-backed evidence records stay inside Polaris first. Open a source profile for provenance, or search within that source to inspect individual rows."
        action={<Link href="/search" className="px-4 py-2 rounded bg-primary text-on-primary text-body-md font-medium hover:bg-primary-container transition-colors focus-ring">Search records</Link>}
      />

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-gutter mb-gutter">
        <Metric label="Indexed rows" value={num(supportedRows)} />
        <Metric label="Live sources" value={num(liveCount)} />
        <Metric label="Partial/planned" value={`${num(partialCount)} / ${num(plannedCount)}`} />
      </div>

      {error ? <Message tone="error">{error}</Message> : null}
      {loading ? <RecordsSkeleton /> : null}

      {!loading && !error ? (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-gutter">
          {sources.map((source) => (
            <SourceRecordCard key={source.id} source={source} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function SourceRecordCard({ source }: { source: SourceCoverageItem }) {
  const profileHref = sourceHref(source.id) ?? "/sources";
  const browseHref = `/records/${encodeURIComponent(source.id)}`;
  const tableLabel = source.table ? typeLabel(source.table, true) : "Planned source";
  const rowText = source.status === "planned" ? "Planned" : `${num(source.rows)} rows${source.approximate ? " approx." : ""}`;
  const latest = source.latest_record_date ? `Latest ${source.latest_record_date}` : freshnessLabel(source.freshness);

  return (
    <div className="card-level-1 card-level-2 rounded-lg p-density-comfortable flex items-start gap-4">
      <div className="w-12 h-12 rounded bg-primary/10 text-primary flex items-center justify-center shrink-0">
        <span className="material-symbols-outlined">{ICON_BY_SOURCE[source.id] ?? "database"}</span>
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex justify-between items-start gap-2">
          <div className="min-w-0">
            <h2 className="font-headline-sm text-[18px] text-primary leading-tight truncate">{source.label}</h2>
            <p className="font-data-tabular text-data-tabular text-on-surface-variant mt-1">{tableLabel}</p>
          </div>
          <CoverageBadge status={source.status} />
        </div>
        <p className="font-body-md text-body-md text-on-surface-variant mt-2 line-clamp-2">{source.description ?? "Internal source coverage profile."}</p>
        <div className="mt-3 flex flex-wrap items-center gap-2 font-data-tabular text-data-tabular text-on-surface-variant">
          <span>{rowText}</span>
          <span aria-hidden="true">·</span>
          <span>{latest}</span>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <Link href={profileHref} className="px-3 py-1.5 rounded bg-primary text-on-primary text-body-md font-medium hover:bg-primary-container transition-colors focus-ring">
            Source profile
          </Link>
          <Link href={browseHref} className="px-3 py-1.5 rounded border border-outline-variant text-body-md font-medium text-on-surface hover:bg-surface-container-low transition-colors focus-ring">
            Open records
          </Link>
        </div>
      </div>
    </div>
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

function RecordsSkeleton() {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-gutter">
      {[0, 1, 2, 3, 4, 5].map((i) => <div key={i} className="skeleton h-44" />)}
    </div>
  );
}

function Message({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "neutral" | "error" }) {
  return (
    <div className={`rounded border px-4 py-3 font-body-md text-body-md mb-gutter ${tone === "error" ? "border-error/30 bg-error/10 text-error" : "border-outline-variant bg-surface-container-low text-on-surface-variant"}`}>
      {children}
    </div>
  );
}

function freshnessLabel(value?: string | null): string {
  if (!value || value === "unknown") return "Freshness unknown";
  if (value === "planned") return "Planned source";
  return `${value.charAt(0).toUpperCase()}${value.slice(1)} freshness`;
}
