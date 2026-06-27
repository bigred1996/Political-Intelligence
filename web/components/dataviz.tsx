"use client";

import { geoConicConformal, geoPath } from "d3-geo";
import { useEffect, useState } from "react";
import { money, num } from "@/lib/api";

// ── helpers ───────────────────────────────────────────────────────────
function hexLerp(a: string, b: string, t: number): string {
  const pa = [1, 3, 5].map((i) => parseInt(a.slice(i, i + 2), 16));
  const pb = [1, 3, 5].map((i) => parseInt(b.slice(i, i + 2), 16));
  const c = pa.map((v, i) => Math.round(v + (pb[i] - v) * t));
  return `#${c.map((v) => v.toString(16).padStart(2, "0")).join("")}`;
}
function NoData({ h = 80 }: { h?: number }) {
  return <div className="flex items-center justify-center text-xs text-fg-dim" style={{ height: h }}>No data</div>;
}

// ── Canada choropleth map ─────────────────────────────────────────────
const NAME2CODE: Record<string, string> = {
  "Quebec": "QC", "Newfoundland and Labrador": "NL", "British Columbia": "BC",
  "Nunavut": "NU", "Northwest Territories": "NT", "New Brunswick": "NB",
  "Nova Scotia": "NS", "Saskatchewan": "SK", "Alberta": "AB",
  "Prince Edward Island": "PE", "Yukon Territory": "YT", "Manitoba": "MB", "Ontario": "ON",
};

interface GeoFC { type: string; features: { type: string; properties: { name: string }; geometry: unknown }[] }

export function CanadaMap({
  rows,
  selected,
  onSelect,
  metric = "records",
}: {
  rows: { code: string; province: string; records: number; amount: number }[];
  selected?: string | null;
  onSelect?: (code: string | null) => void;
  metric?: "records" | "amount";
}) {
  const [geo, setGeo] = useState<GeoFC | null>(null);
  useEffect(() => {
    fetch("/canada-provinces.json").then((r) => r.json()).then(setGeo).catch(() => {});
  }, []);

  if (!geo) return <div className="skeleton" style={{ height: 320 }} />;

  const W = 620, H = 540;
  const byCode: Record<string, number> = {};
  rows.forEach((r) => { byCode[r.code] = (r as unknown as Record<string, number>)[metric] || 0; });
  const max = Math.max(1, ...rows.map((r) => (r as unknown as Record<string, number>)[metric] || 0));

  const proj = geoConicConformal().rotate([98, 0]).center([0, 62]).parallels([49, 77]);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  proj.fitSize([W, H], geo as any);
  const path = geoPath(proj);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" role="img" aria-label="Canada regional footprint map">
      {geo.features.map((f, i) => {
        const code = NAME2CODE[f.properties.name];
        const v = code ? byCode[code] || 0 : 0;
        // Single-hue sequential scale (light slate → Parliament Navy) — a
        // two-hue lerp (e.g. navy→gold) crosses a muddy, off-brand olive
        // band partway through; sequential choropleths read more clearly
        // and stay on-palette at every magnitude.
        const t = v > 0 ? 0.22 + 0.78 * (v / max) : 0;
        const fill = v > 0 ? hexLerp("#cdd8ea", "#041632", t) : "var(--color-surface-container-low)";
        const isSel = selected === code;
        return (
          <path
            key={i}
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            d={path(f as any) || undefined}
            fill={fill}
            stroke={isSel ? "var(--color-primary)" : "var(--color-surface)"}
            strokeWidth={isSel ? 1.8 : 1}
            style={{ cursor: onSelect && code ? "pointer" : "default", transition: "fill .3s" }}
            onClick={() => onSelect && code && onSelect(isSel ? null : code)}
          >
            <title>{f.properties.name}: {metric === "amount" ? money(v) : num(v)}</title>
          </path>
        );
      })}
    </svg>
  );
}

// ── Time-series area chart ────────────────────────────────────────────
export function TrendArea({
  data,
  color = "var(--color-brass)",
  asMoney = false,
  height = 130,
}: {
  data: { year: string; value?: number; count?: number }[];
  color?: string;
  asMoney?: boolean;
  height?: number;
}) {
  const series = data.map((d) => ({ year: d.year, v: (d.value ?? d.count ?? 0) }));
  if (series.length < 2) return <NoData h={height} />;

  const W = 520, H = height, pad = { l: 6, r: 6, t: 12, b: 20 };
  const maxV = Math.max(...series.map((d) => d.v)) || 1;
  const x = (i: number) => pad.l + (i * (W - pad.l - pad.r)) / (series.length - 1);
  const y = (v: number) => pad.t + (1 - v / maxV) * (H - pad.t - pad.b);

  const pts = series.map((d, i) => `${x(i)},${y(d.v)}`).join(" ");
  const areaPath = `M ${x(0)},${H - pad.b} L ${series.map((d, i) => `${x(i)},${y(d.v)}`).join(" L ")} L ${x(series.length - 1)},${H - pad.b} Z`;
  const fmt = (v: number) => (asMoney ? money(v) : num(v));
  const labelIdx = [0, Math.floor((series.length - 1) / 2), series.length - 1];

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height }} aria-hidden="true">
      <line x1={pad.l} y1={H - pad.b} x2={W - pad.r} y2={H - pad.b} stroke="var(--color-line)" strokeWidth="1" />
      <path d={areaPath} fill={color} opacity="0.14" />
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.8" strokeLinejoin="round" strokeLinecap="round" />
      {series.map((d, i) => (
        <circle key={i} cx={x(i)} cy={y(d.v)} r={i === series.length - 1 ? 2.6 : 0} fill={color} />
      ))}
      <text x={pad.l} y={pad.t - 2} fontSize="9.5" className="mono" fill="var(--color-fg-dim)">{fmt(maxV)}</text>
      {labelIdx.map((i) => (
        <text key={i} x={x(i)} y={H - 6} fontSize="9.5" textAnchor={i === 0 ? "start" : i === series.length - 1 ? "end" : "middle"} className="mono" fill="var(--color-fg-dim)">
          {series[i].year}
        </text>
      ))}
    </svg>
  );
}

// ── Year column chart ─────────────────────────────────────────────────
// Optional `onSelect(year)` turns each column into a drill-down control;
// `activeYear` highlights the selected column. Both additive.
export function TrendBars({ data, color = "var(--color-up)", height = 130, onSelect, activeYear }: { data: { year: string; count?: number; value?: number }[]; color?: string; height?: number; onSelect?: (year: string) => void; activeYear?: string | null }) {
  const series = data.map((d) => ({ year: d.year, v: d.count ?? d.value ?? 0 }));
  if (!series.length) return <NoData h={height} />;
  const W = 520, H = height, pad = { l: 6, r: 6, t: 12, b: 20 };
  const maxV = Math.max(...series.map((d) => d.v)) || 1;
  const bw = (W - pad.l - pad.r) / series.length;
  const labelIdx = [0, series.length - 1];
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height }} role={onSelect ? "group" : undefined} aria-hidden={onSelect ? undefined : "true"}>
      {series.map((d, i) => {
        const bh = (d.v / maxV) * (H - pad.t - pad.b);
        const active = activeYear != null && activeYear === d.year;
        const op = activeYear != null ? (active ? 1 : 0.3) : i === series.length - 1 ? 1 : 0.65;
        return (
          <g key={i} onClick={onSelect ? () => onSelect(d.year) : undefined} style={onSelect ? { cursor: "pointer" } : undefined}>
            {/* full-height hit target so thin/zero bars stay clickable */}
            {onSelect && <rect x={pad.l + i * bw} y={pad.t} width={bw} height={H - pad.t - pad.b} fill="transparent" />}
            <rect x={pad.l + i * bw + bw * 0.12} y={H - pad.b - bh} width={bw * 0.76} height={bh} fill={color} opacity={op} rx="1">
              <title>{d.year}: {num(d.v)}</title>
            </rect>
          </g>
        );
      })}
      <line x1={pad.l} y1={H - pad.b} x2={W - pad.r} y2={H - pad.b} stroke="var(--color-line)" strokeWidth="1" />
      <text x={pad.l} y={pad.t - 2} fontSize="9.5" className="mono" fill="var(--color-fg-dim)">{num(maxV)}</text>
      {labelIdx.map((i) => (
        <text key={i} x={pad.l + i * bw + bw / 2} y={H - 6} fontSize="9.5" textAnchor={i === 0 ? "start" : "end"} className="mono" fill="var(--color-fg-dim)">{series[i].year}</text>
      ))}
    </svg>
  );
}

// ── Radial connection network ─────────────────────────────────────────
const EDGE_COLOR: Record<string, string> = {
  regulatory: "#f1c232",
  funding: "#6aa84f",
  policy: "#3b6ea5",
  partnership: "#6c5b8f",
};

export function RadialNetwork({
  center,
  nodes,
  height = 340,
}: {
  center: string;
  nodes: { label: string; sub?: string; type: keyof typeof EDGE_COLOR }[];
  height?: number;
}) {
  if (!nodes.length) return <NoData h={height} />;
  const W = 460, H = height, cx = W / 2, cy = H / 2, R = Math.min(W, H) / 2 - 70;
  const n = nodes.length;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height }} role="img" aria-label={`Connection network for ${center}`}>
      {nodes.map((nd, i) => {
        const a = (i / n) * 2 * Math.PI - Math.PI / 2;
        const x = cx + R * Math.cos(a), y = cy + R * Math.sin(a);
        const col = EDGE_COLOR[nd.type];
        const right = x >= cx;
        return (
          <g key={i}>
            <line x1={cx} y1={cy} x2={x} y2={y} stroke={col} strokeWidth="1.3" opacity="0.55" />
            <circle cx={x} cy={y} r="5" fill="var(--color-panel)" stroke={col} strokeWidth="2" />
            <text x={right ? x + 9 : x - 9} y={y - 1} textAnchor={right ? "start" : "end"} fontSize="11" fill="var(--color-fg)" className="font-medium">
              {nd.label.length > 22 ? nd.label.slice(0, 22) + "…" : nd.label}
            </text>
            {nd.sub && (
              <text x={right ? x + 9 : x - 9} y={y + 11} textAnchor={right ? "start" : "end"} fontSize="9" fill="var(--color-fg-dim)" className="mono uppercase">
                {nd.sub}
              </text>
            )}
          </g>
        );
      })}
      <circle cx={cx} cy={cy} r="34" fill="var(--color-panel-2)" stroke="var(--color-brass)" strokeWidth="1.5" />
      <text x={cx} y={cy} textAnchor="middle" dominantBaseline="middle" fontSize="12" fill="var(--color-brass-bright)" className="font-semibold capitalize">
        {center.length > 12 ? center.slice(0, 12) + "…" : center}
      </text>
    </svg>
  );
}

// ── Entity connection graph ───────────────────────────────────────────
// A radial "how it connects" diagram: the entity at the centre, one coloured
// spoke per source category, node size scaled by connection count. Colours are
// supplied by the caller (from lib/source-visual) so the graph, the legend, and
// the grouped lists below it all read in the same palette.
export function EntityConnectionGraph({
  center,
  nodes,
  height = 280,
}: {
  center: string;
  nodes: { label: string; value: number; color: string }[];
  height?: number;
}) {
  if (!nodes.length) return <NoData h={height} />;
  const W = 460, H = height, cx = W / 2, cy = H / 2, R = Math.min(W, H) / 2 - 56;
  const n = nodes.length;
  const max = Math.max(...nodes.map((d) => d.value)) || 1;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height }} role="img" aria-label={`Connection graph for ${center}`}>
      {nodes.map((nd, i) => {
        const a = (i / n) * 2 * Math.PI - Math.PI / 2;
        const x = cx + R * Math.cos(a), y = cy + R * Math.sin(a);
        const r = 5 + Math.round((nd.value / max) * 11); // 5–16px by volume
        const right = x >= cx - 4;
        return (
          <g key={i}>
            <line x1={cx} y1={cy} x2={x} y2={y} stroke={nd.color} strokeWidth="1.4" opacity="0.45" />
            <circle cx={x} cy={y} r={r} fill={nd.color} opacity="0.18" />
            <circle cx={x} cy={y} r={Math.max(4, r - 4)} fill={nd.color} />
            <text x={right ? x + r + 5 : x - r - 5} y={y - 1} textAnchor={right ? "start" : "end"} fontSize="11" fill="var(--color-on-surface)" className="font-medium">
              {nd.label.length > 20 ? nd.label.slice(0, 20) + "…" : nd.label}
            </text>
            <text x={right ? x + r + 5 : x - r - 5} y={y + 11} textAnchor={right ? "start" : "end"} fontSize="10" fill="var(--color-on-surface-variant)" className="mono">
              {nd.value.toLocaleString()}
            </text>
          </g>
        );
      })}
      <circle cx={cx} cy={cy} r="36" fill="var(--color-primary)" />
      <text x={cx} y={cy} textAnchor="middle" dominantBaseline="middle" fontSize="12" fill="#ffffff" className="font-semibold">
        {center.length > 13 ? center.slice(0, 13) + "…" : center}
      </text>
    </svg>
  );
}

// ── Horizontal bar list ───────────────────────────────────────────────
// Optional `onSelect` makes each row a drill-down control (keyed by `it.key`);
// `activeKey` highlights the currently-selected row. Both are additive — callers
// that pass neither get the original static list.
export function BarList({
  items,
  asMoney = false,
  color = "var(--color-brass)",
  onSelect,
  activeKey,
}: {
  items: { label: string; value: number; href?: string; key?: string }[];
  asMoney?: boolean;
  color?: string;
  onSelect?: (key: string) => void;
  activeKey?: string | null;
}) {
  if (!items.length) return <NoData />;
  const max = Math.max(...items.map((i) => i.value)) || 1;
  return (
    <div className="space-y-1.5">
      {items.map((it, i) => {
        const k = it.key ?? it.label;
        const active = activeKey != null && activeKey === k;
        const row = (
          <>
            <span className={`w-40 shrink-0 truncate capitalize ${active ? "text-brass-bright font-medium" : "text-fg"}`} title={it.label}>{it.label}</span>
            <div className="flex-1 h-3.5 bg-panel-2 rounded-sm overflow-hidden">
              <div className="h-full rounded-sm" style={{ width: `${(it.value / max) * 100}%`, background: color, transition: "width .5s ease", opacity: activeKey != null && !active ? 0.4 : 1 }} />
            </div>
            <span className="mono w-20 shrink-0 text-right text-fg-dim">{asMoney ? money(it.value) : num(it.value)}</span>
          </>
        );
        if (onSelect) {
          return (
            <button key={i} type="button" onClick={() => onSelect(k)} aria-pressed={active}
              className="flex w-full items-center gap-2 text-sm text-left rounded-sm px-1 -mx-1 hover:bg-panel-2 focus-ring">
              {row}
            </button>
          );
        }
        return <div key={i} className="flex items-center gap-2 text-sm">{row}</div>;
      })}
    </div>
  );
}

// ── Category × severity heat matrix ───────────────────────────────────────
// The diligence memo's signature exhibit, ported to the workspace so both
// surfaces read the same. Cell shade scales with the count within the grid;
// an empty cell is a hairline placeholder, never a fabricated bar. Optional
// `onSelect(severityKey)` drills the column's severity into the risk filter.
const HEAT_COL_COLOR: Record<string, string> = {
  high: "var(--color-risk-high)",
  elevated: "var(--color-risk-med)",
  watch: "var(--color-up)",
};

export function HeatMatrix({
  matrix,
  onSelect,
  activeKey,
}: {
  matrix: { rows: string[]; keys: string[]; cols: string[]; colKeys: string[]; values: number[][]; absentRows: string[] };
  onSelect?: (severityKey: string | null) => void;
  activeKey?: string | null;
}) {
  if (matrix.rows.length === 0) return <NoData h={60} />;
  const max = Math.max(1, ...matrix.values.flat());
  return (
    <div className="space-y-2">
      <div className="overflow-hidden rounded-sm">
        {/* header row */}
        <div className="flex items-stretch gap-[3px] mb-[3px]">
          <div className="w-44 shrink-0" />
          {matrix.cols.map((c, j) => {
            const sevKey = matrix.colKeys[j];
            const active = activeKey === sevKey;
            return (
              <button
                key={c}
                type="button"
                onClick={() => onSelect?.(active ? null : sevKey)}
                aria-pressed={active}
                className={`flex-1 text-center mono text-[10px] uppercase tracking-wider py-1 rounded-sm focus-ring ${
                  active ? "text-fg" : "text-fg-dim hover:text-fg"
                }`}
              >
                {c}
              </button>
            );
          })}
        </div>
        {matrix.rows.map((r, i) => (
          <div key={r} className="flex items-stretch gap-[3px] mb-[3px]">
            <div className="w-44 shrink-0 text-[12px] font-medium text-fg flex items-center pr-2 leading-tight">{r}</div>
            {matrix.values[i].map((v, j) => {
              const sevKey = matrix.colKeys[j];
              const op = v > 0 ? 0.4 + 0.6 * (v / max) : 0;
              return (
                <button
                  key={j}
                  type="button"
                  onClick={() => v > 0 && onSelect?.(activeKey === sevKey ? null : sevKey)}
                  className="flex-1 h-9 rounded-sm flex items-center justify-center text-[12px] font-semibold focus-ring"
                  style={
                    v > 0
                      ? { background: HEAT_COL_COLOR[sevKey], opacity: op, color: "#fff", cursor: onSelect ? "pointer" : "default" }
                      : { background: "var(--color-panel-2)", color: "var(--color-fg-dim)", cursor: "default" }
                  }
                >
                  {v > 0 ? v : "·"}
                </button>
              );
            })}
          </div>
        ))}
      </div>
      {matrix.absentRows.length > 0 && (
        <p className="text-[11px] text-fg-dim italic">
          Not observed in this run: {matrix.absentRows.join(", ").toLowerCase()}.
        </p>
      )}
    </div>
  );
}
