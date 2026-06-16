"use client";

import type { SectorsResponse } from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { SectorCard } from "@/components/sector-card";
import { Eyebrow, SkeletonBlock } from "@/components/ui";

export default function SectorsIndex() {
  const { data, loading } = useApi<SectorsResponse>("/api/sectors");
  return (
    <div className="mx-auto max-w-[1180px] px-5 py-12">
      <Eyebrow num="02">Sector Intelligence</Eyebrow>
      <h1 className="font-display text-3xl text-navy mt-2 mb-2">Industries under watch</h1>
      <p className="text-slate max-w-2xl mb-8">
        Each sector view rolls up the full federal footprint — contracts, lobbying, legislation,
        regulation and operations — into a single risk read and the connections that matter.
        Filter any sector by province once inside.
      </p>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {loading
          ? Array.from({ length: 8 }).map((_, i) => <SkeletonBlock key={i} className="h-36 rounded-xl" />)
          : data?.sectors.map((s) => <SectorCard key={s.slug} s={s} />)}
      </div>
    </div>
  );
}
