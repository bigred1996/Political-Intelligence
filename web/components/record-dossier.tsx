import Link from "next/link";
import { Beat, Card, Crumb, Field, SignalBadge } from "@/components/nessus";
import { AvatarLogo } from "@/components/intelligence";
import { OriginalSourceLink } from "@/components/ui";
import type { EvidenceGraphResponse, GraphFinding, LateralGroup, PlayerRef, RecordDetail, RecordRef, RelationGroup } from "@/lib/api";
import { moneyFull } from "@/lib/api";
import { entityHref, findingHref, organizationHref, personHref, recordHref, sectorHref, sourceLabel, typeLabel } from "@/lib/navigation";

/* The shared record dossier — the adaptive two-column intelligence layout used by
   both the universal record page and the bespoke meeting view. Left column is the
   narrative ("tell me": strategic read → analysis → full text → details); the right
   rail is the evidence ("show me": connections → people → governing bodies →
   timeline) and collapses gracefully on one-off records. */

export function RecordDossier({
  detail,
  graph,
  context,
  crumb,
  leadCard,
}: {
  detail: RecordDetail;
  graph?: EvidenceGraphResponse | null;
  context: InvestigationContextValue | null;
  crumb: { label: string; href?: string }[];
  leadCard?: React.ReactNode;
}) {
  const record = detail.record;
  const type = record.type_label || recordTypeLabel(record.record_type, record.source, detail.table);
  const title = record.title || `${type} #${detail.pk}`;
  const assess = detail.assessment;
  const signal = detail.signal;
  const entityUrl = record.entity ? entityHref(record.entity) : null;
  // Only DIRECT (record-supported) findings are relevant on a record; generic
  // sector context belongs on the sector page, not padded onto every record.
  const directFindings = (graph?.findings ?? []).filter(
    (f) => (f as GraphFinding & { relationship_strength?: string }).relationship_strength === "supported",
  );

  return (
    <div className="animate-rise">
      <Crumb items={crumb} />
      {context ? <InvestigationContext context={context} /> : null}

      <div className="flex flex-wrap justify-between items-start gap-4 mb-gutter pb-density-comfortable border-b border-outline-variant">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2 mb-2">
            <span className="font-label-caps text-label-caps text-on-surface-variant uppercase">{type} · {record.source || sourceLabel(detail.table)}</span>
            <SectorChip detail={detail} context={context} />
          </div>
          <h1 className="font-display-lg text-headline-md md:text-display-lg text-primary leading-tight">{title}</h1>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-2 font-data-tabular text-data-tabular text-on-surface-variant">
            {record.entity ? <span>{entityUrl ? <Link href={withContext(entityUrl, context) ?? entityUrl} className="text-primary hover:underline focus-ring rounded">{record.entity}</Link> : record.entity}</span> : null}
            {record.date ? <span>{record.date}</span> : null}
            {record.amount ? <span className="text-primary">{moneyFull(record.amount)}</span> : null}
          </div>
        </div>
        <div className="flex flex-col items-end gap-2 shrink-0">
          {signal ? <SignalBadge level={signal.level} score={signal.score} /> : null}
          {record.url ? <OriginalSourceLink href={record.url} className="font-data-tabular text-[12px] text-on-surface-variant hover:text-primary" /> : null}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-gutter">
        <div className="lg:col-span-8 space-y-gutter">
          {leadCard}

          <Card icon="insights" title="Strategic Read">
            <div className="p-density-comfortable">
              <p className="font-memo-body text-[16px] text-on-surface leading-relaxed">{assess?.strategic_read || "No strategic reading is available for this record."}</p>
              {signal?.drivers?.length ? (
                <div className="mt-4 flex flex-wrap gap-2">
                  {signal.drivers.map((d) => (
                    <span key={d.label} className="inline-flex items-center gap-1.5 rounded-full border border-outline-variant bg-surface-container-lowest px-2.5 py-1 font-data-tabular text-[11px] text-on-surface-variant">
                      <span className="font-label-caps text-on-surface uppercase tracking-wide">{d.label}</span>
                      <span aria-hidden="true">·</span>
                      <span>{d.detail}</span>
                    </span>
                  ))}
                </div>
              ) : null}
            </div>
          </Card>

          {assess ? (
            <Card icon="psychology" title="Analysis">
              <div className="p-density-comfortable space-y-5">
                <Beat label="What this means">{assess.means}</Beat>
                <Beat label="Why it matters">{assess.matters}</Beat>
                <Beat label={detail.industry ? `Impact on ${detail.industry.name}` : "Impact"}>{assess.impact}</Beat>
              </div>
            </Card>
          ) : null}

          {directFindings.length ? (
            <Card icon="flag" title="Cited In Findings">
              <div className="p-density-comfortable space-y-2">
                {directFindings.slice(0, 4).map((f) => (
                  <Link key={f.title} href={withContext(findingHref(f), context) ?? "/signals"} className="block rounded border border-outline-variant bg-surface-container-lowest px-3 py-2 hover:border-primary transition-colors focus-ring">
                    <div className="font-body-md text-body-md text-on-surface">{f.title}</div>
                    {f.summary ? <p className="font-body-md text-[12px] text-on-surface-variant mt-0.5 line-clamp-2">{f.summary}</p> : null}
                  </Link>
                ))}
              </div>
            </Card>
          ) : null}

          {record.body ? (
            <Card icon="article" title="Full Text">
              <div className="p-density-comfortable font-memo-body text-memo-body text-on-surface leading-relaxed whitespace-pre-wrap max-h-[480px] overflow-y-auto">{record.body}</div>
            </Card>
          ) : null}

          <Card icon="fact_check" title="Record Details">
            <div className="p-density-comfortable">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-density-comfortable">
                <Field label="Type" value={type} />
                <Field label="Date" value={record.date ?? "Not provided"} />
                <Field label="Entity" value={record.entity ? (entityUrl ? <Link href={withContext(entityUrl, context) ?? entityUrl} className="text-primary hover:underline focus-ring rounded">{record.entity}</Link> : record.entity) : "Not provided"} />
                <Field label="Amount" value={record.amount ? moneyFull(record.amount) : "Not applicable"} />
                <Field label="Source" value={record.source || sourceLabel(detail.table)} />
                <Field label="Record ID" value={`${detail.table} / ${detail.pk}`} />
              </div>
              {record.fields.length ? (
                <div className="mt-6 grid grid-cols-1 md:grid-cols-2 gap-3">
                  {record.fields.slice(0, 10).map((field) => (
                    <div key={field.key} className="rounded border border-outline-variant bg-surface-container-low px-3 py-2">
                      <div className="font-label-caps text-label-caps text-on-surface-variant uppercase mb-1">{field.label}</div>
                      <div className="font-body-md text-body-md text-on-surface break-words">{field.value}</div>
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          </Card>
        </div>

        <aside className="lg:col-span-4 space-y-gutter">
          <ConnectionsRail detail={detail} context={context} />
          <PeopleRail people={detail.people ?? []} context={context} />
          <GoverningRail regulators={detail.governing_regulators ?? []} sectorName={detail.industry?.name ?? null} context={context} />
          <TimelineRail timeline={detail.relations.timeline ?? []} context={context} />
        </aside>
      </div>
    </div>
  );
}

/* ─── Right-rail sections ─────────────────────────────────────────────────── */

function ConnectionsRail({ detail, context }: { detail: RecordDetail; context: InvestigationContextValue | null }) {
  const sig = detail.relations.cross_source_signature;
  const groups = detail.relations.by_source ?? [];
  const lateral = detail.relations.lateral ?? [];
  const total = detail.relations.total ?? 0;
  const entity = detail.entity?.name ?? detail.record.entity ?? null;
  const entityUrl = entity ? entityHref(entity) : null;

  return (
    <Card icon="hub" title="How It Connects" right={total ? <span className="font-data-tabular text-data-tabular text-primary">{total.toLocaleString()}</span> : undefined}>
      <div className="p-density-comfortable space-y-4">
        {sig?.insight ? (
          <p className="font-memo-body text-memo-body text-on-surface leading-relaxed border-l-2 border-primary/50 bg-primary/5 pl-3 py-1.5">{sig.insight}</p>
        ) : null}

        {groups.length ? (
          <>
            {groups.slice(0, 6).map((group) => <ConnGroupRow key={`${group.table}-${group.source}`} group={group} context={context} />)}
            {entityUrl ? (
              <Link href={withContext(entityUrl, context) ?? entityUrl} className="inline-flex items-center gap-1 font-body-md text-body-md text-primary hover:underline focus-ring rounded">
                Full {entity} profile
                <span className="material-symbols-outlined text-[16px]">arrow_forward</span>
              </Link>
            ) : null}
          </>
        ) : lateral.length ? (
          <>
            <p className="font-body-md text-[12px] text-on-surface-variant">No cross-source activity for this entity. Records sharing context:</p>
            {lateral.map((g) => <LateralGroupRow key={g.label} group={g} context={context} />)}
          </>
        ) : (
          <p className="font-body-md text-body-md text-on-surface-variant">A one-off record — no other federal activity found{entity ? ` for ${entity}` : ""}.</p>
        )}
      </div>
    </Card>
  );
}

function ConnGroupRow({ group, context }: { group: RelationGroup; context: InvestigationContextValue | null }) {
  return (
    <div className="rounded border border-outline-variant bg-surface-container-lowest p-3">
      <div className="flex items-center justify-between gap-2 mb-2">
        <div className="font-label-caps text-label-caps text-on-surface-variant uppercase">{group.label}</div>
        <span className="font-data-tabular text-data-tabular text-primary">{group.count.toLocaleString()}</span>
      </div>
      <div className="space-y-1.5">
        {group.records.slice(0, 3).map((ref) => <RefLink key={`${ref.table}-${ref.pk}`} refItem={ref} context={context} />)}
      </div>
      {group.partial ? <div className="mt-2 font-data-tabular text-[11px] text-on-surface-variant">Showing {Math.min(3, group.records.length)} of {group.count.toLocaleString()}</div> : null}
    </div>
  );
}

function LateralGroupRow({ group, context }: { group: LateralGroup; context: InvestigationContextValue | null }) {
  return (
    <div className="rounded border border-outline-variant bg-surface-container-lowest p-3">
      <div className="font-label-caps text-label-caps text-on-surface-variant uppercase mb-0.5">{group.label}</div>
      <div className="font-data-tabular text-[11px] text-on-surface-variant mb-2">{group.basis}</div>
      <div className="space-y-1.5">
        {group.records.slice(0, 4).map((ref) => <RefLink key={`${ref.table}-${ref.pk}`} refItem={ref} context={context} />)}
      </div>
    </div>
  );
}

function RefLink({ refItem, context }: { refItem: RecordRef; context: InvestigationContextValue | null }) {
  const href = withContext(recordHref(refItem.table, refItem.pk), context);
  const meta = [refItem.date, refItem.amount ? moneyFull(refItem.amount) : null].filter(Boolean).join(" · ");
  const inner = (
    <div className="min-w-0">
      <div className="font-body-md text-body-md text-on-surface group-hover:text-primary transition-colors truncate">{refItem.title}</div>
      {meta ? <div className="font-data-tabular text-[11px] text-on-surface-variant">{meta}</div> : null}
    </div>
  );
  return href ? <Link href={href} className="group block focus-ring rounded">{inner}</Link> : inner;
}

function PeopleRail({ people, context }: { people: PlayerRef[]; context: InvestigationContextValue | null }) {
  if (!people.length) return null;
  return (
    <Card icon="groups" title="People On This Record">
      <div className="p-density-comfortable space-y-3">
        {people.map((p) => {
          const href = p.type === "politician" && p.slug ? withContext(personHref(p.slug), context) : null;
          const inner = (
            <div className="flex items-start gap-3 rounded border border-outline-variant bg-surface-container-lowest p-3 transition-colors group-hover:border-primary">
              <AvatarLogo name={p.name} imageUrl={p.photo_url} type="person" />
              <div className="min-w-0">
                <div className="font-body-md text-body-md font-bold text-primary">{p.name}</div>
                <div className="font-data-tabular text-data-tabular text-on-surface-variant">{[p.role, p.party].filter(Boolean).join(" · ") || p.type}</div>
                <p className="font-body-md text-[12px] text-on-surface-variant mt-1 line-clamp-2">{p.why}</p>
              </div>
            </div>
          );
          return href ? <Link key={`${p.type}-${p.name}`} href={href} className="group block focus-ring rounded">{inner}</Link> : <div key={`${p.type}-${p.name}`}>{inner}</div>;
        })}
      </div>
    </Card>
  );
}

function GoverningRail({ regulators, sectorName, context }: { regulators: string[]; sectorName: string | null; context: InvestigationContextValue | null }) {
  if (!regulators.length) return null;
  return (
    <Card icon="account_balance" title="Who Governs This">
      <div className="p-density-comfortable">
        {sectorName ? <p className="font-body-md text-[12px] text-on-surface-variant mb-3">Federal bodies overseeing {sectorName}.</p> : null}
        <div className="flex flex-wrap gap-2">
          {regulators.map((name) => {
            const href = withContext(organizationHref("regulator", name), context);
            return href ? (
              <Link key={name} href={href} className="font-body-md text-body-md rounded-full border border-outline-variant bg-surface-container-lowest px-3 py-1.5 text-on-surface hover:border-primary hover:text-primary transition-colors focus-ring">{name}</Link>
            ) : (
              <span key={name} className="font-body-md text-body-md rounded-full border border-outline-variant bg-surface-container-lowest px-3 py-1.5 text-on-surface">{name}</span>
            );
          })}
        </div>
      </div>
    </Card>
  );
}

function TimelineRail({ timeline, context }: { timeline: RecordRef[]; context: InvestigationContextValue | null }) {
  const items = timeline.filter((t) => t.date);
  if (items.length < 2) return null;
  return (
    <Card icon="timeline" title="Activity Timeline">
      <div className="p-density-comfortable space-y-2">
        {items.slice(0, 12).map((ref) => {
          const href = withContext(recordHref(ref.table, ref.pk), context);
          const inner = (
            <div className={`flex items-start gap-3 ${ref.current ? "" : "group"}`}>
              <span className="font-data-tabular text-[11px] text-on-surface-variant w-20 shrink-0 pt-0.5">{ref.date}</span>
              <div className="min-w-0">
                <div className={`font-body-md text-body-md truncate ${ref.current ? "text-primary font-bold" : "text-on-surface group-hover:text-primary transition-colors"}`}>{ref.title}</div>
                <div className="font-data-tabular text-[11px] text-on-surface-variant">{ref.current ? "This record" : (ref.source || typeLabel(ref.table))}</div>
              </div>
            </div>
          );
          return ref.current || !href ? <div key={`${ref.table}-${ref.pk}`}>{inner}</div> : <Link key={`${ref.table}-${ref.pk}`} href={href} className="block focus-ring rounded">{inner}</Link>;
        })}
      </div>
    </Card>
  );
}

function SectorChip({ detail, context }: { detail: RecordDetail; context: InvestigationContextValue | null }) {
  if (!detail.industry) {
    return <span className="font-label-caps text-label-caps bg-surface-container-highest text-on-surface-variant px-2 py-1 rounded-full uppercase">Cross-government</span>;
  }
  const { name, slug, confidence } = detail.industry;
  const prefix = confidence === "confirmed" ? "" : "Likely · ";
  return (
    <Link href={withContext(sectorHref(slug), context) ?? "/sectors"} className="font-label-caps text-label-caps bg-primary/10 text-primary px-2 py-1 rounded-full uppercase hover:underline focus-ring">{prefix}{name}</Link>
  );
}

/* ─── Investigation context (preserves the return path through the workflow) ─── */

export type InvestigationContextValue =
  | { from: "search"; label: string; href: string }
  | { from: "sector"; label: string; href: string }
  | { from: "finding"; label: string; href: string }
  | { from: "records"; label: string; href: string };

export type ParamGetter = (key: string) => string | null;

export function investigationContext(get: ParamGetter): InvestigationContextValue | null {
  const from = get("from");
  if (from === "search") {
    const q = get("q") ?? "";
    return { from, label: q ? `Back to search: ${q}` : "Back to search", href: `/search${q ? `?q=${encodeURIComponent(q)}` : ""}` };
  }
  if (from === "sector") {
    const sector = get("sector") ?? "";
    return { from, label: sector ? `Back to sector: ${sector}` : "Back to sector", href: sector ? `/sectors/${encodeURIComponent(sector)}` : "/sectors" };
  }
  if (from === "finding") {
    const finding = get("finding") ?? "";
    return { from, label: finding ? "Back to finding" : "Back to finding", href: finding ? `/signals/${encodeURIComponent(finding)}` : "/signals" };
  }
  if (from === "records") {
    const source = get("source") ?? "";
    return { from, label: "Back to records", href: source ? `/records/${encodeURIComponent(source)}` : "/records" };
  }
  return null;
}

export function withContext(href: string | null, context: InvestigationContextValue | null): string | null {
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
  if (context.from === "records") {
    const source = context.href.split("/records/")[1];
    return `${href}${glue}from=records${source ? `&source=${encodeURIComponent(decodeURIComponent(source))}` : ""}`;
  }
  const finding = context.href.split("/signals/")[1];
  return `${href}${glue}from=finding${finding ? `&finding=${encodeURIComponent(decodeURIComponent(finding))}` : ""}`;
}

export function InvestigationContext({ context }: { context: InvestigationContextValue }) {
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

export function recordTypeLabel(recordType?: string | null, source?: string | null, table?: string | null): string {
  if (source === "social_statements" || source === "public_statements" || recordType === "public_statement" || recordType === "social_post") {
    return "Public statement";
  }
  return typeLabel(table);
}
