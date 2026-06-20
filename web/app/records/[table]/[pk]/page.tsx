"use client";

import Link from "next/link";
import { use } from "react";
import { useSearchParams } from "next/navigation";
import { Card, Crumb, DetailHeader, Field } from "@/components/nessus";
import { AvatarLogo, DocumentThumbnail, RelatedItems, type RelatedItem } from "@/components/intelligence";
import { OriginalSourceLink } from "@/components/ui";
import { useApi } from "@/lib/use-api";
import type { EvidenceGraphResponse, GraphFinding, RecordDetail, RecordRef } from "@/lib/api";
import { moneyFull } from "@/lib/api";
import { entityHref, findingHref, organizationHref, personHref, recordHref, sectorHref, sourceLabel, typeLabel } from "@/lib/navigation";

export default function RecordDetailPage({ params }: { params: Promise<{ table: string; pk: string }> }) {
  const { table, pk } = use(params);
  const searchParams = useSearchParams();
  const context = investigationContext(searchParams);
  const detailPath = `/api/records/${encodeURIComponent(table)}/${encodeURIComponent(pk)}`;
  const graphPath = `/api/graph/record/${encodeURIComponent(table)}/${encodeURIComponent(pk)}`;
  const { data: detail, loading, error } = useApi<RecordDetail>(detailPath);
  const { data: graph } = useApi<EvidenceGraphResponse>(graphPath);

  if (loading) return <RecordSkeleton />;
  if (error) return <Message tone="error">{error}</Message>;
  if (!detail) return <Message>Record not found.</Message>;

  const record = detail.record;
  const type = detail.record.type_label || recordTypeLabel(detail.record.record_type, detail.record.source, detail.table);
  const title = record.title || `${type} #${detail.pk}`;
  const connectedItems = buildConnectedItems(detail, graph, context);
  const evidenceItems = buildEvidenceItems(detail, context);
  const findingItems = buildFindingItems(graph?.findings ?? [], context);
  const sourceGroupItems = buildSourceGroupItems(detail, context);
  const entityUrl = record.entity ? entityHref(record.entity) : null;

  return (
    <div className="animate-rise">
      <Crumb items={[{ label: "Records", href: "/records" }, { label: type }]} />
      {context ? <InvestigationContext context={context} /> : null}
      <DetailHeader
        eyebrow={`${type} - ${record.source || sourceLabel(detail.table)}`}
        title={title}
        subtitle={detail.impact?.meaning || "This record is available inside Nessus with connected entities, source context, and related evidence."}
        action={record.url ? (
          <OriginalSourceLink href={record.url} className="px-4 py-2 bg-surface border border-outline-variant font-body-md text-body-md hover:bg-surface-container-low transition-colors no-underline" />
        ) : null}
      />

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-gutter">
        <div className="lg:col-span-8 space-y-gutter">
          <Card icon="fact_check" title="Normalized Data">
            <div className="p-density-comfortable">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-density-comfortable">
                <Field label="Type" value={type} />
                <Field label="Date" value={record.date ?? "Not provided"} />
                <Field label="Entity" value={record.entity ? (entityUrl ? <Link href={withContext(entityUrl, context) ?? entityUrl} className="text-primary hover:underline focus-ring rounded">{record.entity}</Link> : record.entity) : "Not provided"} />
                <Field label="Amount" value={record.amount ? moneyFull(record.amount) : "Not applicable"} />
                <Field label="Source" value={record.source || sourceLabel(detail.table)} />
                <Field label="Record ID" value={`${detail.table} / ${detail.pk}`} />
              </div>
              <div className="mt-6 grid grid-cols-1 md:grid-cols-2 gap-3">
                {record.fields.slice(0, 10).map((field) => (
                  <div key={field.key} className="rounded border border-outline-variant bg-surface-container-low px-3 py-2">
                    <div className="font-label-caps text-label-caps text-on-surface-variant uppercase mb-1">{field.label}</div>
                    <div className="font-body-md text-body-md text-on-surface break-words">{field.value}</div>
                  </div>
                ))}
              </div>
            </div>
          </Card>

          <Card icon="psychology" title="Why It Matters">
            <div className="p-density-comfortable font-memo-body text-memo-body text-on-surface leading-relaxed">
              {detail.impact?.meaning || "Nessus has not yet inferred a material interpretation for this record. Use the connected evidence below to continue the investigation."}
              <div className="mt-5 flex flex-wrap gap-2">
                {detail.impact?.severity && <StatusChip level={detail.impact.severity}>{detail.impact.severity}</StatusChip>}
                {detail.industry && <Link href={withContext(sectorHref(detail.industry.slug), context) ?? "/sectors"} className="font-label-caps text-label-caps bg-primary/10 text-primary px-2 py-1 rounded-full uppercase hover:underline focus-ring">{detail.industry.name}</Link>}
                {detail.industry?.matched_by && <span className="font-label-caps text-label-caps bg-surface-container-highest text-on-surface-variant px-2 py-1 rounded-full uppercase">matched by {detail.industry.matched_by}</span>}
              </div>
            </div>
          </Card>

          <Card icon="account_tree" title="Connected Intelligence">
            <div className="p-density-comfortable grid grid-cols-1 md:grid-cols-2 gap-density-comfortable">
              <RelatedItems title="Related Findings" items={findingItems} empty="No related findings found." />
              <RelatedItems title="Connected Entities" items={connectedItems} empty="No connected entities found." />
              <RelatedItems title="Connected Bills, Lobbying, Regulations & Sources" items={sourceGroupItems} empty="No connected source groups found." />
            </div>
          </Card>

          <Card icon="history" title="Evidence Timeline">
            <div className="p-density-comfortable">
              <RelatedItems items={evidenceItems} empty="No timeline evidence is available for this record." />
            </div>
          </Card>
        </div>

        <aside className="lg:col-span-4 space-y-gutter">
          <Card icon="description" title="Source Document">
            <div className="p-density-comfortable">
              <DocumentThumbnail
                title={title}
                type={type}
                source={record.source || sourceLabel(detail.table)}
                date={record.date}
                url={record.url}
              />
            </div>
          </Card>

          <Card icon="groups" title="Political Players">
            <div className="p-density-comfortable space-y-3">
              {detail.players.length ? detail.players.map((player) => (
                <Link key={`${player.type}-${player.name}`} href={withContext(player.type === "politician" ? personHref(player.slug) ?? "/politicians" : organizationHref("regulator", player.name) ?? "/organizations/regulator", context) ?? "/politicians"} className="flex items-start gap-3 rounded border border-outline-variant bg-surface-container-lowest p-3 hover:border-primary transition-colors focus-ring">
                  <AvatarLogo name={player.name} imageUrl={player.photo_url} imageAttribution={player.photo_attribution} imageSource={player.photo_source} type={player.type === "politician" ? "person" : "regulator"} />
                  <div className="min-w-0">
                    <div className="font-body-md text-body-md font-bold text-primary">{player.name}</div>
                    <div className="font-data-tabular text-data-tabular text-on-surface-variant">{[player.role, player.party].filter(Boolean).join(" - ") || player.type}</div>
                    <p className="font-body-md text-body-md text-on-surface-variant mt-1 line-clamp-2">{player.why}</p>
                  </div>
                </Link>
              )) : <Message>No political players are connected yet.</Message>}
            </div>
          </Card>

          <Card icon="dataset_linked" title="Supporting Evidence">
            <div className="p-density-comfortable space-y-4">
              {(detail.relations.by_source ?? []).slice(0, 6).map((group) => (
                <div key={`${group.table}-${group.source}`} className="rounded border border-outline-variant bg-surface-container-lowest p-3">
                  <div className="flex items-center justify-between gap-2 mb-2">
                    <div className="font-label-caps text-label-caps text-on-surface-variant uppercase">{group.label}</div>
                    <span className="font-data-tabular text-data-tabular text-primary">{group.count}</span>
                  </div>
                  <div className="space-y-2">
                    {group.records.slice(0, 3).map((ref) => {
                      const href = withContext(recordHref(ref.table, ref.pk), context);
                      return href ? (
                        <Link key={`${ref.table}-${ref.pk}`} href={href} className="block text-body-md font-body-md text-on-surface hover:text-primary focus-ring rounded">
                          {ref.title}
                        </Link>
                      ) : (
                        <span key={`${ref.table}-${ref.pk}`} className="block text-body-md font-body-md text-on-surface">{ref.title}</span>
                      );
                    })}
                  </div>
                </div>
              ))}
              {!detail.relations.by_source?.length && <Message>No source groups available.</Message>}
            </div>
          </Card>
        </aside>
      </div>
    </div>
  );
}

type InvestigationContextValue =
  | { from: "search"; label: string; href: string }
  | { from: "sector"; label: string; href: string }
  | { from: "finding"; label: string; href: string };

function investigationContext(searchParams: ReturnType<typeof useSearchParams>): InvestigationContextValue | null {
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
    return { from, label: finding ? "Back to finding" : "Back to finding", href: finding ? `/signals/${encodeURIComponent(finding)}` : "/signals" };
  }
  return null;
}

function withContext(href: string | null, context: InvestigationContextValue | null): string | null {
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

function InvestigationContext({ context }: { context: InvestigationContextValue }) {
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

function buildConnectedItems(detail: RecordDetail, graph?: EvidenceGraphResponse | null, context: InvestigationContextValue | null = null): RelatedItem[] {
  const items: RelatedItem[] = [];
  if (detail.entity?.name || detail.entity?.canonical) {
    const name = detail.entity.name ?? detail.entity.canonical ?? "Entity";
    items.push({
      id: "entity",
      title: name,
      type: "Company or entity",
      href: withContext(entityHref(name), context),
      relationship: "named on record",
      strength: "direct",
      icon: <AvatarLogo name={name} type="company" />,
    });
  }
  if (detail.industry) {
    items.push({
      id: `sector-${detail.industry.slug}`,
      title: detail.industry.name,
      type: "Sector",
      href: withContext(sectorHref(detail.industry.slug), context),
      description: detail.industry.blurb,
      relationship: "sector match",
      strength: detail.industry.matched_by === "entity roster" ? "direct" : "inferred",
    });
  }
  for (const node of graph?.nodes ?? []) {
    if (node.type !== "sector" && node.type !== "entity") continue;
    const meta = (node.meta ?? {}) as Record<string, unknown>;
    const title = String(node.label ?? meta.name ?? node.id);
    const href = node.type === "sector" ? sectorHref(String(meta.slug ?? "")) : entityHref(title);
    if (items.some((item) => item.href === href || item.title === title)) continue;
    items.push({ id: node.id, title, type: node.type, href: withContext(href, context), relationship: "graph connection", strength: "supported" });
  }
  return items;
}

function buildEvidenceItems(detail: RecordDetail, context: InvestigationContextValue | null = null): RelatedItem[] {
  const current: RecordRef = {
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
  const rows = detail.relations.timeline?.length ? detail.relations.timeline : [current];
  return rows.slice(0, 12).map((ref) => ({
    id: `${ref.table}-${ref.pk}`,
    title: ref.title,
    type: typeLabel(ref.table),
    href: withContext(recordHref(ref.table, ref.pk), context),
    description: [ref.date, ref.entity].filter(Boolean).join(" - ") || null,
    meta: ref.current ? "Current record" : ref.source,
    relationship: ref.current ? "current evidence" : "shared entity timeline",
    strength: ref.current ? "direct" : "supported",
  }));
}

function buildSourceGroupItems(detail: RecordDetail, context: InvestigationContextValue | null = null): RelatedItem[] {
  return (detail.relations.by_source ?? []).slice(0, 8).map((group) => {
    const first = group.records[0];
    return {
      id: `${group.table}-${group.source}`,
      title: group.label,
      type: typeLabel(group.table, true),
      href: first ? withContext(recordHref(first.table, first.pk), context) : null,
      description: `${group.count.toLocaleString()} related ${group.label.toLowerCase()} record${group.count === 1 ? "" : "s"}`,
      meta: group.partial ? "Partial sample" : "Complete sample",
      relationship: sourceGroupRelationship(group.table),
      strength: "supported" as const,
    };
  });
}

function sourceGroupRelationship(table: string): string {
  if (table === "bills") return "bill affects sector";
  if (table === "lobbying" || table === "ocl_registrations") return "organization registered lobbying activity";
  if (table === "gazette" || table === "tribunal") return "regulator opened consultation";
  if (table === "source_records") return "finding supported by source";
  return "shared entity evidence";
}

function recordTypeLabel(recordType?: string | null, source?: string | null, table?: string | null): string {
  if (source === "social_statements" || source === "public_statements" || recordType === "public_statement" || recordType === "social_post") {
    return "Public statement";
  }
  return typeLabel(table);
}

function buildFindingItems(findings: GraphFinding[], context: InvestigationContextValue | null = null): RelatedItem[] {
  return findings.map((finding) => ({
    id: finding.title,
    title: finding.title,
    type: "Finding",
    href: withContext(findingHref(finding.title), context),
    description: finding.summary,
    meta: finding.confidence,
    relationship: "record supports finding",
    strength: (finding as GraphFinding & { relationship_strength?: "direct" | "supported" | "inferred" }).relationship_strength ?? "inferred",
  }));
}

function StatusChip({ level, children }: { level: string; children: React.ReactNode }) {
  const tone = level === "high" || level === "elevated" ? "status-chip-red" : level === "watch" ? "status-chip-amber" : "status-chip-green";
  return <span className={`font-label-caps text-label-caps ${tone} px-2 py-1 rounded-full uppercase`}>{children}</span>;
}

function RecordSkeleton() {
  return <div className="space-y-gutter">{[0, 1, 2, 3].map((i) => <div key={i} className="skeleton h-32" />)}</div>;
}

function Message({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "neutral" | "error" }) {
  return (
    <div className={`rounded border px-4 py-3 font-body-md text-body-md ${tone === "error" ? "border-error/30 bg-error/10 text-error" : "border-outline-variant bg-surface-container-low text-on-surface-variant"}`}>
      {children}
    </div>
  );
}
