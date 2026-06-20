"use client";

import Link from "next/link";
import { useMemo } from "react";
import type { ReactNode } from "react";
import { useApi } from "@/lib/use-api";
import type { ReportSummary, ReportsResponse } from "@/lib/api";
import { reportHref } from "@/lib/navigation";

const STATUS_CLASS: Record<string, string> = {
  approved: "status-chip-green",
  final: "status-chip-green",
  draft: "status-chip-amber",
  review: "status-chip-amber",
  generated: "bg-secondary-container text-on-secondary-container",
};

export default function ReportsHub() {
  const { data, loading, error } = useApi<ReportsResponse>("/api/reports");
  const reports = data?.reports ?? [];
  const stats = useMemo(() => reportStats(reports), [reports]);

  return (
    <div className="animate-rise">
      <div className="flex flex-wrap justify-between items-start gap-4 mb-gutter">
        <div>
          <h1 className="font-display-lg text-display-lg text-primary">Reports Hub</h1>
          <p className="font-body-lg text-body-lg text-on-surface-variant mt-unit max-w-2xl">
            Review generated diligence briefings, open connected findings, and inspect supporting evidence inside Polaris.
          </p>
        </div>
        <Link
          href="/search"
          className="px-4 py-2.5 bg-primary text-on-primary rounded font-body-md text-body-md font-medium hover:bg-primary-container transition-colors flex items-center gap-2 shrink-0 focus-ring"
        >
          <span className="material-symbols-outlined text-[20px]">auto_awesome</span>
          Start Research
        </Link>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-gutter mb-gutter">
        <StatCard label="All Briefings" value={String(data?.count ?? reports.length)} sub="Internal report records" icon="description" />
        <StatCard label="Approved" value={String(stats.approved)} sub="Ready for customer review" icon="task_alt" />
        <StatCard label="Needs Review" value={String(stats.needsReview)} sub="Drafts or generated reports" icon="rate_review" />
      </div>

      <section className="card-level-1 rounded-lg overflow-hidden">
        <div className="px-density-comfortable py-density-comfortable border-b border-outline-variant flex flex-wrap justify-between items-center gap-3">
          <div>
            <h2 className="font-headline-sm text-headline-sm text-primary">Recent Intelligence</h2>
            <p className="text-body-md text-on-surface-variant mt-1">Every report opens as an internal briefing with connected findings and evidence.</p>
          </div>
          <Link href="/dashboard" className="px-3 py-1.5 border border-outline-variant rounded text-on-surface-variant text-body-md font-body-md flex items-center gap-2 hover:bg-surface-container-low transition-colors focus-ring">
            <span className="material-symbols-outlined text-[18px]">space_dashboard</span>
            Dashboard
          </Link>
        </div>

        {loading ? (
          <div className="p-density-comfortable space-y-3">
            {[0, 1, 2, 3].map((i) => <div key={i} className="skeleton h-16" />)}
          </div>
        ) : error ? (
          <Message tone="error">{error}</Message>
        ) : reports.length ? (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse min-w-[760px]">
              <thead>
                <tr className="bg-surface-container-low border-b border-outline-variant">
                  <th className="py-3 px-density-comfortable font-label-caps text-label-caps text-on-surface-variant uppercase tracking-wider">Briefing</th>
                  <th className="py-3 px-density-comfortable font-label-caps text-label-caps text-on-surface-variant uppercase tracking-wider">Type</th>
                  <th className="py-3 px-density-comfortable font-label-caps text-label-caps text-on-surface-variant uppercase tracking-wider">Score</th>
                  <th className="py-3 px-density-comfortable font-label-caps text-label-caps text-on-surface-variant uppercase tracking-wider">Status</th>
                  <th className="py-3 px-density-comfortable font-label-caps text-label-caps text-on-surface-variant uppercase tracking-wider text-right">Created</th>
                </tr>
              </thead>
              <tbody className="font-data-tabular text-data-tabular text-on-surface">
                {reports.map((report) => (
                  <ReportRow key={report.id} report={report} />
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="p-density-comfortable">
            <div className="rounded border border-outline-variant bg-surface-container-low px-4 py-5">
              <div className="font-headline-sm text-[18px] text-primary">No generated briefings yet.</div>
              <p className="text-body-md text-on-surface-variant mt-1">Run a research request or open the dashboard to inspect live findings while report history builds up.</p>
              <div className="flex flex-wrap gap-2 mt-4">
                <Link href="/search" className="px-3 py-2 rounded bg-primary text-on-primary text-body-md font-medium hover:bg-primary-container transition-colors focus-ring">Ask Nessus</Link>
                <Link href="/dashboard" className="px-3 py-2 rounded border border-outline-variant text-body-md font-medium hover:bg-surface-container-low transition-colors focus-ring">Open dashboard</Link>
              </div>
            </div>
          </div>
        )}

        <div className="flex justify-between items-center px-density-comfortable py-3 border-t border-outline-variant">
          <span className="font-data-tabular text-data-tabular text-on-surface-variant">Showing {reports.length} of {data?.count ?? reports.length} briefings</span>
          <Link href="/sources" className="font-label-caps text-label-caps text-on-surface-variant uppercase hover:text-primary focus-ring rounded">Source health</Link>
        </div>
      </section>
    </div>
  );
}

function ReportRow({ report }: { report: ReportSummary }) {
  const status = report.status || "generated";
  const statusClass = STATUS_CLASS[status.toLowerCase()] ?? "bg-surface-container-high text-on-surface-variant";

  return (
    <tr className="border-b border-outline-variant zebra-row hover:bg-surface-container-low transition-colors">
      <td className="py-4 px-density-comfortable">
        <Link href={reportHref(report.id) ?? "/briefings"} className="flex items-center gap-2 font-medium text-primary hover:underline focus-ring rounded">
          <span className="material-symbols-outlined text-[18px] text-on-surface-variant">description</span>
          <span className="break-words">{report.company_name}</span>
        </Link>
        <div className="text-[11px] text-on-surface-variant mt-1">Generated by {report.generated_by || "system"}</div>
      </td>
      <td className="py-4 px-density-comfortable text-on-surface-variant">{labelize(report.report_type)}</td>
      <td className="py-4 px-density-comfortable">
        <span className="font-bold text-primary">{report.overall == null ? "Pending" : `${Math.round(report.overall)}/100`}</span>
      </td>
      <td className="py-4 px-density-comfortable">
        <span className={`px-2 py-1 rounded-full text-[12px] font-medium ${statusClass}`}>{labelize(status)}</span>
      </td>
      <td className="py-4 px-density-comfortable text-on-surface-variant text-right">{formatDate(report.created_at)}</td>
    </tr>
  );
}

function StatCard({ label, value, sub, icon }: { label: string; value: string; sub: string; icon: string }) {
  return (
    <div className="card-level-1 card-level-2 rounded-lg border-l-4 border-primary p-density-comfortable">
      <div className="flex justify-between items-start mb-4">
        <span className="font-label-caps text-label-caps text-on-surface-variant uppercase">{label}</span>
        <span className="material-symbols-outlined text-on-surface-variant">{icon}</span>
      </div>
      <div className="font-display-lg text-headline-md text-primary leading-none mb-2">{value}</div>
      <p className="font-body-md text-body-md text-on-surface-variant">{sub}</p>
    </div>
  );
}

function Message({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "error" }) {
  return (
    <div className={`m-density-comfortable rounded border px-4 py-3 font-body-md text-body-md ${tone === "error" ? "border-error/30 bg-error/10 text-error" : "border-outline-variant bg-surface-container-low text-on-surface-variant"}`}>
      {children}
    </div>
  );
}

function reportStats(reports: ReportSummary[]) {
  return reports.reduce(
    (acc, report) => {
      const status = report.status.toLowerCase();
      if (status === "approved" || status === "final") acc.approved += 1;
      else acc.needsReview += 1;
      return acc;
    },
    { approved: 0, needsReview: 0 },
  );
}

function labelize(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-CA", { month: "short", day: "numeric", year: "numeric" }).format(date);
}
