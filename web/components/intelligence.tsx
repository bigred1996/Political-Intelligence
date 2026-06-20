import Link from "next/link";
import type { ReactNode } from "react";
import { OriginalSourceLink, SourceTag } from "@/components/ui";

export type RelationshipStrength = "direct" | "supported" | "inferred";

export interface RelatedItem {
  id: string;
  title: string;
  type: string;
  href?: string | null;
  description?: string | null;
  meta?: string | null;
  relationship: string;
  strength: RelationshipStrength;
  source?: string | null;
  icon?: ReactNode;
}

export function AvatarLogo({
  name,
  imageUrl,
  imageAttribution,
  imageSource,
  type = "entity",
  className = "w-9 h-9",
  accent,
}: {
  name: string;
  imageUrl?: string | null;
  imageAttribution?: string | null;
  imageSource?: string | null;
  type?: "person" | "company" | "organization" | "department" | "regulator" | "source" | "entity";
  className?: string;
  accent?: string | null;
}) {
  const initials = initialsFor(name, type);
  if (imageUrl) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={imageUrl}
        alt={name}
        title={imageAttribution || imageSource || undefined}
        className={`${className} rounded object-cover bg-panel border border-line shrink-0`}
        loading="lazy"
      />
    );
  }
  return (
    <div
      className={`${className} rounded bg-panel flex items-center justify-center border border-line shrink-0`}
      style={{ color: accent || "var(--color-fg-dim)" }}
      aria-label={name}
    >
      <span className="mono text-[10px] font-bold">{initials}</span>
    </div>
  );
}

export function RelationshipBadge({ strength }: { strength: RelationshipStrength }) {
  const label = strength === "direct" ? "Direct" : strength === "supported" ? "Supported" : "Inferred";
  const color = strength === "inferred" ? "text-fg-dim border-line" : "text-brass-bright border-brass/40";
  return <span className={`mono text-[9px] uppercase tracking-wide border rounded px-1.5 py-0.5 ${color}`}>{label}</span>;
}

export function RelatedItems({
  title,
  items,
  empty = "No related items found.",
  right,
}: {
  title?: string;
  items: RelatedItem[];
  empty?: string;
  right?: ReactNode;
}) {
  return (
    <div className="space-y-2">
      {(title || right) && (
        <div className="flex items-center justify-between gap-2">
          {title && <h3 className="text-sm font-semibold text-fg-bright">{title}</h3>}
          {right}
        </div>
      )}
      {items.length ? (
        <ul className="space-y-1.5">
          {items.map((item) => (
            <li key={item.id}>
              <RelatedItemRow item={item} />
            </li>
          ))}
        </ul>
      ) : (
        <div className="text-sm text-fg-dim border border-line rounded bg-panel-2 px-3 py-2">{empty}</div>
      )}
    </div>
  );
}

function RelatedItemRow({ item }: { item: RelatedItem }) {
  const body = (
    <div className="rounded border border-line bg-panel-2 px-3 py-2 transition-colors group-hover:border-brass/40">
      <div className="flex items-start gap-2">
        {item.icon}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <SourceTag>{item.type}</SourceTag>
            <RelationshipBadge strength={item.strength} />
            <span className="mono text-[10px] text-fg-dim">{item.relationship}</span>
            {item.source && <span className="mono text-[10px] text-fg-dim">{item.source}</span>}
          </div>
          <div className="text-sm text-fg mt-1 group-hover:text-brass-bright transition-colors break-words">{item.title}</div>
          {item.description && <p className="text-xs text-fg-dim mt-1 line-clamp-2">{item.description}</p>}
          {item.meta && <div className="mono text-[10px] text-fg-dim mt-1">{item.meta}</div>}
        </div>
      </div>
    </div>
  );
  return item.href ? <Link href={item.href} className="group block">{body}</Link> : body;
}

function initialsFor(name: string, type: string): string {
  const clean = name.trim();
  if (!clean) {
    if (type === "regulator") return "REG";
    if (type === "department") return "DEPT";
    return "--";
  }
  const words = clean.split(/\s+/).filter(Boolean);
  if (type === "regulator") return "REG";
  if (type === "department") return "DEPT";
  return words.map((word) => word[0]).join("").slice(0, 2).toUpperCase();
}

type VisualIdentity = {
  label: string;
  short: string;
  color: string;
  sourceNote: string;
};

const PARTY_VISUALS: { match: string; label: string; short: string; color: string }[] = [
  { match: "liberal", label: "Liberal", short: "LPC", color: "#d71920" },
  { match: "conservative", label: "Conservative", short: "CPC", color: "#1a4782" },
  { match: "bloc", label: "Bloc Quebecois", short: "BQ", color: "#0098d4" },
  { match: "new democratic", label: "New Democratic", short: "NDP", color: "#f37021" },
  { match: "ndp", label: "New Democratic", short: "NDP", color: "#f37021" },
  { match: "green", label: "Green", short: "GPC", color: "#3d9b35" },
  { match: "independent", label: "Independent", short: "IND", color: "#44474d" },
];

const JURISDICTIONS: Record<string, string> = {
  AB: "Alberta",
  BC: "British Columbia",
  MB: "Manitoba",
  NB: "New Brunswick",
  NL: "Newfoundland and Labrador",
  NS: "Nova Scotia",
  NT: "Northwest Territories",
  NU: "Nunavut",
  ON: "Ontario",
  PE: "Prince Edward Island",
  QC: "Quebec",
  SK: "Saskatchewan",
  YT: "Yukon",
};

export function partyVisual(party?: string | null): VisualIdentity {
  const raw = (party || "").trim();
  const lower = raw.toLowerCase();
  const known = PARTY_VISUALS.find((item) => lower.includes(item.match));
  if (known) {
    return { ...known, sourceNote: "Generated party identity fallback; official party logo is not stored." };
  }
  return {
    label: raw || "Party unavailable",
    short: raw ? raw.split(/\s+/).map((word) => word[0]).join("").slice(0, 3).toUpperCase() : "NA",
    color: "#44474d",
    sourceNote: "Generated party identity fallback; official party logo is not stored.",
  };
}

export function jurisdictionVisual(code?: string | null, label?: string | null): VisualIdentity {
  const raw = (code || label || "").trim();
  const normalized = raw.toUpperCase();
  const jurisdictionLabel = JURISDICTIONS[normalized] || label || raw || "Jurisdiction unavailable";
  return {
    label: jurisdictionLabel,
    short: normalized && normalized.length <= 3 ? normalized : jurisdictionLabel.split(/\s+/).map((word) => word[0]).join("").slice(0, 3).toUpperCase(),
    color: "#1b2b48",
    sourceNote: "Generated jurisdiction symbol fallback; official flag or symbol is not stored.",
  };
}

export function PartyBadge({ party, compact = false }: { party?: string | null; compact?: boolean }) {
  const visual = partyVisual(party);
  return (
    <span
      className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded border font-label-caps text-label-caps uppercase"
      style={{ color: visual.color, borderColor: `${visual.color}33`, background: `${visual.color}14` }}
      title={visual.sourceNote}
      aria-label={`${visual.label} party visual identity`}
    >
      <span className="inline-flex min-w-[24px] h-[18px] items-center justify-center rounded-sm text-[9px] font-bold text-white" style={{ background: visual.color }}>
        {visual.short}
      </span>
      {!compact ? <span>{visual.label}</span> : null}
    </span>
  );
}

export function JurisdictionBadge({ code, label, compact = false }: { code?: string | null; label?: string | null; compact?: boolean }) {
  const visual = jurisdictionVisual(code, label);
  return (
    <span
      className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded border border-outline-variant bg-surface-container-low font-label-caps text-label-caps text-on-surface-variant uppercase"
      title={visual.sourceNote}
      aria-label={`${visual.label} jurisdiction visual identity`}
    >
      <span className="inline-flex min-w-[22px] h-[18px] items-center justify-center rounded-sm bg-primary text-on-primary text-[9px] font-bold">
        {visual.short}
      </span>
      {!compact ? <span>{visual.label}</span> : null}
    </span>
  );
}

export function DocumentThumbnail({
  title,
  type,
  source,
  date,
  url,
  className = "",
}: {
  title: string;
  type: string;
  source?: string | null;
  date?: string | null;
  url?: string | null;
  className?: string;
}) {
  const icon = documentIcon(type);
  const note = "Generated document thumbnail fallback; source document image is not stored.";
  return (
    <div className={`space-y-3 ${className}`}>
      <div
        className="aspect-[4/5] rounded-lg border border-outline-variant bg-surface-container-lowest p-4 shadow-sm flex flex-col"
        title={note}
        aria-label={`${type} document thumbnail fallback`}
      >
        <div className="flex items-center justify-between gap-2 mb-5">
          <SourceTag>{type}</SourceTag>
          <span className="material-symbols-outlined text-primary text-[22px]" aria-hidden="true">
            {icon}
          </span>
        </div>
        <div className="space-y-2 flex-1" aria-hidden="true">
          <div className="h-3 rounded bg-surface-container-high w-11/12" />
          <div className="h-3 rounded bg-surface-container-high w-8/12" />
          <div className="h-px bg-outline-variant my-4" />
          <div className="h-2 rounded bg-surface-container w-full" />
          <div className="h-2 rounded bg-surface-container w-10/12" />
          <div className="h-2 rounded bg-surface-container w-9/12" />
          <div className="h-2 rounded bg-surface-container w-11/12" />
        </div>
        <div className="mt-5 border-t border-outline-variant pt-3">
          <div className="font-label-caps text-label-caps text-on-surface-variant uppercase">Internal evidence</div>
          <div className="font-body-md text-body-md text-on-surface line-clamp-2 mt-1">{title}</div>
        </div>
      </div>
      <div className="rounded border border-outline-variant bg-surface-container-low px-3 py-2">
        <div className="font-data-tabular text-data-tabular text-on-surface-variant">
          {[source, date].filter(Boolean).join(" - ") || "Source metadata not available"}
        </div>
        <div className="font-data-tabular text-[11px] text-on-surface-variant mt-1">{note}</div>
        {url ? (
          <OriginalSourceLink href={url} className="mt-2" />
        ) : (
          <div className="mt-2 text-[12px] text-on-surface-variant">No original source URL is available.</div>
        )}
      </div>
    </div>
  );
}

function documentIcon(type: string): string {
  const lower = type.toLowerCase();
  if (lower.includes("bill") || lower.includes("legislation")) return "gavel";
  if (lower.includes("lobby")) return "record_voice_over";
  if (lower.includes("contract") || lower.includes("grant")) return "request_quote";
  if (lower.includes("statement") || lower.includes("news")) return "campaign";
  if (lower.includes("hansard") || lower.includes("intervention")) return "forum";
  if (lower.includes("regulation") || lower.includes("gazette")) return "rule";
  if (lower.includes("appointment")) return "badge";
  return "description";
}
