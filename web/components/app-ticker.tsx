"use client";

import { num, type FeedItem } from "@/lib/api";
import { useApi } from "@/lib/use-api";

interface OverviewTicker {
  ticker: { house_status: string; next_item: string; bills_in_motion: number; gazette_entries: number; contracts: number; operations: number };
  signals?: FeedItem[];
}

export function AppTicker() {
  const { data } = useApi<OverviewTicker>("/api/overview");
  const t = data?.ticker;

  const items: { label: string; value: string; tone?: string }[] = t
    ? [
        { label: "Bills in motion", value: num(t.bills_in_motion), tone: "var(--color-brass-bright)" },
        { label: "Gazette entries", value: num(t.gazette_entries) },
        { label: "Contracts tracked", value: num(t.contracts) },
        { label: "Operations records", value: num(t.operations) },
      ]
    : [];

  return (
    <footer className="shrink-0 h-8 bg-panel border-t border-line flex items-center px-3 sm:px-4 gap-4 text-[11px] overflow-x-auto no-scrollbar">
      <div className="flex items-center gap-1.5 shrink-0">
        <span className="w-1.5 h-1.5 rounded-full bg-up animate-pulse" />
        <span className="mono uppercase tracking-wide text-fg">{t?.house_status ?? "House of Commons"}</span>
      </div>
      <span className="text-line shrink-0">|</span>
      <span className="mono text-fg-dim shrink-0">NEXT <span className="text-fg">{t?.next_item ?? "—"}</span></span>
      <span className="text-line shrink-0">|</span>
      <div className="flex items-center gap-4 shrink-0">
        {items.map((it) => (
          <span key={it.label} className="mono text-fg-dim shrink-0">
            {it.label} <span style={{ color: it.tone ?? "var(--color-fg-bright)" }}>{it.value}</span>
          </span>
        ))}
      </div>
      <span className="mono text-fg-dim/60 ml-auto shrink-0 hidden sm:inline">POLARIS · Source: Government of Canada open data</span>
    </footer>
  );
}
