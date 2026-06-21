"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";
import type { MovementWindow } from "@/lib/api";

/* ── Reusable dashboard primitives ────────────────────────────────────────
   Built for the home Intelligence Dashboard but deliberately generic so the
   sector / entity pages can adopt them. Nothing here fabricates history:
   movement is rendered honestly from the API's `status` field, and the
   micro-bars draw a *current distribution*, never an invented time-series. */

export type Tone = "neutral" | "up" | "down" | "warn" | "info";

const TONE_VAR: Record<Tone, string> = {
  neutral: "var(--color-primary)",
  up: "var(--color-up)",
  down: "var(--color-down)",
  warn: "var(--color-warn)",
  info: "var(--color-info)",
};

// ── Filter select — accessible labelled dropdown ──────────────────────────
export function FilterSelect({
  label,
  value,
  onChange,
  options,
  icon,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
  icon?: string;
}) {
  const id = `filter-${label.toLowerCase().replace(/\s+/g, "-")}`;
  return (
    <div className="flex items-center gap-2">
      <label htmlFor={id} className="font-label-caps text-label-caps text-on-surface-variant uppercase shrink-0">
        {label}
      </label>
      <div className="relative">
        {icon ? (
          <span className="material-symbols-outlined text-[16px] text-on-surface-variant absolute left-2 top-1/2 -translate-y-1/2 pointer-events-none">
            {icon}
          </span>
        ) : null}
        <select
          id={id}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className={`control appearance-none pr-7 py-1.5 font-body-md text-body-md text-on-surface cursor-pointer hover:border-primary transition-colors ${icon ? "pl-7" : "pl-2.5"}`}
        >
          {options.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
        <span className="material-symbols-outlined text-[18px] text-on-surface-variant absolute right-1.5 top-1/2 -translate-y-1/2 pointer-events-none">
          expand_more
        </span>
      </div>
    </div>
  );
}

// ── Segmented control — e.g. movement window 7/30/90 ──────────────────────
export function Segmented<T extends string | number>({
  value,
  onChange,
  options,
  ariaLabel,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string }[];
  ariaLabel: string;
}) {
  return (
    <div role="radiogroup" aria-label={ariaLabel} className="inline-flex rounded border border-outline-variant bg-surface-container-low p-0.5">
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={String(o.value)}
            role="radio"
            aria-checked={active}
            onClick={() => onChange(o.value)}
            className={`font-data-tabular text-data-tabular px-2.5 py-1 rounded-sm transition-colors cursor-pointer focus-ring ${
              active ? "bg-primary text-on-primary font-bold" : "text-on-surface-variant hover:text-primary"
            }`}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

// ── Movement pips — honest 7/30/90 status row ─────────────────────────────
const DIRECTION_GLYPH: Record<string, string> = {
  increasing: "north_east",
  decreasing: "south_east",
  stable: "east",
  unclear: "remove",
};

export function MovementPips({ windows, active }: { windows: MovementWindow[]; active?: 7 | 30 | 90 }) {
  if (!windows?.length) {
    return <span className="font-data-tabular text-[11px] text-on-surface-variant">No movement data</span>;
  }
  return (
    <div className="flex items-center gap-1.5" role="group" aria-label="7, 30 and 90 day movement">
      {windows.map((w) => {
        const insufficient = w.status === "insufficient_history";
        const tone =
          w.direction === "increasing" ? "var(--color-down)" :
          w.direction === "decreasing" ? "var(--color-up)" :
          "var(--color-on-surface-variant)";
        const isActive = w.window_days === active;
        return (
          <span
            key={w.window_days}
            title={`${w.window_days}d: ${insufficient ? "insufficient history" : w.direction}${w.note ? ` — ${w.note}` : ""}`}
            className={`inline-flex items-center gap-0.5 rounded px-1 py-0.5 font-data-tabular text-[10px] ${isActive ? "ring-1 ring-primary/40" : ""}`}
            style={{ background: isActive ? "color-mix(in srgb, var(--color-primary) 8%, transparent)" : "transparent" }}
          >
            <span className="text-on-surface-variant">{w.window_days}d</span>
            {insufficient ? (
              <span className="material-symbols-outlined text-[13px] text-on-surface-variant/60" aria-label="insufficient history">remove</span>
            ) : (
              <span className="material-symbols-outlined text-[13px]" style={{ color: tone }}>{DIRECTION_GLYPH[w.direction] ?? "remove"}</span>
            )}
          </span>
        );
      })}
    </div>
  );
}

// ── Micro-bars — a CURRENT distribution (not a trend). Honest by design ────
export function MicroBars({ data, color = "var(--color-primary)", height = 26 }: { data: number[]; color?: string; height?: number }) {
  if (!data.length) return null;
  const max = Math.max(...data, 1);
  return (
    <div className="flex items-end gap-[2px]" style={{ height }} aria-hidden="true">
      {data.slice(0, 12).map((v, i) => (
        <span
          key={i}
          className="w-[3px] rounded-sm"
          style={{ height: `${Math.max(8, (v / max) * 100)}%`, background: color, opacity: 0.35 + 0.65 * (v / max) }}
        />
      ))}
    </div>
  );
}

// ── Metric tile — clickable KPI with optional distribution micro-bars ──────
export function MetricTile({
  label,
  value,
  sub,
  tone = "neutral",
  icon,
  href,
  bars,
  caution,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: Tone;
  icon?: string;
  href: string;
  bars?: number[];
  caution?: string;
}) {
  // Status colour only for genuine alerts (down/warn); everything else reads as ink.
  const valueColor = tone === "down" || tone === "warn" ? TONE_VAR[tone] : "var(--color-fg-bright)";
  return (
    <Link
      href={href}
      className="card-level-1 card-level-2 rounded-lg p-4 flex flex-col justify-between min-h-[112px] focus-ring group"
    >
      <div className="flex items-start justify-between gap-2">
        <span className="font-label-caps text-label-caps text-on-surface-variant uppercase leading-tight">{label}</span>
        {icon ? (
          <span className="material-symbols-outlined text-[18px] text-on-surface-variant group-hover:text-primary transition-colors">{icon}</span>
        ) : null}
      </div>
      <div className="flex items-end justify-between gap-2 mt-2">
        <div className="min-w-0">
          <div className="mono text-[28px] font-bold leading-none tracking-tight" style={{ color: valueColor }}>{value}</div>
          {sub ? <div className="font-data-tabular text-data-tabular text-on-surface-variant mt-1.5 truncate">{sub}</div> : null}
        </div>
        {bars?.length ? <MicroBars data={bars} color="var(--color-on-surface-variant)" /> : null}
      </div>
      {caution ? (
        <div className="flex items-center gap-1 mt-2 font-data-tabular text-[11px] text-warn">
          <span className="material-symbols-outlined text-[13px]">info</span>{caution}
        </div>
      ) : null}
    </Link>
  );
}

// ── Connection chain — readable A → B → C of clickable record nodes ────────
export interface ChainNode {
  label: string;
  sub?: string;
  href?: string | null;
  kind?: "actor" | "regulatory" | "lobbying" | "sector" | "record";
}

export function ConnectionChain({ nodes }: { nodes: ChainNode[] }) {
  return (
    <div className="flex items-stretch gap-1.5 flex-wrap">
      {nodes.map((n, i) => {
        const isSector = n.kind === "sector";
        const inner = (
          <span className="flex flex-col items-start rounded border border-outline-variant bg-surface-container-lowest px-2.5 py-1.5 hover:border-primary transition-colors min-w-0 max-w-[180px]">
            {n.sub ? (
              <span className={`font-label-caps text-[9px] uppercase tracking-wide ${isSector ? "text-primary" : "text-on-surface-variant"}`}>{n.sub}</span>
            ) : null}
            <span className="font-body-md text-[13px] text-primary leading-tight truncate w-full">{n.label}</span>
          </span>
        );
        return (
          <div key={i} className="flex items-center gap-1.5 min-w-0">
            {n.href ? (
              <Link href={n.href} className="focus-ring rounded min-w-0">{inner}</Link>
            ) : inner}
            {i < nodes.length - 1 ? (
              <span className="material-symbols-outlined text-[18px] text-on-surface-variant shrink-0">arrow_forward</span>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

// ── Watch star — localStorage-backed sector pinning (prototype behaviour) ──
const WATCH_KEY = "nessus.watchlist.sectors";

export function useWatchlist(): {
  watched: string[];
  toggle: (slug: string) => void;
  isWatched: (slug: string) => boolean;
  ready: boolean;
} {
  const [watched, setWatched] = useState<string[]>([]);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(WATCH_KEY);
      if (raw) setWatched(JSON.parse(raw));
    } catch {
      /* ignore — prototype-only persistence */
    }
    setReady(true);
  }, []);

  const persist = useCallback((next: string[]) => {
    setWatched(next);
    try {
      localStorage.setItem(WATCH_KEY, JSON.stringify(next));
    } catch {
      /* ignore */
    }
  }, []);

  const toggle = useCallback((slug: string) => {
    persist(watched.includes(slug) ? watched.filter((s) => s !== slug) : [...watched, slug]);
  }, [watched, persist]);

  const isWatched = useCallback((slug: string) => watched.includes(slug), [watched]);

  return { watched, toggle, isWatched, ready };
}

export function WatchStar({ active, onToggle, label }: { active: boolean; onToggle: () => void; label: string }) {
  return (
    <button
      onClick={(e) => { e.preventDefault(); e.stopPropagation(); onToggle(); }}
      aria-pressed={active}
      aria-label={active ? `Remove ${label} from watchlist` : `Add ${label} to watchlist`}
      title={active ? "Remove from watchlist" : "Add to watchlist"}
      className="shrink-0 p-1 rounded hover:bg-surface-container-high transition-colors cursor-pointer focus-ring"
    >
      <span
        className="material-symbols-outlined text-[18px]"
        style={{ color: active ? "var(--color-warn)" : "var(--color-on-surface-variant)", fontVariationSettings: active ? "'FILL' 1" : "'FILL' 0" }}
      >
        star
      </span>
    </button>
  );
}

// ── Confidence / coverage micro-labels (light theme variants) ─────────────
export function ConfidenceDot({ value }: { value: string }) {
  const v = (value || "").toLowerCase();
  const color = v === "high" ? "var(--color-up)" : v === "medium" ? "var(--color-warn)" : "var(--color-down)";
  return (
    <span className="inline-flex items-center gap-1 font-data-tabular text-[11px] text-on-surface-variant" title={`${value} confidence`}>
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: color }} />
      {value} conf.
    </span>
  );
}

// ── Section header with optional context note ─────────────────────────────
export function DashSection({
  title,
  caption,
  icon,
  action,
  children,
  id,
}: {
  title: string;
  caption?: ReactNode;
  icon?: string;
  action?: ReactNode;
  children: ReactNode;
  id?: string;
}) {
  return (
    <section id={id} aria-label={title}>
      <div className="flex flex-wrap items-end justify-between gap-3 mb-3">
        <div className="min-w-0">
          <h2 className="font-sans text-[18px] font-semibold tracking-tight text-primary leading-tight flex items-center gap-2">
            {icon ? <span className="material-symbols-outlined text-[19px] text-on-surface-variant">{icon}</span> : null}
            {title}
          </h2>
          {caption ? <p className="font-body-md text-body-md text-on-surface-variant mt-1 leading-snug">{caption}</p> : null}
        </div>
        {action ? <div className="shrink-0">{action}</div> : null}
      </div>
      {children}
    </section>
  );
}
