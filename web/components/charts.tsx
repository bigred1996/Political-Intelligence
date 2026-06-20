import Link from "next/link";
import { recordHref, riskColorVar, type Connection, type Scores } from "@/lib/api";
import { SeverityBadge, SourceTag } from "./ui";

// ── Semicircular risk gauge (dark) ────────────────────────────────────
export function RiskGauge({ score, size = 150 }: { score: number; size?: number }) {
  const r = size / 2 - 12;
  const cx = size / 2;
  const cy = size / 2;
  const circ = Math.PI * r;
  const frac = Math.max(0, Math.min(1, score / 10));
  const color = riskColorVar(score);
  const arc = (start: number, end: number) => {
    const a0 = Math.PI + Math.PI * start;
    const a1 = Math.PI + Math.PI * end;
    return `M ${cx + r * Math.cos(a0)} ${cy + r * Math.sin(a0)} A ${r} ${r} 0 0 1 ${cx + r * Math.cos(a1)} ${cy + r * Math.sin(a1)}`;
  };
  return (
    <svg width={size} height={size / 2 + 26} viewBox={`0 0 ${size} ${size / 2 + 26}`} aria-hidden="true">
      <path d={arc(0, 1)} fill="none" stroke="var(--color-line)" strokeWidth="10" strokeLinecap="round" />
      <path
        d={arc(0, 1)}
        fill="none"
        stroke={color}
        strokeWidth="10"
        strokeLinecap="round"
        strokeDasharray={circ}
        strokeDashoffset={circ * (1 - frac)}
        style={{ transition: "stroke-dashoffset .6s ease" }}
      />
      <text x={cx} y={cy - 2} textAnchor="middle" className="mono" fontSize="32" fontWeight="600" fill="var(--color-fg-bright)">
        {score.toFixed(1)}
      </text>
      <text x={cx} y={cy + 15} textAnchor="middle" className="mono" fontSize="9.5" letterSpacing="1.5" fill="var(--color-fg-dim)">
        / 10
      </text>
    </svg>
  );
}

// ── Four-dimension scorecard (dark) ───────────────────────────────────
const DIMS: { key: keyof Scores; label: string }[] = [
  { key: "regulatory_risk", label: "Regulatory Risk" },
  { key: "policy_volatility", label: "Policy Volatility" },
  { key: "election_sensitivity", label: "Election Sensitivity" },
  { key: "lobbying_intensity", label: "Lobbying Intensity" },
];

export function Scorecard({ scores }: { scores: Scores }) {
  return (
    <div className="space-y-3.5">
      {DIMS.map((d) => {
        const v = scores[d.key] as number;
        return (
          <div key={d.key}>
            <div className="flex items-baseline justify-between mb-1">
              <span className="text-sm text-fg">{d.label}</span>
              <span className="mono text-sm font-semibold" style={{ color: riskColorVar(v) }}>{v.toFixed(1)}</span>
            </div>
            <div className="h-1.5 rounded-full bg-panel-2 overflow-hidden">
              <div className="h-full rounded-full" style={{ width: `${(v / 10) * 100}%`, background: riskColorVar(v), transition: "width .6s ease" }} />
            </div>
            {scores.drivers?.[d.key] && <p className="text-xs text-fg-dim mt-1 leading-snug">{scores.drivers[d.key]}</p>}
          </div>
        );
      })}
    </div>
  );
}

// ── Connection callout (dark) ─────────────────────────────────────────
export function ConnectionCard({ c }: { c: Connection }) {
  const accent = c.severity === "high" ? "var(--color-down)" : c.severity === "elevated" ? "var(--color-warn)" : "var(--color-fg-dim)";
  return (
    <div className="rounded bg-panel-2 border border-line p-3.5 pl-4 relative" style={{ borderLeft: `3px solid ${accent}` }}>
      <div className="flex items-start justify-between gap-3 mb-1">
        <h3 className="text-[15px] font-semibold text-fg-bright leading-snug">{c.title}</h3>
        <SeverityBadge severity={c.severity} />
      </div>
      <p className="text-sm text-fg/85 leading-relaxed">{c.detail}</p>
      <div className="flex flex-wrap gap-1.5 mt-2">
        {c.sources.map((s) => <SourceTag key={s}>{s.replace(/_/g, " ")}</SourceTag>)}
      </div>
      {c.references?.length ? (
        <div className="mt-2 space-y-1 border-t border-line/60 pt-2">
          {c.references.slice(0, 2).map((r) => {
            const href = recordHref(r.table, r.id ?? r.pk);
            return href ? (
              <Link key={`${r.table}:${r.id}`} href={href} className="block mono text-[10px] text-fg-dim hover:text-brass-bright truncate">
                evidence: {r.source} · {r.title}
              </Link>
            ) : null;
          })}
        </div>
      ) : null}
    </div>
  );
}
