"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { AvatarLogo, JurisdictionBadge, PartyBadge } from "@/components/intelligence";
import { type PoliticiansResponse } from "@/lib/api";
import { useApi } from "@/lib/use-api";

/* Political Players — directory grid wired to /api/politicians (343 MPs). */

export default function PoliticiansIndex() {
  const { data, loading } = useApi<PoliticiansResponse>("/api/politicians");
  const [party, setParty] = useState("All Parties");

  const facets = useMemo(() => ["All Parties", ...(data?.parties ?? []).map((p) => p.party).filter(Boolean)], [data]);
  const mps = useMemo(() => {
    const list = data?.politicians ?? [];
    return party === "All Parties" ? list : list.filter((m) => m.party === party);
  }, [data, party]);

  return (
    <div className="animate-rise">
      <div className="mb-gutter pb-density-comfortable border-b border-outline-variant">
        <h1 className="font-display-lg text-display-lg text-primary">Political Players</h1>
        <p className="font-body-lg text-body-lg text-on-surface-variant mt-unit max-w-2xl">
          {data ? `${data.count} Members of Parliament` : "Members of Parliament"} shaping the regulatory landscape — sponsored bills, interventions, and industries touched.
        </p>
      </div>

      <div className="flex flex-wrap gap-2 mb-gutter">
        {facets.slice(0, 7).map((f) => (
          <button
            key={f}
            onClick={() => setParty(f)}
            className={`px-3 py-1.5 rounded-full font-body-md text-body-md transition-colors ${
              f === party ? "bg-primary text-on-primary" : "bg-surface-container text-on-surface-variant hover:bg-surface-container-high"
            }`}
          >
            {f}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-gutter">
        {loading && !data
          ? Array.from({ length: 9 }).map((_, i) => <div key={i} className="card-level-1 rounded-lg p-density-comfortable h-[108px] skeleton" />)
          : mps.slice(0, 60).map((p) => {
              return (
                <Link key={p.slug} href={`/politicians/${p.slug}`} className="card-level-1 card-level-2 rounded-lg p-density-comfortable flex items-start gap-4 focus-ring">
                  <AvatarLogo name={p.name} imageUrl={p.photo_url} imageAttribution={p.photo_attribution} imageSource={p.photo_source} type="person" className="w-14 h-14 rounded-full" />
                  <div className="flex-1 min-w-0">
                    <h2 className="font-headline-sm text-[18px] text-primary leading-tight truncate">{p.name}</h2>
                    <p className="font-body-md text-body-md text-on-surface-variant mb-2 truncate">{p.role ?? p.party}</p>
                    <div className="flex flex-wrap items-center gap-2">
                      <PartyBadge party={p.party} compact />
                      {p.riding && <span className="font-data-tabular text-data-tabular text-on-surface-variant truncate">{p.riding}</span>}
                      {p.photo_source && <span className="font-data-tabular text-data-tabular text-on-surface-variant truncate">Portrait: {p.photo_source}</span>}
                    </div>
                  </div>
                  {p.province && <JurisdictionBadge code={p.province} compact />}
                </Link>
              );
            })}
      </div>
    </div>
  );
}
