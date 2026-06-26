"use client";

import Link from "next/link";
import { use } from "react";
import type { ReactNode } from "react";
import { useSearchParams } from "next/navigation";
import { Crumb, Card, DetailHeader, Field, PrimaryButton } from "@/components/nessus";
import { AvatarLogo, RelatedItems, type RelatedItem } from "@/components/intelligence";
import { EvidenceRows } from "@/components/ui";
import { num, type CommitteeProfile, type EvidenceRef, type GraphFinding } from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { evidenceHref, findingHref, findingSlug, personHref, sectorHref, typeLabel } from "@/lib/navigation";

export default function CommitteeDetail({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  const searchParams = useSearchParams();
  const context = committeeContext(searchParams);
  const decoded = decodeURIComponent(slug);
  const { data: committee, loading, error } = useApi<CommitteeProfile>(`/api/parliament/committee/${encodeURIComponent(decoded)}`);

  if (loading) return <CommitteeSkeleton />;
  if (error) return <Message tone="error">{error}</Message>;
  if (!committee) return <Message>Committee profile not found.</Message>;

  const peopleItems = peopleRelatedItems(committee.connected_people, context);
  const sectorItems = committee.affected_sectors.map((sector): RelatedItem => ({
    id: `sector-${sector.slug}`,
    title: sector.name,
    type: "Sector",
    href: withContext(sectorHref(sector.slug), context),
    relationship: "committee affects sector",
    strength: "inferred",
  }));
  const findingItems = findingRelatedItems(committee.related_findings, context);
  const groupItems = sourceGroupItems(committee.groups, context);
  const recordItems = recordsRelatedItems(committee.connected_records, context);

  return (
    <div className="animate-rise">
      <Crumb items={[context ? { label: context.label, href: context.href } : { label: "Parliament" }, { label: "Committees" }, { label: committee.slug.toUpperCase() }]} />
      {context ? <InvestigationContext context={context} /> : null}
      <DetailHeader
        eyebrow={`${committee.chamber} committee`}
        title={
          <span className="inline-flex items-center gap-4">
            <AvatarLogo name={committee.name} type="organization" className="w-16 h-16 rounded-lg" />
            <span>{committee.name}</span>
          </span>
        }
        subtitle={committee.summary}
        action={<PrimaryButton icon="download">Export PDF</PrimaryButton>}
      />

      <div className="mb-gutter rounded border border-outline-variant bg-surface-container-lowest px-4 py-3 text-body-md text-on-surface-variant">
        Official committee mark not stored yet. Nessus is using the shared organization fallback until source metadata is available.
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-gutter">
        <div className="lg:col-span-8 space-y-gutter">
          <Card icon="insights" title="Committee Interpretation">
            <div className="p-density-comfortable font-memo-body text-memo-body text-on-surface-variant leading-relaxed">
              {committee.why_it_matters}
            </div>
          </Card>

          <Card icon="receipt_long" title="Important Normalized Data">
            <div className="p-density-comfortable grid grid-cols-1 sm:grid-cols-3 gap-4">
              <Field label="Chamber" value={committee.chamber} />
              <Field label="Evidence records" value={num(committee.connected_records.length)} />
              <Field label="Source groups" value={num(committee.groups.length)} />
              <Field label="Related findings" value={num(committee.related_findings.length)} />
              <Field label="Connected people" value={num(committee.connected_people.length)} />
              <Field label="Timeline entries" value={num(committee.timeline.length)} />
            </div>
          </Card>

          <Card icon="account_tree" title="Related Intelligence">
            <div className="p-density-comfortable grid grid-cols-1 md:grid-cols-2 gap-density-comfortable">
              <RelatedItems title="People" items={peopleItems} empty="No connected people resolved yet." />
              <RelatedItems title="Affected sectors" items={sectorItems} empty="No affected sectors inferred yet." />
              <RelatedItems title="Related findings" items={findingItems} empty="No graph findings match this committee yet." />
              <RelatedItems title="Connected source groups" items={groupItems} empty="No connected source groups found." />
              <RelatedItems title="Connected records" items={recordItems} empty="No connected records found." />
            </div>
          </Card>

          <Card icon="history" title="Supporting Evidence Timeline">
            <div className="p-density-comfortable">
              <EvidenceRows refs={committee.timeline} limit={12} hrefFor={(ref) => withContext(evidenceHref(ref), context)} />
            </div>
          </Card>
        </div>

        <aside className="lg:col-span-4 space-y-gutter">
          <Card icon="dataset_linked" title="Source Groups">
            <div className="p-density-comfortable space-y-3">
              {committee.groups.map((group) => (
                <div key={group.table} className="rounded border border-outline-variant bg-surface-container-lowest p-3">
                  <div className="flex items-center justify-between gap-2 mb-2">
                    <div className="font-label-caps text-label-caps text-on-surface-variant uppercase">{group.label}</div>
                    <span className="font-data-tabular text-data-tabular text-primary">{group.count}</span>
                  </div>
                  <EvidenceRows refs={group.records} limit={3} hrefFor={(ref) => withContext(evidenceHref(ref), context)} />
                </div>
              ))}
              {!committee.groups.length ? <Message>No source groups available.</Message> : null}
            </div>
          </Card>
        </aside>
      </div>
    </div>
  );
}

type CommitteeContextValue =
  | { from: "search"; label: string; href: string }
  | { from: "sector"; label: string; href: string }
  | { from: "finding"; label: string; href: string }
  | null;

function committeeContext(searchParams: ReturnType<typeof useSearchParams>): CommitteeContextValue {
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

function withContext(href: string | null, context: CommitteeContextValue): string | null {
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

function InvestigationContext({ context }: { context: NonNullable<CommitteeContextValue> }) {
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

function peopleRelatedItems(people: Record<string, unknown>[], context: CommitteeContextValue): RelatedItem[] {
  return people.slice(0, 8).map((person, index) => {
    const name = String(person.name ?? person.label ?? "Political figure");
    const slug = typeof person.slug === "string" ? person.slug : null;
    return {
      id: `person-${slug ?? index}`,
      title: name,
      type: "Political figure",
      href: withContext(personHref(slug), context),
      description: [person.role, person.party].filter(Boolean).join(" - ") || null,
      relationship: "person mentioned committee",
      strength: person.strength === "inferred" ? "inferred" : "supported",
      icon: <AvatarLogo name={name} imageUrl={typeof person.photo_url === "string" ? person.photo_url : null} type="person" />,
    };
  });
}

function findingRelatedItems(findings: GraphFinding[], context: CommitteeContextValue): RelatedItem[] {
  return findings.slice(0, 6).map((finding, index) => ({
    id: findingSlug(finding) ?? `${finding.title}-${index}`,
    title: finding.title,
    type: "Finding",
    href: withContext(findingHref(finding), context),
    description: finding.summary,
    meta: finding.confidence,
    relationship: "committee connected to finding",
    strength: finding.relationship_strength ?? "supported",
  }));
}

function sourceGroupItems(groups: CommitteeProfile["groups"], context: CommitteeContextValue): RelatedItem[] {
  return groups.slice(0, 8).map((group) => {
    const first = group.records[0];
    return {
      id: group.table,
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

function recordsRelatedItems(records: EvidenceRef[], context: CommitteeContextValue): RelatedItem[] {
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
  if (table === "bills") return "committee studied bill";
  if (table === "hansard_mentions" || table === "hansard_speeches") return "committee evidence record";
  if (table === "lobbying") return "organization registered lobbying activity";
  if (table === "source_records") return "finding supported by source";
  return "committee evidence record";
}

function CommitteeSkeleton() {
  return <div className="space-y-gutter">{[0, 1, 2, 3].map((i) => <div key={i} className="skeleton h-32" />)}</div>;
}

function Message({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "error" }) {
  return (
    <div className={`rounded border px-4 py-3 font-body-md text-body-md ${tone === "error" ? "border-error/30 bg-error/10 text-error" : "border-outline-variant bg-surface-container-low text-on-surface-variant"}`}>
      {children}
    </div>
  );
}
