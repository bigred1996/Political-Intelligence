import { CompassMark } from "./compass-mark";

export function SiteFooter() {
  return (
    <footer className="bg-panel border-t border-line mt-10">
      <div className="mx-auto max-w-[1320px] px-4 py-5 flex flex-col sm:flex-row items-center gap-3 justify-between">
        <div className="flex items-center gap-2 text-brass-bright">
          <CompassMark size={18} />
          <span className="text-fg text-sm font-semibold">POLARIS</span>
        </div>
        <p className="mono uppercase tracking-[0.16em] text-[10px] text-fg-dim">
          Political Intelligence · Strategic Advantage
        </p>
        <p className="mono text-[10px] text-fg-dim/70">Confidential — authorized recipients only</p>
      </div>
    </footer>
  );
}
