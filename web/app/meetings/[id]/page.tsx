"use client";

import Link from "next/link";
import { use } from "react";
import type { ReactNode } from "react";
import { useSearchParams } from "next/navigation";
import { AvatarLogo, RelatedItems, type RelatedItem } from "@/components/intelligence";
import { Crumb, Card, DetailHeader, Field } from "@/components/nessus";
import { EvidenceRows, OriginalSourceLink } from "@/components/ui";
import { useApi } from "@/lib/use-api";
import type { EvidenceGraphResponse, EvidenceRef, GraphFinding, RecordDetail, RecordRef } from "@/lib/api";
import { entityHref, findingHref, organizationHref, personHref, recordHref, sectorHref, sourceLabel, typeLabel } from "@/lib/navigation";

export default function MeetingDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const searchParams = useSearchParams();
  const context = meetingContext(searchParams);
  const { data, loading, error } = useApi<RecordDetail>(`/api/records/lobbying/${encodeURIComponent(id)}`);
  const { data: graph } = useApi<EvidenceGraphResponse>(`/api/graph/record/lobbying/${encodeURIComponent(id)}`);

  if (loading) return <MeetingSkeleton />;
  if (error) return <Message tone="error">{error}</Message>;
  if (!data) return <Message>Meeting record not found.</Message>;

  const record = data.record;
  const sourceHref = withContext(recordHref("lobbying", id), context);
  const title = record.title || "Registered lobbying communication";
  const subject = fieldValue(record.fields, "subject_matters") ?? fieldValue(record.fields, "subject") ?? "Subject matter is not normalized for this communication yet.";
  const relatedFindings = findingItems(graph?.findings ?? [], context);
  const participantItems = participantItemsFor(data, context);
  const sourceGroupItems = sourceGroupsFor(data, context);
  const sectorItems = sectorItemsFor(data, graph, context);
  const timeline = timelineRefs(data);

  return (
    <div className="animate-rise">
      <Crumb items={[context ? { label: context.label, href: context.href } : { label: "Records", href: "/records" }, { label: "Meetings" }, { label: `MTG-${id}` }]} />
      {context ? <InvestigationContext context={context} /> : null}
      <DetailHeader
        eyebrow={`Meeting/contact - ${record.source || sourceLabel("lobbying")}`}
        title={title}
        subtitle={data.impact?.meaning || "This meeting is an internal view over a lobbying communication record with connected findings, participants, and supporting evidence."}
        action={sourceHref ? <Link href={sourceHref} className="px-4 py-2 rounded bg-primary text-on-primary text-body-md font-medium hover:bg-primary-container transition-colors focus-ring">Open evidence record</Link> : null}
      />

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-gutter">
        <div className="lg:col-span-8 space-y-gutter">
          <Card icon="description" title="AI Interpretation">
            <div className="p-density-comfortable font-memo-body text-memo-body text-on-surface leading-relaxed">
              {subject}
              <div className="mt-4 text-body-md text-on-surface-variant">
                Treat this as a registered communication record. It supports an investigative path, but it does not prove policy influence or causation on its own.
              </div>
            </div>
          </Card>

          <Card icon="receipt_long" title="Important Normalized Data">
            <div className="p-density-comfortable grid grid-cols-1 sm:grid-cols-3 gap-4">
              <Field label="Type" value={typeLabel("meetings")} />
              <Field label="Date" value={record.date ?? "Date unavailable"} />
              <Field label="Client" value={record.entity ?? "Not provided"} />
              <Field label="Source" value={record.source || sourceLabel("lobbying")} />
              <Field label="Record type" value={record.record_type || "communication"} />
              <Field label="Evidence record" value={`lobbying / ${id}`} />
            </div>
          </Card>

          <Card icon="account_tree" title="Connected Intelligence">
            <div className="p-density-comfortable grid grid-cols-1 md:grid-cols-2 gap-density-comfortable">
              <RelatedItems title="Participants" items={participantItems} empty="No participants are resolved yet." />
              <RelatedItems title="Related findings" items={relatedFindings} empty="No graph findings are attached to this meeting yet." />
              <RelatedItems title="Affected sectors" items={sectorItems} empty="No sector has been inferred for this communication yet." />
              <RelatedItems title="Connected bills, lobbying, regulations & sources" items={sourceGroupItems} empty="No connected source groups found." />
            </div>
          </Card>

          <Card icon="history" title="Supporting Evidence Timeline">
            <div className="p-density-comfortable">
              <EvidenceRows refs={timeline} limit={10} hrefFor={(ref) => withContext(recordHref(ref.table, ref.pk ?? ref.id), context)} />
            </div>
          </Card>
        </div>

        <aside className="lg:col-span-4 space-y-gutter">
          <Card icon="groups" title="Participants">
            <div className="p-density-comfortable grid grid-cols-1 gap-4">
              <Field label="Client" value={record.entity ?? "Not provided"} />
              <Field label="Institution" value={fieldValue(record.fields, "institutions") ?? fieldValue(record.fields, "institution") ?? "Not provided"} />
              <Field label="Registrant" value={fieldValue(record.fields, "registrant") ?? "Not provided"} />
              <Field label="Communication date" value={record.date ?? "Not provided"} />
            </div>
          </Card>

          <Card icon="open_in_new" title="Original Source">
            <div className="p-density-comfortable space-y-3">
              <p className="text-body-md text-on-surface-variant">Original registry links are secondary. Review the internal evidence record first, then open the source filing if needed.</p>
              {record.url ? (
                <OriginalSourceLink href={record.url} />
              ) : (
                <Message>No original source URL is available for this meeting.</Message>
              )}
            </div>
          </Card>
        </aside>
      </div>
    </div>
  );
}

type MeetingContextValue =
  | { from: "search"; label: string; href: string }
  | { from: "sector"; label: string; href: string }
  | { from: "finding"; label: string; href: string }
  | null;

function meetingContext(searchParams: ReturnType<typeof useSearchParams>): MeetingContextValue {
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

function withContext(href: string | null, context: MeetingContextValue): string | null {
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

function InvestigationContext({ context }: { context: NonNullable<MeetingContextValue> }) {
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

function findingItems(findings: GraphFinding[], context: MeetingContextValue): RelatedItem[] {
  return findings.slice(0, 6).map((finding) => ({
    id: finding.title,
    title: finding.title,
    type: "Finding",
    href: withContext(findingHref(finding), context),
    description: finding.summary,
    meta: finding.confidence,
    relationship: "meeting supported by record",
    strength: finding.relationship_strength ?? "supported",
  }));
}

function participantItemsFor(detail: RecordDetail, context: MeetingContextValue): RelatedItem[] {
  const items: RelatedItem[] = [];
  const entityName = detail.entity.name ?? detail.record.entity;
  if (entityName) {
    items.push({
      id: `entity-${entityName}`,
      title: entityName,
      type: "Company or organization",
      href: withContext(entityHref(entityName), context),
      relationship: "organization registered lobbying activity",
      strength: "direct",
      icon: <AvatarLogo name={entityName} type="company" />,
    });
  }
  for (const player of detail.players) {
    const href = player.type === "politician" ? personHref(player.slug) : organizationHref("regulator", player.name);
    items.push({
      id: `${player.type}-${player.name}`,
      title: player.name,
      type: player.type === "politician" ? "Political figure" : "Regulator",
      href: withContext(href, context),
      description: [player.role, player.party].filter(Boolean).join(" - ") || player.why,
      relationship: "person connected to record",
      strength: "supported",
      icon: <AvatarLogo name={player.name} imageUrl={player.photo_url} imageAttribution={player.photo_attribution} imageSource={player.photo_source} type={player.type === "politician" ? "person" : "regulator"} />,
    });
  }
  return items;
}

function sourceGroupsFor(detail: RecordDetail, context: MeetingContextValue): RelatedItem[] {
  return (detail.relations.by_source ?? []).slice(0, 8).map((group) => {
    const first = group.records[0];
    return {
      id: `${group.table}-${group.source}`,
      title: group.label,
      type: typeLabel(group.table, true),
      href: first ? withContext(recordHref(first.table, first.pk), context) : null,
      description: `${group.count.toLocaleString()} connected record${group.count === 1 ? "" : "s"}`,
      meta: group.partial ? "Partial sample" : "Complete sample",
      relationship: sourceRelationship(group.table),
      strength: "supported" as const,
    };
  });
}

function sectorItemsFor(detail: RecordDetail, graph?: EvidenceGraphResponse | null, context: MeetingContextValue = null): RelatedItem[] {
  const sectors = new Map<string, { slug: string; name: string; description?: string | null; strength: "supported" | "inferred" }>();
  if (detail.industry) {
    sectors.set(detail.industry.slug, { slug: detail.industry.slug, name: detail.industry.name, description: detail.industry.blurb, strength: detail.industry.matched_by === "entity roster" ? "supported" : "inferred" });
  }
  if (graph?.industry?.slug && graph.industry.name) {
    sectors.set(graph.industry.slug, { slug: graph.industry.slug, name: graph.industry.name, description: graph.industry.blurb ?? null, strength: graph.industry.matched_by === "entity roster" ? "supported" : "inferred" });
  }
  for (const finding of graph?.findings ?? []) {
    for (const sector of [finding.sector, ...finding.related_sectors].filter(Boolean) as { slug: string; name: string }[]) {
      if (!sectors.has(sector.slug)) sectors.set(sector.slug, { ...sector, strength: "inferred" });
    }
  }
  return [...sectors.values()].map((sector) => ({
    id: `sector-${sector.slug}`,
    title: sector.name,
    type: "Sector",
    href: withContext(sectorHref(sector.slug), context),
    description: sector.description ?? null,
    relationship: "record affects sector",
    strength: sector.strength,
  }));
}

function timelineRefs(detail: RecordDetail): EvidenceRef[] {
  const refs = (detail.relations.timeline?.length ? detail.relations.timeline : [currentRecordRef(detail)]);
  return refs.map(recordRefToEvidenceRef);
}

function currentRecordRef(detail: RecordDetail): RecordRef {
  return {
    table: detail.table,
    pk: detail.pk,
    source: detail.record.source,
    record_type: detail.record.record_type,
    title: detail.record.title,
    date: detail.record.date,
    amount: detail.record.amount,
    entity: detail.record.entity,
    current: true,
  };
}

function recordRefToEvidenceRef(ref: RecordRef): EvidenceRef {
  return {
    table: ref.table,
    pk: ref.pk,
    id: ref.pk,
    source: ref.source,
    title: ref.title,
    date: ref.date,
    entity: ref.entity,
    record_type: ref.record_type,
  } as EvidenceRef;
}

function sourceRelationship(table: string): string {
  if (table === "bills") return "bill affects sector";
  if (table === "lobbying" || table === "ocl_registrations") return "organization registered lobbying activity";
  if (table === "gazette" || table === "tribunal") return "regulator opened consultation";
  if (table === "source_records") return "finding supported by source";
  return "shared entity evidence";
}

function fieldValue(fields: RecordDetail["record"]["fields"], key: string): string | null {
  return fields.find((field) => field.key === key)?.value ?? null;
}

function MeetingSkeleton() {
  return <div className="space-y-gutter">{[0, 1, 2, 3].map((i) => <div key={i} className="skeleton h-32" />)}</div>;
}

function Message({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "error" }) {
  return (
    <div className={`rounded border px-4 py-3 font-body-md text-body-md ${tone === "error" ? "border-error/30 bg-error/10 text-error" : "border-outline-variant bg-surface-container-low text-on-surface-variant"}`}>
      {children}
    </div>
  );
}
