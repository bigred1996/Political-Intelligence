"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import type { SectorsResponse } from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { Eyebrow } from "@/components/ui";

const SUGGESTED = [
  "telus", "rogers", "bce", "suncor energy", "enbridge", "imperial oil",
  "barrick gold", "teck resources", "cameco", "royal bank of", "loblaw", "bombardier",
];

export default function EntitiesIndex() {
  const router = useRouter();
  const [q, setQ] = useState("");
  const { data } = useApi<SectorsResponse>("/api/sectors");

  function go(name: string) {
    if (name.trim()) router.push(`/entities/${encodeURIComponent(name.trim().toLowerCase())}`);
  }

  return (
    <div>
      <section className="bg-panel border-b border-line map-grid">
        <div className="mx-auto max-w-[1320px] px-4 py-12">
          <Eyebrow>Entity Intelligence</Eyebrow>
          <h1 className="text-3xl font-semibold text-fg-bright mt-2 max-w-2xl leading-tight">
            Look up a company&rsquo;s federal footprint.
          </h1>
          <p className="text-fg-dim mt-2 max-w-xl text-sm">
            One synthesized profile — contracts, lobbying, contributions, legislation and regulatory
            exposure — with the connections that matter for diligence.
          </p>
          <form onSubmit={(e) => { e.preventDefault(); go(q); }} className="mt-6 flex flex-col sm:flex-row gap-2.5 max-w-xl">
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              aria-label="Company name"
              placeholder="Company name, e.g. TELUS, Enbridge, Loblaw"
              className="flex-1 bg-canvas border border-line rounded px-4 py-3 text-fg placeholder:text-fg-dim outline-none focus:border-brass/60 transition-colors mono text-sm"
            />
            <button type="submit" className="rounded bg-brass text-canvas font-semibold px-6 py-3 hover:bg-brass-bright transition-colors cursor-pointer">
              Profile
            </button>
          </form>
        </div>
      </section>

      <div className="mx-auto max-w-[1320px] px-4 py-9">
        <Eyebrow>Frequently tracked</Eyebrow>
        <div className="flex flex-wrap gap-2 mt-3">
          {SUGGESTED.map((s) => (
            <Link key={s} href={`/entities/${encodeURIComponent(s)}`} className="capitalize mono text-[13px] border border-line rounded px-3 py-1.5 text-fg hover:border-brass/60 hover:text-brass-bright transition-colors bg-panel">
              {s}
            </Link>
          ))}
        </div>
        {data && (
          <div className="mt-9">
            <Eyebrow>Or browse by sector</Eyebrow>
            <div className="flex flex-wrap gap-x-4 gap-y-2 mt-3">
              {data.sectors.map((s) => (
                <Link key={s.slug} href={`/sectors/${s.slug}`} className="text-sm text-brass-bright hover:underline">{s.name}</Link>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
