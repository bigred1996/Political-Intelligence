"use client";

import Link from "next/link";
import { AvatarLogo, RelatedItems, type RelatedItem } from "@/components/intelligence";
import { useApi } from "@/lib/use-api";
import type { FindingsResponse, GraphFinding } from "@/lib/api";
import { evidenceHref, findingHref, findingSlug, personHref, sectorHref, typeLabel } from "@/lib/navigation";

export default function EvidenceExplorer() {
  const { data, loading, error } = useApi<FindingsResponse>("/api/graph/findings");
  const findings = data?.findings ?? [];
  const selected = findings[0] ?? null;
  const nodes = buildExplorerNodes(findings);
  const evidenceItems = selected ? evidenceItemsFor(selected) : [];

  return (
    <div className="animate-rise -m-margin-mobile md:-m-margin-desktop flex flex-col h-[calc(100vh-4rem)]">
      <div className="flex items-center justify-between gap-4 px-margin-mobile md:px-margin-desktop py-3 border-b border-outline-variant bg-surface">
        <div className="flex items-center gap-4 min-w-0">
          <h1 className="font-headline-sm text-[20px] font-semibold text-primary shrink-0">Graph Explorer</h1>
          <div className="hidden md:flex gap-2 min-w-0">
            <FilterChip icon="dashboard" label={`${findings.length} findings`} />
            <FilterChip icon="verified" label="Internal evidence only" />
            <FilterChip icon="account_tree" label={`${nodes.length} nodes`} />
          </div>
        </div>
        <div className="flex gap-1">
          <Link href="/signals" className="w-9 h-9 grid place-items-center rounded bg-primary text-on-primary focus-ring" aria-label="Open live feed">
            <span className="material-symbols-outlined text-[20px]">rss_feed</span>
          </Link>
          <Link href="/records" className="w-9 h-9 grid place-items-center rounded border border-outline-variant text-on-surface-variant hover:bg-surface-container-low focus-ring" aria-label="Open records">
            <span className="material-symbols-outlined text-[20px]">table_rows</span>
          </Link>
        </div>
      </div>

      <div className="flex-1 grid grid-cols-1 lg:grid-cols-[320px_1fr] min-h-0">
        <aside className="border-r border-outline-variant bg-surface-bright p-4 space-y-5 overflow-y-auto">
          <div className="card-level-1 rounded-lg p-4">
            <span className="font-label-caps text-label-caps text-secondary uppercase">Selected finding</span>
            <h2 className="font-headline-sm text-headline-sm text-primary mt-1 mb-2 leading-tight">{selected?.title ?? "No active finding"}</h2>
            <p className="font-body-md text-body-md text-on-surface-variant">
              {selected?.summary || "Ingest source data to populate connected graph findings."}
            </p>
            {selected ? (
              <Link href={findingHref(selected) ?? "/signals"} className="mt-3 inline-flex text-body-md text-primary hover:underline focus-ring rounded">
                Open finding detail
              </Link>
            ) : null}
          </div>

          <div>
            <span className="font-label-caps text-label-caps text-on-surface-variant uppercase">Signal Strength</span>
            <div className="flex items-end gap-2 mt-3">
              {strengthBars(findings).map((bar) => (
                <div key={bar.label} className="flex-1 flex flex-col items-center gap-1">
                  <div className="w-full rounded-t" style={{ height: 40 * (bar.value / 100) + 8, background: bar.color }} />
                  <span className="font-label-caps text-[9px] text-on-surface-variant uppercase">{bar.label}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="card-level-1 rounded-lg overflow-hidden">
            <div className="bg-surface-container-low px-3 py-2 border-b border-outline-variant flex items-center justify-between">
              <span className="font-label-caps text-label-caps text-on-surface-variant uppercase">Material findings</span>
              <span className="w-2 h-2 rounded-full bg-error" />
            </div>
            <ul className="divide-y divide-outline-variant">
              {findings.slice(0, 5).map((finding, index) => (
                <li key={findingSlug(finding) ?? `${finding.title}-${index}`} className="p-3">
                  <Link href={findingHref(finding) ?? "/signals"} className="block focus-ring rounded">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="material-symbols-outlined text-primary text-[16px]">hub</span>
                      <span className="text-body-md font-bold text-primary line-clamp-1">{finding.title}</span>
                      <span className={severityClass(finding.severity)}>{finding.severity}</span>
                    </div>
                    <p className="text-[12px] text-on-surface-variant line-clamp-2">{finding.summary}</p>
                  </Link>
                </li>
              ))}
              {!findings.length && <li className="p-3 text-body-md text-on-surface-variant">No findings available.</li>}
            </ul>
          </div>

          <RelatedItems title="Selected evidence" items={evidenceItems} empty="No evidence selected." />
        </aside>

        <div className="relative bg-surface-container-low overflow-hidden">
          <div className="absolute inset-0" style={{ backgroundImage: "radial-gradient(#c5c6ce 1px, transparent 1px)", backgroundSize: "24px 24px", opacity: 0.4 }} />
          <svg className="absolute inset-0 w-full h-full pointer-events-none" aria-hidden="true">
            {nodes.slice(1, 18).map((node) => (
              <line key={`${node.id}-edge`} x1="50%" y1="50%" x2={`${node.x}%`} y2={`${node.y}%`} stroke={node.type === "record" ? "#75777e" : "#ba1a1a"} strokeDasharray={node.type === "record" ? "4 4" : undefined} strokeWidth="1.5" />
            ))}
          </svg>

          {nodes.slice(0, 18).map((node, index) => <GraphNode key={node.id} node={node} primary={index === 0} />)}

          {loading ? <div className="absolute inset-x-6 top-6 skeleton h-12" /> : null}
          {error ? <div className="absolute left-6 right-6 top-6 rounded border border-error/30 bg-error/10 text-error px-4 py-3">{error}</div> : null}

          <div className="absolute bottom-4 right-4 glass-panel rounded-lg p-3 space-y-2">
            {[
              ["Finding", "#041632"],
              ["Evidence record", "#d0e1fb"],
              ["Actor / sector", "#ffdad6"],
            ].map(([label, color]) => (
              <div key={label} className="flex items-center gap-2 font-label-caps text-label-caps text-on-surface uppercase">
                <span className="w-3 h-3 rounded-full" style={{ background: color }} /> {label}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

type ExplorerNode = {
  id: string;
  label: string;
  type: "finding" | "record" | "actor" | "sector";
  href: string | null;
  x: number;
  y: number;
};

function buildExplorerNodes(findings: GraphFinding[]): ExplorerNode[] {
  const nodes: ExplorerNode[] = [];
  const selected = findings[0];
  if (selected) {
    nodes.push({ id: `finding-${findingSlug(selected) ?? selected.title}`, label: selected.title, type: "finding", href: findingHref(selected), x: 50, y: 50 });
  }
  const seen = new Set(nodes.map((node) => node.id));
  const radial = [...findings.flatMap((finding) => [
    ...(finding.references ?? []).slice(0, 3).map((ref) => ({
      id: `record-${ref.table}-${ref.pk ?? ref.id}`,
      label: ref.title,
      type: "record" as const,
      href: evidenceHref(ref),
    })),
    ...(finding.actors ?? []).slice(0, 2).map((actor) => ({
      id: `actor-${actor.slug ?? actor.name ?? actor.label}`,
      label: String(actor.name ?? actor.label ?? "Political actor"),
      type: "actor" as const,
      href: personHref(typeof actor.slug === "string" ? actor.slug : null),
    })),
    ...[finding.sector, ...finding.related_sectors].filter(Boolean).slice(0, 2).map((sector) => ({
      id: `sector-${(sector as { slug: string }).slug}`,
      label: (sector as { name: string }).name,
      type: "sector" as const,
      href: sectorHref((sector as { slug: string }).slug),
    })),
  ])];

  for (const item of radial) {
    if (seen.has(item.id)) continue;
    seen.add(item.id);
    const i = nodes.length;
    const angle = (i / 16) * Math.PI * 2 - Math.PI / 2;
    const radius = i % 3 === 0 ? 32 : i % 3 === 1 ? 24 : 38;
    nodes.push({
      ...item,
      x: Math.max(8, Math.min(92, 50 + Math.cos(angle) * radius)),
      y: Math.max(10, Math.min(90, 50 + Math.sin(angle) * radius)),
    });
  }
  return nodes;
}

function GraphNode({ node, primary }: { node: ExplorerNode; primary: boolean }) {
  const body = (
    <div
      className={`${primary ? "w-24 h-24 rounded-lg bg-primary text-on-primary" : node.type === "record" ? "w-14 h-14 rounded-lg bg-secondary-container text-secondary border border-secondary/40" : "w-14 h-14 rounded-full bg-error-container text-error border border-error/40"} flex items-center justify-center shadow-sm`}
      title={node.label}
    >
      <span className="material-symbols-outlined text-[24px]">{nodeIcon(node.type)}</span>
    </div>
  );
  return (
    <div className="absolute -translate-x-1/2 -translate-y-1/2 group" style={{ left: `${node.x}%`, top: `${node.y}%` }}>
      {node.href ? <Link href={node.href} className="block focus-ring rounded">{body}</Link> : body}
      <div className="absolute top-full left-1/2 -translate-x-1/2 mt-2 hidden group-hover:block w-44 rounded border border-outline-variant bg-surface-container-lowest px-2 py-1 text-[11px] text-on-surface shadow-sm">
        <span className="font-label-caps text-label-caps text-on-surface-variant uppercase">{node.type}</span>
        <div className="line-clamp-2">{node.label}</div>
      </div>
    </div>
  );
}

function evidenceItemsFor(finding: GraphFinding): RelatedItem[] {
  return finding.references.slice(0, 5).map((ref) => ({
    id: `${ref.table}-${ref.pk ?? ref.id}`,
    title: ref.title,
    type: typeLabel(ref.table),
    href: evidenceHref(ref),
    description: ref.date ?? null,
    meta: ref.source,
    relationship: "finding supported by record",
    strength: "supported",
    icon: <AvatarLogo name={ref.source} type="source" />,
  }));
}

function strengthBars(findings: GraphFinding[]) {
  const high = findings.filter((f) => f.severity === "high").length;
  const elevated = findings.filter((f) => f.severity === "elevated").length;
  const watch = findings.filter((f) => f.severity === "watch").length;
  const low = findings.filter((f) => f.severity === "low").length;
  const max = Math.max(high, elevated, watch, low, 1);
  return [
    { label: "High", value: (high / max) * 100, color: "#ba1a1a" },
    { label: "Elev", value: (elevated / max) * 100, color: "#d97706" },
    { label: "Watch", value: (watch / max) * 100, color: "#041632" },
    { label: "Low", value: (low / max) * 100, color: "#75777e" },
  ];
}

function nodeIcon(type: ExplorerNode["type"]) {
  if (type === "record") return "description";
  if (type === "actor") return "person";
  if (type === "sector") return "category";
  return "hub";
}

function severityClass(severity: string) {
  if (severity === "high" || severity === "elevated") return "font-label-caps text-label-caps status-chip-red px-1.5 py-0.5 rounded uppercase ml-auto";
  if (severity === "watch") return "font-label-caps text-label-caps status-chip-amber px-1.5 py-0.5 rounded uppercase ml-auto";
  return "font-label-caps text-label-caps status-chip-green px-1.5 py-0.5 rounded uppercase ml-auto";
}

function FilterChip({ icon, label }: { icon: string; label: string }) {
  return (
    <div className="flex items-center gap-1.5 px-3 py-1.5 rounded border border-outline-variant text-body-md text-on-surface bg-surface-container-low">
      <span className="material-symbols-outlined text-[16px] text-on-surface-variant">{icon}</span>
      {label}
    </div>
  );
}
