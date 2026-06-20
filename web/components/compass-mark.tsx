// The Nessus compass-star mark from the style guide. Brass on transparent.
export function CompassMark({ size = 28, className = "" }: { size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 100 100"
      fill="none"
      className={className}
      aria-hidden="true"
    >
      <circle cx="50" cy="50" r="47" stroke="currentColor" strokeWidth="2" opacity="0.55" />
      <circle cx="50" cy="50" r="38" stroke="currentColor" strokeWidth="1" opacity="0.3" />
      {/* primary 4-point star */}
      <path
        d="M50 6 L57 43 L94 50 L57 57 L50 94 L43 57 L6 50 L43 43 Z"
        fill="currentColor"
        opacity="0.92"
      />
      {/* secondary diagonal points */}
      <path
        d="M50 18 L54 46 L82 50 L54 54 L50 82 L46 54 L18 50 L46 46 Z"
        fill="var(--color-navy)"
        opacity="0.18"
      />
      <circle cx="50" cy="50" r="4" fill="currentColor" />
    </svg>
  );
}
