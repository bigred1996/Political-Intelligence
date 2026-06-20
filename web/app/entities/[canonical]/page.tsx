"use client";

import Link from "next/link";
import { use } from "react";
import type { ReactNode } from "react";
import { useSearchParams } from "next/navigation";
import { Crumb, Card, DetailHeader, Field, StatGrid, PrimaryButton } from "@/components/nessus";
import { AvatarLogo, RelatedItems, type RelatedItem } from "@/components/intelligence";
import { EvidenceRows, SourceCoverageList } from "@/components/ui";
import { money, num, type EntityProfile, type EvidenceRef } from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { evidenceHref, reportHref, sectorHref, typeLabel } from "@/lib/navigation";

export default function EntityProfilePage({ params }: { params: Promise<{ canonical: string }> }) {
  const { canonical } = use(params);
  const searchParams = useSearchParams();
  const context = entityContext(searchParams);
  const decoded = decodeURIComponent(canonical);
  const { data: entity, loading, error } = useApi<EntityProfile>(`/api/entities/${encodeURIComponent(decoded)}`);

  if (loading) return <EntitySkeleton />;
  if (error) return <Message tone="error">{error}</Message>;
  if (!entity) return <Message>Entity profile not found.</Message>;

  const allEvidence = entityEvidence(entity);
  const connectionItems = connectionRelatedItems(entity, context);
  const sectorHrefValue = entity.sector ? withContext(sectorHref(entity.sector.slug), context) : null;

  return (
    <div className="animate-rise">
      <Crumb items={[context ? { label: context.label, href: context.href } : { label: "Entities", href: "/entities" }, { label: entity.company }]} />
      {context ? <InvestigationContext context={context} /> : null}
      <DetailHeader
        eyebrow={`Company or organization - ${entity.canonical}`}
        title={
          <span className="inline-flex items-center gap-4">
            <AvatarLogo name={entity.company} type="company" className="w-16 h-16 rounded-lg" />
            <span>{entity.company}</span>
          </span>
        }
        subtitle={entity.narrative || "Cross-source entity profile resolved across federal records."}
        action={<PrimaryButton icon="bookmark_add">Watchlist</PrimaryButton>}
      />

      <div className="mb-gutter rounded border border-outline-variant bg-surface-container-lowest px-4 py-3 text-body-md text-on-surface-variant">
        Official logo not stored yet. Nessus is using the shared initials fallback until logo source metadata is available.
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-gutter">
        <div className="lg:col-span-8 space-y-gutter">
          <Card icon="insights" title="Cross-source summary">
            <div className="p-density-comfortable space-y-5">
              <div className="font-memo-body text-memo-body text-on-surface-variant leading-relaxed">{entity.narrative}</div>
              <StatGrid stats={[
                { label: "Contracts", value: num(entity.evidence.contracts.count) },
                { label: "Lobbying", value: num(entity.evidence.lobbying.count) },
                { label: "Donations", value: num(entity.evidence.donations.count) },
                { label: "Bills touched", value: num(entity.evidence.bills.count) },
              ]} />
            </div>
          </Card>

          <Card icon="psychology" title="Why It Matters">
            <div className="p-density-comfortable grid grid-cols-1 md:grid-cols-2 gap-4">
              <Field label="Overall score" value={`${entity.scores.overall}/10`} />
              <Field label="Regulatory risk" value={`${entity.scores.regulatory_risk}/10`} />
              <Field label="Lobbying intensity" value={`${entity.scores.lobbying_intensity}/10`} />
              <Field label="Contract value" value={money(entity.evidence.contracts.total_value)} />
              {sectorHrefValue ? (
                <Field label="Primary sector" value={<Link href={sectorHrefValue} className="text-primary hover:underline focus-ring rounded">{entity.sector?.name}</Link>} />
              ) : (
                <Field label="Primary sector" value="No sector match yet" />
              )}
              <Field label="Evidence records" value={num(allEvidence.length)} />
            </div>
          </Card>

          <Card icon="account_tree" title="Connected Intelligence">
            <div className="p-density-comfortable grid grid-cols-1 md:grid-cols-2 gap-density-comfortable">
              <RelatedItems title="Cross-source patterns" items={connectionItems} empty="No cross-source patterns detected yet." />
              <RelatedItems title="Reports including this entity" items={reportItems(entity, context)} empty="No generated reports include this entity yet." />
              <RelatedItems title="Top departments" items={departmentItems(entity, context)} empty="No department concentration found." />
              <RelatedItems title="Connected bills" items={recordItems(entity.evidence.bills.records, "bill affects sector", context)} empty="No bill evidence found." />
              <RelatedItems title="Lobbying & regulations" items={recordItems([...entity.evidence.lobbying.records, ...entity.evidence.regulations.records], "organization registered lobbying activity", context)} empty="No lobbying or regulatory records found." />
            </div>
          </Card>

          <Card icon="history" title="Supporting Evidence">
            <div className="p-density-comfortable">
              <EvidenceRows refs={allEvidence} limit={10} hrefFor={(ref) => withContext(evidenceHref(ref), context)} />
            </div>
          </Card>
        </div>

        <aside className="lg:col-span-4 space-y-gutter">
          <Card icon="dataset" title="Source Coverage">
            <div className="p-density-comfortable">
              <SourceCoverageList items={entity.source_coverage} limit={10} />
            </div>
          </Card>
          <Card icon="receipt_long" title="Normalized Data">
            <div className="p-density-comfortable grid grid-cols-1 gap-4">
              <Field label="Canonical name" value={entity.canonical} />
              <Field label="Company" value={entity.company} />
              <Field label="Known institutions" value={entity.evidence.lobbying.institutions.slice(0, 4).join(", ") || "Not available"} />
            </div>
          </Card>
        </aside>
      </div>
    </div>
  );
}

type EntityContextValue =
  | { from: "search"; label: string; href: string }
  | { from: "sector"; label: string; href: string }
  | { from: "finding"; label: string; href: string }
  | null;

function entityContext(searchParams: ReturnType<typeof useSearchParams>): EntityContextValue {
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

function withContext(href: string | null, context: EntityContextValue): string | null {
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

function InvestigationContext({ context }: { context: NonNullable<EntityContextValue> }) {
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

function entityEvidence(entity: EntityProfile): EvidenceRef[] {
  return [
    ...entity.evidence.contracts.records,
    ...entity.evidence.lobbying.records,
    ...entity.evidence.donations.records,
    ...entity.evidence.bills.records,
    ...entity.evidence.regulations.records,
    ...entity.evidence.tribunal_decisions.records,
    ...entity.evidence.appointments.records,
    ...entity.evidence.breadth.records,
  ];
}

function connectionRelatedItems(entity: EntityProfile, context: EntityContextValue): RelatedItem[] {
  return entity.connections.slice(0, 6).map((connection, index) => {
    const ref = (connection as { references?: EvidenceRef[] }).references?.[0];
    return {
      id: `connection-${index}`,
      title: connection.title,
      type: "Finding",
      href: ref ? withContext(evidenceHref(ref), context) : null,
      description: connection.detail,
      meta: connection.sources.join(", "),
      relationship: "finding supported by record",
      strength: "supported",
    };
  });
}

function departmentItems(entity: EntityProfile, context: EntityContextValue): RelatedItem[] {
  return entity.evidence.contracts.by_department.slice(0, 6).map((dept) => ({
    id: `department-${dept.dept}`,
    title: dept.dept || "Unknown department",
    type: "Department",
    href: dept.dept ? withContext(`/organizations/department/${encodeURIComponent(dept.dept)}`, context) : null,
    description: `${num(dept.count)} contract record${dept.count === 1 ? "" : "s"}`,
    meta: money(dept.value),
    relationship: "department administers program",
    strength: "supported",
    icon: <AvatarLogo name={dept.dept || "Department"} type="department" />,
  }));
}

function reportItems(entity: EntityProfile, context: EntityContextValue): RelatedItem[] {
  return (entity.reports ?? []).slice(0, 6).map((report) => ({
    id: `report-${report.id}`,
    title: report.company_name,
    type: "Briefing",
    href: withContext(reportHref(report.id), context),
    description: [labelize(report.report_type), report.status].filter(Boolean).join(" - "),
    meta: report.overall == null ? report.created_at : `${Math.round(report.overall)}/100 - ${report.created_at}`,
    relationship: "report covers entity",
    strength: "direct",
  }));
}

function recordItems(records: EvidenceRef[], relationship: string, context: EntityContextValue): RelatedItem[] {
  return records.slice(0, 6).map((ref) => ({
    id: `${ref.table}-${ref.pk ?? ref.id}`,
    title: ref.title,
    type: typeLabel(ref.table),
    href: withContext(evidenceHref(ref), context),
    description: ref.date ?? null,
    meta: ref.source,
    relationship,
    strength: "supported",
  }));
}

function labelize(value: string): string {
  return value.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function EntitySkeleton() {
  return <div className="space-y-gutter">{[0, 1, 2, 3].map((i) => <div key={i} className="skeleton h-32" />)}</div>;
}

function Message({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "error" }) {
  return (
    <div className={`rounded border px-4 py-3 font-body-md text-body-md ${tone === "error" ? "border-error/30 bg-error/10 text-error" : "border-outline-variant bg-surface-container-low text-on-surface-variant"}`}>
      {children}
    </div>
  );
}
