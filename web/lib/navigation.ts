import type { EvidenceRef, IntelligenceFinding } from "@/lib/api";

export type NessusType =
  | "finding"
  | "record"
  | "sector"
  | "entity"
  | "person"
  | "organization"
  | "committee"
  | "source"
  | "report";

export interface TypeRegistryEntry {
  key: string;
  label: string;
  plural: string;
  type: NessusType;
  aliases?: string[];
  sourceLabel?: string;
}

export const TYPE_REGISTRY: TypeRegistryEntry[] = [
  { key: "findings", label: "Finding", plural: "Findings", type: "finding" },
  { key: "signals", label: "Signal", plural: "Signals", type: "finding" },
  { key: "contracts", label: "Federal contract", plural: "Federal contracts", type: "record", sourceLabel: "Open Government contracts" },
  { key: "donations", label: "Political donation", plural: "Political donations", type: "record", sourceLabel: "Elections Canada" },
  { key: "grants", label: "Grant or contribution", plural: "Grants & contributions", type: "record", sourceLabel: "Open Government grants" },
  { key: "lobbying", label: "Lobbying communication", plural: "Lobbying communications", type: "record", aliases: ["lobby", "lobbying_records"], sourceLabel: "OCL Lobbying Registry" },
  { key: "ocl_registrations", label: "Lobbying registration", plural: "Lobbying registrations", type: "record", sourceLabel: "OCL Lobbying Registry" },
  { key: "bills", label: "Bill", plural: "Bills & legislation", type: "record", sourceLabel: "LEGISinfo" },
  { key: "gazette", label: "Regulation", plural: "Canada Gazette", type: "record", aliases: ["gazette_entries"], sourceLabel: "Canada Gazette" },
  { key: "tribunal", label: "Tribunal decision", plural: "Tribunal decisions", type: "record", aliases: ["tribunal_decisions"], sourceLabel: "Administrative tribunals" },
  { key: "appointments", label: "GIC appointment", plural: "GIC appointments", type: "record", sourceLabel: "Governor in Council appointments" },
  { key: "hansard_mentions", label: "House intervention", plural: "House interventions", type: "record", sourceLabel: "Hansard" },
  { key: "hansard_speeches", label: "Hansard transcript", plural: "Hansard transcripts", type: "record", sourceLabel: "Hansard (full text)" },
  { key: "source_records", label: "Source record", plural: "Source records", type: "record" },
  { key: "social_statements", label: "Public statement", plural: "Public statements", type: "record", aliases: ["public_statements", "social_posts"], sourceLabel: "Public statements" },
  { key: "reports", label: "Report", plural: "Reports", type: "report", aliases: ["briefings"] },
  { key: "sectors", label: "Sector", plural: "Sectors", type: "sector" },
  { key: "entities", label: "Entity", plural: "Entities", type: "entity" },
  { key: "meetings", label: "Meeting", plural: "Meetings", type: "record", aliases: ["communications", "contacts"] },
  { key: "politicians", label: "Political figure", plural: "Political figures", type: "person" },
  { key: "senators", label: "Senator", plural: "Senators", type: "person" },
  { key: "ministers", label: "Minister", plural: "Ministers", type: "person" },
  { key: "committees", label: "Committee", plural: "Committees", type: "committee" },
  { key: "departments", label: "Department", plural: "Departments", type: "organization" },
  { key: "regulators", label: "Regulator", plural: "Regulators", type: "organization" },
  { key: "organizations", label: "Organization", plural: "Organizations", type: "organization" },
  { key: "sources", label: "Source", plural: "Sources", type: "source" },
];

const ENTRY_BY_KEY = new Map<string, TypeRegistryEntry>();
for (const entry of TYPE_REGISTRY) {
  ENTRY_BY_KEY.set(entry.key, entry);
  for (const alias of entry.aliases ?? []) ENTRY_BY_KEY.set(alias, entry);
}

export function registryEntry(key?: string | null): TypeRegistryEntry | null {
  return key ? ENTRY_BY_KEY.get(key) ?? null : null;
}

export function canonicalType(key?: string | null): string | null {
  return registryEntry(key)?.key ?? key ?? null;
}

export function typeLabel(key?: string | null, plural = false): string {
  const entry = registryEntry(key);
  if (entry) return plural ? entry.plural : entry.label;
  return (key || "Unsupported").replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

export function recordHref(table: string | undefined | null, pk: number | string | undefined | null): string | null {
  if (!table || pk == null || pk === "") return null;
  const canonical = canonicalType(table) ?? table;
  if (canonical === "meetings") return meetingHref(pk);
  return `/records/${encodeURIComponent(canonical)}/${encodeURIComponent(String(pk))}`;
}

export function meetingHref(id?: number | string | null): string | null {
  return id == null || id === "" ? null : `/meetings/${encodeURIComponent(String(id))}`;
}

export function evidenceHref(ref?: Pick<EvidenceRef, "table" | "id" | "pk"> | null): string | null {
  return ref ? recordHref(ref.table, ref.pk ?? ref.id) : null;
}

export function entityHref(name?: string | null): string | null {
  return name ? `/entities/${encodeURIComponent(name)}` : null;
}

export function sectorHref(slug?: string | null): string | null {
  return slug ? `/sectors/${encodeURIComponent(slug)}` : null;
}

export function personHref(slug?: string | null): string | null {
  return slug ? `/politicians/${encodeURIComponent(slug)}` : null;
}

export function senatorHref(slug?: string | null): string | null {
  return slug ? `/senators/${encodeURIComponent(slug)}` : null;
}

export function ministerHref(slug?: string | null): string | null {
  return slug ? `/ministers/${encodeURIComponent(slug)}` : null;
}

export function organizationHref(kind: "department" | "regulator" | "organization", name?: string | null): string | null {
  return name ? `/organizations/${encodeURIComponent(kind)}/${encodeURIComponent(name)}` : null;
}

export function committeeHref(slug?: string | null): string | null {
  return slug ? `/committees/${encodeURIComponent(slug)}` : null;
}

export function sourceHref(id?: string | null): string | null {
  return id ? `/sources/${encodeURIComponent(id)}` : null;
}

export function reportHref(id?: string | null): string | null {
  return id ? `/briefings/${encodeURIComponent(id)}` : null;
}

export function slugifyFindingTitle(title: string): string {
  return title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 96) || "finding";
}

type FindingLike = Pick<IntelligenceFinding, "title"> & {
  sector?: { slug?: string | null } | null;
  primary_sector?: { slug?: string | null } | null;
};

export function findingSlug(finding: FindingLike | string | null | undefined): string | null {
  const title = typeof finding === "string" ? finding : finding?.title;
  if (!title) return null;
  const sector = typeof finding === "object" && finding ? finding.sector?.slug ?? finding.primary_sector?.slug ?? null : null;
  return slugifyFindingTitle(sector ? `${title} ${sector}` : title);
}

export function legacyFindingSlug(finding: Pick<IntelligenceFinding, "title"> | string | null | undefined): string | null {
  const title = typeof finding === "string" ? finding : finding?.title;
  return title ? slugifyFindingTitle(title) : null;
}

export function findingHref(finding: FindingLike | string | null | undefined): string | null {
  const slug = findingSlug(finding);
  return slug ? `/signals/${encodeURIComponent(slug)}` : null;
}

export function sourceLabel(table?: string | null, fallback?: string | null): string {
  return registryEntry(table)?.sourceLabel ?? fallback ?? "Original source";
}
