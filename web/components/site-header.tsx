"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";
import { CompassMark } from "./compass-mark";

const NAV = [
  { href: "/sectors", label: "Sectors" },
  { href: "/entities", label: "Entities" },
  { href: "/search", label: "Search" },
  { href: "/briefings", label: "Briefings" },
];

export function SiteHeader() {
  const pathname = usePathname();
  const router = useRouter();
  const [q, setQ] = useState("");

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (q.trim()) router.push(`/search?q=${encodeURIComponent(q.trim())}`);
  }

  return (
    <header className="sticky top-0 z-30 bg-panel border-b border-line">
      <div className="mx-auto max-w-[1320px] px-4 h-14 flex items-center gap-5">
        <Link href="/" className="flex items-center gap-2 text-brass-bright shrink-0 group">
          <CompassMark size={26} className="transition-transform duration-300 group-hover:rotate-[30deg]" />
          <span className="text-fg-bright text-base font-semibold tracking-wide">NESSUS</span>
          <span className="hidden sm:inline mono text-[10px] text-up flex items-center gap-1 ml-1">● LIVE</span>
        </Link>

        <nav className="flex items-center gap-0.5 text-[13px] mono uppercase tracking-wide overflow-x-auto no-scrollbar">
          {NAV.map((n) => {
            const active = pathname === n.href || pathname.startsWith(n.href + "/");
            return (
              <Link
                key={n.href}
                href={n.href}
                className={`px-2.5 py-1.5 rounded whitespace-nowrap transition-colors duration-200 ${
                  active ? "text-brass-bright bg-panel-2" : "text-fg-dim hover:text-fg"
                }`}
              >
                {n.label}
              </Link>
            );
          })}
        </nav>

        <form onSubmit={submit} className="ml-auto hidden lg:flex items-center">
          <div className="flex items-center bg-canvas border border-line rounded overflow-hidden focus-within:border-brass/60 transition-colors">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" className="ml-2.5 text-fg-dim">
              <circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="2" />
              <path d="m20 20-3.5-3.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search the federal record…"
              aria-label="Search"
              className="bg-transparent text-sm text-fg placeholder:text-fg-dim px-2.5 py-1.5 w-52 outline-none"
            />
          </div>
        </form>
      </div>
    </header>
  );
}
