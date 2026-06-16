"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useApi } from "@/lib/use-api";
import { money, partyColor, recordHref, type PlayerRef, type RecordDetail, type RecordRef } from "@/lib/api";
import { Eyebrow, EmptyState, Panel, SeverityBadge, SkeletonBlock, SourceTag } from "@/components/ui";

export default function RecordPage() {
  const params = useParams<{ table: string; pk: string }>();
  const table = params?.table;
  const pk = params?.pk;
  const { data, loading, error } = useApi<RecordDetail>(
    table && pk ? `/api/records/${table}/${pk}` : null
  );

  if (loading) {
    return (
      <div className="mx-auto max-w-[1320px] px-4 py-6 space-y-3">
        <SkeletonBlock className="h-24 rounded" />
        <div className="grid lg:grid-cols-3 gap-3">
          <SkeletonBlock className="h-72 rounded" />
          <SkeletonBlock className="h-72 rounded lg:col-span-2" />
        </div>
      </div>
    );
  }
  if (error || !data) {
    return (
      <div className="mx-auto max-w-[1320px] px-4 py-10">
        <p className="text-fg-dim">Record not found. {error}</p>
        <Link href="/search" className="text-brass-bright text-sm mt-2 inline-block">← Back to search</Link>
      </div>
    );
  }

  const { record, entity, industry, impact, players, relations } = data;

  return (
    <div>
      {/* Header band — industry first */}
      <section className="bg-panel border-b border-line map-grid">
        <div className="mx-auto max-w-[1320px] px-4 py-8">
          <div className="flex items-center gap-2 flex-wrap">
            {industry ? (
              <Link href={`/sectors/${industry.slug}`} className="mono text-[11px] uppercase tracking-wide font-semibold text-brass-bright border border-brass/40 rounded px-2 py-0.5 hover:bg-brass/10">
                {industry.name}
              </Link>
            ) : (
              <span className="mono text-[10px] uppercase tracking-wide text-fg-dim border border-line rounded px-2 py-0.5">Unclassified industry</span>
            )}
            <SourceTag>{record.source}</SourceTag>
            <span className="mono text-[10px] uppercase tracking-wide text-fg-dim">{record.record_type}</span>
            {record.date && <span className="mono text-[10px] text-fg-dim">{record.date}</span>}
          </div>
          <h1 className="text-xl md:text-2xl font-semibold text-fg-bright mt-2 max-w-3xl leading-snug">
            {record.title}
          </h1>
          <div className="flex items-center gap-4 mt-3 flex-wrap text-sm">
            {record.amount != null && (
              <span className="mono text-brass-bright font-semibold">{money(record.amount)}</span>
            )}
            {entity.canonical && (
              <Link href={`/entities/${encodeURIComponent(entity.canonical)}`} className="text-fg hover:text-brass-bright">
                {entity.name || entity.canonical} <span className="text-fg-dim">· full entity profile →</span>
              </Link>
            )}
            {record.url && (
              <a href={record.url} target="_blank" rel="noopener noreferrer" className="mono text-xs text-fg-dim hover:text-fg">
                source ↗
              </a>
            )}
          </div>
        </div>
      </section>

      <div className="mx-auto max-w-[1320px] px-4 py-6 grid lg:grid-cols-3 gap-3">
        {/* Left: the data point itself */}
        <div className="space-y-3">
          <Panel title="Record fields">
            <dl className="divide-y divide-line">
              {record.fields.map((f) => (
                <div key={f.key} className="py-2 grid grid-cols-3 gap-2">
                  <dt className="eyebrow !text-fg-dim col-span-1">{f.label}</dt>
                  <dd className="text-sm text-fg col-span-2 break-words">{f.value}</dd>
                </div>
              ))}
            </dl>
          </Panel>
          {record.raw && Object.keys(record.raw).length > 0 && (
            <Panel title="Raw source data">
              <dl className="divide-y divide-line">
                {Object.entries(record.raw).slice(0, 40).map(([k, v]) => (
                  <div key={k} className="py-1.5 grid grid-cols-3 gap-2">
                    <dt className="mono text-[11px] text-fg-dim col-span-1 break-words">{k}</dt>
                    <dd className="text-xs text-fg col-span-2 break-words">{String(v)}</dd>
                  </div>
                ))}
              </dl>
            </Panel>
          )}
        </div>

        {/* Right: industry lens + the inferred connection graph */}
        <div className="lg:col-span-2 space-y-3">
          {/* What this means for the industry */}
          <Panel
            title={industry ? `Impact on ${industry.name}` : "Industry impact"}
            className="border-l-2 border-l-brass"
            right={<SeverityBadge severity={impact.severity} />}
          >
            <p className="text-[15px] text-fg/90 leading-relaxed">{impact.meaning}</p>
            {impact.regulators.length > 0 && (
              <div className="mt-3 flex flex-wrap items-center gap-1.5">
                <span className="eyebrow !text-fg-dim mr-1">Governed by</span>
                {impact.regulators.map((r) => (
                  <span key={r} className="text-xs text-fg border border-line rounded px-2 py-0.5 bg-panel-2">{r}</span>
                ))}
              </div>
            )}
          </Panel>

          {/* Relevant political players */}
          {players.length > 0 && (
            <Panel title="Relevant political players" right={<Eyebrow>who shapes this</Eyebrow>}>
              <div className="grid sm:grid-cols-2 gap-2">
                {players.map((p, i) => <PlayerCard key={`${p.name}:${i}`} p={p} />)}
              </div>
            </Panel>
          )}

          <Panel
            title="Cross-source connections"
            right={<span className="mono text-xs text-brass">{relations.total.toLocaleString()} linked records</span>}
          >
            {entity.canonical ? (
              <p className="text-sm text-fg-dim">
                Every record below shares the canonical entity{" "}
                <span className="text-fg">{entity.name || entity.canonical}</span>
                {relations.sector && (
                  <>
                    {" "}· sector{" "}
                    <Link href={`/sectors/${relations.sector.slug}`} className="text-brass-bright">
                      {relations.sector.name}
                    </Link>
                  </>
                )}
                . This is the entity graph that connects activity across the entire federal record.
              </p>
            ) : (
              <p className="text-sm text-fg-dim">
                This record has no resolved entity, so cross-source links are limited. Records with a
                company or person resolve into the full connection graph.
              </p>
            )}
          </Panel>

          {/* Related records grouped by source */}
          {relations.by_source.length > 0 && (
            <div className="grid md:grid-cols-2 gap-3">
              {relations.by_source.map((g) => (
                <Panel
                  key={`${g.table}:${g.source}`}
                  title={g.label}
                  right={<span className="mono text-xs text-fg-dim">{g.count.toLocaleString()}</span>}
                >
                  <ul className="space-y-1.5">
                    {g.records.map((r) => <RelRow key={`${r.table}:${r.pk}`} r={r} />)}
                  </ul>
                  {g.partial && (
                    <div className="mono text-[10px] text-fg-dim mt-2">
                      showing top {g.records.length} of {g.count.toLocaleString()}
                    </div>
                  )}
                </Panel>
              ))}
            </div>
          )}

          {/* Sector peers */}
          {relations.sector_peers.length > 0 && (
            <Panel title={`Peers in ${relations.sector?.name ?? "sector"}`}>
              <div className="flex flex-wrap gap-2">
                {relations.sector_peers.map((p) => (
                  <Link
                    key={p.canonical}
                    href={`/entities/${encodeURIComponent(p.canonical)}`}
                    className="text-xs text-fg border border-line rounded px-2 py-1 bg-panel-2 hover:border-brass/60 hover:text-brass-bright transition-colors"
                  >
                    {p.name}
                  </Link>
                ))}
              </div>
            </Panel>
          )}

          {/* Temporal co-occurrence */}
          {relations.timeline.length > 0 && (
            <Panel title="Activity timeline" right={<Eyebrow>temporal co-occurrence</Eyebrow>}>
              <ul className="space-y-1">
                {relations.timeline.map((r, i) => (
                  <RelRow key={`tl:${r.table}:${r.pk}:${i}`} r={r} showSource timeline />
                ))}
              </ul>
            </Panel>
          )}

          {!relations.by_source.length && !relations.timeline.length && (
            <Panel title="Connections"><EmptyState>No linked records found for this data point.</EmptyState></Panel>
          )}
        </div>
      </div>
    </div>
  );
}

function PlayerCard({ p }: { p: PlayerRef }) {
  const inner = (
    <div className="flex items-center gap-2.5 p-2 rounded border border-line bg-panel-2 group-hover:border-brass/40 transition-colors">
      {p.type === "politician" && p.photo_url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={p.photo_url} alt={p.name} className="w-9 h-9 rounded object-cover bg-panel" loading="lazy" />
      ) : (
        <div className="w-9 h-9 rounded bg-panel flex items-center justify-center shrink-0"
             style={{ color: p.type === "regulator" ? "var(--color-fg-dim)" : partyColor(p.party) }}>
          <span className="mono text-[10px] font-bold">{p.type === "regulator" ? "REG" : p.name.split(" ").map((w) => w[0]).slice(0, 2).join("")}</span>
        </div>
      )}
      <div className="min-w-0 flex-1">
        <div className="text-sm text-fg truncate group-hover:text-brass-bright transition-colors">{p.name}</div>
        <div className="mono text-[10px] text-fg-dim truncate">{p.role || p.why}</div>
      </div>
      {p.party && (
        <span className="mono text-[9px] px-1 py-0.5 rounded shrink-0"
              style={{ color: partyColor(p.party), borderColor: partyColor(p.party), border: "1px solid" }}>
          {p.party.slice(0, 4).toUpperCase()}
        </span>
      )}
    </div>
  );
  return p.slug ? (
    <Link href={`/politicians/${p.slug}`} className="group block">{inner}</Link>
  ) : (
    <div className="group">{inner}</div>
  );
}

function RelRow({ r, showSource, timeline }: { r: RecordRef; showSource?: boolean; timeline?: boolean }) {
  const href = recordHref(r.table, r.pk);
  const inner = (
    <div className={`flex items-center gap-2 ${r.current ? "text-brass-bright" : ""}`}>
      {(showSource || timeline) && <SourceTag>{r.source}</SourceTag>}
      <span className="text-sm truncate flex-1 group-hover:text-brass-bright transition-colors">
        {r.current ? "● " : ""}{r.title}
      </span>
      {r.amount != null && <span className="mono text-xs text-brass shrink-0">{money(r.amount)}</span>}
      {r.date && <span className="mono text-[10px] text-fg-dim shrink-0">{r.date}</span>}
    </div>
  );
  return (
    <li>
      {href ? (
        <Link href={href} className="group block hover:bg-panel-2 -mx-1 px-1 py-0.5 rounded">{inner}</Link>
      ) : (
        <div className="px-1 py-0.5">{inner}</div>
      )}
    </li>
  );
}
