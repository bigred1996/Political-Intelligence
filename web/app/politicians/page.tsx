"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useApi } from "@/lib/use-api";
import { partyColor, type PoliticiansResponse } from "@/lib/api";
import { Eyebrow, EmptyState, Panel, SkeletonBlock } from "@/components/ui";

export default function PoliticiansPage() {
  const [party, setParty] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const { data, loading } = useApi<PoliticiansResponse>("/api/politicians");

  const filtered = useMemo(() => {
    if (!data) return [];
    const needle = q.trim().toLowerCase();
    return data.politicians.filter(
      (p) =>
        (!party || p.party === party) &&
        (!needle ||
          p.name.toLowerCase().includes(needle) ||
          (p.riding || "").toLowerCase().includes(needle))
    );
  }, [data, party, q]);

  return (
    <div>
      <section className="bg-panel border-b border-line map-grid">
        <div className="mx-auto max-w-[1320px] px-4 py-8">
          <Eyebrow>Political players</Eyebrow>
          <h1 className="text-2xl md:text-3xl font-semibold text-fg-bright mt-2">
            The people who shape every industry.
          </h1>
          <p className="text-fg-dim mt-2 max-w-2xl text-sm">
            Every federal Member of Parliament — the sponsors, regulators and voices behind the
            contracts, bills and rules that move each sector.
          </p>
          <div className="mt-5 flex flex-col sm:flex-row gap-2.5 max-w-2xl">
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search by name or riding…"
              aria-label="Search politicians"
              className="flex-1 bg-canvas border border-line rounded px-4 py-2.5 text-fg placeholder:text-fg-dim outline-none focus:border-brass/60 transition-colors mono text-sm"
            />
          </div>
          {data && (
            <div className="flex flex-wrap gap-1.5 mt-3">
              <Chip active={party === null} onClick={() => setParty(null)} label={`All ${data.count}`} />
              {data.parties.map((p) => (
                <Chip
                  key={p.party}
                  active={party === p.party}
                  onClick={() => setParty(party === p.party ? null : p.party)}
                  label={`${p.party} ${p.count}`}
                  color={partyColor(p.party)}
                />
              ))}
            </div>
          )}
        </div>
      </section>

      <div className="mx-auto max-w-[1320px] px-4 py-6">
        {loading && (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3">
            {Array.from({ length: 15 }).map((_, i) => <SkeletonBlock key={i} className="h-44 rounded" />)}
          </div>
        )}
        {!loading && (
          <>
            <div className="mono text-xs text-fg-dim mb-3">{filtered.length} representatives</div>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3">
              {filtered.map((p) => (
                <Link
                  key={p.slug}
                  href={`/politicians/${p.slug}`}
                  className="panel p-0 overflow-hidden hover:border-brass/50 transition-colors group"
                >
                  <div className="aspect-[3/3.4] bg-panel-2 overflow-hidden relative">
                    {p.photo_url ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={p.photo_url} alt={p.name} loading="lazy"
                        className="w-full h-full object-cover object-top grayscale-[35%] group-hover:grayscale-0 transition-all" />
                    ) : (
                      <div className="w-full h-full flex items-center justify-center text-fg-dim mono text-2xl">
                        {p.name.split(" ").map((w) => w[0]).slice(0, 2).join("")}
                      </div>
                    )}
                    <span className="absolute top-0 left-0 w-1 h-full" style={{ background: partyColor(p.party) }} />
                  </div>
                  <div className="p-2.5">
                    <div className="text-sm font-medium text-fg group-hover:text-brass-bright transition-colors leading-tight truncate">{p.name}</div>
                    <div className="mono text-[10px] text-fg-dim mt-1 truncate">{p.riding || "—"}</div>
                    <div className="mono text-[10px] mt-0.5 truncate" style={{ color: partyColor(p.party) }}>{p.party || "Independent"}</div>
                  </div>
                </Link>
              ))}
            </div>
            {!filtered.length && <EmptyState>No politicians match.</EmptyState>}
          </>
        )}
      </div>
    </div>
  );
}

function Chip({ active, onClick, label, color }: { active: boolean; onClick: () => void; label: string; color?: string }) {
  return (
    <button
      onClick={onClick}
      className={`mono text-xs rounded px-2.5 py-1 border transition-colors cursor-pointer ${
        active ? "border-brass/60 text-fg bg-brass/10" : "border-line text-fg-dim hover:text-fg"
      }`}
      style={active && color ? { borderColor: color, color } : undefined}
    >
      {label}
    </button>
  );
}
