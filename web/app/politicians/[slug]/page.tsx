"use client";

import Link from "next/link";
import { use } from "react";
import { useSearchParams } from "next/navigation";
import { AvatarLogo, JurisdictionBadge, PartyBadge, RelatedItems, type RelatedItem } from "@/components/intelligence";
import { OriginalSourceLink } from "@/components/ui";
import { useApi } from "@/lib/use-api";
import { type PoliticianDetail } from "@/lib/api";
import { committeeHref, recordHref, sectorHref } from "@/lib/navigation";

export default function MPProfile({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  const searchParams = useSearchParams();
  const context = politicianContext(searchParams);
  const { data: mp, loading, error } = useApi<PoliticianDetail>(`/api/politicians/${encodeURIComponent(slug)}`);

  if (loading) return <ProfileSkeleton />;
  if (error) return <Message tone="error">{error}</Message>;
  if (!mp) return <Message>Political profile not found.</Message>;

  const billItems = mp.bills.slice(0, 8).map((bill): RelatedItem => ({
    id: `bill-${bill.pk}`,
    title: `${bill.bill_number} - ${bill.title}`,
    type: "Bill",
    href: withContext(recordHref(bill.table, bill.pk), context),
    description: [bill.status, bill.date].filter(Boolean).join(" - ") || null,
    relationship: "person mentioned bill",
    strength: "direct",
  }));
  const sectorItems = mp.industries.map((sector): RelatedItem => ({
    id: `sector-${sector.slug}`,
    title: sector.name,
    type: "Sector",
    href: withContext(sectorHref(sector.slug), context),
    relationship: "person connected to sector finding",
    strength: "supported",
  }));
  const speechItems = mp.speeches.slice(0, 8).map((speech, index): RelatedItem => ({
    id: `speech-${index}`,
    title: speech.keyword,
    type: "House intervention",
    href: withContext(recordHref(speech.table, speech.pk), context),
    description: speech.excerpt,
    meta: [speech.date, speech.url ? "Original source available on evidence record" : null].filter(Boolean).join(" - "),
    relationship: "person connected to record",
    strength: "supported",
  }));
  const committeeItems = committeeItemsFor(mp, context);

  return (
    <div className="animate-rise">
      <div className="flex items-center gap-2 text-on-surface-variant mb-6 font-label-caps text-label-caps uppercase tracking-wider">
        <Link className="hover:text-primary transition-colors focus-ring rounded" href={context?.href ?? "/politicians"}>{context?.label ?? "Intelligence"}</Link>
        <span className="material-symbols-outlined text-[14px]">chevron_right</span>
        <Link className="hover:text-primary transition-colors focus-ring rounded" href="/politicians">Parliament</Link>
        <span className="material-symbols-outlined text-[14px]">chevron_right</span>
        <span className="text-primary font-bold">Profile: {mp.name}</span>
      </div>
      {context ? <InvestigationContext context={context} /> : null}

      <div className="bg-surface-container-lowest border border-outline-variant rounded-lg overflow-hidden mb-8">
        <div className="h-1 w-full bg-primary" />
        <div className="p-8 flex flex-col md:flex-row gap-8 items-start">
          <div className="shrink-0 relative">
            <AvatarLogo
              name={mp.name}
              imageUrl={mp.photo_url}
              imageAttribution={mp.photo_attribution}
              imageSource={mp.photo_source}
              type="person"
              className="w-32 h-32 md:w-40 md:h-40 rounded-full"
            />
            <div className="mt-3 text-center font-data-tabular text-data-tabular text-on-surface-variant">
              Portrait: {mp.photo_source ?? "not available"}
            </div>
            {mp.photo_source_url ? (
              <OriginalSourceLink href={mp.photo_source_url} label="View portrait source" className="mt-1 w-full justify-center font-data-tabular text-[11px]" />
            ) : null}
          </div>

          <div className="flex-1">
            <div className="flex flex-col md:flex-row md:justify-between md:items-start gap-4">
              <div>
                <h1 className="font-headline-md text-headline-md text-on-surface mb-1">{mp.name}</h1>
                <p className="font-body-lg text-body-lg text-on-surface-variant mb-3">{mp.role ?? "Member of Parliament"}</p>
                <div className="flex flex-wrap items-center gap-3">
                  <PartyBadge party={mp.party} />
                  {mp.province ? <JurisdictionBadge code={mp.province} /> : null}
                  {mp.riding ? <Badge icon="location_on">{mp.riding}</Badge> : null}
                  {mp.since_date ? <Badge icon="calendar_today">In office since {mp.since_date}</Badge> : null}
                </div>
              </div>
              <div className="flex gap-4 md:text-right border-l border-outline-variant pl-4 md:pl-6">
                <div className="flex flex-col">
                  <span className="font-label-caps text-label-caps text-on-surface-variant uppercase mb-1">Connected evidence</span>
                  <span className="font-headline-sm text-headline-sm text-primary flex items-center gap-1 md:justify-end">
                    {mp.bills.length + mp.speeches.length}
                  </span>
                  <span className="text-xs text-on-surface-variant mt-1 flex items-center gap-1 md:justify-end">
                    <span className="material-symbols-outlined text-primary text-[14px]">hub</span> bills and interventions
                  </span>
                </div>
              </div>
            </div>
            <div className="mt-6 font-memo-body text-memo-body text-on-surface-variant max-w-3xl leading-relaxed">
              {mp.summary}
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-gutter">
        <div className="lg:col-span-8 flex flex-col gap-gutter">
          <section className="bg-surface-container-lowest border border-outline-variant rounded-lg overflow-hidden">
            <div className="bg-surface-container-low px-6 py-4 border-b border-outline-variant flex justify-between items-center">
              <h2 className="font-headline-sm text-[20px] font-semibold text-on-surface">Sector Focus &amp; Connected Evidence</h2>
              <Link href={`/search?q=${encodeURIComponent(mp.name)}`} className="text-sm text-primary hover:underline font-medium focus-ring rounded">Search activity</Link>
            </div>
            <div className="p-6 grid grid-cols-1 md:grid-cols-2 gap-8">
              <RelatedItems title="Affected sectors" items={sectorItems} empty="No sector connections detected yet." />
              <RelatedItems title="Committee context" items={committeeItems} empty="No committee context inferred yet." />
            </div>
          </section>

          <section className="bg-surface-container-lowest border border-outline-variant rounded-lg overflow-hidden">
            <div className="bg-surface-container-low px-6 py-4 border-b border-outline-variant flex justify-between items-center">
              <h2 className="font-headline-sm text-[20px] font-semibold text-on-surface">Active Legislative Chain</h2>
              <Link href="/records" className="text-sm text-primary hover:underline font-medium focus-ring rounded">View all records</Link>
            </div>
            <div className="p-density-comfortable">
              <RelatedItems items={billItems} empty="No sponsored bills are linked to this profile yet." />
            </div>
          </section>

          <section className="bg-surface-container-lowest border border-outline-variant rounded-lg overflow-hidden">
            <div className="bg-surface-container-low px-6 py-4 border-b border-outline-variant">
              <h2 className="font-headline-sm text-[20px] font-semibold text-on-surface">House Intervention Timeline</h2>
            </div>
            <div className="p-density-comfortable">
              <RelatedItems items={speechItems} empty="No Hansard interventions are linked to this profile yet." />
            </div>
          </section>
        </div>

        <div className="lg:col-span-4 flex flex-col gap-gutter">
          <section className="bg-surface-container-lowest border border-outline-variant rounded-lg overflow-hidden relative shadow-sm">
            <div className="absolute top-0 left-0 right-0 h-0.5 bg-primary" />
            <div className="p-6">
              <h2 className="font-headline-sm text-[20px] font-semibold text-on-surface mb-1">Profile Data</h2>
              <p className="font-body-md text-body-md text-on-surface-variant mb-6">Important normalized fields</p>
              <div className="space-y-4">
                <Fact label="Party" value={mp.party ?? "Unknown"} />
                <Fact label="Riding" value={mp.riding ?? "Unknown"} />
                <Fact label="Province" value={mp.province ?? "Unknown"} />
                <Fact label="Email" value={mp.email ?? "Not published"} />
              </div>
            </div>
          </section>

          <section className="bg-surface-container-lowest border border-outline-variant rounded-lg p-6">
            <h2 className="font-headline-sm text-[20px] font-semibold text-on-surface mb-4">Original Sources</h2>
            <ul className="space-y-3">
              {mp.openparliament_url ? <SourceLink href={mp.openparliament_url} label="OpenParliament profile" /> : null}
              {mp.commons_url ? <SourceLink href={mp.commons_url} label="House of Commons profile" /> : null}
              {!mp.openparliament_url && !mp.commons_url ? <li className="text-body-md text-on-surface-variant">No original source URL is available.</li> : null}
            </ul>
          </section>
        </div>
      </div>
    </div>
  );
}

type PoliticianContextValue =
  | { from: "search"; label: string; href: string }
  | { from: "sector"; label: string; href: string }
  | { from: "finding"; label: string; href: string }
  | null;

function politicianContext(searchParams: ReturnType<typeof useSearchParams>): PoliticianContextValue {
  const from = searchParams.get("from");
  if (from === "search") {
    const q = searchParams.get("q") ?? "";
    return { from, label: q ? `Back to search: ${q}` : "Back to search", href: `/search${q ? `?q=${encodeURIComponent(q)}` : ""}` };
  }
  if (from === "sector") {
    const sector = searchParams.get("sector") ?? "";
    return { from, label: sector ? `Back to sector: ${sector}` : "Back to sector", href: sector ? `/sectors/${encodeURIComponent(sector)}` : "/sectors" };
  }
  if (from === "finding") {
    const finding = searchParams.get("finding") ?? "";
    return { from, label: "Back to finding", href: finding ? `/signals/${encodeURIComponent(finding)}` : "/signals" };
  }
  return null;
}

function withContext(href: string | null, context: PoliticianContextValue): string | null {
  if (!href || !context) return href;
  const glue = href.includes("?") ? "&" : "?";
  if (context.from === "search") {
    const q = context.href.includes("?q=") ? decodeURIComponent(context.href.split("?q=")[1] ?? "") : "";
    return `${href}${glue}from=search${q ? `&q=${encodeURIComponent(q)}` : ""}`;
  }
  if (context.from === "sector") {
    const sector = context.href.split("/sectors/")[1];
    return `${href}${glue}from=sector${sector ? `&sector=${encodeURIComponent(decodeURIComponent(sector))}` : ""}`;
  }
  const finding = context.href.split("/signals/")[1];
  return `${href}${glue}from=finding${finding ? `&finding=${encodeURIComponent(decodeURIComponent(finding))}` : ""}`;
}

function InvestigationContext({ context }: { context: NonNullable<PoliticianContextValue> }) {
  return (
    <div className="mb-gutter rounded border border-outline-variant bg-surface-container-lowest px-4 py-3 flex flex-wrap items-center justify-between gap-3">
      <div>
        <div className="font-label-caps text-label-caps text-on-surface-variant uppercase">Investigation context</div>
        <div className="font-body-md text-body-md text-on-surface">{context.label}</div>
      </div>
      <Link href={context.href} className="inline-flex items-center gap-2 px-3 py-1.5 rounded border border-outline-variant text-primary hover:bg-surface-container-low transition-colors focus-ring">
        <span className="material-symbols-outlined text-[18px]">arrow_back</span>
        Return
      </Link>
    </div>
  );
}

function committeeItemsFor(mp: PoliticianDetail, context: PoliticianContextValue): RelatedItem[] {
  const text = `${mp.summary} ${mp.bills.map((b) => b.title).join(" ")} ${mp.speeches.map((s) => `${s.keyword} ${s.excerpt}`).join(" ")}`.toLowerCase();
  const committees = [];
  if (text.includes("industry") || text.includes("technology") || text.includes("privacy") || text.includes("ai")) {
    committees.push({ slug: "indu", name: "Standing Committee on Industry and Technology" });
  }
  if (text.includes("finance") || text.includes("treasury") || text.includes("tax")) {
    committees.push({ slug: "fina", name: "Standing Committee on Finance" });
  }
  return committees.map((committee, index) => ({
    id: `committee-${committee.slug}-${index}`,
    title: committee.name,
    type: "Committee",
    href: withContext(committeeHref(committee.slug), context),
    relationship: "person serves on committee",
    strength: "inferred",
  }));
}

function Badge({ icon, children }: { icon: string; children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1 text-on-surface-variant font-data-tabular text-data-tabular bg-surface-container py-1 px-2.5 rounded border border-outline-variant/40">
      <span className="material-symbols-outlined text-[16px]">{icon}</span>
      {children}
    </span>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-outline-variant bg-surface-container-low px-3 py-2">
      <div className="font-label-caps text-label-caps text-on-surface-variant uppercase mb-1">{label}</div>
      <div className="font-body-md text-body-md text-on-surface break-words">{value}</div>
    </div>
  );
}

function SourceLink({ href, label }: { href: string; label: string }) {
  return (
    <li>
      <OriginalSourceLink href={href} label={label} className="text-sm text-on-surface hover:text-primary" />
    </li>
  );
}

function ProfileSkeleton() {
  return <div className="space-y-gutter">{[0, 1, 2, 3].map((i) => <div key={i} className="skeleton h-32" />)}</div>;
}

function Message({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "neutral" | "error" }) {
  return (
    <div className={`rounded border px-4 py-3 font-body-md text-body-md ${tone === "error" ? "border-error/30 bg-error/10 text-error" : "border-outline-variant bg-surface-container-low text-on-surface-variant"}`}>
      {children}
    </div>
  );
}
