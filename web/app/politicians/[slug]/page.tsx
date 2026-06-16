"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useApi } from "@/lib/use-api";
import { partyColor, recordHref, type PoliticianDetail } from "@/lib/api";
import { Eyebrow, EmptyState, Panel, SkeletonBlock } from "@/components/ui";

export default function PoliticianPage() {
  const params = useParams<{ slug: string }>();
  const slug = params?.slug;
  const { data, loading, error } = useApi<PoliticianDetail>(slug ? `/api/politicians/${slug}` : null);

  if (loading) {
    return (
      <div className="mx-auto max-w-[1320px] px-4 py-6 grid lg:grid-cols-3 gap-3">
        <SkeletonBlock className="h-96 rounded" />
        <SkeletonBlock className="h-96 rounded lg:col-span-2" />
      </div>
    );
  }
  if (error || !data) {
    return (
      <div className="mx-auto max-w-[1320px] px-4 py-10">
        <p className="text-fg-dim">Politician not found. {error}</p>
        <Link href="/politicians" className="text-brass-bright text-sm mt-2 inline-block">← All political players</Link>
      </div>
    );
  }

  const color = partyColor(data.party);

  return (
    <div className="mx-auto max-w-[1320px] px-4 py-6">
      <Link href="/politicians" className="mono text-xs text-fg-dim hover:text-fg">← Political players</Link>
      <div className="grid lg:grid-cols-3 gap-3 mt-3">
        {/* Left: identity card */}
        <div className="space-y-3">
          <div className="panel overflow-hidden">
            <div className="aspect-[3/3.2] bg-panel-2 relative">
              {data.photo_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={data.photo_url} alt={data.name} className="w-full h-full object-cover object-top" />
              ) : (
                <div className="w-full h-full flex items-center justify-center text-fg-dim mono text-4xl">
                  {data.name.split(" ").map((w) => w[0]).slice(0, 2).join("")}
                </div>
              )}
              <span className="absolute top-0 left-0 w-1.5 h-full" style={{ background: color }} />
            </div>
            <div className="p-4">
              <h1 className="text-xl font-semibold text-fg-bright leading-tight">{data.name}</h1>
              <div className="mono text-xs mt-1 font-semibold" style={{ color }}>{data.party || "Independent"}</div>
              <dl className="mt-3 space-y-2 text-sm">
                <Row label="Role" value={data.role} />
                <Row label="Riding" value={data.riding} />
                <Row label="Province" value={data.province} />
                <Row label="In office since" value={data.since_date} />
                <Row label="Email" value={data.email} />
              </dl>
              <div className="mt-3 flex flex-wrap gap-2">
                {data.commons_url && <Ext href={data.commons_url}>ourcommons.ca ↗</Ext>}
                {data.openparliament_url && <Ext href={data.openparliament_url}>openparliament ↗</Ext>}
              </div>
            </div>
          </div>
        </div>

        {/* Right: summary, industries, activity */}
        <div className="lg:col-span-2 space-y-3">
          <Panel title="Summary" className="border-l-2 border-l-brass">
            <p className="text-[15px] text-fg/90 leading-relaxed">{data.summary}</p>
          </Panel>

          <Panel title="Industries they touch" right={<Eyebrow>sector lens</Eyebrow>}>
            {data.industries.length ? (
              <div className="flex flex-wrap gap-2">
                {data.industries.map((s) => (
                  <Link key={s.slug} href={`/sectors/${s.slug}`}
                    className="text-sm text-fg border border-line rounded px-2.5 py-1 bg-panel-2 hover:border-brass/60 hover:text-brass-bright transition-colors">
                    {s.name}
                  </Link>
                ))}
              </div>
            ) : (
              <EmptyState>No tracked-sector activity recorded yet (grows as Hansard & bills ingest).</EmptyState>
            )}
          </Panel>

          <div className="grid md:grid-cols-2 gap-3">
            <Panel title="Sponsored bills" right={<span className="mono text-xs text-fg-dim">{data.bills.length}</span>}>
              {data.bills.length ? (
                <ul className="space-y-1.5">
                  {data.bills.map((b) => (
                    <li key={b.pk}>
                      <Link href={recordHref(b.table, b.pk) || "#"} className="group block hover:bg-panel-2 -mx-1 px-1 py-0.5 rounded">
                        <span className="mono text-xs text-brass">{b.bill_number}</span>{" "}
                        <span className="text-sm text-fg group-hover:text-brass-bright">{b.title}</span>
                        {b.status && <span className="mono text-[10px] text-fg-dim block">{b.status}</span>}
                      </Link>
                    </li>
                  ))}
                </ul>
              ) : <EmptyState>None on record.</EmptyState>}
            </Panel>

            <Panel title="House interventions" right={<span className="mono text-xs text-fg-dim">{data.speeches.length}</span>}>
              {data.speeches.length ? (
                <ul className="space-y-2">
                  {data.speeches.map((s, i) => (
                    <li key={i} className="border-b border-line pb-2 last:border-0">
                      <div className="flex items-center gap-2">
                        <span className="mono text-[10px] text-brass">{s.keyword}</span>
                        {s.date && <span className="mono text-[10px] text-fg-dim">{s.date}</span>}
                      </div>
                      {s.excerpt && <p className="text-xs text-fg-dim mt-1 leading-snug line-clamp-3">{s.excerpt}</p>}
                    </li>
                  ))}
                </ul>
              ) : <EmptyState>None on record.</EmptyState>}
            </Panel>
          </div>
        </div>
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string | null }) {
  if (!value) return null;
  return (
    <div className="grid grid-cols-3 gap-2">
      <dt className="eyebrow !text-fg-dim col-span-1">{label}</dt>
      <dd className="text-sm text-fg col-span-2 break-words">{value}</dd>
    </div>
  );
}

function Ext({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noopener noreferrer"
      className="mono text-[10px] text-fg-dim border border-line rounded px-2 py-1 hover:text-fg hover:border-brass/40 transition-colors">
      {children}
    </a>
  );
}
