"use client";

import Link from "next/link";
import { use, useState } from "react";
import { Crumb } from "@/components/nessus";
import { EmptyState, PageHeader } from "@/components/ui";
import { money, num, type SourceRecordsPage } from "@/lib/api";
import { recordHref, sourceHref, typeLabel } from "@/lib/navigation";
import { useApi } from "@/lib/use-api";

const PAGE_SIZE = 25;

export default function SourceRecordsBrowsePage({ params }: { params: Promise<{ table: string }> }) {
  const { table: sourceId } = use(params);
  const [cursors, setCursors] = useState<(number | null)[]>([null]);
  const cursor = cursors[cursors.length - 1];
  const path = `/api/sources/${encodeURIComponent(sourceId)}/records?limit=${PAGE_SIZE}${cursor ? `&cursor=${cursor}` : ""}`;
  const { data, loading, error } = useApi<SourceRecordsPage>(path);
  const pageNumber = cursors.length;

  return (
    <div className="animate-rise">
      <Crumb items={[{ label: "Records", href: "/records" }, { label: data?.label ?? "Browse" }]} />
      <PageHeader
        title={data?.label ?? "Records"}
        subtitle={data ? `${num(data.total_rows)}${data.approximate ? "+" : ""} ${typeLabel(data.table, true).toLowerCase()} loaded — newest first.` : "Loading source coverage…"}
        action={<Link href={sourceHref(sourceId) ?? "/sources"} className="px-4 py-2 rounded border border-outline-variant text-body-md font-medium text-on-surface hover:bg-surface-container-low transition-colors focus-ring">Source profile</Link>}
      />

      {error ? <Message tone="error">{error}</Message> : null}
      {loading && !data ? <RecordsListSkeleton /> : null}

      {data && !data.records.length ? (
        <EmptyState>No rows are loaded for this source yet.</EmptyState>
      ) : null}

      {data && data.records.length ? (
        <div className="card-level-1 rounded-lg divide-y divide-outline-variant">
          {data.records.map((ref) => {
            const href = recordHref(ref.table, ref.pk ?? ref.id);
            const row = (
              <div className="flex items-center gap-4 px-4 py-3 hover:bg-surface-container-low transition-colors">
                <span className="font-label-caps text-label-caps text-on-surface-variant uppercase w-32 shrink-0 truncate">{typeLabel(ref.table)}</span>
                <span className="font-body-md text-body-md text-on-surface flex-1 min-w-0 truncate">{ref.title}</span>
                {ref.amount ? <span className="font-data-tabular text-data-tabular text-primary shrink-0">{money(ref.amount)}</span> : null}
                <span className="font-data-tabular text-data-tabular text-on-surface-variant shrink-0 w-24 text-right">{ref.date ?? "—"}</span>
              </div>
            );
            return href ? (
              <Link key={`${ref.table}-${ref.pk ?? ref.id}`} href={`${href}?from=records&source=${encodeURIComponent(sourceId)}`} className="block focus-ring">{row}</Link>
            ) : (
              <div key={`${ref.table}-${ref.pk ?? ref.id}`}>{row}</div>
            );
          })}
        </div>
      ) : null}

      {data ? (
        <div className="flex items-center justify-between mt-gutter">
          <button
            type="button"
            disabled={pageNumber <= 1}
            onClick={() => setCursors((s) => (s.length > 1 ? s.slice(0, -1) : s))}
            className="px-4 py-2 rounded border border-outline-variant text-body-md font-medium text-on-surface disabled:opacity-40 disabled:cursor-not-allowed hover:bg-surface-container-low transition-colors focus-ring"
          >
            Previous
          </button>
          <span className="font-data-tabular text-data-tabular text-on-surface-variant">Page {pageNumber}</span>
          <button
            type="button"
            disabled={!data.has_more}
            onClick={() => setCursors((s) => [...s, data.next_cursor])}
            className="px-4 py-2 rounded border border-outline-variant text-body-md font-medium text-on-surface disabled:opacity-40 disabled:cursor-not-allowed hover:bg-surface-container-low transition-colors focus-ring"
          >
            Next
          </button>
        </div>
      ) : null}
    </div>
  );
}

function RecordsListSkeleton() {
  return (
    <div className="card-level-1 rounded-lg divide-y divide-outline-variant">
      {[0, 1, 2, 3, 4, 5, 6, 7].map((i) => <div key={i} className="skeleton h-12" />)}
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
