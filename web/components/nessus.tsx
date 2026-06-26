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

const SIGNAL_CFG = {
  strong: { label: "Strong", fill: 3, color: "var(--color-up)" },
  moderate: { label: "Moderate", fill: 2, color: "var(--color-warn)" },
  low: { label: "Low", fill: 1, color: "var(--color-outline)" },
} as const;

type SignalLevelName = keyof typeof SIGNAL_CFG;

/* Calibrated signal-strength badge (compact, for header/inline use). */
export function SignalBadge({ level, score }: { level: SignalLevelName; score?: number }) {
  const cfg = SIGNAL_CFG[level];
  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-outline-variant bg-surface-container-lowest px-3 py-1.5">
      <span className="flex items-center gap-0.5" aria-hidden="true">
        {[0, 1, 2].map((i) => (
          <span key={i} className="w-1.5 h-4 rounded-sm" style={{ background: i < cfg.fill ? cfg.color : "var(--color-outline-variant)" }} />
        ))}
      </span>
      <span className="font-label-caps text-label-caps uppercase tracking-wide text-on-surface">{cfg.label} signal</span>
      {typeof score === "number" ? <span className="font-data-tabular text-[11px] text-on-surface-variant">{score}</span> : null}
    </span>
  );
}

/* Signal-strength meter — a segmented bar with a score readout, for the hero
   verdict block. `variant="onDark"` adapts label colours for the navy panel. */
export function SignalMeter({ level, score, variant = "light" }: { level: SignalLevelName; score?: number; variant?: "light" | "onDark" }) {
  const cfg = SIGNAL_CFG[level];
  const onDark = variant === "onDark";
  const trackEmpty = onDark ? "rgba(255,255,255,0.16)" : "var(--color-outline-variant)";
  return (
    <div className="flex items-center gap-3">
      <div className="flex items-end gap-1" aria-hidden="true">
        {[0, 1, 2].map((i) => (
          <span key={i} className="w-2.5 rounded-sm" style={{ height: 10 + i * 7, background: i < cfg.fill ? cfg.color : trackEmpty }} />
        ))}
      </div>
      <div className="leading-tight">
        <div className={`font-label-caps text-label-caps uppercase tracking-wide ${onDark ? "text-white/60" : "text-on-surface-variant"}`}>Signal strength</div>
        <div className="flex items-baseline gap-2">
          <span className="font-display-lg text-[20px]" style={{ color: cfg.color }}>{cfg.label}</span>
          {typeof score === "number" ? <span className={`font-data-tabular text-data-tabular ${onDark ? "text-white/50" : "text-on-surface-variant"}`}>{score}/100</span> : null}
        </div>
      </div>
    </div>
  );
}

/* One labeled narrative beat — the building block of the "What does it mean? Why
   does it matter? What is the impact?" reading. An optional coloured icon gives
   each beat a distinct visual anchor instead of an undifferentiated grey block. */
export function Beat({ label, icon, accent, children }: { label: string; icon?: string; accent?: string; children: React.ReactNode }) {
  const color = accent ?? "var(--color-on-surface-variant)";
  return (
    <div className="flex gap-3">
      {icon ? (
        <span className="material-symbols-outlined text-[20px] mt-0.5 shrink-0" style={{ color }} aria-hidden="true">{icon}</span>
      ) : null}
      <div className="min-w-0">
        <div className="font-label-caps text-label-caps uppercase tracking-wider mb-1" style={{ color }}>{label}</div>
        <p className="font-memo-body text-memo-body text-on-surface leading-relaxed">{children}</p>
      </div>
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
