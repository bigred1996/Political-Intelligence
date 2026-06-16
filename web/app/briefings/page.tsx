"use client";

import Link from "next/link";
import type { ReportsResponse } from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { Eyebrow, Panel, RiskBadge, SkeletonBlock } from "@/components/ui";

function typeLabel(t: string) {
  return t.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export default function BriefingsIndex() {
  const { data, loading } = useApi<ReportsResponse>("/api/reports");

  return (
    <div>
      <section className="bg-panel border-b border-line map-grid">
        <div className="mx-auto max-w-[1320px] px-4 py-10">
          <Eyebrow>Briefings</Eyebrow>
          <h1 className="text-3xl font-semibold text-fg-bright mt-2 leading-tight">Commissioned intelligence briefings</h1>
          <p className="text-fg-dim mt-2 max-w-2xl text-sm">
            Analyst-reviewed, nine-section political-risk reports — scored across four dimensions and
            served as a confidential briefing.
          </p>
        </div>
      </section>

      <div className="mx-auto max-w-[1320px] px-4 py-6">
        {loading ? (
          <div className="space-y-2">{Array.from({ length: 6 }).map((_, i) => <SkeletonBlock key={i} className="h-12 rounded" />)}</div>
        ) : !data?.count ? (
          <p className="text-fg-dim">No briefings yet.</p>
        ) : (
          <Panel bodyClass="p-0">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-fg-dim mono text-[10px] uppercase tracking-wide border-b border-line">
                  <th className="py-2.5 px-4 font-medium">Subject</th>
                  <th className="py-2.5 px-3 font-medium">Type</th>
                  <th className="py-2.5 px-3 font-medium">Overall</th>
                  <th className="py-2.5 px-3 font-medium">Status</th>
                  <th className="py-2.5 px-4 font-medium text-right">Open</th>
                </tr>
              </thead>
              <tbody>
                {data.reports.map((r) => (
                  <tr key={r.id} className="border-b border-line/60 last:border-0 hover:bg-panel-2 transition-colors">
                    <td className="py-2.5 px-4"><Link href={`/briefings/${r.id}`} className="font-medium text-fg hover:text-brass-bright">{r.company_name}</Link></td>
                    <td className="py-2.5 px-3 text-fg-dim">{typeLabel(r.report_type)}</td>
                    <td className="py-2.5 px-3">{r.overall != null ? <RiskBadge score={r.overall} /> : "—"}</td>
                    <td className="py-2.5 px-3"><span className="mono text-[10px] uppercase tracking-wide text-fg-dim">{r.status.replace(/_/g, " ")}</span></td>
                    <td className="py-2.5 px-4 text-right"><Link href={`/briefings/${r.id}`} className="mono text-xs text-brass-bright hover:underline">VIEW →</Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
        )}
      </div>
    </div>
  );
}
