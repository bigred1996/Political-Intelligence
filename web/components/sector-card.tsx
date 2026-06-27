import Link from "next/link";
import type { SectorSummary } from "@/lib/api";

export function SectorCard({ s }: { s: SectorSummary }) {
  return (
    <Link
      href={`/sectors/${s.slug}`}
      className="group block panel card-level-2 p-4 focus-ring"
    >
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-[15px] font-semibold text-on-surface leading-snug group-hover:text-primary transition-colors">
          {s.name}
        </h3>
        <span className="material-symbols-outlined text-[18px] text-outline group-hover:text-primary shrink-0 mt-0.5 transition-colors" aria-hidden="true">arrow_forward</span>
      </div>
      <p className="text-[13px] text-on-surface-variant mt-1.5 leading-snug">{s.blurb}</p>
      <div className="mt-3 pt-2.5 border-t border-surface-container-high flex items-center gap-2 mono text-[10px] uppercase tracking-wide text-on-surface-variant">
        <span className="text-primary">{s.entity_count} entities</span>
        <span className="text-outline-variant">·</span>
        <span className="truncate">{s.regulators.slice(0, 2).join(", ")}</span>
      </div>
    </Link>
  );
}
