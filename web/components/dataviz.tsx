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
        const t = v > 0 ? 0.18 + 0.82 * (v / max) : 0;
        const fill = v > 0 ? hexLerp("#15263f", "#d8a23a", t) : "#0c1626";
        const isSel = selected === code;
        return (
          <path
            key={i}
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            d={path(f as any) || undefined}
            fill={fill}
            stroke={isSel ? "var(--color-brass-bright)" : "#1c2c46"}
            strokeWidth={isSel ? 1.8 : 0.6}
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
export function TrendBars({ data, color = "var(--color-up)", height = 130 }: { data: { year: string; count?: number; value?: number }[]; color?: string; height?: number }) {
  const series = data.map((d) => ({ year: d.year, v: d.count ?? d.value ?? 0 }));
  if (!series.length) return <NoData h={height} />;
  const W = 520, H = height, pad = { l: 6, r: 6, t: 12, b: 20 };
  const maxV = Math.max(...series.map((d) => d.v)) || 1;
  const bw = (W - pad.l - pad.r) / series.length;
  const labelIdx = [0, series.length - 1];
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height }} aria-hidden="true">
      {series.map((d, i) => {
        const bh = (d.v / maxV) * (H - pad.t - pad.b);
        return <rect key={i} x={pad.l + i * bw + bw * 0.12} y={H - pad.b - bh} width={bw * 0.76} height={bh} fill={color} opacity={i === series.length - 1 ? 1 : 0.65} rx="1" />;
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
  regulatory: "#e3a93a",
  funding: "#3ecf8e",
  policy: "#5b8def",
  partnership: "#a978e8",
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

// ── Horizontal bar list ───────────────────────────────────────────────
export function BarList({
  items,
  asMoney = false,
  color = "var(--color-brass)",
}: {
  items: { label: string; value: number; href?: string }[];
  asMoney?: boolean;
  color?: string;
}) {
  if (!items.length) return <NoData />;
  const max = Math.max(...items.map((i) => i.value)) || 1;
  return (
    <div className="space-y-1.5">
      {items.map((it, i) => (
        <div key={i} className="flex items-center gap-2 text-sm">
          <span className="w-40 shrink-0 truncate text-fg capitalize" title={it.label}>{it.label}</span>
          <div className="flex-1 h-3.5 bg-panel-2 rounded-sm overflow-hidden">
            <div className="h-full rounded-sm" style={{ width: `${(it.value / max) * 100}%`, background: color, transition: "width .5s ease" }} />
          </div>
          <span className="mono w-20 shrink-0 text-right text-fg-dim">{asMoney ? money(it.value) : num(it.value)}</span>
        </div>
      ))}
    </div>
  );
}
