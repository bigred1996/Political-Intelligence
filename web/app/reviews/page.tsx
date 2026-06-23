"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  api,
  type ReviewInputs,
  type ReviewsListResponse,
  type ReviewWorkspaceResponse,
  type SectorsResponse,
} from "@/lib/api";
import { EmptyState, PageHeader, Panel, Pill } from "@/components/ui";

/* Goal B4 — Start Diligence. A guided form captures the analyst's framing and a
   DEPTH TIER, then launches exactly ONE B3 research run (the tier is the single
   source of truth that flows form → B3). On submit we create a persistent
   Review and route to its workspace (/reviews/[id]), which READS the stored run
   — it never re-runs the loop. No document uploads. */

const TIERS = [
  { id: "brief", label: "Brief", hint: "1–2 rounds · fastest" },
  { id: "standard", label: "Standard", hint: "3–4 rounds · balanced" },
  { id: "deep", label: "Deep", hint: "5–6 rounds · most thorough" },
] as const;

const STATUS_CHIP: Record<ReviewInputs["status"], string> = {
  researching: "status-chip-amber",
  ready: "status-chip-green",
  failed: "status-chip-red",
};

type Tier = "brief" | "standard" | "deep";

export default function ReviewsPage() {
  const router = useRouter();

  const [company, setCompany] = useState("");
  const [sectors, setSectors] = useState<string[]>([]);
  const [transactionType, setTransactionType] = useState("");
  const [jurisdiction, setJurisdiction] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [keyConcerns, setKeyConcerns] = useState("");
  const [keywords, setKeywords] = useState("");
  const [researchQuestion, setResearchQuestion] = useState("");
  const [tier, setTier] = useState<Tier>("standard");

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [sectorOpts, setSectorOpts] = useState<{ slug: string; name: string }[]>([]);
  const [recent, setRecent] = useState<ReviewInputs[]>([]);

  useEffect(() => {
    api<SectorsResponse>("/api/sectors")
      .then((r) => setSectorOpts(r.sectors.map((s) => ({ slug: s.slug, name: s.name }))))
      .catch(() => setSectorOpts([]));
    api<ReviewsListResponse>("/api/reviews?limit=12")
      .then((r) => setRecent(r.reviews))
      .catch(() => setRecent([]));
  }, []);

  const toggleSector = (slug: string) =>
    setSectors((prev) => (prev.includes(slug) ? prev.filter((s) => s !== slug) : [...prev, slug]));

  const submit = useCallback(() => {
    if (!company.trim() || submitting) return;
    setSubmitting(true);
    setError(null);
    api<ReviewWorkspaceResponse>("/api/reviews", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        company: company.trim(),
        sectors,
        transaction_type: transactionType.trim() || null,
        jurisdiction: jurisdiction.trim() || null,
        date_from: dateFrom.trim() || null,
        date_to: dateTo.trim() || null,
        key_concerns: keyConcerns.trim() || null,
        keywords: keywords.split(",").map((k) => k.trim()).filter(Boolean),
        research_question: researchQuestion.trim() || null,
        depth_tier: tier,
      }),
    })
      .then((r) => router.push(`/reviews/${r.review.id}`))
      .catch((e) => {
        setError(String(e));
        setSubmitting(false);
      });
  }, [company, sectors, transactionType, jurisdiction, dateFrom, dateTo, keyConcerns,
      keywords, researchQuestion, tier, submitting, router]);

  return (
    <div className="animate-rise space-y-gutter">
      <PageHeader
        title="Start Diligence"
        subtitle="Frame a target and launch one deep-research run over internal records. The result opens as a persistent, revisitable workspace — every finding interpreted, cross-synthesized, and linked to its underlying record. No buy/sell conclusions; insufficient evidence is shown as such."
      />

      <Panel title="Target & scope" bodyClass="p-4 space-y-4">
        <Field label="Company / asset" required>
          <input
            value={company}
            onChange={(e) => setCompany(e.target.value)}
            placeholder="e.g. Rogers Communications"
            className={inputCls}
          />
        </Field>

        <Field label="Sector(s)" hint="optional — focuses retrieval and the sector-exposure section">
          <div className="flex flex-wrap gap-2">
            {sectorOpts.length === 0 && <span className="text-[12px] text-on-surface-variant">Loading sectors…</span>}
            {sectorOpts.map((s) => (
              <button
                key={s.slug}
                type="button"
                onClick={() => toggleSector(s.slug)}
                className={chipCls(sectors.includes(s.slug))}
              >
                {s.name}
              </button>
            ))}
          </div>
        </Field>

        <div className="grid sm:grid-cols-2 gap-4">
          <Field label="Transaction type" hint="optional">
            <input value={transactionType} onChange={(e) => setTransactionType(e.target.value)}
              placeholder="acquisition, investment, partnership…" className={inputCls} />
          </Field>
          <Field label="Jurisdiction" hint="optional">
            <input value={jurisdiction} onChange={(e) => setJurisdiction(e.target.value)}
              placeholder="Federal, Ontario…" className={inputCls} />
          </Field>
          <Field label="Date range — from" hint="optional (YYYY)">
            <input value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} placeholder="2020" className={inputCls} />
          </Field>
          <Field label="Date range — to" hint="optional (YYYY)">
            <input value={dateTo} onChange={(e) => setDateTo(e.target.value)} placeholder="2025" className={inputCls} />
          </Field>
        </div>

        <Field label="Key concerns" hint="optional — what the diligence should prioritize">
          <textarea value={keyConcerns} onChange={(e) => setKeyConcerns(e.target.value)} rows={2}
            placeholder="e.g. regulatory exposure, lobbying intensity, foreign-ownership review" className={inputCls} />
        </Field>

        <div className="grid sm:grid-cols-2 gap-4">
          <Field label="Keywords" hint="optional — comma-separated">
            <input value={keywords} onChange={(e) => setKeywords(e.target.value)}
              placeholder="spectrum, merger, CRTC" className={inputCls} />
          </Field>
          <Field label="Specific research question" hint="optional — overrides the seed framing">
            <input value={researchQuestion} onChange={(e) => setResearchQuestion(e.target.value)}
              placeholder="What is the target's federal lobbying footprint?" className={inputCls} />
          </Field>
        </div>

        <Field label="Depth tier" hint="controls the hard per-run cap on rounds and AI calls">
          <div className="flex flex-wrap items-center gap-2">
            {TIERS.map((t) => (
              <button key={t.id} type="button" onClick={() => setTier(t.id)} className={tierCls(tier === t.id)}>
                {t.label} <span className="text-on-surface-variant text-[11px]">· {t.hint}</span>
              </button>
            ))}
          </div>
        </Field>

        {error && <div className="text-[13px] text-on-error-container bg-error-container/20 rounded px-3 py-2">{error}</div>}

        <div className="flex items-center gap-3">
          <button
            onClick={submit}
            disabled={submitting || !company.trim()}
            className="px-4 py-2 bg-primary text-on-primary rounded text-[13px] font-semibold disabled:opacity-50 inline-flex items-center gap-2"
          >
            {submitting && <span className="material-symbols-outlined animate-spin text-[18px]">progress_activity</span>}
            {submitting ? "Researching…" : "Start diligence"}
          </button>
          {submitting && (
            <span className="text-[12px] text-on-surface-variant">
              Planning → retrieving → interpreting → synthesizing. This can take a moment at deeper tiers.
            </span>
          )}
        </div>
      </Panel>

      <Panel title="Recent reviews" bodyClass="p-0">
        {recent.length ? (
          <div className="divide-y divide-outline-variant/40">
            {recent.map((r) => (
              <Link key={r.id} href={`/reviews/${r.id}`}
                className="flex items-center gap-3 p-3 hover:bg-surface-container-high transition-colors focus-ring">
                <span className={`mono text-[10px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded ${STATUS_CHIP[r.status]}`}>
                  {r.status}
                </span>
                <span className="font-body-md text-body-md text-on-surface truncate flex-1">{r.company}</span>
                <Pill>{r.depth_tier}</Pill>
                {r.created_at && (
                  <span className="font-data-tabular text-[11px] text-on-surface-variant">
                    {new Date(r.created_at).toLocaleDateString()}
                  </span>
                )}
              </Link>
            ))}
          </div>
        ) : (
          <EmptyState>No reviews yet. Start one above.</EmptyState>
        )}
      </Panel>
    </div>
  );
}

const inputCls =
  "w-full bg-surface-container-lowest border border-outline-variant rounded px-3 py-2 text-body-md text-on-surface focus-ring";

function chipCls(active: boolean) {
  return `px-2.5 py-1 rounded text-[12px] border transition-colors ${
    active ? "border-primary text-on-surface bg-surface-container-high" : "border-outline-variant text-on-surface-variant hover:border-primary"
  }`;
}

function tierCls(active: boolean) {
  return `px-3 py-1.5 rounded text-[13px] border transition-colors ${
    active ? "border-primary text-on-surface bg-surface-container-high" : "border-outline-variant text-on-surface-variant hover:border-primary"
  }`;
}

function Field({ label, hint, required, children }: {
  label: string; hint?: string; required?: boolean; children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label className="font-label-caps text-label-caps text-on-surface-variant uppercase flex items-center gap-2">
        {label}
        {required && <span className="text-primary">*</span>}
        {hint && <span className="normal-case tracking-normal text-[11px] text-on-surface-variant/70">{hint}</span>}
      </label>
      {children}
    </div>
  );
}
