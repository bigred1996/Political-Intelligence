"use client";

import Link from "next/link";
import { AvatarLogo, RelatedItems, type RelatedItem } from "@/components/intelligence";
import { Crumb, Card, DetailHeader, Field } from "@/components/nessus";
import { EvidenceRows } from "@/components/ui";
import { num, type EvidenceRef, type FindingsResponse, type GraphFinding, type SearchHit, type SearchResponse } from "@/lib/api";
import { evidenceHref, findingHref, typeLabel } from "@/lib/navigation";
import { useApi } from "@/lib/use-api";

export type PlannedPoliticalProfileKind = "senator" | "minister";

export function PlannedPoliticalProfile({
  kind,
  slug,
}: {
  kind: PlannedPoliticalProfileKind;
  slug: string;
}) {
  const name = titleCase(decodeURIComponent(slug));
  const profile = PROFILE_COPY[kind];
  const searchPath = `/api/search?q=${encodeURIComponent(name)}&limit=12&answer=false`;
  const { data: search, loading: searchLoading, error: searchError } = useApi<SearchResponse>(searchPath);
  const { data: graph, loading: graphLoading } = useApi<FindingsResponse>("/api/graph/findings");

  const evidence = evidenceFromSearch(search?.results ?? []);
  const relatedFindings = relatedFindingsFor(graph?.findings ?? [], name);
  const sourceItems = sourceItemsFor(evidence);
  const findingItems = relatedFindings.slice(0, 6).map((finding): RelatedItem => ({
    id: finding.title,
    title: finding.title,
    type: "Finding",
    href: findingHref(finding.title),
    description: finding.summary,
    meta: finding.confidence,
    relationship: `${profile.relationshipSubject} connected to finding`,
    strength: finding.relationship_strength ?? "inferred",
  }));
  const evidenceItems = evidence.slice(0, 8).map((ref): RelatedItem => ({
    id: `${ref.table}-${ref.pk ?? ref.id}`,
    title: ref.title,
    type: typeLabel(ref.table),
    href: evidenceHref(ref),
    description: ref.date ?? null,
    meta: ref.source,
    relationship: `${profile.relationshipSubject} mentioned in record`,
    strength: "supported",
  }));
  const sectors = uniqueSectors(relatedFindings);
  const activeLoading = searchLoading || graphLoading;

  return (
    <div className="animate-rise">
      <Crumb items={profile.crumbs(name)} />
      <DetailHeader
        eyebrow={profile.eyebrow}
        title={
          <span className="inline-flex items-center gap-4 min-w-0">
            <AvatarLogo name={name} type="person" className="w-16 h-16 rounded-lg" />
            <span className="truncate">{name}</span>
          </span>
        }
        subtitle={profile.subtitle}
        action={<Link href={`/search?q=${encodeURIComponent(name)}`} className="px-4 py-2 rounded bg-primary text-on-primary text-body-md font-medium hover:bg-primary-container transition-colors focus-ring">Search activity</Link>}
      />

      <div className="mb-gutter rounded border border-outline-variant bg-surface-container-lowest px-4 py-3 text-body-md text-on-surface-variant">
        Official {profile.imageLabel} source metadata is not stored yet. Nessus is using the shared person fallback and showing source-backed matches from search and graph findings.
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-gutter">
        <div className="lg:col-span-8 space-y-gutter">
          <Card icon="insights" title="AI Interpretation">
            <div className="p-density-comfortable font-memo-body text-memo-body text-on-surface-variant leading-relaxed">
              {profile.interpretation(name)}
            </div>
          </Card>

          <Card icon="receipt_long" title="Important Normalized Data">
            <div className="p-density-comfortable grid grid-cols-1 sm:grid-cols-3 gap-4">
              <Field label="Name" value={name} />
              <Field label="Profile type" value={profile.typeLabel} />
              <Field label="Source coverage" value={profile.coverage} />
              <Field label="Matching records" value={activeLoading ? "Loading..." : num(evidence.length)} />
              <Field label="Related findings" value={activeLoading ? "Loading..." : num(relatedFindings.length)} />
              <Field label="Original profile source" value="Not stored yet" />
            </div>
          </Card>

          <Card icon="account_tree" title="Related Intelligence">
            <div className="p-density-comfortable grid grid-cols-1 md:grid-cols-2 gap-density-comfortable">
              <RelatedItems title="Related findings" items={findingItems} empty={`No graph findings currently cite this ${profile.relationshipSubject}.`} />
              <RelatedItems title="Supporting records" items={evidenceItems} empty="No matching internal records found from search yet." />
              <RelatedItems title="Source groups" items={sourceItems} empty="No source groups matched this profile yet." />
              <RelatedItems title="Affected sectors" items={sectors} empty="No affected sectors inferred yet." />
            </div>
          </Card>

          <Card icon="history" title="Supporting Evidence Timeline">
            <div className="p-density-comfortable">
              <EvidenceRows refs={evidence} limit={12} />
              {searchError ? <div className="mt-3 rounded border border-error/30 bg-error/10 px-3 py-2 text-error text-body-md">{searchError}</div> : null}
            </div>
          </Card>
        </div>

        <aside className="lg:col-span-4 space-y-gutter">
          <Card icon="dataset" title="Source Coverage Gap">
            <div className="p-density-comfortable space-y-3 text-body-md text-on-surface-variant">
              <p>{profile.gap}</p>
              <div className="rounded border border-outline-variant bg-surface-container-low px-3 py-2">
                {profile.noEvidenceLabel}
              </div>
            </div>
          </Card>

          <Card icon="travel_explore" title="Investigation Paths">
            <div className="p-density-comfortable space-y-2">
              <Link href={`/search?q=${encodeURIComponent(name)}`} className="block rounded border border-outline-variant bg-surface-container-lowest px-3 py-2 text-primary hover:underline focus-ring">
                Search all records for {name}
              </Link>
              <Link href="/signals" className="block rounded border border-outline-variant bg-surface-container-lowest px-3 py-2 text-primary hover:underline focus-ring">
                Open connected findings
              </Link>
              <Link href="/sources/social_statements" className="block rounded border border-outline-variant bg-surface-container-lowest px-3 py-2 text-primary hover:underline focus-ring">
                Planned public statements source
              </Link>
            </div>
          </Card>
        </aside>
      </div>
    </div>
  );
}

const PROFILE_COPY = {
  senator: {
    typeLabel: "Senator",
    relationshipSubject: "senator",
    eyebrow: "Senate profile",
    subtitle: "Internal investigation page for a senator reference while dedicated Senate ingestion is incomplete.",
    coverage: "Planned Senate source coverage",
    imageLabel: "Senate portrait",
    noEvidenceLabel: "No dedicated Senate evidence feed is loaded yet.",
    gap: "Senate committee memberships, sponsored bills, debates, appointments, ethics disclosures, official portraits, and source attribution still need first-class ingestion.",
    crumbs: (name: string) => [{ label: "Parliament" }, { label: "Senate" }, { label: name }],
    interpretation: (name: string) => `${name} is kept inside Polaris as an internal senator investigation object. Until Senate-specific feeds are connected, Nessus only treats matching search records and graph findings as supporting context, not verified chamber activity.`,
  },
  minister: {
    typeLabel: "Cabinet minister",
    relationshipSubject: "minister",
    eyebrow: "Cabinet profile",
    subtitle: "Internal investigation page for a minister or portfolio reference while cabinet source coverage is incomplete.",
    coverage: "Planned cabinet source coverage",
    imageLabel: "ministerial portrait",
    noEvidenceLabel: "No dedicated ministerial evidence feed is loaded yet.",
    gap: "Ministerial portfolios, mandate letters, department responsibilities, cabinet changes, official portraits, statements, and source attribution still need first-class ingestion.",
    crumbs: (name: string) => [{ label: "Cabinet" }, { label: name }],
    interpretation: (name: string) => `${name} is kept inside Polaris as an internal cabinet investigation object. Until ministerial portfolio feeds are connected, Nessus only treats matching search records and graph findings as supporting context, not verified portfolio activity.`,
  },
} satisfies Record<PlannedPoliticalProfileKind, {
  typeLabel: string;
  relationshipSubject: string;
  eyebrow: string;
  subtitle: string;
  coverage: string;
  imageLabel: string;
  noEvidenceLabel: string;
  gap: string;
  crumbs: (name: string) => { label: string; href?: string }[];
  interpretation: (name: string) => string;
}>;

function evidenceFromSearch(results: SearchHit[]): EvidenceRef[] {
  const seen = new Set<string>();
  return results.flatMap((hit) => {
    if (!hit.table || hit.pk == null) return [];
    const key = `${hit.table}:${hit.pk}`;
    if (seen.has(key)) return [];
    seen.add(key);
    return [{
      table: hit.table,
      pk: hit.pk,
      id: hit.pk,
      source: hit.source,
      title: hit.title,
      date: hit.date ?? null,
      url: hit.url ?? null,
      record_type: hit.table,
    } as EvidenceRef];
  });
}

function relatedFindingsFor(findings: GraphFinding[], name: string): GraphFinding[] {
  const needle = name.toLowerCase();
  return findings.filter((finding) => {
    const text = [
      finding.title,
      finding.summary,
      ...finding.references.map((ref) => `${ref.title} ${ref.entity ?? ""}`),
      ...finding.actors.map((actor) => Object.values(actor).join(" ")),
    ].join(" ").toLowerCase();
    return text.includes(needle);
  });
}

function sourceItemsFor(refs: EvidenceRef[]): RelatedItem[] {
  const byTable = new Map<string, { count: number; first: EvidenceRef }>();
  for (const ref of refs) {
    const current = byTable.get(ref.table);
    if (current) current.count += 1;
    else byTable.set(ref.table, { count: 1, first: ref });
  }
  return [...byTable.entries()].map(([table, group]) => ({
    id: table,
    title: typeLabel(table, true),
    type: "Source group",
    href: evidenceHref(group.first),
    description: `${num(group.count)} matching record${group.count === 1 ? "" : "s"}`,
    meta: group.first.source,
    relationship: "profile supported by source records",
    strength: "supported",
  }));
}

function uniqueSectors(findings: GraphFinding[]): RelatedItem[] {
  const sectors = new Map<string, { slug: string; name: string }>();
  for (const finding of findings) {
    for (const sector of [finding.sector, ...finding.related_sectors].filter(Boolean) as { slug: string; name: string }[]) {
      sectors.set(sector.slug, sector);
    }
  }
  return [...sectors.values()].map((sector) => ({
    id: sector.slug,
    title: sector.name,
    type: "Sector",
    href: `/sectors/${encodeURIComponent(sector.slug)}`,
    relationship: "profile associated with sector finding",
    strength: "inferred",
  }));
}

function titleCase(value: string): string {
  return value
    .replace(/-/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}
