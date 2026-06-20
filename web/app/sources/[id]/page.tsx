"use client";

import Link from "next/link";
import { use } from "react";
import { type GraphFinding, type SourceDetail } from "@/lib/api";
import { evidenceHref, findingHref, sectorHref, sourceLabel, typeLabel } from "@/lib/navigation";
import { AvatarLogo, RelatedItems, type RelatedItem } from "@/components/intelligence";
import { ConfidenceBadge, CoverageBadge, EmptyState, EvidenceRows, PageHeader, Panel, SectionHeader, SkeletonBlock, SourceTag } from "@/components/ui";
import { useApi } from "@/lib/use-api";

export default function SourceDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data, loading, error } = useApi<SourceDetail>(id ? `/api/sources/${encodeURIComponent(id)}` : null);

  if (loading) {
    return <div className="pr-1 pb-4 space-y-[14px]"><SkeletonBlock className="h-28 rounded-lg" /><SkeletonBlock className="h-72 rounded-lg" /></div>;
  }
  if (error || !data) {
    return (
      <div className="pr-1 pb-4">
        <PageHeader title="Source not found" subtitle="This source is not yet supported as an internal Nessus object." action={<Link href="/sources" className="text-[12.5px] font-semibold text-fg hover:text-brass-bright">All sources</Link>} />
        <EmptyState>{error || "No source detail is available."}</EmptyState>
      </div>
    );
  }

  const findingItems = findingItemsFor(data.related_findings);
  const recordItems = data.connected_records.slice(0, 10).map((record, index): RelatedItem => ({
    id: `${record.table}:${record.pk ?? record.id}:${index}`,
    title: record.title,
    type: recordTypeLabel(record.record_type, record.source, record.table),
    href: evidenceHref(record),
    description: record.date || null,
    relationship: "source supports record",
    strength: "direct",
    source: sourceLabel(record.table, record.source),
  }));

  return (
    <div className="pr-1 pb-4 space-y-[14px] animate-rise">
      <PageHeader
        title={data.label}
        subtitle={data.summary}
        action={<Link href="/sources" className="text-[12.5px] font-semibold text-fg hover:text-brass-bright">All sources</Link>}
      />

      <section className="grid grid-cols-12 gap-[14px]">
        <Panel className="col-span-12 xl:col-span-8" bodyClass="p-[22px]">
          <div className="flex flex-wrap items-center gap-2 mb-4">
            <AvatarLogo name={data.label} type="source" />
            <CoverageBadge status={data.status} />
            <CoverageBadge status={data.freshness} />
            <ConfidenceBadge value={data.confidence === "planned" ? "low" : data.confidence} />
            <SourceTag>Internal source profile</SourceTag>
          </div>
          <SectionHeader title="Why it matters" subtitle="Source status affects how much confidence Nessus should place on connected findings." />
          <p className="text-[15px] text-fg leading-relaxed">{data.why_it_matters}</p>
        </Panel>
        <Panel className="col-span-12 xl:col-span-4" bodyClass="p-[22px]">
          <SectionHeader title="Normalized data" />
          <div className="grid grid-cols-2 gap-3">
            <Fact label="Rows" value={String(data.important_data.rows ?? 0)} />
            <Fact label="Table" value={String(data.important_data.table ?? "planned")} />
            <Fact label="Freshness" value={data.freshness} />
            <Fact label="Count method" value={String(data.important_data.row_count_method ?? "unknown")} />
          </div>
        </Panel>
      </section>

      <section className="grid grid-cols-12 gap-[14px]">
        <Panel className="col-span-12 xl:col-span-4" bodyClass="p-[22px]">
          <SectionHeader title="Affected sectors" />
          {data.affected_sectors.length ? <div className="flex flex-wrap gap-2">{data.affected_sectors.map((sector) => <Link key={sector.slug} href={sectorHref(sector.slug) ?? "/sectors"} className="text-[12.5px] font-medium rounded-full px-3 py-1.5 bg-panel-2 text-fg hover:text-brass-bright">{sector.name}</Link>)}</div> : <EmptyState>No sector has been inferred for this source yet.</EmptyState>}
        </Panel>
        <Panel className="col-span-12 xl:col-span-4" bodyClass="p-[22px]">
          <SectionHeader title="Related findings" />
          <RelatedItems items={findingItems} empty="No findings currently cite this source." />
        </Panel>
        <Panel className="col-span-12 xl:col-span-4" bodyClass="p-[22px]">
          <SectionHeader title="Connected records" />
          <RelatedItems items={recordItems} empty="No internal records are loaded for this source yet." />
        </Panel>
      </section>

      {data.known_gaps.length ? (
        <Panel bodyClass="p-[22px]">
          <SectionHeader title="Known gaps" subtitle="These limits should temper interpretation and diligence conclusions." />
          <div className="grid md:grid-cols-2 gap-2">
            {data.known_gaps.map((gap) => <div key={gap} className="rounded-xl border border-line bg-panel-2 p-3 text-[13px] text-fg/90 leading-snug">{gap}</div>)}
          </div>
        </Panel>
      ) : null}

      <section className="grid grid-cols-12 gap-[14px]">
        {data.groups.map((group) => (
          <Panel key={group.table} className="col-span-12 lg:col-span-6" title={group.label} right={<span className="mono text-xs text-fg-dim">{group.count.toLocaleString()}</span>}>
            <EvidenceRows refs={group.records} limit={8} />
          </Panel>
        ))}
      </section>

      {data.timeline.length ? <Panel title="Activity timeline"><EvidenceRows refs={data.timeline} limit={10} /></Panel> : null}
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-line bg-panel-2 p-3 min-w-0">
      <div className="mono text-[10px] text-muted uppercase">{label}</div>
      <div className="text-[13px] font-semibold text-fg-bright mt-1 break-words">{value}</div>
    </div>
  );
}

function findingItemsFor(findings: GraphFinding[]): RelatedItem[] {
  return findings.map((finding, index) => ({
    id: `finding:${finding.title}:${index}`,
    title: finding.title,
    type: "Finding",
    href: findingHref(finding.title),
    description: finding.summary,
    relationship: "finding supported by source",
    strength: "supported",
    source: finding.sector?.name ?? finding.related_sectors?.[0]?.name ?? null,
  }));
}

function recordTypeLabel(recordType?: string | null, source?: string | null, table?: string | null): string {
  if (source === "Public statements" || source === "social_statements" || source === "public_statements" || recordType === "public_statement" || recordType === "social_post") {
    return "Public statement";
  }
  return typeLabel(table);
}
