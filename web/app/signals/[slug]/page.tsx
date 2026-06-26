"use client";

import Link from "next/link";
import { use } from "react";
import { useSearchParams } from "next/navigation";
import { Card, Crumb, DetailHeader } from "@/components/nessus";
import { AvatarLogo, RelatedItems, type RelatedItem } from "@/components/intelligence";
import { useApi } from "@/lib/use-api";
import type { EvidenceRef, FindingsResponse, GraphFinding, ReportsResponse } from "@/lib/api";
import { committeeHref, entityHref, evidenceHref, findingSlug, legacyFindingSlug, personHref, reportHref, sectorHref, typeLabel } from "@/lib/navigation";

export default function SignalDetail({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  const searchParams = useSearchParams();
  const { data, loading, error } = useApi<FindingsResponse>("/api/graph/findings");
  const decoded = decodeURIComponent(slug);
  const context = findingContext(searchParams);
  const { data: reports } = useApi<ReportsResponse>(`/api/reports/by-finding/${encodeURIComponent(decoded)}`);
  const finding = data?.findings.find((f) => findingSlug(f) === decoded || legacyFindingSlug(f) === decoded) ?? data?.findings[0] ?? null;

  if (loading) return <SignalSkeleton />;
  if (error) return <Message tone="error">{error}</Message>;
  if (!finding) return <Message>No finding is available for this workspace yet.</Message>;

  const stableFindingSlug = findingSlug(finding) ?? legacyFindingSlug(finding) ?? decoded;
  const evidenceItems = evidenceRelatedItems(finding, stableFindingSlug);
  const sectorItems = sectorRelatedItems(finding, stableFindingSlug);
  const actorItems = actorRelatedItems(finding, stableFindingSlug);
  const committeeItems = committeeRelatedItems(finding, stableFindingSlug);
  const companyItems = companyRelatedItems(finding, stableFindingSlug);
  const billItems = recordRelatedItems(finding, stableFindingSlug, ["bills"]);
  const fileItems = recordRelatedItems(finding, stableFindingSlug, ["lobbying", "ocl_registrations", "gazette", "tribunal", "source_records"]);
  const reportItems: RelatedItem[] = (reports?.reports ?? []).map((report) => ({
    id: report.id,
    title: report.company_name,
    type: "Report",
    href: withFindingContext(reportHref(report.id), stableFindingSlug),
    description: `${report.report_type} - ${report.status}`,
    relationship: "report includes finding",
    strength: "direct",
  }));

  return (
    <div className="animate-rise">
      <Crumb items={[{ label: context.label, href: context.href }, { label: "Finding" }]} />
      <DetailHeader
        eyebrow={`${finding.type.replace(/_/g, " ")} - ${finding.confidence}`}
        title={finding.title}
        subtitle={finding.summary || "Nessus connected this finding from the available source graph."}
        action={<Link href="/search" className="px-4 py-2 bg-primary text-on-primary rounded font-body-md text-body-md hover:bg-primary-container transition-colors flex items-center gap-2 focus-ring">
          <span className="material-symbols-outlined text-[18px]">forum</span> Ask Nessus
        </Link>}
      />

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-gutter">
        <div className="lg:col-span-8 space-y-gutter">
          <Card icon="psychology" title="Interpretation">
            <div className="p-density-comfortable font-memo-body text-memo-body text-on-surface leading-relaxed">
              {finding.summary || "This is an observed relationship in the current evidence graph. Review the underlying records before treating it as causal."}
              <div className="mt-5 flex flex-wrap gap-2">
                <StatusChip level={finding.severity}>{finding.severity}</StatusChip>
                <span className="font-label-caps text-label-caps bg-surface-container-highest text-on-surface-variant px-2 py-1 rounded-full uppercase">{finding.confidence}</span>
                {(finding as GraphFinding & { relationship_strength?: string }).relationship_strength && (
                  <span className="font-label-caps text-label-caps bg-primary/10 text-primary px-2 py-1 rounded-full uppercase">
                    {(finding as GraphFinding & { relationship_strength?: string }).relationship_strength}
                  </span>
                )}
              </div>
            </div>
          </Card>

          <Card icon="history" title="Supporting Evidence">
            <div className="p-density-comfortable">
              <RelatedItems items={evidenceItems} empty="No supporting evidence references are attached to this finding." />
            </div>
          </Card>

          <Card icon="account_tree" title="Connected Entities">
            <div className="p-density-comfortable grid grid-cols-1 md:grid-cols-2 gap-density-comfortable">
              <RelatedItems title="People" items={actorItems} empty="No connected people found." />
              <RelatedItems title="Companies & organizations" items={companyItems} empty="No named company or organization found in evidence." />
              <RelatedItems title="Sectors" items={sectorItems} empty="No affected sectors found." />
              <RelatedItems title="Committees" items={committeeItems} empty="No connected committees found." />
              <RelatedItems title="Connected bills" items={billItems} empty="No bill records are attached to this finding." />
              <RelatedItems title="Lobbying, regulations & sources" items={fileItems} empty="No lobbying, regulatory, or source records are attached." />
            </div>
          </Card>
        </div>

        <aside className="lg:col-span-4 space-y-gutter">
          <Card icon="dashboard" title="Finding Profile">
            <dl className="p-density-comfortable grid grid-cols-2 gap-4">
              <Fact label="Type" value={finding.type.replace(/_/g, " ")} />
              <Fact label="Severity" value={finding.severity} />
              <Fact label="Confidence" value={finding.confidence} />
              <Fact label="Evidence" value={String(finding.references.length)} />
            </dl>
          </Card>
          <Card icon="travel_explore" title="Investigation Path">
            <div className="p-density-comfortable space-y-3 text-body-md text-on-surface-variant">
              {context.from !== "signals" ? <PathStep label="0" text={`Return path preserved from ${context.label.toLowerCase()}.`} /> : null}
              <PathStep label="1" text="Open the linked evidence record inside Nessus." />
              <PathStep label="2" text="Review connected people, entities, sectors, and timeline." />
              <PathStep label="3" text="Use the original source only after the internal evidence context is clear." />
            </div>
          </Card>
          <Card icon="description" title="Reports including this finding">
            <div className="p-density-comfortable">
              <RelatedItems items={reportItems} empty="No generated reports include this finding yet." />
            </div>
          </Card>
        </aside>
      </div>
    </div>
  );
}

function evidenceRelatedItems(finding: GraphFinding, findingSlug: string): RelatedItem[] {
  return dedupeRefs(finding.references).map((ref) => ({
    id: `${ref.table}-${ref.pk ?? ref.id}`,
    title: ref.title,
    type: typeLabel(ref.table),
    href: withFindingContext(evidenceHref(ref), findingSlug),
    description: ref.date ? `Dated ${ref.date}` : null,
    meta: ref.source,
    relationship: "finding supported by record",
    strength: "supported",
  }));
}

function companyRelatedItems(finding: GraphFinding, findingSlug: string): RelatedItem[] {
  const entities = new Map<string, EvidenceRef>();
  for (const ref of finding.references) {
    const entity = ref.entity?.trim();
    if (entity && !entities.has(entity.toLowerCase())) entities.set(entity.toLowerCase(), ref);
  }
  return Array.from(entities.values()).slice(0, 8).map((ref) => ({
    id: `entity-${ref.entity}`,
    title: ref.entity ?? "Named entity",
    type: "Company or organization",
    href: withFindingContext(entityHref(ref.entity), findingSlug),
    description: `Named on supporting ${typeLabel(ref.table).toLowerCase()} evidence.`,
    meta: ref.source,
    relationship: "finding affects company",
    strength: "supported",
    icon: <AvatarLogo name={ref.entity ?? "Entity"} type="company" />,
  }));
}

function recordRelatedItems(finding: GraphFinding, findingSlug: string, tables: string[]): RelatedItem[] {
  const allowed = new Set(tables);
  return dedupeRefs(finding.references)
    .filter((ref) => allowed.has(ref.table))
    .slice(0, 8)
    .map((ref) => ({
      id: `${ref.table}-${ref.pk ?? ref.id}`,
      title: ref.title,
      type: typeLabel(ref.table),
      href: withFindingContext(evidenceHref(ref), findingSlug),
      description: [ref.date, ref.entity].filter(Boolean).join(" - ") || null,
      meta: ref.source,
      relationship: sourceRelationship(ref.table),
      strength: "supported",
    }));
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

function sourceRelationship(table: string): string {
  if (table === "bills") return "bill affects sector";
  if (table === "lobbying" || table === "ocl_registrations") return "organization registered lobbying activity";
  if (table === "gazette" || table === "tribunal") return "regulator opened consultation";
  if (table === "source_records") return "finding supported by source";
  return "finding supported by record";
}

function findingContext(searchParams: ReturnType<typeof useSearchParams>): { from: string; label: string; href: string } {
  const from = searchParams.get("from");
  if (from === "dashboard") return { from, label: "Dashboard", href: "/dashboard" };
  if (from === "briefing") return { from, label: "Morning Brief", href: "/" };
  if (from === "watchlists") return { from, label: "Watchlists", href: "/watchlists" };
  if (from === "cross-sector") return { from, label: "Cross-Sector", href: "/cross-sector" };
  if (from === "sector") {
    const sector = searchParams.get("sector");
    return { from, label: "Sector", href: sector ? `/sectors/${encodeURIComponent(sector)}` : "/sectors" };
  }
  return { from: "signals", label: "Live Feed", href: "/signals" };
}

function withFindingContext(href: string | null, findingSlug: string): string | null {
  if (!href) return href;
  const glue = href.includes("?") ? "&" : "?";
  return `${href}${glue}from=finding&finding=${encodeURIComponent(findingSlug)}`;
}

function sectorRelatedItems(finding: GraphFinding, findingSlug: string): RelatedItem[] {
  const sectors = [finding.sector, ...finding.related_sectors].filter(Boolean) as { slug: string; name: string }[];
  const unique = new Map(sectors.map((s) => [s.slug, s]));
  return [...unique.values()].map((sector) => ({
    id: `sector-${sector.slug}`,
    title: sector.name,
    type: "Sector",
    href: withFindingContext(sectorHref(sector.slug), findingSlug),
    relationship: "affected by finding",
    strength: finding.sector?.slug === sector.slug ? "supported" : "inferred",
  }));
}

function actorRelatedItems(finding: GraphFinding, findingSlug: string): RelatedItem[] {
  return (finding.actors ?? []).map((actor, index) => {
    const name = String(actor.name ?? actor.label ?? "Political actor");
    const slug = typeof actor.slug === "string" ? actor.slug : null;
    return {
      id: `actor-${slug ?? index}`,
      title: name,
      type: "Political figure",
      href: withFindingContext(personHref(slug), findingSlug),
      description: [actor.role, actor.party].filter(Boolean).join(" - ") || null,
      relationship: "person connected to finding",
      strength: slug ? "supported" : "inferred",
      icon: <AvatarLogo name={name} imageUrl={typeof actor.photo_url === "string" ? actor.photo_url : null} type="person" />,
    };
  });
}

function committeeRelatedItems(finding: GraphFinding, findingSlug: string): RelatedItem[] {
  const text = `${finding.title} ${finding.summary} ${finding.references.map((r) => r.title).join(" ")}`.toLowerCase();
  const slug = text.includes("privacy") || text.includes("technology") || text.includes("industry") ? "indu" : null;
  const committees = slug ? [{ slug, name: "Standing Committee on Industry and Technology" }] : [];
  return committees.map((item, index) => committeeItem(item, index, findingSlug));
}

function committeeItem(item: { slug: string; name: string }, index: number, findingSlug: string): RelatedItem {
  return {
    id: `committee-${item.slug}-${index}`,
    title: item.name,
    type: "Committee",
    href: withFindingContext(committeeHref(item.slug), findingSlug),
    relationship: "committee connected to finding",
    strength: "inferred",
  };
}

function StatusChip({ level, children }: { level: string; children: React.ReactNode }) {
  const tone = level === "high" || level === "elevated" ? "status-chip-red" : level === "watch" ? "status-chip-amber" : "status-chip-green";
  return <span className={`font-label-caps text-label-caps ${tone} px-2 py-1 rounded-full uppercase`}>{children}</span>;
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="font-label-caps text-label-caps text-on-surface-variant uppercase mb-1">{label}</dt>
      <dd className="font-body-md text-body-md text-on-surface capitalize">{value}</dd>
    </div>
  );
}

function PathStep({ label, text }: { label: string; text: string }) {
  return (
    <div className="flex gap-3">
      <span className="w-6 h-6 rounded bg-primary text-on-primary text-data-tabular font-data-tabular flex items-center justify-center shrink-0">{label}</span>
      <span>{text}</span>
    </div>
  );
}

function SignalSkeleton() {
  return <div className="space-y-gutter">{[0, 1, 2].map((i) => <div key={i} className="skeleton h-32" />)}</div>;
}

function Message({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "neutral" | "error" }) {
  return (
    <div className={`rounded border px-4 py-3 ${tone === "error" ? "border-error/30 bg-error/10 text-error" : "border-outline-variant bg-surface-container-low text-on-surface-variant"}`}>
      {children}
    </div>
  );
}
