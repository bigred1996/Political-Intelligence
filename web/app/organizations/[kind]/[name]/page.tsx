"use client";

import Link from "next/link";
import { use } from "react";
import type { ReactNode } from "react";
import { useSearchParams } from "next/navigation";
import { Crumb, Card, DetailHeader, Field, PrimaryButton } from "@/components/nessus";
import { AvatarLogo, RelatedItems, type RelatedItem } from "@/components/intelligence";
import { EvidenceRows } from "@/components/ui";
import { num, type EvidenceRef, type GraphFinding, type OrganizationProfile } from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { evidenceHref, findingHref, findingSlug, sectorHref, typeLabel } from "@/lib/navigation";

export default function OrganizationProfilePage({ params }: { params: Promise<{ kind: string; name: string }> }) {
  const { kind, name } = use(params);
  const searchParams = useSearchParams();
  const context = organizationContext(searchParams);
  const path = `/api/organizations/${encodeURIComponent(kind)}/${encodeURIComponent(name)}`;
  const { data: org, loading, error } = useApi<OrganizationProfile>(path);

  if (loading) return <OrganizationSkeleton />;
  if (error) return <Message tone="error">{error}</Message>;
  if (!org) return <Message>Organization profile not found.</Message>;

  const type = org.kind === "department" ? "department" : org.kind === "regulator" ? "regulator" : "organization";
  const groupItems = sourceGroupItems(org.groups, context);
  const findingItems = findingRelatedItems(org.related_findings, context);
  const sectorItems = org.affected_sectors.map((sector): RelatedItem => ({
    id: `sector-${sector.slug}`,
    title: sector.name,
    type: "Sector",
    href: withContext(sectorHref(sector.slug), context),
    relationship: "organization affects sector",
    strength: "inferred",
  }));

  return (
    <div className="animate-rise">
      <Crumb items={[context ? { label: context.label, href: context.href } : { label: "Organizations" }, { label: org.kind }, { label: org.name }]} />
      {context ? <InvestigationContext context={context} /> : null}
      <DetailHeader
        eyebrow={`${org.kind} - Government of Canada`}
        title={
          <span className="inline-flex items-center gap-4">
            <AvatarLogo name={org.name} type={type} className="w-16 h-16 rounded-lg" />
            <span>{org.name}</span>
          </span>
        }
        subtitle={org.summary}
        action={<PrimaryButton icon="bookmark_add">Watchlist</PrimaryButton>}
      />

      <div className="mb-gutter rounded border border-outline-variant bg-surface-container-lowest px-4 py-3 text-body-md text-on-surface-variant">
        Official mark not stored yet. Nessus is using the shared organization fallback until source metadata is available.
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-gutter">
        <div className="lg:col-span-8 space-y-gutter">
          <Card icon="insights" title="Role & Mandate">
            <div className="p-density-comfortable font-memo-body text-memo-body text-on-surface-variant leading-relaxed">
              {org.why_it_matters}
            </div>
          </Card>

          <Card icon="receipt_long" title="Important Normalized Data">
            <div className="p-density-comfortable grid grid-cols-1 sm:grid-cols-3 gap-4">
              {org.metrics.map((metric) => <Field key={metric.label} label={metric.label} value={String(metric.value)} />)}
              <Field label="Type" value={org.kind} />
              <Field label="Evidence groups" value={num(org.groups.length)} />
              <Field label="Timeline records" value={num(org.timeline.length)} />
            </div>
          </Card>

          <Card icon="account_tree" title="Related Intelligence">
            <div className="p-density-comfortable grid grid-cols-1 md:grid-cols-2 gap-density-comfortable">
              <RelatedItems title="Affected sectors" items={sectorItems} empty="No sector matches inferred yet." />
              <RelatedItems title="Related findings" items={findingItems} empty="No graph findings name this organization yet." />
              <RelatedItems title="Connected source groups" items={groupItems} empty="No connected source groups found." />
              <RelatedItems title="Connected records" items={recordItems(org.connected_records, context)} empty="No connected records found." />
            </div>
          </Card>

          <Card icon="history" title="Supporting Evidence">
            <div className="p-density-comfortable">
              <EvidenceRows refs={org.timeline} limit={12} hrefFor={(ref) => withContext(evidenceHref(ref), context)} />
            </div>
          </Card>
        </div>

        <aside className="lg:col-span-4 space-y-gutter">
          <Card icon="dataset_linked" title="Source Groups">
            <div className="p-density-comfortable space-y-3">
              {org.groups.map((group) => (
                <div key={`${group.table}-${group.source}`} className="rounded border border-outline-variant bg-surface-container-lowest p-3">
                  <div className="flex items-center justify-between gap-2 mb-2">
                    <div className="font-label-caps text-label-caps text-on-surface-variant uppercase">{group.label}</div>
                    <span className="font-data-tabular text-data-tabular text-primary">{group.count}</span>
                  </div>
                  <EvidenceRows refs={group.records} limit={3} hrefFor={(ref) => withContext(evidenceHref(ref), context)} />
                </div>
              ))}
            </div>
          </Card>
        </aside>
      </div>
    </div>
  );
}

type OrganizationContextValue =
  | { from: "search"; label: string; href: string }
  | { from: "sector"; label: string; href: string }
  | { from: "finding"; label: string; href: string }
  | null;

function organizationContext(searchParams: ReturnType<typeof useSearchParams>): OrganizationContextValue {
  const from = searchParams.get("from");
  if (from === "search") {
    const q = searchParams.get("q") ?? "";
    return { from, label: q ? `Back to search: ${q}` : "Back to search", href: `/search${q ? `?q=${encodeURIComponent(q)}` : ""}` };
  }
  if (from === "sector") {
    const sector = searchParams.get("sector") ?? "";
    return { from, label: sector ? `Back to sector: ${sector}` : "Back to sector", href: sector ? `/sectors/${encodeURIComponent(sector)}` : "/sectors" };
  }
  if (from === "finding") {
    const finding = searchParams.get("finding") ?? "";
    return { from, label: "Back to finding", href: finding ? `/signals/${encodeURIComponent(finding)}` : "/signals" };
  }
  return null;
}

function withContext(href: string | null, context: OrganizationContextValue): string | null {
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

function InvestigationContext({ context }: { context: NonNullable<OrganizationContextValue> }) {
  return (
    <div className="mb-gutter rounded border border-outline-variant bg-surface-container-lowest px-4 py-3 flex flex-wrap items-center justify-between gap-3">
      <div>
        <div className="font-label-caps text-label-caps text-on-surface-variant uppercase">Investigation context</div>
        <div className="font-body-md text-body-md text-on-surface">{context.label}</div>
      </div>
      <Link href={context.href} className="inline-flex items-center gap-2 px-3 py-1.5 rounded border border-outline-variant text-primary hover:bg-surface-container-low transition-colors focus-ring">
        <span className="material-symbols-outlined text-[18px]">arrow_back</span>
        Return
      </Link>
    </div>
  );
}

function findingRelatedItems(findings: GraphFinding[], context: OrganizationContextValue): RelatedItem[] {
  return findings.slice(0, 6).map((finding, index) => ({
    id: findingSlug(finding) ?? `${finding.title}-${index}`,
    title: finding.title,
    type: "Finding",
    href: withContext(findingHref(finding), context),
    description: finding.summary,
    meta: finding.confidence,
    relationship: "organization connected to finding",
    strength: finding.relationship_strength ?? "supported",
  }));
}

function sourceGroupItems(groups: OrganizationProfile["groups"], context: OrganizationContextValue): RelatedItem[] {
  return groups.slice(0, 8).map((group) => {
    const first = group.records[0];
    return {
      id: `${group.table}-${group.source}`,
      title: group.label,
      type: typeLabel(group.table, true),
      href: first ? withContext(evidenceHref(first), context) : null,
      description: `${num(group.count)} record${group.count === 1 ? "" : "s"}`,
      meta: group.partial ? "Partial sample" : "Complete sample",
      relationship: sourceRelationship(group.table),
      strength: "supported" as const,
    };
  });
}

function recordItems(records: EvidenceRef[], context: OrganizationContextValue): RelatedItem[] {
  return records.slice(0, 8).map((ref) => ({
    id: `${ref.table}-${ref.pk ?? ref.id}`,
    title: ref.title,
    type: typeLabel(ref.table),
    href: withContext(evidenceHref(ref), context),
    description: ref.date ?? null,
    meta: ref.source,
    relationship: sourceRelationship(ref.table),
    strength: "supported",
  }));
}

function sourceRelationship(table: string): string {
  if (table === "contracts" || table === "grants") return "department administers program";
  if (table === "lobbying" || table === "ocl_registrations") return "organization registered lobbying activity";
  if (table === "gazette" || table === "tribunal") return "regulator opened consultation";
  if (table === "appointments") return "organization named on appointment";
  return "shared entity evidence";
}

function OrganizationSkeleton() {
  return <div className="space-y-gutter">{[0, 1, 2, 3].map((i) => <div key={i} className="skeleton h-32" />)}</div>;
}

function Message({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "error" }) {
  return (
    <div className={`rounded border px-4 py-3 font-body-md text-body-md ${tone === "error" ? "border-error/30 bg-error/10 text-error" : "border-outline-variant bg-surface-container-low text-on-surface-variant"}`}>
      {children}
    </div>
  );
}
