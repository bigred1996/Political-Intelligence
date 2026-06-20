"use client";

import Link from "next/link";
import { use } from "react";
import { AvatarLogo, RelatedItems, type RelatedItem } from "@/components/intelligence";
import { EvidenceRows } from "@/components/ui";
import { useApi } from "@/lib/use-api";
import type { EvidenceGraphResponse, EvidenceRef, IntelligenceFinding, SectorOverview } from "@/lib/api";
import { money, num } from "@/lib/api";
import { committeeHref, entityHref, evidenceHref, findingHref, organizationHref, personHref, recordHref, sourceHref, typeLabel } from "@/lib/navigation";

export default function SectorDetail({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  const { data, loading, error } = useApi<SectorOverview>(`/api/sectors/${encodeURIComponent(slug)}/overview`);

  if (loading) return <SectorSkeleton />;
  if (error) return <Message tone="error">{error}</Message>;
  if (!data) return <Message>Sector not found.</Message>;

  const sector = data.sector;
  const graph = data.graph as EvidenceGraphResponse | undefined;
  const findings = data.findings?.length ? data.findings : data.intelligence_brief?.top_findings ?? [];
  const evidenceRefs = collectSectorEvidence(data).slice(0, 10);
  const connectedPeople = peopleItems(graph, sector.slug);
  const connectedOrganizations = organizationItems(data, sector.slug);
  const connectedRecords = evidenceRefs.map((ref) => evidenceItem(ref, sector.slug));

  return (
    <div className="overflow-x-hidden animate-rise">
      <div className="mb-gutter flex flex-col md:flex-row justify-between md:items-end gap-4">
        <div>
          <div className="flex items-center gap-density-compact mb-density-compact text-on-surface-variant">
            <Link className="font-label-caps text-label-caps hover:text-primary transition-colors uppercase focus-ring rounded" href="/sectors">
              Sectors
            </Link>
            <span className="material-symbols-outlined text-[14px]">chevron_right</span>
            <span className="font-label-caps text-label-caps text-primary uppercase">{sector.name}</span>
          </div>
          <h1 className="font-display-lg text-display-lg text-primary">{sector.name}</h1>
          <p className="font-body-lg text-body-lg text-on-surface-variant mt-unit max-w-3xl">
            {data.intelligence_brief?.risk_summary || data.narrative || sector.blurb || sector.description || "Connected sector intelligence assembled from internal evidence records."}
          </p>
        </div>
        <div className="flex gap-density-compact shrink-0">
          <Link href={`/search?q=${encodeURIComponent(sector.name)}`} className="px-4 py-2 border border-outline-variant text-secondary rounded font-body-md text-body-md hover:bg-surface-container-low transition-colors flex items-center gap-2 focus-ring">
            <span className="material-symbols-outlined text-[18px]">travel_explore</span>
            Search sector
          </Link>
          <Link href="/watchlists" className="px-4 py-2 bg-primary text-on-primary rounded font-body-md text-body-md hover:bg-primary-container transition-colors flex items-center gap-2 focus-ring">
            <span className="material-symbols-outlined text-[18px]">add_alert</span>
            Track Sector
          </Link>
        </div>
      </div>

      <div className="grid grid-cols-12 gap-gutter">
        <div className="col-span-12 lg:col-span-8 flex flex-col gap-gutter">
          <section className="card-level-1 card-level-2 rounded-lg p-density-comfortable">
            <div className="flex flex-wrap justify-between items-center gap-3 mb-density-comfortable border-b border-outline-variant pb-density-compact">
              <h2 className="font-headline-sm text-headline-sm text-primary">Sector Risk Profile</h2>
              <span className={riskClass(data.risk_band)}>{data.risk_band}</span>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <Metric label="Overall risk" value={String(data.scores?.overall ?? 0)} />
              <Metric label="Lobbying" value={num(data.evidence?.lobbying?.count)} />
              <Metric label="Legislation" value={num(data.evidence?.bills?.count)} />
              <Metric label="Contracts" value={money(data.evidence?.contracts?.total_value)} />
            </div>
            <div className="mt-5 grid grid-cols-1 md:grid-cols-3 gap-3">
              {(data.movement ?? []).map((window) => (
                <div key={window.window_days} className="rounded border border-outline-variant bg-surface-container-low px-3 py-2">
                  <div className="font-label-caps text-label-caps text-on-surface-variant uppercase">{window.window_days} days</div>
                  <div className="font-body-md text-body-md text-primary capitalize">{window.status.replace(/_/g, " ")}</div>
                  <p className="text-[12px] text-on-surface-variant mt-1">{window.note}</p>
                </div>
              ))}
            </div>
          </section>

          <section className="card-level-1 card-level-2 rounded-lg overflow-hidden">
            <div className="bg-surface-bright px-density-comfortable py-density-compact border-b border-outline-variant flex justify-between items-center">
              <h2 className="font-headline-sm text-headline-sm text-primary">Top Material Findings</h2>
              <Link href="/signals" className="font-label-caps text-label-caps text-primary hover:underline focus-ring rounded">View live feed</Link>
            </div>
            <div className="flex flex-col">
              {findings.slice(0, 5).map((finding, index) => <FindingRow key={finding.title} finding={finding} sectorSlug={sector.slug} last={index === Math.min(findings.length, 5) - 1} />)}
              {!findings.length && <div className="p-density-comfortable text-on-surface-variant">No findings are available for this sector yet.</div>}
            </div>
          </section>

          <section className="card-level-1 card-level-2 rounded-lg overflow-hidden">
            <div className="bg-surface-bright px-density-comfortable py-density-compact border-b border-outline-variant">
              <h2 className="font-headline-sm text-headline-sm text-primary">Supporting Evidence</h2>
            </div>
            <div className="p-density-comfortable grid grid-cols-1 md:grid-cols-2 gap-density-comfortable">
              <RelatedItems title="Connected bills, lobbying, regulations & sources" items={connectedRecords} empty="No linked evidence records found." />
              <div>
                <h3 className="text-sm font-semibold text-on-surface mb-2">Evidence timeline</h3>
                <EvidenceRows refs={evidenceRefs} limit={8} hrefFor={(ref) => withSectorContext(evidenceHref(ref), sector.slug)} />
              </div>
            </div>
          </section>
        </div>

        <aside className="col-span-12 lg:col-span-4 flex flex-col gap-gutter">
          <section className="card-level-1 card-level-2 rounded-lg p-density-comfortable">
            <h2 className="font-headline-sm text-headline-sm text-primary mb-density-comfortable flex items-center gap-2 border-b border-outline-variant pb-density-compact">
              <span className="material-symbols-outlined text-[20px]">account_tree</span>
              Connected Entities
            </h2>
            <div className="space-y-density-comfortable">
              <RelatedItems title="People" items={connectedPeople} empty="No connected people found." />
              <RelatedItems title="Companies & organizations" items={connectedOrganizations} empty="No connected organizations found." />
            </div>
          </section>

          <section className="card-level-1 card-level-2 rounded-lg overflow-hidden">
            <div className="bg-surface-bright px-density-comfortable py-density-compact border-b border-outline-variant">
              <h2 className="font-headline-sm text-headline-sm text-primary">Source Coverage</h2>
            </div>
            <div className="p-density-comfortable space-y-2">
              {(data.source_coverage ?? []).slice(0, 8).map((source) => (
                <Link key={source.id} href={sourceHref(source.id) ?? "/sources"} className="flex items-center justify-between gap-3 rounded border border-outline-variant bg-surface-container-lowest px-3 py-2 hover:border-primary transition-colors focus-ring">
                  <span className="font-body-md text-body-md text-primary">{source.label}</span>
                  <span className={coverageClass(source.status)}>{source.status}</span>
                </Link>
              ))}
              {!data.source_coverage?.length && <Message>No source coverage rows are available.</Message>}
            </div>
          </section>

          <section className="card-level-1 card-level-2 rounded-lg overflow-hidden">
            <div className="bg-surface-bright px-density-comfortable py-density-compact border-b border-outline-variant">
              <h2 className="font-headline-sm text-headline-sm text-primary">Suggested Questions</h2>
            </div>
            <div className="p-density-comfortable space-y-2">
              {(data.suggested_questions ?? data.intelligence_brief?.suggested_questions ?? []).slice(0, 4).map((question) => (
                <Link key={question} href={`/search?q=${encodeURIComponent(question)}`} className="block rounded border border-outline-variant bg-surface-container-lowest px-3 py-2 text-body-md text-on-surface hover:border-primary transition-colors focus-ring">
                  {question}
                </Link>
              ))}
            </div>
          </section>
        </aside>
      </div>
    </div>
  );
}

function FindingRow({ finding, sectorSlug, last }: { finding: IntelligenceFinding; sectorSlug: string; last: boolean }) {
  const href = findingHref(finding.title) ?? "/signals";
  const firstEvidence = finding.related_records?.[0] ? evidenceHref(finding.related_records[0]) : finding.evidence_references?.[0]?.internal_url;
  return (
    <div className={`px-density-comfortable py-density-comfortable zebra-row flex gap-gutter items-start ${last ? "" : "border-b border-outline-variant"}`}>
      <div className="w-2 h-16 rounded-full bg-surface-container-high overflow-hidden flex flex-col-reverse shrink-0">
        <div className={`w-full ${finding.risk_level === "high" || finding.risk_level === "elevated" ? "h-full bg-error" : "h-2/3 bg-amber-500"}`} />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex justify-between items-start gap-3 mb-1">
          <Link href={`${href}?from=sector&sector=${encodeURIComponent(sectorSlug)}`} className="font-body-lg text-body-lg font-bold text-primary hover:underline focus-ring rounded">
            {finding.title}
          </Link>
          <span className={riskClass(finding.risk_level)}>{finding.risk_level}</span>
        </div>
        <p className="font-body-md text-body-md text-on-surface-variant mb-density-compact">
          {finding.concise_summary || finding.why_it_matters || "Connected evidence is available for analyst review."}
        </p>
        <div className="flex flex-wrap gap-2">
          <span className="text-xs bg-surface-container px-2 py-1 rounded text-secondary border border-outline-variant">{finding.signal_type}</span>
          <span className="text-xs bg-surface-container px-2 py-1 rounded text-secondary border border-outline-variant">{finding.confidence} confidence</span>
          {firstEvidence && <Link href={`${firstEvidence}${firstEvidence.includes("?") ? "&" : "?"}from=sector&sector=${encodeURIComponent(sectorSlug)}`} className="text-xs bg-primary/10 px-2 py-1 rounded text-primary border border-primary/20 hover:underline focus-ring">Open evidence</Link>}
        </div>
      </div>
    </div>
  );
}

function collectSectorEvidence(data: SectorOverview): EvidenceRef[] {
  return [
    ...(data.evidence?.bills?.records ?? []),
    ...(data.evidence?.regulations?.records ?? []),
    ...(data.evidence?.lobbying?.records ?? []),
    ...(data.evidence?.contracts?.records ?? []),
    ...(data.evidence?.tribunal_decisions?.records ?? []),
    ...(data.evidence?.appointments?.records ?? []),
    ...(data.evidence?.breadth?.records ?? []),
  ].filter((ref) => ref.table && (ref.pk ?? ref.id) != null && ref.title);
}

function evidenceItem(ref: EvidenceRef, sectorSlug: string): RelatedItem {
  const href = evidenceHref(ref);
  return {
    id: `${ref.table}-${ref.pk ?? ref.id}`,
    title: ref.title,
    type: typeLabel(ref.table),
    href: withSectorContext(href, sectorSlug),
    description: ref.date ?? null,
    meta: ref.source,
    relationship: evidenceRelationship(ref.table),
    strength: "supported",
  };
}

function evidenceRelationship(table: string): string {
  if (table === "bills") return "bill affects sector";
  if (table === "lobbying" || table === "ocl_registrations") return "organization registered lobbying activity";
  if (table === "gazette" || table === "regulations" || table === "tribunal") return "regulator opened consultation";
  if (table === "contracts" || table === "grants") return "company belongs to sector";
  return "finding supported by record";
}

function withSectorContext(href: string | null, sectorSlug: string): string | null {
  if (!href) return href;
  const glue = href.includes("?") ? "&" : "?";
  return `${href}${glue}from=sector&sector=${encodeURIComponent(sectorSlug)}`;
}

function peopleItems(graph: EvidenceGraphResponse | undefined, sectorSlug: string): RelatedItem[] {
  const actors = new Map<string, Record<string, unknown>>();
  for (const finding of graph?.findings ?? []) {
    for (const actor of finding.actors ?? []) {
      const name = String(actor.name ?? actor.label ?? "");
      if (name) actors.set(name, actor);
    }
  }
  return [...actors.entries()].slice(0, 6).map(([name, actor]) => {
    const slug = typeof actor.slug === "string" ? actor.slug : null;
    return {
      id: `person-${slug ?? name}`,
      title: name,
      type: "Political figure",
      href: withSectorContext(personHref(slug), sectorSlug),
      description: [actor.role, actor.party].filter(Boolean).join(" - ") || null,
      relationship: "person connected to sector finding",
      strength: slug ? "supported" : "inferred",
      icon: <AvatarLogo name={name} imageUrl={typeof actor.photo_url === "string" ? actor.photo_url : null} type="person" />,
    };
  });
}

function organizationItems(data: SectorOverview, sectorSlug: string): RelatedItem[] {
  const items: RelatedItem[] = [];
  for (const row of (data.top_entities ?? []).slice(0, 6)) {
    items.push({
      id: `entity-${row.entity}`,
      title: row.entity,
      type: "Company",
      href: withSectorContext(entityHref(row.entity), sectorSlug),
      description: `${num(row.contracts)} contract(s), ${num(row.lobbying)} lobbying record(s)`,
      relationship: "company belongs to sector",
      strength: "direct",
      icon: <AvatarLogo name={row.entity} type="company" />,
    });
  }
  for (const regulator of (data.sector?.regulators ?? []).slice(0, 4)) {
    items.push({
      id: `regulator-${regulator}`,
      title: regulator,
      type: "Regulator",
      href: withSectorContext(organizationHref("regulator", regulator), sectorSlug),
      relationship: "regulator opened consultation",
      strength: "inferred",
      icon: <AvatarLogo name={regulator} type="regulator" />,
    });
  }
  const committee = (data.evidence?.bills?.records ?? []).length ? { slug: "indu", name: "Standing Committee on Industry and Technology" } : null;
  if (committee) {
    items.push({
      id: `committee-${committee.slug}`,
      title: committee.name,
      type: "Committee",
      href: withSectorContext(committeeHref(committee.slug), sectorSlug),
      relationship: "committee connected to finding",
      strength: "inferred",
    });
  }
  return items;
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-outline-variant bg-surface-container-lowest p-3">
      <span className="block font-label-caps text-label-caps text-on-surface-variant uppercase mb-1">{label}</span>
      <span className="font-headline-sm text-[20px] text-primary">{value}</span>
    </div>
  );
}

function SectorSkeleton() {
  return <div className="space-y-gutter">{[0, 1, 2, 3].map((i) => <div key={i} className="skeleton h-36" />)}</div>;
}

function Message({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "neutral" | "error" }) {
  return (
    <div className={`rounded border px-4 py-3 font-body-md text-body-md ${tone === "error" ? "border-error/30 bg-error/10 text-error" : "border-outline-variant bg-surface-container-low text-on-surface-variant"}`}>
      {children}
    </div>
  );
}

function riskClass(level?: string | null) {
  const l = (level ?? "unknown").toLowerCase();
  if (l.includes("high") || l.includes("elevated")) return "font-label-caps text-label-caps status-chip-red px-2 py-1 rounded-full uppercase shrink-0";
  if (l.includes("moderate") || l.includes("medium") || l.includes("watch")) return "font-label-caps text-label-caps status-chip-amber px-2 py-1 rounded-full uppercase shrink-0";
  return "font-label-caps text-label-caps status-chip-green px-2 py-1 rounded-full uppercase shrink-0";
}

function coverageClass(status?: string) {
  const s = (status ?? "unknown").toLowerCase();
  if (s === "live") return "font-label-caps text-label-caps status-chip-green px-2 py-1 rounded-full uppercase";
  if (s === "partial") return "font-label-caps text-label-caps status-chip-amber px-2 py-1 rounded-full uppercase";
  return "font-label-caps text-label-caps bg-surface-container text-on-surface-variant px-2 py-1 rounded-full uppercase";
}
