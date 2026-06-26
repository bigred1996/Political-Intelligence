"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

type Item = { href: string; label: string; icon: string };

const NAV: Item[] = [
  { href: "/", label: "Dashboard", icon: "space_dashboard" },
  { href: "/dashboard", label: "Brief", icon: "newspaper" },
  { href: "/signals", label: "Live Feed", icon: "rss_feed" },
  { href: "/sectors", label: "Sectors", icon: "category" },
  { href: "/watchlists", label: "Watchlists", icon: "visibility" },
  { href: "/search", label: "Ask Nessus", icon: "forum" },
  { href: "/reviews", label: "Diligence", icon: "fact_check" },
  { href: "/briefings", label: "Reports", icon: "description" },
];

const DIRECTORY: Item[] = [
  { href: "/politicians", label: "Players", icon: "account_balance" },
  { href: "/entities", label: "Entities", icon: "corporate_fare" },
  { href: "/records", label: "Records", icon: "database" },
  { href: "/retrieve", label: "Retrieval", icon: "fact_check" },
  { href: "/research", label: "Deep Research", icon: "neurology" },
  { href: "/explorer", label: "Evidence Graph", icon: "hub" },
  { href: "/sources", label: "Sources", icon: "dataset" },
];

const SECONDARY: Item[] = [
  { href: "/sources", label: "Settings", icon: "settings" },
  { href: "/search", label: "Support", icon: "help" },
];

function NavRow({ item, active }: { item: Item; active: boolean }) {
  return (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      className={`flex items-center gap-density-comfortable px-density-compact py-density-compact rounded-lg cursor-pointer active:scale-95 transition-colors duration-200 ${
        active
          ? "text-primary font-bold border-r-4 border-primary bg-primary-container/10"
          : "text-on-surface-variant hover:text-primary hover:bg-surface-container-high"
      }`}
    >
      <span className="material-symbols-outlined text-[22px]" style={active ? { fontVariationSettings: "'FILL' 1" } : undefined}>
        {item.icon}
      </span>
      <span className="font-body-md text-body-md">{item.label}</span>
    </Link>
  );
}

export function AppSidebar() {
  const pathname = usePathname();
  const isActive = (href: string) => (href === "/" ? pathname === "/" : pathname.startsWith(href));

  return (
    <nav className="hidden md:flex h-screen w-64 shrink-0 border-r border-outline-variant bg-surface z-50 flex-col py-margin-mobile">
      {/* Brand */}
      <div className="px-6 mb-6 flex items-center gap-3">
        <Link href="/" className="w-8 h-8 rounded bg-primary flex items-center justify-center focus-ring">
          <img src="/brand/nessus-monogram-white.svg" alt="Nessus Intelligence" className="w-5 h-5" />
        </Link>
        <div>
          <h1 className="font-headline-sm text-headline-sm font-bold text-primary tracking-tight leading-none">NESSUS</h1>
          <p className="font-label-caps text-label-caps text-on-surface-variant uppercase mt-1">Intelligence Grade</p>
        </div>
      </div>

      {/* New Briefing */}
      <div className="px-4 mb-5">
        <Link
          href="/briefings"
          className="w-full bg-primary text-on-primary py-2 px-4 rounded-lg flex items-center justify-center gap-2 hover:bg-primary-container transition-colors font-body-md text-body-md font-medium focus-ring"
        >
          <span className="material-symbols-outlined text-[18px]">add</span>
          New Briefing
        </Link>
      </div>

      {/* Nav */}
      <div className="flex-1 overflow-y-auto px-4 space-y-1" role="navigation" aria-label="Primary">
        {NAV.map((it) => (
          <NavRow key={it.label} item={it} active={isActive(it.href)} />
        ))}

        <div className="font-label-caps text-label-caps text-on-surface-variant uppercase px-density-compact pt-5 pb-2">Intelligence</div>
        {DIRECTORY.map((it) => (
          <NavRow key={it.label} item={it} active={isActive(it.href)} />
        ))}
      </div>

      {/* Footer */}
      <div className="px-4 space-y-1 pt-4 border-t border-outline-variant">
        {SECONDARY.map((it) => (
          <NavRow key={it.label} item={it} active={false} />
        ))}
      </div>
    </nav>
  );
}
