"use client";

import Link from "next/link";
import { Suspense, useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api, money, type RetrievalHit, type RetrievalResponse } from "@/lib/api";
import { EmptyState, PageHeader, Panel, Pill } from "@/components/ui";

/* Internal-records retrieval — Goal B1. Deliberately NOT "Ask Nessus": no
   synthesis, no AI prose, no answer field. Shows exactly what was retrieved,
   grouped by record type, each linking to its real Nessus page, plus the
   retrieval_set_id any later citation must be checked against. */

export default function RetrievalPage() {
  return (
    <Suspense fallback={null}>
      <Retrieval />
    </Suspense>
  );
}

const SUGGESTIONS = [
  "Industry and Technology committee telecom",
  "TELUS lobbying communications",
  "Bills sponsored on critical minerals",
  "Acme Corp report",
];

function humanizeType(recordType: string): string {
  return recordType
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function Retrieval() {
  const router = useRouter();
  const params = useSearchParams();
  const urlQ = params.get("q") ?? "";
  const [input, setInput] = useState(urlQ);
  const [query, setQuery] = useState(urlQ);
  const [data, setData] = useState<RetrievalResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback((q: string) => {
    setQuery(q);
    setLoading(true);
    setError(null);
    setData(null);
    api<RetrievalResponse>(`/api/retrieve?q=${encodeURIComponent(q)}`)
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
    router.push(`/retrieve?q=${encodeURIComponent(q.trim())}`);
    run(q.trim());
  };

  const typeEntries = data ? Object.entries(data.by_type).sort((a, b) => b[1].length - a[1].length) : [];

  return (
    <div className="animate-rise space-y-gutter">
      <PageHeader
        title="Internal Records Retrieval"
        subtitle="Natural-language query in, every internal record actually retrieved out — grouped by type, each linking to its real Nessus page. No synthesis, no AI prose: this is the transparent retrieval layer downstream interpretation has to cite against."
      />

      <Panel bodyClass="p-4">
        <form
          onSubmit={(e) => { e.preventDefault(); submit(input); }}
          className="flex items-center gap-2"
        >
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Search every internal record…"
            className="flex-1 bg-surface-container-lowest border border-outline-variant rounded-lg px-4 py-2.5 font-body-md text-body-md text-on-surface placeholder:text-on-surface-variant/60 outline-none focus:border-primary"
          />
          <button
            type="submit"
            className="px-4 py-2.5 bg-primary text-on-primary rounded-lg font-body-md text-body-md font-medium hover:bg-primary-container transition-colors"
          >
            Retrieve
          </button>
        </form>
        {!query && (
          <div className="flex flex-wrap gap-2 mt-3">
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                onClick={() => submit(s)}
                className="px-3 py-1.5 bg-surface-container-lowest border border-outline-variant rounded text-[13px] text-on-surface-variant hover:border-primary hover:text-on-surface transition-colors"
              >
                {s}
              </button>
            ))}
          </div>
        )}
      </Panel>

      {loading && (
        <Panel bodyClass="p-4">
          <div className="flex items-center gap-3 text-on-surface-variant">
            <span className="material-symbols-outlined animate-spin">progress_activity</span>
            <span className="font-data-tabular text-data-tabular">Retrieving internal records…</span>
          </div>
        </Panel>
      )}

      {error && (
        <Panel bodyClass="p-4">
          <div className="text-on-error-container">{error}</div>
        </Panel>
      )}

      {data && (
        <>
          <Panel title="Retrieval coverage" bodyClass="p-4">
            <div className="flex flex-wrap items-center gap-2">
              <Pill>{data.counts.returned} returned</Pill>
              <Pill>{data.counts.structured} structured match(es)</Pill>
              <Pill>{data.counts.semantic} semantic match(es)</Pill>
              <Pill>{data.counts.deterministic} catalog match(es)</Pill>
              <Pill>retrieval set {data.retrieval_set_id}</Pill>
              <Pill>{data.embedding_model}</Pill>
            </div>
          </Panel>

          {data.empty ? (
            <EmptyState>No internal records matched this query. Try a broader or differently-worded search.</EmptyState>
          ) : (
            typeEntries.map(([recordType, hits]) => (
              <Panel key={recordType} title={`${humanizeType(recordType)} (${hits.length})`} bodyClass="p-0">
                <div className="divide-y divide-outline-variant/40">
                  {hits.map((hit) => <HitRow key={hit.id} hit={hit} retrievalSetId={data.retrieval_set_id} />)}
                </div>
              </Panel>
            ))
          )}
        </>
      )}
    </div>
  );
}

// Pseudo-table hits (politicians, sectors, entities, organizations,
// committees, reports) aren't evidentiary records the interpretation layer's
// record loader can resolve — only offer "Interpret" for real source tables.
const NON_EVIDENTIARY_TABLES = new Set(["politicians", "sectors", "entities", "organizations", "committees", "reports"]);

function HitRow({ hit, retrievalSetId }: { hit: RetrievalHit; retrievalSetId: string }) {
  const inner = (
    <div className="flex items-start gap-3 p-3 hover:bg-surface-container-high transition-colors">
      <span className="material-symbols-outlined text-[18px] text-primary mt-0.5">
        {hit.match === "both" ? "verified" : hit.match === "deterministic" ? "fact_check" : "description"}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-label-caps text-label-caps text-on-surface-variant uppercase">{hit.source}</span>
          {hit.date && <span className="font-data-tabular text-[11px] text-on-surface-variant">{hit.date}</span>}
          <span className="font-data-tabular text-[11px] text-on-surface-variant">score {hit.score.toFixed(2)}</span>
          {hit.amount ? <span className="font-data-tabular text-[11px] text-primary ml-auto">{money(hit.amount)}</span> : null}
        </div>
        <p className="font-body-md text-body-md text-on-surface leading-snug">{hit.title}</p>
        {hit.snippet && <p className="text-[12px] text-on-surface-variant line-clamp-2">{hit.snippet}</p>}
      </div>
    </div>
  );
  return (
    <div className="flex items-center">
      <div className="flex-1 min-w-0">
        {hit.internal_url ? <Link href={hit.internal_url} className="block focus-ring">{inner}</Link> : inner}
      </div>
      {!NON_EVIDENTIARY_TABLES.has(hit.table) && (
        <Link
          href={`/interpret?retrieval_set_id=${encodeURIComponent(retrievalSetId)}&table=${encodeURIComponent(hit.table)}&pk=${encodeURIComponent(String(hit.pk))}`}
          className="shrink-0 mr-3 px-2.5 py-1.5 bg-surface-container-lowest border border-outline-variant rounded text-[12px] text-on-surface-variant hover:border-primary hover:text-on-surface transition-colors"
        >
          Interpret
        </Link>
      )}
    </div>
  );
}
