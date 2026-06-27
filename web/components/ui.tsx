import Link from "next/link";
import { num, recordHref, riskBand, type EvidenceRef, type IntelligenceFinding, type SourceCoverageItem } from "@/lib/api";
import { sourceHref } from "@/lib/navigation";

export function Eyebrow({ children, num }: { children: React.ReactNode; num?: string }) {
  return (
    <div className="eyebrow flex items-center gap-2">
      {num && <span className="text-brass/60">{num}</span>}
      <span>{children}</span>
    </div>
  );
}

/* Terminal panel — thin-bordered module with an optional header bar. */
export function Panel({
  id,
  title,
  right,
  children,
  className = "",
  bodyClass = "p-4",
}: {
  id?: string;
  title?: React.ReactNode;
  right?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  bodyClass?: string;
}) {
  return (
    <section id={id} className={`panel ${className}`}>
      {title && (
        <div className="panel-head">
          <span className="eyebrow !text-fg-dim flex-1 truncate">{title}</span>
          {right}
        </div>
      )}
      <div className={bodyClass}>{children}</div>
    </section>
  );
}

/* Page-level greeting header (h1) — pages own their title now that the
   topbar is just search + actions. Matches the Dashboard greeting scale. */
export function PageHeader({ title, subtitle, action }: { title: React.ReactNode; subtitle?: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3 mb-gutter">
      <div className="min-w-0">
        <h1 className="font-display-lg text-headline-md md:text-display-lg text-primary leading-tight">{title}</h1>
        {subtitle ? <p className="font-body-lg text-body-lg text-on-surface-variant mt-unit max-w-2xl">{subtitle}</p> : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}

export function SectionHeader({
  title,
  subtitle,
  action,
}: {
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-4 mb-4">
      <div className="min-w-0">
        <h2 className="font-headline-sm text-[18px] font-semibold text-primary leading-tight">{title}</h2>
        {subtitle ? <p className="text-body-md text-on-surface-variant mt-1 leading-snug">{subtitle}</p> : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}

// Back-compat simple bordered box (maps to panel surface).
export function Card({
  children,
  className = "",
  as: Tag = "div",
}: {
  children: React.ReactNode;
  className?: string;
  as?: React.ElementType;
}) {
  return <Tag className={`panel ${className}`}>{children}</Tag>;
}

export function SectionTitle({ children, sub }: { children: React.ReactNode; sub?: string }) {
  return (
    <div className="mb-3">
      <h2 className="text-lg font-semibold text-fg-bright">{children}</h2>
      {sub && <p className="text-sm text-fg-dim mt-0.5">{sub}</p>}
    </div>
  );
}

const SEVERITY: Record<string, { label: string; cls: string }> = {
  high: { label: "High", cls: "bg-down/15 text-down border-down/40" },
  elevated: { label: "Elevated", cls: "bg-warn/15 text-warn border-warn/40" },
  watch: { label: "Watch", cls: "bg-fg-dim/15 text-fg-dim border-fg-dim/30" },
};

export function SeverityBadge({ severity }: { severity: string }) {
  const s = SEVERITY[severity] ?? SEVERITY.watch;
  return (
    <span className={`mono text-[10px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded border ${s.cls}`}>
      {s.label}
    </span>
  );
}

export function RiskBadge({ score }: { score: number }) {
  const band = riskBand(score);
  const color = band === "high" ? "var(--color-risk-high)" : band === "medium" ? "var(--color-risk-med)" : "var(--color-risk-low)";
  return (
    <span
      className="mono inline-flex items-baseline gap-0.5 px-1.5 py-0.5 rounded border text-sm font-semibold"
      style={{ color, borderColor: `color-mix(in srgb, ${color} 40%, transparent)`, background: `color-mix(in srgb, ${color} 12%, transparent)` }}
    >
      {score.toFixed(1)}<span className="text-[9px] opacity-70">/10</span>
    </span>
  );
}

const RISK_BANDS: Record<string, { label: string; color: string }> = {
  high: { label: "High", color: "var(--color-risk-high)" },
  elevated: { label: "Elevated", color: "var(--color-risk-med)" },
  moderate: { label: "Moderate", color: "var(--color-warn)" },
  low: { label: "Low", color: "var(--color-risk-low)" },
  unknown: { label: "Unknown", color: "var(--color-fg-dim)" },
  "insufficient evidence": { label: "Insufficient", color: "var(--color-fg-dim)" },
};

export function RiskBandBadge({ band }: { band: string }) {
  const item = RISK_BANDS[band] ?? RISK_BANDS.unknown;
  return (
    <span
      className="mono inline-flex items-center px-1.5 py-0.5 rounded border text-[10px] font-semibold uppercase tracking-wide"
      style={{ color: item.color, borderColor: `color-mix(in srgb, ${item.color} 42%, transparent)`, background: `color-mix(in srgb, ${item.color} 12%, transparent)` }}
    >
      {item.label}
    </span>
  );
}

const CONFIDENCE: Record<string, { label: string; cls: string }> = {
  high: { label: "High", cls: "bg-up/10 text-up border-up/30" },
  medium: { label: "Medium", cls: "bg-warn/10 text-warn border-warn/30" },
  low: { label: "Low", cls: "bg-down/10 text-down border-down/30" },
};

export function ConfidenceBadge({ value }: { value: string }) {
  const c = CONFIDENCE[value] ?? CONFIDENCE.low;
  return <span className={`mono text-[9px] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded border ${c.cls}`}>{c.label} confidence</span>;
}

export function InterpretationBadge({ value }: { value: string }) {
  return <span className="mono text-[9px] uppercase tracking-wide px-1.5 py-0.5 rounded border border-line text-fg-dim bg-panel-2">{value || "observed"}</span>;
}

export function SourceTag({ children }: { children: React.ReactNode }) {
  return (
    <span className="mono inline-block text-[10px] uppercase tracking-wide text-on-surface-variant rounded px-1.5 py-0.5 bg-surface-container-high">
      {children}
    </span>
  );
}

export function OriginalSourceLink({
  href,
  label = "View original source",
  source,
  className = "",
}: {
  href: string;
  label?: string;
  source?: string | null;
  className?: string;
}) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className={`inline-flex items-center gap-1.5 text-primary hover:underline focus-ring rounded ${className}`}
    >
      <span className="material-symbols-outlined text-[16px]" aria-hidden="true">open_in_new</span>
      <span>{label}{source ? ` - ${source}` : ""}</span>
    </a>
  );
}

const COVERAGE: Record<string, { label: string; cls: string }> = {
  live: { label: "Live", cls: "bg-up/15 text-up border-up/40" },
  partial: { label: "Partial", cls: "bg-warn/15 text-warn border-warn/40" },
  stale: { label: "Stale", cls: "bg-warn/10 text-warn border-warn/30" },
  empty: { label: "Empty", cls: "bg-fg-dim/10 text-fg-dim border-line" },
  failed: { label: "Failed", cls: "bg-down/10 text-down border-down/30" },
  approximate: { label: "Approx.", cls: "bg-brass/10 text-brass border-brass/30" },
  planned: { label: "Planned", cls: "bg-panel-2 text-fg-dim border-line" },
};

export function CoverageBadge({ status }: { status: string }) {
  const c = COVERAGE[status] ?? COVERAGE.empty;
  return (
    <span className={`mono text-[9px] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded border ${c.cls}`}>
      {c.label}
    </span>
  );
}

export function SourceCoverageList({ items, limit = 8 }: { items: SourceCoverageItem[]; limit?: number }) {
  const shown = items.slice(0, limit);
  return (
    <div className="space-y-1.5">
      {shown.map((s) => {
        const href = sourceHref(s.id);
        const body = (
          <div className="flex items-center justify-between gap-2 text-[12px] rounded px-1 py-1 hover:bg-panel-2 focus-ring">
            <div className="min-w-0">
              <div className="text-fg truncate">{s.label}</div>
              <div className="mono text-[10px] text-fg-dim">{num(s.rows)} rows{s.approximate ? " approx." : ""}</div>
            </div>
            <CoverageBadge status={s.status} />
          </div>
        );
        return href ? <Link key={s.id} href={href} className="block">{body}</Link> : <div key={s.id}>{body}</div>;
      })}
    </div>
  );
}

export function MetricCard({
  label,
  value,
  change,
  tone = "neutral",
  href,
  spark,
}: {
  label: string;
  value: React.ReactNode;
  change?: string;
  tone?: "neutral" | "up" | "down" | "warn";
  href?: string;
  spark?: number[];
}) {
  const toneColor = tone === "up" ? "var(--color-up)" : tone === "down" ? "var(--color-down)" : tone === "warn" ? "var(--color-warn)" : "var(--color-brass)";
  const body = (
    <div className="panel card-level-2 p-4 min-h-[104px]">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="font-label-caps text-label-caps uppercase text-on-surface-variant truncate">{label}</div>
          <div className="text-[30px] leading-none font-bold text-on-surface tracking-[-0.02em] mt-3">{value}</div>
          {change ? <div className="mono text-[11px] mt-2.5" style={{ color: toneColor }}>{change}</div> : null}
        </div>
        {spark?.length ? <Sparkline data={spark} color={toneColor} /> : null}
      </div>
    </div>
  );
  return href ? <Link href={href} className="block focus-ring rounded-lg">{body}</Link> : body;
}

export function Sparkline({ data, color = "var(--color-brass)" }: { data: number[]; color?: string }) {
  const w = 86, h = 38;
  const max = Math.max(...data, 1);
  const min = Math.min(...data, 0);
  const range = Math.max(1, max - min);
  const points = data.map((v, i) => `${(i / Math.max(1, data.length - 1)) * w},${h - ((v - min) / range) * (h - 4) - 2}`).join(" ");
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden="true" className="shrink-0">
      <polyline points={points} fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function ChartFrame({ title, subtitle, right, children }: { title: string; subtitle?: string; right?: React.ReactNode; children: React.ReactNode }) {
  return (
    <Panel bodyClass="p-4">
      <SectionHeader title={title} subtitle={subtitle} action={right} />
      {children}
    </Panel>
  );
}

export function EvidenceRows({
  refs,
  limit = 3,
  hrefFor,
}: {
  refs: EvidenceRef[];
  limit?: number;
  hrefFor?: (ref: EvidenceRef) => string | null;
}) {
  const linked = refs
    .flatMap((r) => {
      const href = hrefFor ? hrefFor(r) : recordHref(r.table, r.id ?? r.pk);
      return href ? [{ ...r, href }] : [];
    })
    .slice(0, limit);
  if (!linked.length) return <div className="text-[12px] text-fg-dim">No linked evidence.</div>;
  return (
    <div className="space-y-1.5">
      {linked.map((r) => (
        <Link key={`${r.table}:${r.id ?? r.pk}`} href={r.href} className="group flex items-center gap-2 min-w-0 rounded px-1 py-1 hover:bg-panel-2 focus-ring">
          <SourceTag>{r.source}</SourceTag>
          <span className="text-[12px] text-fg-dim group-hover:text-brass-bright truncate">{r.title}</span>
          {r.date ? <span className="mono text-[10px] text-fg-dim ml-auto shrink-0">{r.date}</span> : null}
        </Link>
      ))}
    </div>
  );
}

export function FindingCard({ finding, href }: { finding: IntelligenceFinding; href?: string }) {
  const evidence = finding.related_records ?? [];
  return (
    <article className="signal-card card-level-2 p-4 h-full">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap gap-1.5 mb-2">
            <RiskBandBadge band={finding.risk_level} />
            <ConfidenceBadge value={finding.confidence} />
            <InterpretationBadge value={finding.interpretation_type} />
          </div>
          <h3 className="text-[14px] font-semibold text-fg-bright leading-snug">{finding.title}</h3>
        </div>
        <span className="mono text-[10px] text-fg-dim shrink-0">{finding.evidence_references?.length ?? evidence.length} evidence</span>
      </div>
      <p className="text-[13px] text-fg/85 leading-snug mt-2 line-clamp-2">{finding.concise_summary}</p>
      <div className="grid grid-cols-2 gap-2 mt-3 text-[11px]">
        <div><span className="text-fg-dim">Sector</span><div className="font-medium text-fg-bright truncate">{finding.primary_sector?.name ?? "Cross-sector"}</div></div>
        <div><span className="text-fg-dim">Signal</span><div className="font-medium text-fg-bright truncate capitalize">{finding.signal_type}</div></div>
        <div><span className="text-fg-dim">Direction</span><div className="font-medium text-fg-bright capitalize">{finding.risk_direction}</div></div>
        <div><span className="text-fg-dim">Recency</span><div className="font-medium text-fg-bright capitalize">{finding.recency}</div></div>
      </div>
      <div className="mt-3 pt-3 border-t border-line">
        <div className="flex items-center justify-between gap-2">
          <span className="text-[12px] text-fg-dim">Next action</span>
          {href ? (
            <Link href={href} className="mono text-[10px] text-brass-bright hover:underline focus-ring rounded">
              Open related view
            </Link>
          ) : (
            <span className="mono text-[10px] text-brass-bright">Review evidence</span>
          )}
        </div>
        {evidence.length ? (
          <details className="mt-2 group">
            <summary className="mono text-[10px] text-fg-dim cursor-pointer hover:text-brass-bright focus-ring rounded">
              Evidence details
            </summary>
            <div className="mt-2">
              <EvidenceRows refs={evidence} limit={4} />
            </div>
          </details>
        ) : null}
      </div>
    </article>
  );
}

export function TimelineItem({ title, meta, href }: { title: string; meta?: string; href?: string | null }) {
  const body = (
    <div className="relative pl-5 py-2">
      <span className="absolute left-0 top-3 w-2 h-2 rounded-full bg-brass" />
      <div className="text-[13px] text-fg-bright leading-snug">{title}</div>
      {meta ? <div className="mono text-[10px] text-fg-dim mt-1 uppercase">{meta}</div> : null}
    </div>
  );
  return href ? <Link href={href} className="block hover:bg-panel-2 rounded px-1 focus-ring">{body}</Link> : body;
}

export function EmptyState({ children, icon = "inbox" }: { children: React.ReactNode; icon?: string }) {
  return (
    <div className="flex flex-col items-center gap-2 text-center py-8 px-4 rounded-lg border border-dashed border-outline-variant bg-surface-container-low/60">
      <span className="material-symbols-outlined text-[22px] text-outline" aria-hidden="true">{icon}</span>
      <p className="text-body-sm text-on-surface-variant max-w-sm">{children}</p>
    </div>
  );
}

export function Pill({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-block font-body-sm text-body-sm text-on-surface-variant rounded px-2 py-0.5 bg-surface-container-high">
      {children}
    </span>
  );
}

export function Stat({ label, value, accent, tone }: { label: string; value: React.ReactNode; accent?: boolean; tone?: string }) {
  return (
    <div>
      <div className="eyebrow !text-fg-dim mb-1">{label}</div>
      <div className="mono text-2xl font-semibold leading-none" style={tone ? { color: tone } : undefined}>
        <span className={!tone ? (accent ? "text-brass-bright" : "text-fg-bright") : ""}>{value}</span>
      </div>
    </div>
  );
}


export function LinkButton({
  href,
  children,
  variant = "primary",
}: {
  href: string;
  children: React.ReactNode;
  variant?: "primary" | "ghost";
}) {
  const base = "inline-flex items-center gap-1.5 rounded px-4 py-2 text-sm font-semibold transition-colors duration-200 cursor-pointer";
  const cls =
    variant === "primary"
      ? "bg-brass text-white hover:bg-brass-bright"
      : "bg-panel text-fg hover:bg-panel-2";
  return <Link href={href} className={`${base} ${cls}`}>{children}</Link>;
}

export function SkeletonBlock({ className = "" }: { className?: string }) {
  return <div className={`skeleton ${className}`} />;
}
