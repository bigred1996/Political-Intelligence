"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";

const MOBILE_NAV = [
  { href: "/", label: "Briefing" },
  { href: "/signals", label: "Live Feed" },
  { href: "/sectors", label: "Sectors" },
  { href: "/watchlists", label: "Watchlists" },
  { href: "/search", label: "Ask Nessus" },
  { href: "/briefings", label: "Reports" },
  { href: "/newsletters", label: "Newsletter" },
];

export function AppTopBar() {
  const router = useRouter();
  const pathname = usePathname();
  const [q, setQ] = useState("");

  return (
    <header className="shrink-0 bg-surface/80 backdrop-blur-md border-b border-outline-variant z-40">
      <div className="h-16 flex items-center justify-between gap-4 px-margin-mobile md:px-margin-desktop">
        <div className="flex items-center gap-4 min-w-0">
          <Link
            href="/"
            className="md:hidden w-8 h-8 rounded bg-primary flex items-center justify-center shrink-0"
            aria-label="Nessus home"
          >
            <img src="/brand/nessus-monogram-white.svg" alt="" className="w-5 h-5" />
          </Link>
          <span className="hidden md:block font-headline-sm text-headline-sm font-bold text-primary shrink-0">
            Nessus Intelligence
          </span>
        </div>

        <div className="flex items-center gap-4">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (q.trim()) router.push(`/search?q=${encodeURIComponent(q.trim())}`);
            }}
            className="relative hidden sm:block w-56 lg:w-72"
          >
            <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-on-surface-variant text-[20px] pointer-events-none">
              search
            </span>
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search bills, sectors, MPs…"
              aria-label="Global search"
              className="w-full bg-surface-container-low border border-outline-variant rounded-full py-1.5 pl-10 pr-4 font-body-md text-body-md text-on-surface placeholder:text-on-surface-variant focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary transition-colors"
            />
          </form>

          <div className="flex items-center gap-2 sm:border-l sm:border-outline-variant sm:pl-4">
            <button
              type="button"
              aria-label="Notifications"
              className="w-9 h-9 flex items-center justify-center rounded-full text-on-surface-variant hover:text-primary hover:bg-surface-container-low transition-all"
            >
              <span className="material-symbols-outlined text-[20px]">notifications</span>
            </button>
            <button
              type="button"
              onClick={() => window.print()}
              aria-label="History"
              className="hidden sm:flex w-9 h-9 items-center justify-center rounded-full text-on-surface-variant hover:text-primary hover:bg-surface-container-low transition-all"
            >
              <span className="material-symbols-outlined text-[20px]">history</span>
            </button>
            <div className="w-8 h-8 rounded-full bg-secondary-container border border-outline-variant ml-1 flex items-center justify-center text-[12px] font-bold text-on-secondary-container">
              AM
            </div>
          </div>
        </div>
      </div>

      {/* Mobile nav */}
      <nav className="md:hidden flex items-center gap-1 px-4 pb-2 overflow-x-auto no-scrollbar">
        {MOBILE_NAV.map((n) => {
          const active = n.href === "/" ? pathname === "/" : pathname.startsWith(n.href);
          return (
            <Link
              key={n.label}
              href={n.href}
              className={`px-2.5 py-1.5 rounded font-label-caps text-label-caps uppercase whitespace-nowrap ${
                active ? "text-primary bg-primary-container/10" : "text-on-surface-variant"
              }`}
            >
              {n.label}
            </Link>
          );
        })}
      </nav>
    </header>
  );
}
