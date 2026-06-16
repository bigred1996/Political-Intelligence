"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { CompassMark } from "./compass-mark";

type Item = { href: string; label: string; icon: React.ReactNode; soon?: boolean };

const I = {
  grid: <path d="M3 3h7v7H3zM14 3h7v7h-7zM14 14h7v7h-7zM3 14h7v7H3z" />,
  layers: <path d="M12 2 2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" />,
  building: <path d="M3 21h18M5 21V7l8-4v18M19 21V11l-6-3M9 9h.01M9 13h.01M9 17h.01" />,
  search: <><circle cx="11" cy="11" r="7" /><path d="m21 21-4-4" /></>,
  doc: <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M8 13h8M8 17h8" />,
  map: <path d="m9 4-6 2v14l6-2 6 2 6-2V4l-6 2-6-2zM9 4v14M15 6v14" />,
  network: <><circle cx="12" cy="5" r="2" /><circle cx="5" cy="19" r="2" /><circle cx="19" cy="19" r="2" /><path d="M12 7v4M10.5 13 6.5 17M13.5 13l4 4" /></>,
  folder: <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />,
  people: <><circle cx="9" cy="7" r="3" /><path d="M2 21v-1a6 6 0 0 1 12 0v1M16 3.5a3 3 0 0 1 0 7M22 21v-1a6 6 0 0 0-4-5.6" /></>,
};

const GROUPS: { label: string; items: Item[] }[] = [
  {
    label: "Analysis",
    items: [
      { href: "/", label: "Overview", icon: I.grid },
      { href: "/sectors", label: "Industries", icon: I.layers },
      { href: "/entities", label: "Entities", icon: I.building },
      { href: "/politicians", label: "Political Players", icon: I.people },
    ],
  },
  {
    label: "Intelligence",
    items: [
      { href: "/search", label: "Ask Polaris", icon: I.search },
      { href: "/briefings", label: "Briefings", icon: I.doc },
    ],
  },
  {
    label: "Coming soon",
    items: [
      { href: "#", label: "Regions", icon: I.map, soon: true },
      { href: "#", label: "Influence Map", icon: I.network, soon: true },
      { href: "#", label: "Data Library", icon: I.folder, soon: true },
    ],
  },
];

export function AppSidebar() {
  const pathname = usePathname();
  return (
    <aside className="hidden md:flex flex-col w-56 shrink-0 bg-panel border-r border-line">
      <Link href="/" className="flex items-center gap-2 px-4 h-14 border-b border-line text-brass-bright shrink-0">
        <CompassMark size={24} />
        <div className="leading-none">
          <div className="text-fg-bright text-sm font-semibold tracking-wide">POLARIS</div>
          <div className="mono text-[9px] text-fg-dim tracking-[0.2em] mt-0.5">POLITICAL INTELLIGENCE</div>
        </div>
      </Link>
      <nav className="flex-1 overflow-y-auto no-scrollbar py-3">
        {GROUPS.map((g) => (
          <div key={g.label} className="mb-4">
            <div className="eyebrow !text-fg-dim px-4 mb-1.5">{g.label}</div>
            {g.items.map((it) => {
              const active = it.href === "/" ? pathname === "/" : pathname.startsWith(it.href) && it.href !== "#";
              if (it.soon) {
                return (
                  <div key={it.label} className="flex items-center gap-2.5 px-4 py-1.5 text-fg-dim/60 cursor-default">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">{it.icon}</svg>
                    <span className="text-[13px]">{it.label}</span>
                    <span className="mono text-[8px] uppercase tracking-wide ml-auto border border-line rounded px-1 py-0.5">soon</span>
                  </div>
                );
              }
              return (
                <Link key={it.href} href={it.href} className={`flex items-center gap-2.5 px-4 py-1.5 text-[13px] transition-colors border-l-2 ${active ? "text-brass-bright border-brass bg-panel-2" : "text-fg border-transparent hover:text-fg-bright hover:bg-panel-2/50"}`}>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">{it.icon}</svg>
                  <span>{it.label}</span>
                </Link>
              );
            })}
          </div>
        ))}
      </nav>
      <div className="px-4 py-3 border-t border-line mono text-[10px] text-fg-dim">
        <div className="flex items-center gap-1.5"><span className="w-1.5 h-1.5 rounded-full bg-up inline-block" /> Live · 14 sources</div>
      </div>
    </aside>
  );
}
