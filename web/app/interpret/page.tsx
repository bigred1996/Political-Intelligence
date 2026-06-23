"use client";

import Link from "next/link";
import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api, type InterpretationClaim, type InterpretationResponse } from "@/lib/api";
import { EmptyState, PageHeader, Panel, Pill } from "@/components/ui";

/* Single-finding AI interpretation — Goal B2. Strictly downstream of
   /retrieve: takes a retrieval_set_id + (table, pk) that was already
   retrieved, and shows the structured, citation-checked interpretation of
   that ONE finding. No multi-step research, no report assembly. */

export default function InterpretPage() {
  return (
    <Suspense fallback={null}>
      <Interpret />
    </Suspense>
  );
}

const LABEL_CHIP: Record<InterpretationClaim["label"], string> = {
  observed: "status-chip-green",
  inferred: "status-chip-amber",
  speculative: "status-chip-red",
};

const CONFIDENCE_CHIP: Record<InterpretationResponse["confidence"], string> = {
  high: "status-chip-green",
  medium: "status-chip-amber",
  low: "status-chip-red",
};

function Interpret() {
  const params = useSearchParams();
  const retrievalSetId = params.get("retrieval_set_id") ?? "";
  const table = params.get("table") ?? "";
  const pk = params.get("pk") ?? "";

  const [data, setData] = useState<InterpretationResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback((forceRefresh: boolean) => {
    setLoading(true);
    setError(null);
    api<InterpretationResponse>("/api/interpret", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ retrieval_set_id: retrievalSetId, table, pk, force_refresh: forceRefresh }),
    })
      .then(setData)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [retrievalSetId, table, pk]);

  useEffect(() => {
    if (retrievalSetId && table && pk) run(false);
  }, [retrievalSetId, table, pk, run]);

  if (!retrievalSetId || !table || !pk) {
    return (
      <div className="animate-rise space-y-gutter">
        <PageHeader
          title="Finding Interpretation"
          subtitle="Open this from a result on the Retrieval page — interpretation always starts from a real retrieval set."
        />
        <EmptyState>
          Missing <code>retrieval_set_id</code>, <code>table</code>, or <code>pk</code>. Go to{" "}
          <Link href="/retrieve" className="text-primary underline">Retrieval</Link> and click “Interpret” on a result.
        </EmptyState>
      </div>
    );
  }

  return (
    <div className="animate-rise space-y-gutter">
      <PageHeader
        title="Finding Interpretation"
        subtitle={`AI-assisted analysis of one retrieved record (${table}:${pk}) — every cited record was actually returned by retrieval set ${retrievalSetId}. No buy/sell/proceed/valuation conclusions; recommendations are diligence questions only.`}
        action={
          data && !loading ? (
            <button
              onClick={() => run(true)}
              className="px-3 py-1.5 bg-surface-container-lowest border border-outline-variant rounded text-[13px] text-on-surface-variant hover:border-primary hover:text-on-surface transition-colors"
            >
              Re-run (skip cache)
            </button>
          ) : null
        }
      />

      {loading && (
        <Panel bodyClass="p-4">
          <div className="flex items-center gap-3 text-on-surface-variant">
            <span className="material-symbols-outlined animate-spin">progress_activity</span>
            <span className="font-data-tabular text-data-tabular">Interpreting finding…</span>
          </div>
        </Panel>
      )}

      {error && (
        <Panel bodyClass="p-4">
          <div className="text-on-error-container">{error}</div>
        </Panel>
      )}

      {data && !loading && <InterpretationView data={data} />}
    </div>
  );
}

function InterpretationView({ data }: { data: InterpretationResponse }) {
  return (
    <>
      <Panel title="Status" bodyClass="p-4">
        <div className="flex flex-wrap items-center gap-2">
          <Pill>status: {data.status}</Pill>
          <span className={`mono text-[10px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded ${CONFIDENCE_CHIP[data.confidence]}`}>
            confidence: {data.confidence}
          </span>
          <Pill>{data.generated_by} · {data.model}</Pill>
          <Pill>{data.from_cache ? "from cache" : "freshly generated"}</Pill>
          <Pill>interpretation {data.id}</Pill>
        </div>
        {data.status !== "ok" && data.rejection_reason && (
          <p className="text-[12px] text-on-surface-variant mt-3">
            {data.status === "rejected" ? "Rejected after re-prompt: " : "Degraded: "}
            <span className="font-data-tabular">{data.rejection_reason}</span>
          </p>
        )}
      </Panel>

      <Panel title="Source fact — observed only" bodyClass="p-4">
        <p className="font-body-md text-body-md text-on-surface leading-relaxed">{data.source_fact}</p>
      </Panel>

      <Panel title="Interpretation" bodyClass="p-4">
        <p className="font-body-md text-body-md text-on-surface leading-relaxed">{data.interpretation}</p>
      </Panel>

      <Panel title="Potential impact" bodyClass="p-4">
        <p className="font-body-md text-body-md text-on-surface leading-relaxed">{data.impact}</p>
      </Panel>

      <Panel title="Recommendation" bodyClass="p-4">
        <p className="font-body-md text-body-md text-on-surface leading-relaxed">{data.recommendation}</p>
        <p className="text-[11px] text-on-surface-variant mt-2">Diligence question, monitoring step, or expert-review suggestion only — never a buy/sell/proceed/valuation conclusion.</p>
      </Panel>

      <Panel title="Evidence limitations" bodyClass="p-4">
        <p className="font-body-md text-body-md text-on-surface leading-relaxed">{data.evidence_limitations}</p>
      </Panel>

      <Panel title={`Claims (${data.claims.length})`} bodyClass="p-0">
        <div className="divide-y divide-outline-variant/40">
          {data.claims.map((claim, i) => (
            <div key={i} className="flex items-start gap-3 p-3">
              <span className={`mono text-[10px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded shrink-0 ${LABEL_CHIP[claim.label]}`}>
                {claim.label}
              </span>
              <p className="font-body-md text-body-md text-on-surface leading-snug">{claim.text}</p>
            </div>
          ))}
        </div>
      </Panel>

      <Panel title={`Cited records (${data.cited_records.length})`} bodyClass="p-0">
        <div className="divide-y divide-outline-variant/40">
          {data.cited_records.map((rec) => (
            <CitedRow key={`${rec.table}:${rec.pk}`} table={rec.table} pk={rec.pk} title={rec.title} internalUrl={rec.internal_url} />
          ))}
        </div>
      </Panel>
    </>
  );
}

function CitedRow({ table, pk, title, internalUrl }: { table: string; pk: string | number; title: string; internalUrl: string | null }) {
  const inner = (
    <div className="flex items-center gap-3 p-3 hover:bg-surface-container-high transition-colors">
      <span className="material-symbols-outlined text-[18px] text-primary">fact_check</span>
      <div className="min-w-0 flex-1">
        <span className="font-label-caps text-label-caps text-on-surface-variant uppercase">{table}:{pk}</span>
        <p className="font-body-md text-body-md text-on-surface leading-snug">{title}</p>
      </div>
    </div>
  );
  return internalUrl ? <Link href={internalUrl} className="block focus-ring">{inner}</Link> : inner;
}
