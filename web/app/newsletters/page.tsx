"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { api, num, type NewsletterSummary, type NewslettersResponse } from "@/lib/api";
import { newsletterHref } from "@/lib/navigation";
import { useApi } from "@/lib/use-api";

export default function NewslettersPage() {
  const router = useRouter();
  const { data, loading, error } = useApi<NewslettersResponse>("/api/newsletters");
  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const issues = useMemo(() => data?.issues ?? [], [data?.issues]);
  const stats = useMemo(() => newsletterStats(issues), [issues]);

  async function generateIssue() {
    setGenerating(true);
    setGenerateError(null);
    try {
      const issue = await api<NewsletterSummary>("/api/newsletters/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      router.push(newsletterHref(issue.id) ?? "/newsletters");
    } catch (err) {
      setGenerateError(err instanceof Error ? err.message : String(err));
    } finally {
      setGenerating(false);
    }
  }

  return (
    <div className="animate-rise">
      <div className="flex flex-wrap justify-between items-start gap-4 mb-gutter">
        <div>
          <h1 className="font-display-lg text-display-lg text-primary">Weekly Newsletter</h1>
          <p className="font-body-lg text-body-lg text-on-surface-variant mt-unit max-w-2xl">
            Generate cited, Opus-drafted weekly political intelligence issues for internal review and email-ready sharing.
          </p>
        </div>
        <button
          type="button"
          onClick={generateIssue}
          disabled={generating}
          className="px-4 py-2.5 bg-primary text-on-primary rounded font-body-md text-body-md font-medium hover:bg-primary-container disabled:opacity-60 transition-colors flex items-center gap-2 shrink-0 focus-ring"
        >
          <span className="material-symbols-outlined text-[20px]">{generating ? "hourglass_top" : "auto_awesome"}</span>
          {generating ? "Generating..." : "Generate Prior Week"}
        </button>
      </div>

      {generateError ? (
        <div className="mb-gutter rounded border border-error/30 bg-error/10 px-4 py-3 text-error text-body-md">
          {generateError}
        </div>
      ) : null}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-gutter mb-gutter">
        <StatCard label="Issues" value={num(data?.count ?? issues.length)} sub="Generated newsletter drafts" icon="mark_email_read" />
        <StatCard label="Avg. Length" value={stats.avgWords ? num(stats.avgWords) : "0"} sub="Words per issue" icon="notes" />
        <StatCard label="Latest Week" value={stats.latestWeek || "—"} sub="Most recent issue window" icon="calendar_month" />
      </div>

      <section className="card-level-1 rounded-lg overflow-hidden">
        <div className="px-density-comfortable py-density-comfortable border-b border-outline-variant flex flex-wrap justify-between items-center gap-3">
          <div>
            <h2 className="font-headline-sm text-headline-sm text-primary">Generated Issues</h2>
            <p className="text-body-md text-on-surface-variant mt-1">Each issue opens with validation detail, source links, and the finished email HTML.</p>
          </div>
          <Link href="/sources" className="px-3 py-1.5 border border-outline-variant rounded text-on-surface-variant text-body-md font-body-md flex items-center gap-2 hover:bg-surface-container-low transition-colors focus-ring">
            <span className="material-symbols-outlined text-[18px]">dataset</span>
            Source health
          </Link>
        </div>

        {loading ? (
          <div className="p-density-comfortable space-y-3">
            {[0, 1, 2].map((i) => <div key={i} className="skeleton h-16" />)}
          </div>
        ) : error ? (
          <Message tone="error">{error}</Message>
        ) : issues.length ? (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse min-w-[760px]">
              <thead>
                <tr className="bg-surface-container-low border-b border-outline-variant">
                  <th className="py-3 px-density-comfortable font-label-caps text-label-caps text-on-surface-variant uppercase tracking-wider">Issue</th>
                  <th className="py-3 px-density-comfortable font-label-caps text-label-caps text-on-surface-variant uppercase tracking-wider">Week</th>
                  <th className="py-3 px-density-comfortable font-label-caps text-label-caps text-on-surface-variant uppercase tracking-wider">Model</th>
                  <th className="py-3 px-density-comfortable font-label-caps text-label-caps text-on-surface-variant uppercase tracking-wider">Words</th>
                  <th className="py-3 px-density-comfortable font-label-caps text-label-caps text-on-surface-variant uppercase tracking-wider text-right">Created</th>
                </tr>
              </thead>
              <tbody className="font-data-tabular text-data-tabular text-on-surface">
                {issues.map((issue) => <IssueRow key={issue.id} issue={issue} />)}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="p-density-comfortable">
            <div className="rounded border border-outline-variant bg-surface-container-low px-4 py-5">
              <div className="font-headline-sm text-[18px] text-primary">No newsletter issues yet.</div>
              <p className="text-body-md text-on-surface-variant mt-1">Generate the prior week once the source feeds are fresh and Opus is configured.</p>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}

function IssueRow({ issue }: { issue: NewsletterSummary }) {
  return (
    <tr className="border-b border-outline-variant zebra-row hover:bg-surface-container-low transition-colors">
      <td className="py-4 px-density-comfortable">
        <Link href={newsletterHref(issue.id) ?? "/newsletters"} className="flex items-center gap-2 font-medium text-primary hover:underline focus-ring rounded">
          <span className="material-symbols-outlined text-[18px] text-on-surface-variant">newspaper</span>
          <span className="break-words">{issue.title}</span>
        </Link>
        <div className="text-[11px] text-on-surface-variant mt-1">{labelize(issue.status)} via {issue.generated_by}</div>
      </td>
      <td className="py-4 px-density-comfortable text-on-surface-variant">{formatDate(issue.week_start)} - {formatDate(issue.week_end)}</td>
      <td className="py-4 px-density-comfortable text-on-surface-variant">{issue.model}</td>
      <td className="py-4 px-density-comfortable font-bold text-primary">{num(issue.word_count)}</td>
      <td className="py-4 px-density-comfortable text-on-surface-variant text-right">{formatDate(issue.created_at)}</td>
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

function Message({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "neutral" | "error" }) {
  return (
    <div className={`m-density-comfortable rounded border px-4 py-3 font-body-md text-body-md ${tone === "error" ? "border-error/30 bg-error/10 text-error" : "border-outline-variant bg-surface-container-low text-on-surface-variant"}`}>
      {children}
    </div>
  );
}

function newsletterStats(issues: NewsletterSummary[]) {
  const avgWords = issues.length ? Math.round(issues.reduce((sum, issue) => sum + issue.word_count, 0) / issues.length) : 0;
  const latest = issues[0];
  return { avgWords, latestWeek: latest ? `${formatDate(latest.week_start)} - ${formatDate(latest.week_end)}` : "" };
}

function labelize(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-CA", { month: "short", day: "numeric", year: "numeric" }).format(date);
}
