"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { api, money, recordHref, type SearchResponse } from "@/lib/api";
import { Eyebrow, Panel, SkeletonBlock, SourceTag } from "@/components/ui";

export default function SearchPage() {
  return (
    <Suspense fallback={null}>
      <SearchView />
    </Suspense>
  );
}

function SearchView() {
  const params = useSearchParams();
  const router = useRouter();
  const q = params.get("q") ?? "";
  const [input, setInput] = useState(q);
  const [data, setData] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => setInput(q), [q]);
  useEffect(() => {
    if (!q) { setData(null); return; }
    let alive = true;
    setLoading(true); setError(null);
    api<SearchResponse>(`/api/search?answer=true&limit=40&q=${encodeURIComponent(q)}`)
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(String(e)))
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, [q]);

  const EXAMPLES = [
    "federal contracts over $1 million for IT services",
    "pipeline incidents involving TransCanada",
    "lobbying on telecommunications",
    "pollutant releases by facilities in Alberta",
  ];

  return (
    <div>
      <section className="bg-panel border-b border-line map-grid">
        <div className="mx-auto max-w-[1320px] px-4 py-10">
          <Eyebrow>Ask Polaris</Eyebrow>
          <h1 className="text-2xl md:text-3xl font-semibold text-fg-bright mt-2 max-w-2xl leading-tight">
            Query the entire federal record.
          </h1>
          <p className="text-fg-dim mt-2 max-w-xl text-sm">
            A planner turns plain English into filters, then fuses exact matches across every source
            with semantic search. <span className="text-brass-bright">★ both</span> = matched both ways.
          </p>
          <form
            onSubmit={(e) => { e.preventDefault(); if (input.trim()) router.push(`/search?q=${encodeURIComponent(input.trim())}`); }}
            className="mt-6 flex flex-col sm:flex-row gap-2.5 max-w-2xl"
          >
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              aria-label="Search query"
              placeholder="e.g. pipeline incidents in Alberta since 2020"
              className="flex-1 bg-canvas border border-line rounded px-4 py-3 text-fg placeholder:text-fg-dim outline-none focus:border-brass/60 transition-colors mono text-sm"
            />
            <button type="submit" className="rounded bg-brass text-canvas font-semibold px-6 py-3 hover:bg-brass-bright transition-colors cursor-pointer">Search</button>
          </form>
          {!q && (
            <div className="flex flex-wrap gap-2 mt-4">
              {EXAMPLES.map((ex) => (
                <button key={ex} onClick={() => router.push(`/search?q=${encodeURIComponent(ex)}`)} className="mono text-xs border border-line text-fg-dim rounded px-3 py-1.5 hover:border-brass/60 hover:text-fg transition-colors cursor-pointer">
                  {ex}
                </button>
              ))}
            </div>
          )}
        </div>
      </section>

      <div className="mx-auto max-w-[1320px] px-4 py-6">
        {error && <p className="text-fg-dim">Search failed. {error}</p>}
        {loading && (
          <div className="space-y-2.5 max-w-3xl">
            <SkeletonBlock className="h-20 rounded" />
            {Array.from({ length: 5 }).map((_, i) => <SkeletonBlock key={i} className="h-12 rounded" />)}
          </div>
        )}

        {!loading && data && (
          <div className="grid lg:grid-cols-3 gap-3">
            <div className="lg:col-span-2 space-y-3">
              {data.answer && (
                <Panel title="Synthesis" className="border-l-2 border-l-brass">
                  <p className="text-[15px] text-fg/90 leading-relaxed whitespace-pre-wrap">{data.answer}</p>
                </Panel>
              )}
              <div className="mono text-xs text-fg-dim">
                {data.counts.returned} results · {data.counts.structured} exact, {data.counts.semantic} semantic
                {data.plan?.planner ? ` · planner: ${data.plan.planner}` : ""}
              </div>
              <div className="space-y-2">
                {data.results.map((h, i) => {
                  const href = recordHref(h.table, h.pk);
                  return (
                  <div key={i} className="panel p-3 hover:border-brass/40 transition-colors">
                    <div className="flex items-center gap-2 mb-1">
                      <SourceTag>{h.source}</SourceTag>
                      {h.match === "both" && <span className="mono text-[10px] text-brass-bright font-semibold">★ BOTH</span>}
                      {h.match === "semantic" && <span className="mono text-[10px] text-fg-dim">SEMANTIC</span>}
                      {h.date && <span className="mono text-[10px] text-fg-dim ml-auto">{h.date}</span>}
                    </div>
                    {href ? (
                      <Link href={href} className="text-sm text-fg hover:text-brass-bright font-medium">{h.title}</Link>
                    ) : (
                      <span className="text-sm text-fg font-medium">{h.title}</span>
                    )}
                    {h.snippet && <p className="text-xs text-fg-dim mt-1 leading-snug">{h.snippet}</p>}
                    <div className="flex items-center gap-3 mt-1">
                      {h.amount ? <span className="mono text-xs text-brass">{money(h.amount)}</span> : null}
                      {href && <Link href={href} className="mono text-[10px] text-fg-dim hover:text-brass-bright">view connections →</Link>}
                      {h.url && <a href={h.url} target="_blank" rel="noopener noreferrer" className="mono text-[10px] text-fg-dim hover:text-fg">source ↗</a>}
                    </div>
                  </div>
                  );
                })}
                {!data.results.length && <p className="text-sm text-fg-dim">No matching records.</p>}
              </div>
            </div>
            <aside>
              <Panel title="Results by source">
                <ul className="space-y-1.5 text-sm">
                  {Object.entries(data.counts.by_source || {}).sort((a, b) => b[1] - a[1]).map(([src, n]) => (
                    <li key={src} className="flex justify-between">
                      <span className="text-fg">{src}</span>
                      <span className="mono text-fg-dim">{n}</span>
                    </li>
                  ))}
                </ul>
              </Panel>
            </aside>
          </div>
        )}
      </div>
    </div>
  );
}
