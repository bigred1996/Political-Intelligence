"use client";

import Link from "next/link";
import { Suspense, useCallback, useEffect, useState, type ReactNode } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api, money, type SearchHit, type SearchResponse } from "@/lib/api";
import { OriginalSourceLink } from "@/components/ui";
import { recordHref, sourceLabel } from "@/lib/navigation";

/* Ask Nessus — research workspace wired to /api/search. Faithful to
   nessus_research_workspace_ask_nessus, now with live results. */

export default function AskNessusPage() {
  return (
    <Suspense fallback={null}>
      <AskNessus />
    </Suspense>
  );
}

const SUGGESTIONS = [
  "Pipeline incidents involving TransCanada since 2020",
  "$1M+ IT contracts awarded to Telus",
  "Telecom lobbying ahead of the spectrum auction",
  "Who sponsored Bill C-27?",
];

function AskNessus() {
  const router = useRouter();
  const params = useSearchParams();
  const urlQ = params.get("q") ?? "";
  const [input, setInput] = useState(urlQ);
  const [query, setQuery] = useState(urlQ);
  const [data, setData] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback((q: string) => {
    setQuery(q);
    setLoading(true);
    setError(null);
    setData(null);
    api<SearchResponse>(`/api/search?q=${encodeURIComponent(q)}`)
      .then(setData)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (urlQ) run(urlQ);
  }, [urlQ, run]);

  const submit = (q: string) => {
    if (!q.trim()) return;
    setInput(q);
    router.push(`/search?q=${encodeURIComponent(q.trim())}`);
    run(q.trim());
  };

  const sources = data ? Object.entries(data.counts.by_source).sort((a, b) => b[1] - a[1]).slice(0, 6) : [];

  return (
    <div className="animate-rise -m-margin-mobile md:-m-margin-desktop">
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] min-h-[calc(100vh-4rem)]">
        {/* Chat canvas */}
        <div className="flex flex-col bg-surface border-r border-outline-variant relative">
          <div className="flex-1 px-margin-mobile md:px-margin-desktop py-8 space-y-8 overflow-y-auto">
            {!query ? (
              <div className="max-w-2xl mx-auto text-center pt-16">
                <div className="w-12 h-12 rounded-lg bg-primary text-on-primary flex items-center justify-center mx-auto mb-4">
                  <span className="material-symbols-outlined text-[28px]">forum</span>
                </div>
                <h2 className="font-headline-md text-headline-md text-primary mb-2">Ask Nessus</h2>
                <p className="font-body-lg text-body-lg text-on-surface-variant mb-8">Query the intelligence database, synthesize recent legislation, or analyze lobbying activity across every federal source.</p>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-left">
                  {SUGGESTIONS.map((s) => (
                    <button key={s} onClick={() => submit(s)} className="px-4 py-3 bg-surface-container-lowest border border-outline-variant rounded-lg text-body-md text-on-surface hover:border-primary transition-colors text-left">
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <>
                {/* User message */}
                <div className="flex flex-col items-end gap-1">
                  <div className="bg-surface-container-high rounded-lg rounded-tr-sm px-5 py-3 max-w-3xl text-on-surface font-body-md text-body-md leading-relaxed border border-outline-variant/30 shadow-sm">{query}</div>
                </div>

                {/* Response */}
                <div className="flex flex-col items-start gap-3">
                  <div className="flex items-center gap-2 ml-1">
                    <div className="w-6 h-6 rounded-sm bg-primary flex items-center justify-center text-on-primary"><span className="material-symbols-outlined text-[14px]">psychology</span></div>
                    <span className="font-label-caps text-label-caps text-primary tracking-wider uppercase">Nessus Analysis</span>
                  </div>

                  {loading && (
                    <div className="bg-surface-bright border border-outline-variant rounded-lg w-full max-w-4xl p-4 flex items-center gap-3 text-on-surface-variant">
                      <span className="material-symbols-outlined animate-spin">progress_activity</span>
                      <span className="font-data-tabular text-data-tabular">Searching every source…</span>
                    </div>
                  )}

                  {error && <div className="bg-error-container/40 border border-error/20 rounded-lg p-4 text-on-error-container max-w-4xl">{error}</div>}

                  {data && (
                    <div className="bg-surface-container-lowest border border-outline-variant rounded-lg rounded-tl-sm p-6 max-w-4xl shadow-sm text-on-surface space-y-5 w-full">
                      <AnswerMarkdown
                        text={data.answer || `Found ${data.counts.returned} matching records across ${Object.keys(data.counts.by_source).length} sources for "${data.query}".`}
                      />
                      <div className="space-y-3">
                        <h4 className="font-label-caps text-label-caps text-on-surface-variant uppercase border-b border-outline-variant/50 pb-1">Top Evidence</h4>
                        <div className="space-y-2">
                          {data.results.slice(0, 8).map((r, i) => <HitRow key={i} hit={r} query={data.query} />)}
                          {data.results.length === 0 && <p className="font-body-md text-body-md text-on-surface-variant">No records matched. Try a broader query.</p>}
                        </div>
                      </div>
                    </div>
                  )}
                </div>
                <div className="h-8" />
              </>
            )}
          </div>

          {/* Input */}
          <div className="sticky bottom-0 bg-gradient-to-t from-surface via-surface to-transparent pt-10 pb-6 px-margin-mobile md:px-margin-desktop">
            <form
              className="max-w-4xl mx-auto"
              onSubmit={(e) => { e.preventDefault(); submit(input); }}
            >
              <div className="relative bg-surface-container-lowest border border-outline-variant rounded-lg shadow-sm flex items-end p-2 focus-within:border-primary focus-within:ring-1 focus-within:ring-primary transition-all">
                <button type="button" className="p-2 text-on-surface-variant hover:text-primary transition-colors mb-1 rounded-md hover:bg-surface-container-low"><span className="material-symbols-outlined">attach_file</span></button>
                <textarea
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(input); } }}
                  className="w-full bg-transparent border-none focus:ring-0 resize-none max-h-32 min-h-[44px] py-3 px-3 font-body-md text-body-md text-on-surface placeholder:text-on-surface-variant/60 outline-none"
                  placeholder="Ask Nessus about policy, legislation, or intelligence…"
                  rows={1}
                />
                <button type="submit" className="p-2 bg-primary text-on-primary rounded-lg ml-2 hover:bg-primary-container transition-colors mb-1 shadow-sm flex items-center justify-center h-10 w-10"><span className="material-symbols-outlined text-[20px]">arrow_upward</span></button>
              </div>
              <div className="flex justify-between items-center mt-2 px-1">
                <span className="text-[11px] font-label-caps text-on-surface-variant flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-primary" /> Nessus Intelligence Engine</span>
                <span className="text-[11px] font-data-tabular text-on-surface-variant">Shift + Enter for new line</span>
              </div>
            </form>
          </div>
        </div>

        {/* Evidence rail */}
        <aside className="hidden lg:flex flex-col bg-surface-bright border-l border-outline-variant overflow-y-auto">
          <div className="p-4 border-b border-outline-variant/50 flex items-center gap-2">
            <span className="material-symbols-outlined text-on-surface-variant text-lg">info</span>
            <h3 className="font-label-caps text-label-caps text-on-surface-variant uppercase tracking-widest">Context &amp; Evidence</h3>
          </div>
          <div className="p-4 space-y-6">
            <div className="space-y-3">
              <h4 className="font-label-caps text-label-caps text-on-surface-variant">Active Sources</h4>
              <div className="space-y-2">
                {sources.length === 0 && <p className="font-data-tabular text-[12px] text-on-surface-variant">Run a query to see which sources matched.</p>}
                {sources.map(([src, n]) => (
                  <div key={src} className="bg-surface-container-lowest border border-outline-variant rounded p-2.5 flex items-center justify-between">
                    <span className="font-data-tabular text-[13px] font-medium text-on-surface capitalize">{src.replace(/_/g, " ")}</span>
                    <span className="font-data-tabular text-[12px] text-on-surface-variant">{n}</span>
                  </div>
                ))}
              </div>
            </div>
            {data && (
              <div className="space-y-3">
                <h4 className="font-label-caps text-label-caps text-on-surface-variant">Query Plan</h4>
                <div className="bg-surface-container-lowest border border-outline-variant rounded p-2.5 font-data-tabular text-[12px] text-on-surface-variant space-y-1">
                  <div>Planner: <span className="text-on-surface">{data.plan.planner ?? "deterministic"}</span></div>
                  <div>Structured: <span className="text-on-surface">{data.counts.structured}</span> · Semantic: <span className="text-on-surface">{data.counts.semantic}</span></div>
                </div>
              </div>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}

function HitRow({ hit, query }: { hit: SearchHit; query: string }) {
  const href = recordHref(hit.table, hit.pk);
  const internalHref = href ? `${href}?from=search&q=${encodeURIComponent(query)}` : null;
  const readableSource = sourceLabel(hit.table ?? hit.source, hit.source);
  const inner = (
    <div className="flex items-start gap-3 p-2.5 rounded border border-outline-variant/50 bg-surface-container-low hover:bg-surface-container-high transition-colors">
      <span className="material-symbols-outlined text-[18px] text-primary mt-0.5">{hit.match === "both" ? "verified" : "description"}</span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="font-label-caps text-label-caps text-on-surface-variant uppercase">{readableSource}</span>
          {hit.date && <span className="font-data-tabular text-[11px] text-on-surface-variant">{hit.date}</span>}
          {hit.amount ? <span className="font-data-tabular text-[11px] text-primary ml-auto">{money(hit.amount)}</span> : null}
        </div>
        <p className="font-body-md text-body-md text-on-surface leading-snug truncate">{hit.title}</p>
        {hit.snippet && <p className="text-[12px] text-on-surface-variant line-clamp-1">{hit.snippet}</p>}
      </div>
    </div>
  );
  return internalHref ? (
    <div>
      <Link href={internalHref} className="block focus-ring rounded">{inner}</Link>
      {hit.url ? (
        <OriginalSourceLink href={hit.url} source={readableSource} className="ml-8 mt-1 text-[11px] font-data-tabular text-on-surface-variant hover:text-primary" />
      ) : null}
    </div>
  ) : inner;
}

/* Lightweight, dependency-free markdown renderer for the synthesized answer.
   Handles headings, bold, inline code, bullet lists, and pipe tables — enough
   for the Claude-generated due-diligence summaries without pulling in react-markdown. */
function renderInline(text: string, keyBase: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const regex = /\*\*(.+?)\*\*|`([^`]+?)`/g;
  let last = 0;
  let i = 0;
  let m: RegExpExecArray | null;
  while ((m = regex.exec(text)) !== null) {
    if (m.index > last) nodes.push(text.slice(last, m.index));
    if (m[1] !== undefined) {
      nodes.push(<strong key={`${keyBase}-b${i}`} className="font-semibold text-on-surface">{m[1]}</strong>);
    } else if (m[2] !== undefined) {
      nodes.push(<code key={`${keyBase}-c${i}`} className="font-data-tabular text-[0.88em] bg-surface-container px-1 py-0.5 rounded">{m[2]}</code>);
    }
    last = m.index + m[0].length;
    i++;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

function MarkdownTable({ rows, idx }: { rows: string[]; idx: number }) {
  const cells = rows.map((r) => r.replace(/^\s*\|/, "").replace(/\|\s*$/, "").split("|").map((c) => c.trim()));
  const isSep = (r: string[]) => r.every((c) => /^:?-{2,}:?$/.test(c));
  const header = cells[0] ?? [];
  const body = cells.slice(1).filter((r) => !isSep(r));
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left border-collapse font-memo-body text-[0.92em]">
        <thead>
          <tr className="border-b border-outline-variant">
            {header.map((c, ci) => (
              <th key={ci} className="py-1.5 pr-4 font-label-caps text-label-caps uppercase text-on-surface-variant">{renderInline(c, `th${idx}-${ci}`)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {body.map((r, ri) => (
            <tr key={ri} className="border-b border-outline-variant/40">
              {r.map((c, ci) => (
                <td key={ci} className="py-1.5 pr-4 align-top text-on-surface">{renderInline(c, `td${idx}-${ri}-${ci}`)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AnswerMarkdown({ text }: { text: string }) {
  const lines = text.replace(/\r/g, "").split("\n");
  const blocks: ReactNode[] = [];
  let para: string[] = [];
  let list: string[] = [];
  const flushPara = () => {
    if (para.length) {
      const k = blocks.length;
      blocks.push(<p key={`p${k}`} className="font-memo-body text-memo-body leading-relaxed text-on-surface">{renderInline(para.join(" "), `p${k}`)}</p>);
      para = [];
    }
  };
  const flushList = () => {
    if (list.length) {
      const k = blocks.length;
      const items = list;
      blocks.push(
        <ul key={`u${k}`} className="list-disc pl-5 space-y-1 font-memo-body text-memo-body text-on-surface">
          {items.map((li, li2) => <li key={li2}>{renderInline(li, `u${k}-${li2}`)}</li>)}
        </ul>,
      );
      list = [];
    }
  };
  let i = 0;
  while (i < lines.length) {
    const line = lines[i].trim();
    if (!line) { flushPara(); flushList(); i++; continue; }
    if (line.startsWith("|")) {
      flushPara(); flushList();
      const tbl: string[] = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) { tbl.push(lines[i].trim()); i++; }
      blocks.push(<MarkdownTable key={`t${blocks.length}`} rows={tbl} idx={blocks.length} />);
      continue;
    }
    const heading = line.match(/^(#{1,4})\s+(.*)$/);
    if (heading) {
      flushPara(); flushList();
      const level = heading[1].length;
      const content = renderInline(heading[2], `h${blocks.length}`);
      const k = blocks.length;
      blocks.push(
        level <= 2
          ? <h3 key={`h${k}`} className="font-display text-lg font-semibold text-on-surface pt-1">{content}</h3>
          : <h4 key={`h${k}`} className="font-label-caps text-label-caps uppercase tracking-wide text-on-surface-variant pt-1">{content}</h4>,
      );
      i++; continue;
    }
    const bullet = line.match(/^[-*]\s+(.*)$/);
    if (bullet) { flushPara(); list.push(bullet[1]); i++; continue; }
    flushList();
    para.push(line);
    i++;
  }
  flushPara(); flushList();
  return <div className="space-y-3">{blocks}</div>;
}
