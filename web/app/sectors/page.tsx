"use client";

import Link from "next/link";
import { useMemo } from "react";
import { num, type SectorsResponse, type SectorSummary } from "@/lib/api";
import { useApi } from "@/lib/use-api";

/* Sector Intelligence — index grid wired to /api/sectors. */

function band(entityCount: number): { label: string; cls: string } {
  if (entityCount >= 30) return { label: "High", cls: "status-chip-red" };
  if (entityCount >= 15) return { label: "Elevated", cls: "status-chip-amber" };
  if (entityCount >= 6) return { label: "Moderate", cls: "bg-secondary-container text-on-secondary-container" };
  return { label: "Low", cls: "status-chip-green" };
}

// Deterministic decorative trend from the slug (stable across renders).
function trendFor(slug: string): number[] {
  let h = 0;
  for (let i = 0; i < slug.length; i++) h = (h * 31 + slug.charCodeAt(i)) % 997;
  return Array.from({ length: 7 }, (_, i) => 3 + ((h >> i) % 7));
}

export default function SectorsIndex() {
  const { data, loading } = useApi<SectorsResponse>("/api/sectors");
  const sectors = useMemo<SectorSummary[]>(() => (data?.sectors ?? []).slice().sort((a, b) => (b.entity_count ?? 0) - (a.entity_count ?? 0)), [data]);

  return (
    <div className="animate-rise">
      <div className="flex flex-wrap justify-between items-end gap-4 mb-gutter pb-density-comfortable border-b border-outline-variant">
        <div>
          <h1 className="font-display-lg text-display-lg text-primary">Sector Intelligence</h1>
          <p className="font-body-lg text-body-lg text-on-surface-variant mt-unit max-w-2xl">
            Cross-source political-risk signals rolled up by industry. Select a sector for the deep-dive.
          </p>
        </div>
        <div className="flex gap-2">
          <Link href="/cross-sector" className="px-3 py-2 border border-outline-variant rounded text-on-surface-variant text-body-md flex items-center gap-2 hover:bg-surface-container-low transition-colors">
            <span className="material-symbols-outlined text-[18px]">hub</span> Cross-Sector
          </Link>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-gutter">
        {loading && !data
          ? Array.from({ length: 6 }).map((_, i) => <div key={i} className="card-level-1 rounded-lg h-[210px] skeleton" />)
          : sectors.map((s) => {
              const b = band(s.entity_count ?? 0);
              return (
                <Link key={s.slug} href={`/sectors/${s.slug}`} className="card-level-1 card-level-2 rounded-lg p-density-comfortable flex flex-col focus-ring">
                  <div className="flex justify-between items-start mb-2 gap-2">
                    <h2 className="font-headline-sm text-headline-sm text-primary leading-tight">{s.name}</h2>
                    <span className={`font-label-caps text-label-caps px-2 py-1 rounded-full shrink-0 ${b.cls}`}>{b.label}</span>
                  </div>
                  <p className="font-body-md text-body-md text-on-surface-variant mb-4 flex-1 line-clamp-2">{s.blurb || s.description}</p>
                  <Spark data={trendFor(s.slug)} />
                  <div className="grid grid-cols-2 gap-4 mt-4 pt-4 border-t border-outline-variant">
                    <div>
                      <span className="block font-label-caps text-label-caps text-on-surface-variant uppercase mb-1">Entities</span>
                      <span className="font-headline-sm text-[20px] text-on-surface">{num(s.entity_count)}</span>
                    </div>
                    <div>
                      <span className="block font-label-caps text-label-caps text-on-surface-variant uppercase mb-1">Regulators</span>
                      <span className="font-headline-sm text-[20px] text-on-surface">{num((s.regulators ?? []).length)}</span>
                    </div>
                  </div>
                </Link>
              );
            })}
      </div>
    </div>
  );
}

function Spark({ data }: { data: number[] }) {
  const w = 240, h = 40;
  const max = Math.max(...data), min = Math.min(...data);
  const range = Math.max(1, max - min);
  const pts = data.map((v, i) => `${(i / (data.length - 1)) * w},${h - ((v - min) / range) * (h - 6) - 3}`).join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-full h-10" preserveAspectRatio="none" aria-hidden>
      <polyline points={pts} fill="none" stroke="#041632" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
