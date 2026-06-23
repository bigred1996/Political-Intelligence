"use client";

import Link from "next/link";
import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  api,
  type ResearchRunResponse,
  type ResearchRound,
  type SynthesisItem,
} from "@/lib/api";
import { EmptyState, PageHeader, Panel, Pill } from "@/components/ui";

/* Multi-step research loop — Goal B3. Built on /retrieve (B1) + /interpret
   (B2): plans gap-driven queries, retrieves, interprets each evidentiary
   finding, loops under a hard per-tier round/interpretation cap, then
   synthesizes across findings. No memo formatting (that is B6); every
   synthesized claim drills down to its supporting findings → internal
   records. */

export default function ResearchPage() {
  return (
    <Suspense fallback={null}>
      <Research />
    </Suspense>
  );
}

const STATUS_CHIP: Record<ResearchRunResponse["status"], string> = {
  running: "status-chip-amber",
  complete: "status-chip-green",
  insufficient_evidence: "status-chip-amber",
  degraded: "status-chip-amber",
  error: "status-chip-red",
};

const LABEL_CHIP: Record<SynthesisItem["label"], string> = {
  observed: "status-chip-green",
  inferred: "status-chip-amber",
  speculative: "status-chip-red",
};

const TIERS = [
  { id: "brief", label: "Brief", hint: "1–2 rounds" },
  { id: "standard", label: "Standard", hint: "3–4 rounds" },
  { id: "deep", label: "Deep", hint: "5–6 rounds" },
] as const;

function Research() {
  const params = useSearchParams();
  const existingId = params.get("id") ?? "";

  const [topic, setTopic] = useState("");
  const [tier, setTier] = useState<"brief" | "standard" | "deep">("standard");
  const [data, setData] = useState<ResearchRunResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadExisting = useCallback((id: string) => {
    setLoading(true);
    setError(null);
    api<ResearchRunResponse>(`/api/research/${id}`)
      .then(setData)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (existingId) loadExisting(existingId);
  }, [existingId, loadExisting]);

  const start = useCallback(() => {
    if (!topic.trim()) return;
    setLoading(true);
    setError(null);
    setData(null);
    api<ResearchRunResponse>("/api/research", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ topic: topic.trim(), depth_tier: tier }),
    })
      .then(setData)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [topic, tier]);

  return (
    <div className="animate-rise space-y-gutter">
      <PageHeader
        title="Deep Research"
        subtitle="Multi-step research over internal records: plan → retrieve → interpret → find gaps → synthesize across findings. Hard per-tier caps on rounds and AI calls. Every claim cites only records actually retrieved; no buy/sell/proceed/valuation conclusions."
      />

      <Panel title="New research run" bodyClass="p-4 space-y-3">
        <input
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && start()}
          placeholder="Research topic — e.g. “Rogers regulatory and lobbying exposure”"
          className="w-full bg-surface-container-lowest border border-outline-variant rounded px-3 py-2 text-body-md text-on-surface focus-ring"
        />
        <div className="flex flex-wrap items-center gap-2">
          {TIERS.map((t) => (
            <button
              key={t.id}
              onClick={() => setTier(t.id)}
              className={`px-3 py-1.5 rounded text-[13px] border transition-colors ${
                tier === t.id
                  ? "border-primary text-on-surface bg-surface-container-high"
                  : "border-outline-variant text-on-surface-variant hover:border-primary"
              }`}
            >
              {t.label} <span className="text-on-surface-variant text-[11px]">· {t.hint}</span>
            </button>
          ))}
          <button
            onClick={start}
            disabled={loading || !topic.trim()}
            className="ml-auto px-4 py-1.5 bg-primary text-on-primary rounded text-[13px] font-semibold disabled:opacity-50"
          >
            Run research
          </button>
        </div>
      </Panel>

      {loading && (
        <Panel bodyClass="p-4">
          <div className="flex items-center gap-3 text-on-surface-variant">
            <span className="material-symbols-outlined animate-spin">progress_activity</span>
            <span className="font-data-tabular text-data-tabular">Running research loop — planning, retrieving, interpreting…</span>
          </div>
        </Panel>
      )}

      {error && (
        <Panel bodyClass="p-4">
          <div className="text-on-error-container">{error}</div>
        </Panel>
      )}

      {data && !loading && <RunView data={data} />}

      {!data && !loading && !error && (
        <EmptyState>Enter a topic and pick a depth tier to start a research run.</EmptyState>
      )}
    </div>
  );
}

function RunView({ data }: { data: ResearchRunResponse }) {
  const s = data.synthesis;
  return (
    <>
      <Panel title="Run" bodyClass="p-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className={`mono text-[10px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded ${STATUS_CHIP[data.status]}`}>
            {data.status.replace(/_/g, " ")}
          </span>
          <Pill>tier: {data.depth_tier}</Pill>
          <Pill>rounds {data.rounds_used} / {data.max_rounds}</Pill>
          <Pill>interpretations {data.interpretations_used} / {data.max_interpretations}</Pill>
          <Pill>model calls {data.model_call_count}</Pill>
          <Pill>{data.provider} · {data.model}</Pill>
          <Pill>run {data.id}</Pill>
        </div>
        <p className="font-body-md text-body-md text-on-surface leading-relaxed mt-3">{data.topic}</p>
      </Panel>

      <Panel title="Coverage summary" bodyClass="p-4">
        <div className="flex items-center gap-2 mb-2">
          <span className={`mono text-[10px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded ${LABEL_CHIP[s.overall_confidence === "high" ? "observed" : s.overall_confidence === "medium" ? "inferred" : "speculative"]}`}>
            confidence: {s.overall_confidence}
          </span>
          <Pill>synthesis: {s.generated_by}</Pill>
        </div>
        <p className="font-body-md text-body-md text-on-surface leading-relaxed">{s.coverage_summary}</p>
      </Panel>

      {s.themes.length > 0 && (
        <Panel title={`Themes (${s.themes.length})`} bodyClass="p-0">
          <div className="divide-y divide-outline-variant/40">
            {s.themes.map((t, i) => <ItemRow key={i} item={t} heading={t.title} />)}
          </div>
        </Panel>
      )}

      <Panel title={`Material risks (${s.material_risks.length})`} bodyClass="p-0">
        {s.material_risks.length ? (
          <div className="divide-y divide-outline-variant/40">
            {s.material_risks.map((r, i) => <ItemRow key={i} item={r} />)}
          </div>
        ) : <p className="p-4 text-[12px] text-on-surface-variant">No material risks surfaced.</p>}
      </Panel>

      <Panel title={`Opportunities (${s.opportunities.length})`} bodyClass="p-0">
        {s.opportunities.length ? (
          <div className="divide-y divide-outline-variant/40">
            {s.opportunities.map((o, i) => <ItemRow key={i} item={o} />)}
          </div>
        ) : <p className="p-4 text-[12px] text-on-surface-variant">No opportunities surfaced.</p>}
      </Panel>

      {s.diligence_questions.length > 0 && (
        <Panel title={`Recommended diligence questions (${s.diligence_questions.length})`} bodyClass="p-4">
          <ul className="list-disc pl-5 space-y-1">
            {s.diligence_questions.map((q, i) => (
              <li key={i} className="font-body-md text-body-md text-on-surface leading-snug">{q}</li>
            ))}
          </ul>
        </Panel>
      )}

      <Panel title={`Evidence trail — ${data.rounds.length} round(s)`} bodyClass="p-0">
        <div className="divide-y divide-outline-variant/40">
          {data.rounds.map((rd) => <RoundRow key={rd.round} round={rd} />)}
        </div>
      </Panel>
    </>
  );
}

function ItemRow({ item, heading }: { item: SynthesisItem; heading?: string }) {
  return (
    <div className="p-3 space-y-2">
      <div className="flex items-start gap-3">
        <span className={`mono text-[10px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded shrink-0 ${LABEL_CHIP[item.label]}`}>
          {item.label}
        </span>
        <div className="min-w-0">
          {heading && <p className="font-label-caps text-label-caps text-on-surface-variant uppercase">{heading}</p>}
          <p className="font-body-md text-body-md text-on-surface leading-snug">{item.text}</p>
        </div>
      </div>
      {item.findings.length > 0 && (
        <div className="flex flex-wrap gap-1.5 pl-9">
          {item.findings.map((f) => (
            f.internal_url ? (
              <Link
                key={`${f.table}:${f.pk}`}
                href={f.internal_url}
                className="text-[11px] px-1.5 py-0.5 rounded border border-outline-variant text-on-surface-variant hover:border-primary hover:text-on-surface transition-colors focus-ring"
                title={f.title}
              >
                {f.table}:{f.pk}
              </Link>
            ) : (
              <span key={`${f.table}:${f.pk}`} className="text-[11px] px-1.5 py-0.5 rounded border border-outline-variant text-on-surface-variant">
                {f.table}:{f.pk}
              </span>
            )
          ))}
        </div>
      )}
    </div>
  );
}

function RoundRow({ round }: { round: ResearchRound }) {
  return (
    <div className="p-3 space-y-2">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="font-label-caps text-label-caps text-on-surface-variant uppercase">round {round.round}</span>
        {round.queries.map((q, i) => <Pill key={i}>{q}</Pill>)}
        <span className="font-data-tabular text-[11px] text-on-surface-variant ml-auto">
          {round.interpretations.length} interpreted · {round.coverage_gaps.length} gap(s)
        </span>
      </div>
      {round.interpretations.length > 0 && (
        <div className="space-y-1 pl-2">
          {round.interpretations.map((it) => (
            <Link
              key={it.id}
              href={`/interpret?retrieval_set_id=${it.retrieval_set_id}&table=${it.table}&pk=${it.pk}`}
              className="flex items-start gap-2 text-[12px] hover:bg-surface-container-high rounded p-1 transition-colors focus-ring"
            >
              <span className="material-symbols-outlined text-[16px] text-primary mt-0.5">fact_check</span>
              <span className="min-w-0">
                <span className="font-label-caps text-label-caps text-on-surface-variant uppercase">{it.table}:{it.pk}</span>{" "}
                <span className="text-on-surface">{it.source_fact}</span>
              </span>
            </Link>
          ))}
        </div>
      )}
      {round.coverage_gaps.length > 0 && (
        <div className="flex flex-wrap gap-1.5 pl-2">
          {round.coverage_gaps.map((g, i) => (
            <span key={i} className="text-[11px] px-1.5 py-0.5 rounded status-chip-amber" title={g.title || ""}>
              {g.type.replace(/_/g, " ")}{g.table ? ` · ${g.table}:${g.pk}` : ""}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
