"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";
import { CompassMark } from "./compass-mark";

const MOBILE_NAV = [
  { href: "/", label: "Overview" },
  { href: "/sectors", label: "Sectors" },
  { href: "/entities", label: "Entities" },
  { href: "/search", label: "Search" },
  { href: "/briefings", label: "Briefings" },
];

export function AppTopBar() {
  const router = useRouter();
  const pathname = usePathname();
  const [q, setQ] = useState("");

  return (
    <header className="shrink-0 bg-panel border-b border-line">
      <div className="flex items-center gap-3 h-14 px-3 sm:px-4">
        {/* Mobile logo (sidebar hidden < md) */}
        <Link href="/" className="md:hidden flex items-center gap-2 text-brass-bright shrink-0">
          <CompassMark size={24} />
        </Link>

        <form
          onSubmit={(e) => { e.preventDefault(); if (q.trim()) router.push(`/search?q=${encodeURIComponent(q.trim())}`); }}
          className="flex-1 max-w-2xl"
        >
          <div className="flex items-center bg-canvas border border-line rounded-md overflow-hidden focus-within:border-brass/50 transition-colors">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" className="ml-3 text-fg-dim"><circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="2" /><path d="m20 20-3.5-3.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" /></svg>
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search sectors, entities, regions, bills, organizations…"
              aria-label="Global search"
              className="flex-1 bg-transparent text-sm text-fg placeholder:text-fg-dim px-3 py-2 outline-none"
            />
          </div>
        </form>

        <div className="ml-auto flex items-center gap-2 sm:gap-3">
          <Link href="/" className="hidden sm:flex items-center gap-1.5 mono text-[11px] text-fg-dim hover:text-fg transition-colors" title="Signals">
            <span className="relative">
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 0 1-3.4 0" /></svg>
              <span className="absolute -top-0.5 -right-0.5 w-1.5 h-1.5 rounded-full bg-down" />
            </span>
          </Link>
          <div className="w-7 h-7 rounded-full bg-brass/20 border border-brass/40 grid place-items-center mono text-[11px] text-brass-bright font-semibold">P</div>
        </div>
      </div>

      {/* Mobile nav row */}
      <nav className="md:hidden flex items-center gap-0.5 px-2 pb-2 mono text-[12px] uppercase tracking-wide overflow-x-auto no-scrollbar">
        {MOBILE_NAV.map((n) => {
          const active = n.href === "/" ? pathname === "/" : pathname.startsWith(n.href);
          return <Link key={n.href} href={n.href} className={`px-2.5 py-1 rounded whitespace-nowrap ${active ? "text-brass-bright bg-panel-2" : "text-fg-dim"}`}>{n.label}</Link>;
        })}
      </nav>
    </header>
  );
}
