"use client";

import Link from "next/link";
import { use, useMemo, useState } from "react";
import {
  num,
  type EvidenceRef,
  type NewsletterIssue,
  type NewsletterSections,
  type NewsletterStory,
} from "@/lib/api";
import { evidenceHref } from "@/lib/navigation";
import { useApi } from "@/lib/use-api";

export default function NewsletterDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data, loading, error } = useApi<NewsletterIssue>(`/api/newsletters/${id}`);
  const [device, setDevice] = useState<"desktop" | "mobile">("desktop");
  const [copied, setCopied] = useState(false);

  const warnings = useMemo(() => (data ? collectWarnings(data) : []), [data]);

  if (error) {
    return (
      <div className="mx-auto max-w-[1100px] py-16 text-center text-on-surface-variant">
        Couldn&rsquo;t load this newsletter. {error}
        <div className="mt-3"><Link href="/newsletters" className="text-primary underline">All newsletters</Link></div>
      </div>
    );
  }
  if (loading || !data) {
    return (
      <div className="space-y-4">
        <div className="skeleton h-10 w-72" />
        <div className="skeleton h-32 w-full" />
        <div className="skeleton h-[420px] w-full" />
      </div>
    );
  }

  const sections = data.sections ?? {};
  const metrics = data.visuals.metrics ?? {};
  const htmlUrl = `/newsletter/${encodeURIComponent(data.id)}`;
  const wordsInRange = data.word_count >= 900 && data.word_count <= 1200;

  async function copyHtml() {
    try {
      await navigator.clipboard.writeText(data!.html);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="animate-rise">
      <div className="flex flex-wrap justify-between items-start gap-4 mb-gutter">
        <div>
          <Link href="/newsletters" className="font-label-caps text-label-caps text-on-surface-variant uppercase hover:text-primary focus-ring rounded">← Newsletters</Link>
          <h1 className="font-display-lg text-display-lg text-primary mt-2">{data.title}</h1>
          <p className="font-body-lg text-body-lg text-on-surface-variant mt-unit max-w-3xl">
            {formatDate(data.week_start)} - {formatDate(data.week_end)} · {data.model} ·{" "}
            <span className={wordsInRange ? "text-up" : "text-error"}>{num(data.word_count)} words</span>
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={copyHtml}
            className="px-4 py-2.5 border border-outline-variant rounded font-body-md text-body-md font-medium text-on-surface hover:bg-surface-container-low transition-colors flex items-center gap-2 focus-ring"
          >
            <span className="material-symbols-outlined text-[20px]">{copied ? "check" : "content_copy"}</span>
            {copied ? "Copied" : "Copy HTML"}
          </button>
          <a href={htmlUrl} target="_blank" rel="noopener noreferrer" className="px-4 py-2.5 bg-primary text-on-primary rounded font-body-md text-body-md font-medium hover:bg-primary-container transition-colors flex items-center gap-2 focus-ring">
            <span className="material-symbols-outlined text-[20px]">open_in_new</span>
            Open Email HTML
          </a>
        </div>
      </div>

      {/* Subject + preheader (inbox preview) */}
      <div className="card-level-1 rounded-lg p-density-comfortable mb-gutter">
        <div className="font-label-caps text-label-caps text-on-surface-variant uppercase mb-2">Inbox preview</div>
        <div className="font-semibold text-on-surface">{sections.title ?? data.title}</div>
        <div className="text-body-md text-on-surface-variant mt-0.5">{sections.preheader || "No preheader set."}</div>
      </div>

      {warnings.length ? (
        <div className="mb-gutter rounded-lg border border-amber-soft/40 bg-amber-soft/10 px-4 py-3">
          <div className="font-label-caps text-label-caps text-amber-soft uppercase mb-1">Pre-send checks</div>
          <ul className="list-disc pl-5 text-body-md text-on-surface">
            {warnings.map((w) => <li key={w}>{w}</li>)}
          </ul>
        </div>
      ) : null}

      <div className="grid grid-cols-1 md:grid-cols-4 gap-gutter mb-gutter">
        <Metric label="Records" value={num(metrics.records_reviewed ?? 0)} />
        <Metric label="Stories" value={num(metrics.major_developments ?? 0)} />
        <Metric label="Sectors" value={num(metrics.sectors_affected ?? 0)} />
        <Metric label="Top Source" value={metrics.top_source_category ?? "—"} />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_360px] gap-gutter">
        <div className="space-y-gutter">
          <section className="card-level-1 rounded-lg overflow-hidden">
            <div className="px-density-comfortable py-density-comfortable border-b border-outline-variant flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="font-headline-sm text-headline-sm text-primary">Email Preview</h2>
                <p className="text-body-md text-on-surface-variant mt-1">Rendered from the exact saved HTML — preview cannot drift from the export.</p>
              </div>
              <div className="flex rounded border border-outline-variant overflow-hidden shrink-0">
                {(["desktop", "mobile"] as const).map((mode) => (
                  <button
                    key={mode}
                    type="button"
                    onClick={() => setDevice(mode)}
                    className={`px-3 py-1.5 text-body-md flex items-center gap-1.5 transition-colors focus-ring ${device === mode ? "bg-primary text-on-primary" : "text-on-surface-variant hover:bg-surface-container-low"}`}
                  >
                    <span className="material-symbols-outlined text-[18px]">{mode === "desktop" ? "desktop_windows" : "smartphone"}</span>
                    {mode === "desktop" ? "Desktop" : "Mobile"}
                  </button>
                ))}
              </div>
            </div>
            <div className="bg-surface-container-high flex justify-center p-3">
              <iframe
                title="Newsletter HTML preview"
                srcDoc={data.html}
                className="bg-white border border-outline-variant transition-[width] duration-200"
                style={{ width: device === "mobile" ? 390 : "100%", height: 820 }}
              />
            </div>
          </section>

          {sections.lead_story ? (
            <section className="card-level-1 rounded-lg p-density-comfortable">
              <h2 className="font-headline-sm text-headline-sm text-primary mb-3">Lead Story</h2>
              <StoryBlock story={sections.lead_story} />
            </section>
          ) : null}

          {sections.supporting_stories?.length ? (
            <section className="card-level-1 rounded-lg p-density-comfortable">
              <h2 className="font-headline-sm text-headline-sm text-primary mb-3">Supporting Stories</h2>
              <div className="space-y-3">
                {sections.supporting_stories.map((story, index) => (
                  <div key={`${story.headline}-${index}`} className="rounded border border-outline-variant bg-surface-container-low p-4">
                    <StoryBlock story={story} compact />
                  </div>
                ))}
              </div>
            </section>
          ) : null}

          {sections.radar_items?.length ? (
            <section className="card-level-1 rounded-lg p-density-comfortable">
              <h2 className="font-headline-sm text-headline-sm text-primary mb-3">On the Radar</h2>
              <ul className="space-y-2.5">
                {sections.radar_items.map((item, index) => (
                  <li key={`${item.headline}-${index}`} className="rounded border border-outline-variant bg-surface-container-low px-3 py-2.5">
                    <div className="font-medium text-on-surface">{item.headline}</div>
                    <div className="text-body-md text-on-surface-variant mt-0.5">{item.summary}</div>
                    {item.next_milestone ? <div className="text-[12px] text-primary mt-1">Next: {item.next_milestone}</div> : null}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </div>

        <aside className="space-y-gutter">
          <section className="card-level-1 rounded-lg p-density-comfortable">
            <h2 className="font-headline-sm text-headline-sm text-primary mb-3">Validation</h2>
            <div className={`rounded border px-3 py-2 text-body-md ${data.validation.ok ? "border-up/30 bg-up/10 text-up" : "border-error/30 bg-error/10 text-error"}`}>
              {data.validation.ok ? "Passed citation and word-count checks" : "Validation warnings present"}
            </div>
            {data.validation.errors?.length ? (
              <ul className="mt-3 list-disc pl-5 text-body-md text-error">
                {data.validation.errors.map((item) => <li key={item}>{item}</li>)}
              </ul>
            ) : null}
          </section>

          {sections.key_points?.length ? (
            <section className="card-level-1 rounded-lg p-density-comfortable">
              <h2 className="font-headline-sm text-headline-sm text-primary mb-3">What Matters Today</h2>
              <ul className="space-y-2">
                {sections.key_points.map((point, index) => (
                  <li key={index} className="text-body-md">
                    <span className="font-semibold text-on-surface">{point.development}</span>
                    <span className="text-on-surface-variant"> — {point.significance}</span>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          {sections.statistics?.length ? (
            <section className="card-level-1 rounded-lg p-density-comfortable">
              <h2 className="font-headline-sm text-headline-sm text-primary mb-3">By the Numbers</h2>
              <div className="space-y-3">
                {sections.statistics.map((stat, index) => (
                  <div key={index} className="flex gap-3">
                    <div className="font-display-lg text-headline-sm text-brass leading-none shrink-0 mono">{stat.value}</div>
                    <div>
                      <div className="font-label-caps text-label-caps text-on-surface-variant uppercase">{stat.label}</div>
                      <div className="text-body-md text-on-surface mt-0.5">{stat.significance}</div>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          ) : null}

          <section className="card-level-1 rounded-lg p-density-comfortable">
            <h2 className="font-headline-sm text-headline-sm text-primary mb-3">Source Mix</h2>
            <Bars rows={(data.visuals.source_mix ?? []).map((row) => ({ label: row.category, value: row.count }))} color="var(--color-brass)" />
          </section>

          <section className="card-level-1 rounded-lg p-density-comfortable">
            <h2 className="font-headline-sm text-headline-sm text-primary mb-3">Cited Sources</h2>
            <div className="space-y-2">
              {data.source_references.map((sourceRef) => <SourceRow key={`${sourceRef.table}:${sourceRef.pk ?? sourceRef.id}`} sourceRef={sourceRef} />)}
            </div>
          </section>
        </aside>
      </div>
    </div>
  );
}

function StoryBlock({ story, compact = false }: { story: NewsletterStory; compact?: boolean }) {
  return (
    <div>
      {story.eyebrow ? <div className="font-label-caps text-label-caps text-brass uppercase mb-1">{story.eyebrow}</div> : null}
      <div className={`font-semibold text-primary ${compact ? "" : "text-[18px]"}`}>{story.headline}</div>
      {story.standfirst ? <p className="text-body-md text-on-surface-variant mt-1">{story.standfirst}</p> : null}
      <div className="mt-2 space-y-2">
        {story.sections.map((section, index) => (
          <p key={index} className="text-body-md text-on-surface">
            {section.label ? <span className="font-semibold text-on-surface">{section.label}: </span> : null}
            {section.body}
          </p>
        ))}
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="card-level-1 rounded-lg p-density-comfortable">
      <div className="font-label-caps text-label-caps text-on-surface-variant uppercase">{label}</div>
      <div className="font-display-lg text-headline-sm text-primary mt-2 leading-tight">{value}</div>
    </div>
  );
}

function Bars({ rows, color = "var(--color-primary)" }: { rows: { label: string; value: number }[]; color?: string }) {
  const max = Math.max(1, ...rows.map((row) => row.value));
  return (
    <div className="space-y-2">
      {rows.map((row) => (
        <div key={row.label}>
          <div className="flex items-center justify-between gap-2 text-[12px] mb-1">
            <span className="truncate text-on-surface">{row.label}</span>
            <span className="mono text-on-surface-variant">{row.value}</span>
          </div>
          <div className="h-2 rounded-full bg-surface-container-high overflow-hidden">
            <div className="h-full rounded-full" style={{ width: `${Math.max(4, (row.value / max) * 100)}%`, background: color }} />
          </div>
        </div>
      ))}
    </div>
  );
}

function SourceRow({ sourceRef }: { sourceRef: EvidenceRef }) {
  const href = evidenceHref(sourceRef);
  const body = (
    <div className="rounded border border-outline-variant bg-surface-container-low px-3 py-2 hover:bg-surface-container-high">
      <div className="text-body-md text-primary leading-snug">{sourceRef.title}</div>
      <div className="mono text-[10px] text-on-surface-variant mt-1">{sourceRef.source} · {sourceRef.date ?? "undated"}</div>
    </div>
  );
  return href ? <Link href={href} className="block focus-ring rounded">{body}</Link> : body;
}

function collectWarnings(data: NewsletterIssue): string[] {
  const warnings: string[] = [];
  const sections: NewsletterSections = data.sections ?? {};
  if (data.word_count < 900 || data.word_count > 1200) {
    warnings.push(`Visible word count (${data.word_count}) is outside the 900–1,200 range.`);
  }
  if (!sections.lead_story?.citations?.length) warnings.push("Lead story has no cited source.");
  (sections.supporting_stories ?? []).forEach((story, index) => {
    if (!story.citations?.length) warnings.push(`Supporting story ${index + 1} has no cited source.`);
  });
  if (!data.source_references?.length) warnings.push("No source references resolved for this issue.");
  if (!data.html?.includes("nessus-horizontal")) warnings.push("Masthead logo is missing from the rendered HTML.");
  return warnings;
}

function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-CA", { month: "short", day: "numeric", year: "numeric" }).format(date);
}
