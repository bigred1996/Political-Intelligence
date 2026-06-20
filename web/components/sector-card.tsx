import Link from "next/link";
import type { SectorSummary } from "@/lib/api";

export function SectorCard({ s }: { s: SectorSummary }) {
  return (
    <Link
      href={`/sectors/${s.slug}`}
      className="group block panel p-[18px] transition-shadow duration-200 hover:shadow-[0_1px_2px_rgba(30,32,28,.05),0_10px_28px_rgba(30,32,28,.08)]"
    >
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-[15px] font-bold text-fg-bright leading-snug group-hover:text-[#1b2b48] transition-colors">
          {s.name}
        </h3>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" className="text-fg-dim group-hover:text-[#1b2b48] shrink-0 mt-0.5 transition-all duration-200 group-hover:translate-x-0.5" aria-hidden="true">
          <path d="M5 12h14M13 6l6 6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </div>
      <p className="text-[13px] text-fg-dim mt-1.5 leading-snug">{s.blurb}</p>
      <div className="mt-3 pt-2.5 flex items-center gap-2 mono text-[10px] uppercase tracking-wide text-muted" style={{ borderTop: "1px solid #e6e8ea" }}>
        <span style={{ color: "#1b2b48" }}>{s.entity_count} entities</span>
        <span style={{ color: "#e0e3e5" }}>·</span>
        <span className="truncate">{s.regulators.slice(0, 2).join(", ")}</span>
      </div>
    </Link>
  );
}
