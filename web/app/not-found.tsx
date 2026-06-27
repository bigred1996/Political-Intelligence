import { LinkButton } from "@/components/ui";

export default function NotFound() {
  return (
    <div className="min-h-[60vh] flex items-center justify-center">
      <div className="text-center max-w-md">
        <div className="mx-auto mb-5 w-14 h-14 rounded-full bg-surface-container-low border border-outline-variant flex items-center justify-center">
          <span className="material-symbols-outlined text-[26px] text-on-surface-variant" aria-hidden="true">search_off</span>
        </div>
        <div className="font-data-tabular text-data-tabular text-on-surface-variant uppercase tracking-wide mb-2">Error 404</div>
        <h1 className="font-display-lg text-headline-md text-primary leading-tight mb-2">Page not found</h1>
        <p className="font-body-lg text-body-lg text-on-surface-variant mb-6">
          The record, page, or evidence link you followed doesn&rsquo;t exist — it may have moved, or the reference was generated for a different table.
        </p>
        <div className="flex items-center justify-center gap-3">
          <LinkButton href="/">Return to dashboard</LinkButton>
          <LinkButton href="/search" variant="ghost">Ask Nessus</LinkButton>
        </div>
      </div>
    </div>
  );
}
