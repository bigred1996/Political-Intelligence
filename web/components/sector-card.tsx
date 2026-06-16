import Link from "next/link";
import type { SectorSummary } from "@/lib/api";

export function SectorCard({ s }: { s: SectorSummary }) {
  return (
    <Link
      href={`/sectors/${s.slug}`}
      className="group block panel p-4 transition-colors duration-200 hover:border-brass/50"
    >
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-[15px] font-semibold text-fg-bright leading-snug group-hover:text-brass-bright transition-colors">
          {s.name}
        </h3>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" className="text-fg-dim group-hover:text-brass-bright shrink-0 mt-0.5 transition-all duration-200 group-hover:translate-x-0.5" aria-hidden="true">
          <path d="M5 12h14M13 6l6 6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </div>
      <p className="text-[13px] text-fg-dim mt-1.5 leading-snug">{s.blurb}</p>
      <div className="mt-3 pt-2.5 border-t border-line flex items-center gap-2 mono text-[10px] uppercase tracking-wide text-fg-dim">
        <span className="text-brass">{s.entity_count} entities</span>
        <span className="text-line">·</span>
        <span className="truncate">{s.regulators.slice(0, 2).join(", ")}</span>
      </div>
    </Link>
  );
}
