"use client";

import Link from "next/link";
import { AvatarLogo } from "@/components/intelligence";
import { CoverageBadge, PageHeader } from "@/components/ui";
import { num, type EvidenceRef, type FindingsResponse, type GraphFinding } from "@/lib/api";
import { entityHref, evidenceHref, findingHref, sectorHref, typeLabel } from "@/lib/navigation";
import { useApi } from "@/lib/use-api";

interface EntityRow {
  name: string;
  sector?: { slug: string; name: string } | null;
  findings: Set<string>;
  references: EvidenceRef[];
  counts: Record<string, number>;
}

export default function EntitiesIndex() {
  const { data, loading, error } = useApi<FindingsResponse>("/api/graph/findings");
  const findings = data?.findings ?? [];
  const entities = buildEntityRows(findings);
  const evidenceCount = entities.reduce((sum, entity) => sum + entity.references.length, 0);

  return (
    <div className="animate-rise">
      <PageHeader
        title="Entities"
        subtitle="Companies and organizations observed in connected findings. Each card opens an internal source-backed profile instead of a static directory row."
        action={<Link href="/search" className="px-4 py-2 rounded bg-primary text-on-primary text-body-md font-medium hover:bg-primary-container transition-colors focus-ring">Search entities</Link>}
      />

      <form action="/search" className="mb-gutter max-w-xl">
        <label htmlFor="entity-search" className="sr-only">Search entities</label>
        <div className="relative">
          <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-on-surface-variant text-[20px]">search</span>
          <input
            id="entity-search"
            name="q"
            className="w-full pl-10 pr-4 py-2 bg-surface-container-low border border-outline-variant rounded-full font-body-md text-body-md focus:border-primary focus:ring-1 focus:ring-primary outline-none"
            placeholder="Search companies, departments, regulators..."
          />
        </div>
      </form>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-gutter mb-gutter">
        <Metric label="Observed entities" value={num(entities.length)} />
        <Metric label="Linked findings" value={num(new Set(entities.flatMap((entity) => [...entity.findings])).size)} />
        <Metric label="Evidence records" value={num(evidenceCount)} />
      </div>

      {error ? <Message tone="error">{error}</Message> : null}
      {loading ? <EntitySkeleton /> : null}
      {!loading && !error && !entities.length ? <Message>No connected entities found yet. Ingest source data, then refresh the graph findings.</Message> : null}

      {!loading && !error && entities.length ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-gutter">
          {entities.map((entity) => <EntityCard key={entity.name} entity={entity} />)}
        </div>
      ) : null}
    </div>
  );
}

function EntityCard({ entity }: { entity: EntityRow }) {
  const profileHref = entityHref(entity.name) ?? "/entities";
  const firstEvidence = entity.references[0];
  const firstFinding = [...entity.findings][0];
  const contracts = entity.counts.contracts ?? 0;
  const lobbying = (entity.counts.lobbying ?? 0) + (entity.counts.lobbying_records ?? 0) + (entity.counts.ocl_registrations ?? 0);
  const regulations = (entity.counts.gazette ?? 0) + (entity.counts.gazette_entries ?? 0) + (entity.counts.tribunal ?? 0) + (entity.counts.tribunal_decisions ?? 0);

  return (
    <article className="card-level-1 card-level-2 rounded-lg p-density-comfortable">
      <Link href={profileHref} className="block focus-ring rounded">
        <div className="flex items-center gap-4 mb-4">
          <AvatarLogo name={entity.name} type="company" className="w-12 h-12 rounded-lg" />
          <div className="min-w-0">
            <h2 className="font-headline-sm text-[18px] text-primary leading-tight truncate">{entity.name}</h2>
            <p className="font-body-md text-body-md text-on-surface-variant truncate">{entity.sector?.name ?? "Sector not resolved"}</p>
          </div>
        </div>
      </Link>

      <div className="grid grid-cols-3 gap-3 pt-4 border-t border-outline-variant">
        <MiniMetric label="Contracts" value={contracts} />
        <MiniMetric label="Lobbying" value={lobbying} />
        <MiniMetric label="Regulatory" value={regulations} />
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <CoverageBadge status={entity.references.length ? "partial" : "empty"} />
        {entity.sector ? <Link href={sectorHref(entity.sector.slug) ?? "/sectors"} className="font-data-tabular text-data-tabular text-primary hover:underline focus-ring rounded">{entity.sector.name}</Link> : null}
      </div>

      <div className="mt-4 space-y-2 font-body-md text-body-md text-on-surface-variant">
        {firstFinding ? (
          <Link href={findingHref(firstFinding) ?? "/signals"} className="block text-primary hover:underline focus-ring rounded">
            finding affects company · {firstFinding}
          </Link>
        ) : null}
        {firstEvidence ? (
          <Link href={evidenceHref(firstEvidence) ?? "/records"} className="block hover:text-primary focus-ring rounded">
            {typeLabel(firstEvidence.table)} evidence · {firstEvidence.title}
          </Link>
        ) : null}
      </div>
    </article>
  );
}

function buildEntityRows(findings: GraphFinding[]): EntityRow[] {
  const rows = new Map<string, EntityRow>();
  for (const finding of findings) {
    const candidates = new Set<string>();
    for (const ref of finding.references) {
      if (ref.entity) candidates.add(ref.entity);
    }
    for (const actor of finding.actors) {
      const name = stringValue(actor, "entity") ?? stringValue(actor, "organization") ?? stringValue(actor, "company") ?? stringValue(actor, "name");
      const type = stringValue(actor, "type");
      if (name && type !== "politician" && type !== "person") candidates.add(name);
    }
    for (const name of candidates) {
      const row = rows.get(name) ?? {
        name,
        sector: finding.sector ?? finding.related_sectors[0] ?? null,
        findings: new Set<string>(),
        references: [],
        counts: {},
      };
      row.findings.add(finding.title);
      for (const ref of finding.references) {
        if (!ref.entity || ref.entity === name) {
          row.references.push(ref);
          row.counts[ref.table] = (row.counts[ref.table] ?? 0) + 1;
        }
      }
      if (!row.sector) row.sector = finding.sector ?? finding.related_sectors[0] ?? null;
      rows.set(name, row);
    }
  }
  return [...rows.values()]
    .sort((a, b) => (b.findings.size + b.references.length) - (a.findings.size + a.references.length))
    .slice(0, 24);
}

function stringValue(obj: Record<string, unknown>, key: string): string | null {
  const value = obj[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-outline-variant bg-surface-container-lowest px-4 py-3">
      <div className="font-label-caps text-label-caps text-on-surface-variant uppercase">{label}</div>
      <div className="font-data-tabular text-[24px] leading-tight text-primary mt-1">{value}</div>
    </div>
  );
}

function MiniMetric({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <span className="block font-label-caps text-label-caps text-on-surface-variant uppercase mb-1">{label}</span>
      <span className="font-headline-sm text-[20px] text-on-surface">{num(value)}</span>
    </div>
  );
}

function EntitySkeleton() {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-gutter">
      {[0, 1, 2, 3, 4, 5].map((i) => <div key={i} className="skeleton h-56" />)}
    </div>
  );
}

function Message({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "neutral" | "error" }) {
  return (
    <div className={`rounded border px-4 py-3 font-body-md text-body-md mb-gutter ${tone === "error" ? "border-error/30 bg-error/10 text-error" : "border-outline-variant bg-surface-container-low text-on-surface-variant"}`}>
      {children}
    </div>
  );
}
