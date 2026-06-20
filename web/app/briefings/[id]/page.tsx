"use client";

import Link from "next/link";
import { use } from "react";
import { useSearchParams } from "next/navigation";
import { riskColorVar, type GraphFinding, type ReportDetail, type Scores } from "@/lib/api";
import { evidenceHref, findingHref } from "@/lib/navigation";
import { RelatedItems, type RelatedItem } from "@/components/intelligence";
import { useApi } from "@/lib/use-api";
import { EvidenceRows, Eyebrow, OriginalSourceLink, Panel, RiskBadge, SectionHeader, SkeletonBlock } from "@/components/ui";

function typeLabel(t: string) {
  return t.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// Light scorecard for the parchment "deliverable" surface (the dark Scorecard
// component is for the terminal workspace).
const DIMS: { key: keyof Scores; label: string }[] = [
  { key: "regulatory_risk", label: "Regulatory Risk" },
  { key: "policy_volatility", label: "Policy Volatility" },
  { key: "election_sensitivity", label: "Election Sensitivity" },
  { key: "lobbying_intensity", label: "Lobbying Intensity" },
];
function LightScorecard({ scores }: { scores: Scores }) {
  return (
    <div className="space-y-3.5">
      {DIMS.map((d) => {
        const v = scores[d.key] as number;
        return (
          <div key={d.key}>
            <div className="flex items-baseline justify-between mb-1">
              <span className="text-sm text-navy">{d.label}</span>
              <span className="text-sm font-semibold" style={{ color: riskColorVar(v) }}>{v.toFixed(1)}</span>
            </div>
            <div className="h-1.5 rounded-full bg-parchment-2 overflow-hidden">
              <div className="h-full rounded-full" style={{ width: `${(v / 10) * 100}%`, background: riskColorVar(v) }} />
            </div>
            {scores.drivers?.[d.key] && <p className="text-xs text-slate mt-1 leading-snug">{scores.drivers[d.key]}</p>}
          </div>
        );
      })}
    </div>
  );
}

export default function BriefingReader({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const searchParams = useSearchParams();
  const context = briefingContext(searchParams);
  const { data, loading, error } = useApi<ReportDetail>(`/api/reports/${id}`);

  if (error) {
    return (
      <div className="mx-auto max-w-[1180px] px-5 py-20 text-center text-slate">
        Couldn&rsquo;t load this briefing. {error}
        <div className="mt-3"><Link href="/briefings" className="text-brass-700 underline">← All briefings</Link></div>
      </div>
    );
  }
  if (loading || !data) {
    return (
      <div className="mx-auto max-w-[900px] px-5 py-12 space-y-4">
        <SkeletonBlock className="h-8 w-72" />
        <SkeletonBlock className="h-40 w-full" />
        <SkeletonBlock className="h-64 w-full" />
      </div>
    );
  }

  const findingItems = reportFindingItems(data.graph_findings ?? [], context);
  const evidenceRefs = data.source_references ?? [];

  return (
    <div className="bg-parchment">
      {/* Classification strip */}
      <div className="bg-navy text-parchment border-b border-brass/25">
        <div className="mx-auto max-w-[900px] px-6 py-2.5 flex items-center justify-between text-[11px] uppercase tracking-[0.18em]">
          <Link href={context?.href ?? "/briefings"} className="text-parchment/60 hover:text-brass">{context ? `← ${context.label}` : "← Briefings"}</Link>
          <span className="text-red bg-red/10 border border-red/30 rounded px-2 py-0.5">Confidential</span>
        </div>
      </div>

      <article className="mx-auto max-w-[900px] px-6 py-10">
        {/* Cover block */}
        <header className="border-b border-slate/20 pb-7 mb-8">
          <Eyebrow>{typeLabel(data.report_type)}</Eyebrow>
          <h1 className="font-display text-4xl text-navy mt-2 leading-tight">{data.company_name}</h1>
          <div className="flex flex-wrap items-center gap-x-5 gap-y-2 mt-4 text-sm text-slate">
            <span className="flex items-center gap-2">
              Overall risk {data.risk_scores ? <RiskBadge score={data.risk_scores.overall} /> : "—"}
            </span>
            <span>Status: {data.status.replace(/_/g, " ")}</span>
            <span>Drafted via {data.generated_by}</span>
          </div>
          <div className="flex gap-3 mt-5">
            <a
              href={`/report/${data.id}/pdf`}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 rounded-lg bg-navy text-parchment px-4 py-2 text-sm font-semibold hover:bg-navy-600 transition-colors"
            >
              Download PDF
            </a>
            <a
              href={`/report/${data.id}`}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate/30 text-navy px-4 py-2 text-sm font-semibold hover:bg-parchment-2 transition-colors"
            >
              Branded view
            </a>
          </div>
        </header>

        {/* Scorecard */}
        {data.risk_scores && (
          <section className="mb-9 rounded-xl border border-slate/20 bg-paper p-6">
            <div className="eyebrow !text-slate mb-4">Risk Scorecard</div>
            <LightScorecard scores={data.risk_scores} />
          </section>
        )}


        {(findingItems.length || evidenceRefs.length) ? (
          <section className="mb-9 grid md:grid-cols-2 gap-4">
            <Panel title="Connected findings" bodyClass="p-4">
              <RelatedItems
                items={findingItems}
                empty="No graph findings are attached to this report yet."
              />
            </Panel>
            <Panel title="Supporting evidence" bodyClass="p-4">
              <SectionHeader title="Internal records" subtitle="Evidence opens inside Nessus first." />
              <EvidenceRows refs={evidenceRefs} limit={8} hrefFor={(ref) => withContext(evidenceHref(ref), context)} />
              {externalSourceRefs(evidenceRefs).length ? (
                <div className="mt-3 pt-3 border-t border-line space-y-1.5">
                  <div className="mono text-[10px] text-muted uppercase">Original sources</div>
                  {externalSourceRefs(evidenceRefs).slice(0, 4).map((ref) => (
                    <OriginalSourceLink key={`${ref.table}:${ref.pk ?? ref.id}:external`} href={ref.url!} source={ref.source} className="mono text-[10px] text-muted hover:text-fg" />
                  ))}
                </div>
              ) : null}
            </Panel>
          </section>
        ) : null}

        {/* Sections */}
        <div className="space-y-9">
          {data.sections
            .filter((s) => s.title !== "Risk Scorecard")
            .map((s) => (
              <section key={s.key}>
                <h2 className="font-display text-2xl text-navy mb-3 pb-2 border-b border-brass/30">{s.title}</h2>
                <div className="briefing-prose" dangerouslySetInnerHTML={{ __html: s.html }} />
              </section>
            ))}
        </div>

        {data.analyst_notes && (
          <section className="mt-10 rounded-xl bg-navy text-parchment/90 p-6">
            <div className="eyebrow !text-brass mb-2">Analyst Notes</div>
            <p className="text-sm leading-relaxed whitespace-pre-wrap">{data.analyst_notes}</p>
          </section>
        )}
      </article>
    </div>
  );
}

type BriefingContextValue =
  | { from: "search"; label: string; href: string }
  | { from: "sector"; label: string; href: string }
  | { from: "finding"; label: string; href: string }
  | null;

function briefingContext(searchParams: ReturnType<typeof useSearchParams>): BriefingContextValue {
  const from = searchParams.get("from");
  if (from === "search") {
    const q = searchParams.get("q") ?? "";
    return { from, label: q ? `Search: ${q}` : "Search", href: `/search${q ? `?q=${encodeURIComponent(q)}` : ""}` };
  }
  if (from === "sector") {
    const sector = searchParams.get("sector") ?? "";
    return { from, label: sector ? `Sector: ${sector}` : "Sectors", href: sector ? `/sectors/${encodeURIComponent(sector)}` : "/sectors" };
  }
  if (from === "finding") {
    const finding = searchParams.get("finding") ?? "";
    return { from, label: "Finding", href: finding ? `/signals/${encodeURIComponent(finding)}` : "/signals" };
  }
  return null;
}

function withContext(href: string | null, context: BriefingContextValue): string | null {
  if (!href || !context) return href;
  const glue = href.includes("?") ? "&" : "?";
  if (context.from === "search") {
    const q = context.href.includes("?q=") ? decodeURIComponent(context.href.split("?q=")[1] ?? "") : "";
    return `${href}${glue}from=search${q ? `&q=${encodeURIComponent(q)}` : ""}`;
  }
  if (context.from === "sector") {
    const sector = context.href.split("/sectors/")[1];
    return `${href}${glue}from=sector${sector ? `&sector=${encodeURIComponent(decodeURIComponent(sector))}` : ""}`;
  }
  const finding = context.href.split("/signals/")[1];
  return `${href}${glue}from=finding${finding ? `&finding=${encodeURIComponent(decodeURIComponent(finding))}` : ""}`;
}

function reportFindingItems(findings: GraphFinding[], context: BriefingContextValue): RelatedItem[] {
  return findings.map((finding, index) => ({
    id: `report-finding:${finding.title}:${index}`,
    title: finding.title,
    type: "Finding",
    href: withContext(findingHref(finding.title), context),
    description: finding.summary,
    meta: finding.references?.length ? `${finding.references.length} evidence record${finding.references.length === 1 ? "" : "s"}` : finding.confidence,
    relationship: "report includes finding",
    strength: "supported",
    source: finding.sector?.name ?? finding.related_sectors?.[0]?.name ?? null,
  }));
}

function externalSourceRefs(refs: ReportDetail["source_references"]) {
  return refs.filter((ref) => ref.url);
}
