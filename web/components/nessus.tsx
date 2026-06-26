import Link from "next/link";

/* Shared Nessus "Intelligence Grade" building blocks for detail pages. */

export function Crumb({ items }: { items: { label: string; href?: string }[] }) {
  return (
    <div className="flex items-center gap-2 text-on-surface-variant mb-6 font-label-caps text-label-caps uppercase tracking-wider">
      {items.map((c, i) => (
        <span key={c.label} className="flex items-center gap-2">
          {i > 0 && <span className="material-symbols-outlined text-[14px]">chevron_right</span>}
          {c.href && i < items.length - 1 ? (
            <Link href={c.href} className="hover:text-primary transition-colors">{c.label}</Link>
          ) : (
            <span className={i === items.length - 1 ? "text-primary" : ""}>{c.label}</span>
          )}
        </span>
      ))}
    </div>
  );
}

export function DetailHeader({ eyebrow, title, subtitle, action }: { eyebrow?: string; title: React.ReactNode; subtitle?: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap justify-between items-end gap-4 mb-gutter pb-density-comfortable border-b border-outline-variant">
      <div className="min-w-0">
        {eyebrow && <div className="font-label-caps text-label-caps text-on-surface-variant uppercase mb-2">{eyebrow}</div>}
        <h1 className="font-display-lg text-headline-md md:text-display-lg text-primary leading-tight">{title}</h1>
        {subtitle && <p className="font-body-lg text-body-lg text-on-surface-variant mt-unit max-w-2xl">{subtitle}</p>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

export function Card({ icon, title, right, children, className = "" }: { icon?: string; title?: string; right?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <section className={`card-level-1 rounded-lg overflow-hidden ${className}`}>
      {title && (
        <div className="bg-surface-container-low px-density-comfortable py-density-compact border-b border-outline-variant flex items-center justify-between">
          <h2 className="font-label-caps text-label-caps text-on-surface-variant uppercase tracking-wider flex items-center gap-2">
            {icon && <span className="material-symbols-outlined text-[16px]">{icon}</span>} {title}
          </h2>
          {right}
        </div>
      )}
      {children}
    </section>
  );
}

/* Calibrated signal-strength badge (Strong/Moderate/Low) — replaces the old
   miscalibrated severity chip. Brass = strong (brand accent), amber = moderate,
   dim = low. Colour denotes how much the record lights up the graph, not good/bad. */
export function SignalBadge({ level, score }: { level: "strong" | "moderate" | "low"; score?: number }) {
  const cfg = {
    strong: { label: "Strong signal", dots: 3, cls: "text-primary border-primary/40 bg-primary/10" },
    moderate: { label: "Moderate signal", dots: 2, cls: "text-warn border-warn/40 bg-warn/10" },
    low: { label: "Low signal", dots: 1, cls: "text-on-surface-variant border-outline-variant bg-surface-container-low" },
  }[level];
  return (
    <span className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 ${cfg.cls}`}>
      <span className="flex items-center gap-0.5" aria-hidden="true">
        {[0, 1, 2].map((i) => (
          <span key={i} className={`w-1.5 h-1.5 rounded-full bg-current ${i < cfg.dots ? "" : "opacity-25"}`} />
        ))}
      </span>
      <span className="font-label-caps text-label-caps uppercase tracking-wide">{cfg.label}</span>
      {typeof score === "number" ? <span className="font-data-tabular text-[11px] opacity-70">{score}</span> : null}
    </span>
  );
}

/* One labeled narrative beat — the building block of the "What does it mean? Why
   does it matter? What is the impact?" reading. */
export function Beat({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="font-label-caps text-label-caps text-on-surface-variant uppercase tracking-wider mb-1.5">{label}</div>
      <p className="font-memo-body text-memo-body text-on-surface leading-relaxed">{children}</p>
    </div>
  );
}

export function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <span className="block font-label-caps text-label-caps text-on-surface-variant uppercase mb-1">{label}</span>
      <span className="text-body-md text-on-surface">{value}</span>
    </div>
  );
}

export function Avatar({ initials, shape = "rounded-full", size = "w-16 h-16" }: { initials: string; shape?: string; size?: string }) {
  return (
    <div className={`${size} ${shape} bg-primary-container text-on-primary flex items-center justify-center font-headline-sm text-[18px] shrink-0`}>
      {initials}
    </div>
  );
}

export function StatGrid({ stats }: { stats: { label: string; value: React.ReactNode }[] }) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 pt-4 border-t border-outline-variant">
      {stats.map((s) => (
        <div key={s.label}>
          <span className="block font-label-caps text-label-caps text-on-surface-variant uppercase mb-1">{s.label}</span>
          <span className="font-headline-sm text-[20px] text-on-surface">{s.value}</span>
        </div>
      ))}
    </div>
  );
}

export function PrimaryButton({ icon, children }: { icon: string; children: React.ReactNode }) {
  return (
    <button className="px-4 py-2 bg-primary text-on-primary rounded font-body-md text-body-md hover:bg-primary-container transition-colors flex items-center gap-2">
      <span className="material-symbols-outlined text-[18px]">{icon}</span> {children}
    </button>
  );
}
