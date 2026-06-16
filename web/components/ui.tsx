import Link from "next/link";
import { riskBand } from "@/lib/api";

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
  title,
  right,
  children,
  className = "",
  bodyClass = "p-4",
}: {
  title?: React.ReactNode;
  right?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  bodyClass?: string;
}) {
  return (
    <section className={`panel ${className}`}>
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

export function SourceTag({ children }: { children: React.ReactNode }) {
  return (
    <span className="mono inline-block text-[10px] uppercase tracking-wide text-fg-dim border border-line rounded px-1.5 py-0.5 bg-panel-2">
      {children}
    </span>
  );
}

export function Pill({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-block text-xs text-fg border border-line rounded px-2 py-0.5 bg-panel-2">
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

export function EmptyState({ children }: { children: React.ReactNode }) {
  return <div className="text-sm text-fg-dim text-center py-6">{children}</div>;
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
      ? "bg-brass text-canvas hover:bg-brass-bright"
      : "border border-line text-fg hover:bg-panel-2";
  return <Link href={href} className={`${base} ${cls}`}>{children}</Link>;
}

export function SkeletonBlock({ className = "" }: { className?: string }) {
  return <div className={`skeleton ${className}`} />;
}
