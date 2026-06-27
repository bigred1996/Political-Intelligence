---
name: Nessus Intelligence — Intelligence Grade
status: implemented (web/app/globals.css is the source of truth; this file documents it)
---

# Nessus Intelligence — Design System

This is the canonical design-system reference for the `web/` client app. It documents what's
actually implemented in `app/globals.css` plus the shared components in `components/`, not an
aspirational spec — when the two disagree, trust the code and update this file.

The product reads as a **professional intelligence terminal**: precise, data-rich, restrained.
Off-white/parchment-tinted surfaces, Parliament Navy as the single dominant brand colour, muted
semantic accents, dense tabular data set in a true monospace face. Avoid generic "startup SaaS"
gradients, large rounded-2xl cards, or saturated accent colours — hierarchy comes from type,
spacing, and tonal layering, not decoration.

Origin note: this direction was explored under the codename "Intelligence Grade" in
`New DESIGN INSTRUCTIONS/intelligence_grade/DESIGN.md`. That file is a snapshot from the original
design-tool export; this file supersedes it for anything implemented in `web/`.

---

## Brand & style

- **Personality:** authoritative, evidence-backed, non-partisan. Built for analysts, lobbyists,
  GR executives — people who need to scan dense cross-source evidence quickly and trust it.
- **Style:** Corporate Modern with tonal layering. Generous whitespace at the page level, high
  density inside data modules (tables, evidence rails, badges).
- **Two visual surfaces** (see `CLAUDE.md`): this terminal workspace (everything under
  `AppSidebar`/`AppTopBar`), and the separate light parchment "deliverable" reader at
  `/briefings/[id]` (`.briefing-prose`, `--color-navy`/`--color-parchment` tokens). Don't mix the
  two — a `Scorecard`/`Panel` from the workspace should never appear inside `.briefing-prose`.

---

## Colour

All colours are CSS custom properties under `@theme` in `app/globals.css`, generated into Tailwind
utilities automatically (`bg-primary`, `text-on-surface-variant`, `border-outline-variant`, …).
Reference the token, never a raw hex, in new code.

| Role | Token | Hex | Use |
|---|---|---|---|
| Brand / primary | `--color-primary` | `#041632` | Parliament Navy. Headlines, primary buttons, active nav, links, hero panels |
| Primary container | `--color-primary-container` | `#1b2b48` | Primary-button hover, dark panel fills |
| Secondary | `--color-secondary` | `#505f76` | Slate — secondary emphasis, "what to watch" callouts |
| Tertiary | `--color-tertiary` | `#151717` | Reserved, near-black |
| Error | `--color-error` | `#ba1a1a` | Oxblood — error states, high-risk |
| Background | `--color-background` / `--color-surface` | `#f7f9fb` | Page canvas |
| Surface (card) | `--color-surface-container-lowest` | `#ffffff` | Card/panel fill |
| Surface (low) | `--color-surface-container-low` | `#f2f4f6` | Panel headers, table header rows, input fill |
| Surface (high/highest) | `--color-surface-container-high/-highest` | `#e6e8ea` / `#e0e3e5` | Pills, inactive chips |
| Text (primary) | `--color-on-surface` | `#191c1e` | Body copy, dark text |
| Text (secondary) | `--color-on-surface-variant` | `#44474d` | Secondary copy, labels |
| Border (default) | `--color-outline-variant` | `#c5c6ce` | Card borders, dividers, input borders |
| Border (subtle) | `--color-hairline` | `#e2e8f0` | Card-level-1 hairline (slightly lighter than outline-variant) |
| Outline (dim text) | `--color-outline` | `#5f636c` | Dimmest secondary text/icons (darkened from `#75777e` so meta labels clear AA on tinted surface fills) |

**Semantic / risk scale** — desaturated, used for badges, gauges, bar fills, trend lines:

| Token | Hex | Meaning |
|---|---|---|
| `--color-up` / `--color-risk-low` | `#059669` | Positive movement, low risk, "live"/"monitoring" |
| `--color-warn` / `--color-risk-med` | `#d97706` | Caution, medium risk, "partial"/"watch" |
| `--color-down` / `--color-risk-high` | `#ba1a1a` | Negative movement, high risk, "failed"/"stale" |

**Source-category palette** (`lib/source-visual.ts`) — the complementary accent system. One
federal data source = one consistent `{ icon, color, soft }` triple, reused everywhere that source
appears (connection rails, the entity connection graph, timeline dots, source chips, record header
tiles). This is the *only* place hue varies by category rather than by semantic state — don't
invent new per-feature colours; add a source to this map instead. Current assignments: contracts
blue `#2563eb`, grants green `#059669`, donations red `#dc2626`, lobbying amber `#d97706`, bills
violet `#7c3aed`, gazette cyan `#0891b2`, tribunal teal `#0d9488`, appointments indigo `#4f46e5`,
hansard purple `#9333ea`, npri lime `#65a30d`, CER yellow `#ca8a04`, news/social slate `#475569`.

**Choropleth / sequential data-viz scale** (`components/dataviz.tsx: CanadaMap`) — light
slate-blue `#cdd8ea` → Parliament Navy `#041632`, single-hue sequential. Don't build a two-hue
lerp (e.g. navy→gold) for magnitude scales — interpolating across very different hues in RGB space
crosses a muddy, off-brand band partway through. Categorical (non-sequential) diagrams, like
`RadialNetwork`'s edge types, may use a small distinct hue per category instead — that's a
legitimate complementary use, just keep it to 3–4 hues and don't reuse those hues for risk/status.

---

## Typography

Three-typeface pairing, loaded via `next/font/google` in `app/layout.tsx`:

| Typeface | Token | Role |
|---|---|---|
| **Source Serif 4** (400/600/700) | `--font-display` / `font-display-lg`, `font-headline-md`, `font-headline-sm`, `font-memo-body` | Headlines (h1/h2) and narrative analysis prose ("Strategic Read", "Analysis" beats). Gives the platform an editorial, briefing-document authority instead of a generic SaaS sans-everywhere look. |
| **Public Sans** (400/500/600/700) | `--font-sans` / `font-body-lg`, `font-body-md`, `font-label-caps` | Interface: body copy, labels, nav, buttons, form controls. Neutral and highly legible at small dashboard sizes. |
| **JetBrains Mono** (400/500/600) | `--font-mono-data` → `font-data-tabular` / `.mono` | **Data, IDs, dates, scores, citations, technical metadata.** Anything that is a value rather than prose: table cells, badge text, timestamps, record IDs, dollar amounts, "score 0.92"-style strings. |

This is a deliberate three-way split, not a decoration: serif = analyst's voice, sans = interface
chrome, mono = raw evidence. When adding a new piece of UI, ask which of the three it is before
picking a class. **`font-data-tabular` and `.mono` are the same token** (`--font-data-tabular`) —
use whichever reads better at the call site, they always stay in sync.

### Type scale

| Token | Size / line-height | Weight | Use |
|---|---|---|---|
| `display-lg` | 34px / 40px, -0.02em | 600 | Page h1 (desktop) |
| `headline-md` | 26px / 32px, -0.015em | 600 | Page h1 (mobile), section h1 |
| `headline-sm` | 20px / 28px, -0.01em | 600 | Card/section h2 |
| `memo-body` | 18px / 28px | 400 | Serif narrative prose (Analysis beats, briefing prose) |
| `body-lg` | 16px / 24px | 400 | Page subtitles, lead paragraphs |
| `body-md` | 14px / 20px | 400 | Default interface body text |
| `body-sm` | 12px / 16px | 400 | Secondary/meta text |
| `label-caps` | 11px / 16px, +0.05em | 700 | ALL-CAPS section labels, eyebrows, badge text |
| `data-tabular` | 13px / 18px, +0.01em | 500 | Mono data — table cells, scores, dates, IDs |

The scale is deliberately **restrained** — a dense intelligence terminal leads with data, not
billboard headlines. Page h1 tops out at 34px (was 48px) with negative tracking for an editorial,
typeset feel; section heads step down cleanly from there. Oversized hero headings read as
consumer/marketing — keep h1 at the `display-lg` token, never larger.

`PageHeader`/`DetailHeader` (`components/ui.tsx`, `components/nessus.tsx`) own the h1 pattern —
reuse them instead of hand-rolling `<h1>` classes on a new page (the `display-lg` token is serif;
hand-rolled `font-sans` h1s drift off-system — the home dashboard was the one offender and is now
aligned).

---

## Spacing & layout

4px base unit, named tokens (use these over arbitrary `p-[Npx]` where they fit):

| Token | Value | Use |
|---|---|---|
| `--spacing-unit` | 4px | Smallest gap (subtitle margin under h1) |
| `--spacing-density-compact` | 8px | Tight internal padding (panel-head, nav row) |
| `--spacing-density-comfortable` | 16px | Card body padding, standard internal gap |
| `--spacing-gutter` | 24px | Grid/section gaps, gap between page-level cards |
| `--spacing-margin-mobile` | 16px | Page margin, mobile |
| `--spacing-margin-desktop` | 40px | Page margin, desktop (`main`'s `md:p-margin-desktop`) |

Layout shell (`app/layout.tsx`): fixed `AppSidebar` (256px) + `AppTopBar` + a single scrolling
`<main>`, content capped at `max-w-[1440px]`. The page root never sets its own height — let content
size naturally. **In a `grid`/flex row of unequal sibling cards, add `items-start` (or `self-start`
per item)** so a short card never stretches to match a taller sibling and leave a dead gap (see
`watchlists/page.tsx`'s `grid grid-cols-1 lg:grid-cols-3 gap-gutter items-start`).

## Shape

Radius is **tokenized** in `@theme` (overriding Tailwind's defaults) and deliberately tighter than
stock — softer rounding reads consumer/SaaS:

| Token | Value | Use |
|---|---|---|
| `--radius-sm` / `--radius` | 0.25rem (4px) | Inputs, buttons, badges, chips, small controls |
| `--radius-md` | 0.3125rem (5px) | Rarely needed in-between |
| `--radius-lg` | 0.375rem (6px) | **Cards, panels** — the default for `.panel`/`card-level-1` |
| `--radius-xl` | 0.5rem (8px) | Largest allowed; the parchment `/briefings` report surface only |
| `rounded-full` | — | Avatars, status **dots**, the segmented-bar meter — never as a default chip shape |

Rules: cards round to `lg` (6px), controls/badges to `rounded` (4px). **Don't pill-shape chips,
badges, status tags, filter links, or search inputs** — `rounded-full` is reserved for avatars and
genuine dots; squared badges read institutional, pill chips read consumer. Nothing in primary
content rounds past `lg`; `xl` (8px) is for the report deliverable only.

## Elevation

Tonal layers, not shadow stacks. There is **one** canonical card shadow — `--shadow-card`
(`0 1px 2px / 0 8px 24px`, navy-tinted `rgba(4,22,50,…)` rather than flat black, so lifts read as
cohesive with the brand). Never hand-roll a per-component `shadow-[…]`.
- **Level 0** — page background (`--color-background`).
- **Level 1** (`.card-level-1`) — white surface, 1px `--color-hairline` border, no shadow at rest.
- **Level 2** (`.card-level-2`, combine with level-1/`.panel`) — on hover, `var(--shadow-card)` plus
  a primary-colour border. Use for clickable cards (`MetricCard`, sector/entity cards, finding
  cards). Don't reach for Tailwind's `shadow-md`/`shadow-lg` — they're flat-black and off-system.
- Hero/verdict blocks (e.g. record page's "Strategic Read") use solid `bg-primary` instead of a
  tonal layer — reserve that treatment for content that's actually populated; an *empty* hero block
  reads as broken, not "nothing here" (see Empty states below).

---

## Components

Shared building blocks live in `components/ui.tsx` and `components/nessus.tsx`. Prefer composing
these over one-off markup:

- **`Panel`/`Card`** — the standard bordered module: header bar (`bg-surface-container-low`,
  `label-caps` title, optional icon + right-aligned action) over a white body. Use for every
  page-level content module.
- **`PageHeader`/`DetailHeader`** — h1 + optional subtitle + right-aligned action, with the
  `display-lg`/`headline-md` responsive step built in.
- **`SectionHeader`/`SectionTitle`** — the h2-level equivalent inside a page (not inside a Panel,
  which has its own header).
- **Badges** (`SeverityBadge`, `RiskBadge`, `RiskBandBadge`, `ConfidenceBadge`, `CoverageBadge`,
  `SourceTag`) — all follow the same shape: `mono`, uppercase, `10–11px`, `px-1.5 py-0.5`,
  `rounded`, 10–15% tint background + matching border + full-strength text colour. Match this
  recipe for any new status pill rather than inventing a new badge shape.
- **`MetricCard`** — KPI tile: label (`body-sm`, dim) → big number (`30px` bold, *not* mono — large
  hero numbers read better in the display weight than in tabular mono) → optional delta/sparkline.
- **`EmptyState`** (`ui.tsx`) and `RelatedItems`'s `empty` prop (`intelligence.tsx`) — both render a
  dashed-border, icon-prefixed box (see below). Always pass a specific, concrete empty message
  ("No sponsored bills are linked to this profile yet"), never a bare "—" or blank space.
- **Icons** — Material Symbols Outlined exclusively (loaded once in `app/layout.tsx`'s `<head>`),
  weight 400, fill 0 by default, fill 1 for the active sidebar item only. Sizes are inlined per
  context (`text-[14px]` breadcrumbs/timeline dots, `text-[16–18px]` inline-with-label icons,
  `text-[20–26px]` standalone/header icons) — there's no separate icon-size token, just stay inside
  that 14/16/18/20/22/26px ladder so new icons don't introduce an odd in-between size. A handful of
  hand-drawn `<svg>` chevrons/search glyphs exist in unused/legacy components
  (`site-header.tsx`, `site-footer.tsx`, `app-ticker.tsx` — none are mounted in `app/layout.tsx`);
  don't copy that pattern in mounted code, use the icon font.

### States

- **Hover** — cards: border tints to `--color-primary` + soft shadow (`.card-level-2`). Rows/links:
  background tints to `--color-surface-container-low`/`-high`, or text tints to `--color-primary`.
- **Focus** — `.focus-ring` (global, auto-applied to links/buttons/inputs): 2px ring,
  `color-mix(primary 55%, transparent)`, 2px offset. Always keep this on interactive elements;
  don't suppress outline without supplying an equivalent.
- **Active/selected** — nav: `border-r-4 border-primary` + bold text + 10%-tint background. Lists:
  10%-tint `bg-primary-container/10` row background.
- **Disabled** — `disabled:opacity-50` on the button itself; pair with `disabled:cursor-not-allowed`
  when adding new disableable controls.
- **Loading** — `.skeleton` (shimmer gradient block) for content placeholders; an inline
  `font-data-tabular` "Running…/Searching…" status line for in-progress async actions.
- **Empty** — dashed `border-outline-variant`/`border-line`, muted `bg-surface-container-low`
  (~60% opacity), one small icon (commonly `inbox`), and one concrete sentence. Never render an
  empty state at the same visual weight as populated content (e.g. a full-bleed `bg-primary` hero
  block) — drop to an outlined/muted treatment instead so "nothing here yet" doesn't read as
  "something broke."
- **Error** — `border-error/30 bg-error/10 text-error`, plain sentence, no icon needed at this
  weight (matches existing `Message` patterns across pages).
- **Success** — `--color-up` / `status-chip-green` (10% tint bg, full-strength text), used for
  "Live"/"Monitoring"/"Approved" status chips.

---

## Known cleanup (not yet done — read before extending these files)

A handful of components/pages still use an older "back-compat alias" class set instead of the
canonical tokens above (defined side-by-side in `globals.css`, e.g. `bg-panel` = 1:1 alias for
`bg-surface-container-lowest`, `text-brass-bright` = alias for `text-primary`). They render
**pixel-identical** today, so this is pure code hygiene, not a visual bug — but the two parallel
naming systems should eventually collapse to one. Known offenders: `components/intelligence.tsx`,
`components/charts.tsx`, `components/sector-card.tsx`, parts of `components/ui.tsx`, and a few
`[id]`/`[slug]` detail pages. If you're already editing one of these files for something else, take
the opportunity to swap its alias classes for the canonical ones using this exact mapping (verified
against the hex values in `globals.css`) — but don't do a blind project-wide search/replace in one
pass; `--color-fg-dim` (`#75777e`) maps to `--color-outline`, **not** `--color-on-surface-variant`
(`#44474d`, that's `--color-fg`) — the three greys form a ladder and are easy to cross-wire:

| Alias | → Canonical |
|---|---|
| `bg-panel` | `bg-surface-container-lowest` |
| `bg-panel-2` | `bg-surface-container-low` |
| `border-line` | `border-hairline` |
| `text-fg-bright` | `text-on-surface` |
| `text-fg` | `text-on-surface-variant` |
| `text-fg-dim` | `text-outline` |
| `bg-brass` / `text-brass` | `bg-primary` / `text-primary` |
| `text-brass-bright` | `text-primary-container` (verify against intended contrast — this one is *not* a flat alias of `text-primary`) |

`components/app-ticker.tsx`, `components/site-header.tsx`, `components/site-footer.tsx` also use
the alias set, but none of the three are imported by `app/layout.tsx` or any route — they're
unmounted/legacy. Don't spend cleanup effort there unless you're actually wiring one back in.

---

## Change log

- **Institutional-polish pass (2026-06-27):** a disciplined product-design pass to make the
  workspace read as premium enterprise intelligence rather than vibecoded SaaS. Systemic, token-led:
  - **Type scale tightened** — `display-lg` 48→34px, `headline-md` 32→26px, `headline-sm` 24→20px,
    all with negative tracking. Removes the "oversized heading" tell across all 33 pages at once.
  - **Radius tokenized + tightened** — added `--radius-*` to `@theme`; cards 8→6px (`--radius-lg`),
    `xl` 12→8px (deliverable only). `.panel`/`panel-head`/`panel-dark`/`panel-accent`/`signal-card`
    now reference the token instead of hardcoded `0.5rem`.
  - **One elevation token** — `--shadow-card` (navy-tinted) replaces three different hand-rolled
    `shadow-[…]` stacks (`MetricCard`, `SectorCard`) and Tailwind `shadow-md`/`shadow-lg`
    (`FindingCard`, explorer graph nodes).
  - **De-pilled** — squared `rounded-full` chips/badges/filter-links/search input → `rounded` in
    the topbar, sidebar, home dashboard (RiskChip, HealthPill, watchlist + attention chips),
    `SignalBadge`, `Pill`, `SourceTag`. `rounded-full` now reserved for avatars/dots.
  - **Calmer interactions** — removed the bouncy `active:scale-95` and `transition-all` from nav
    rows, topbar buttons, sector cards, the search composer; nav active rule softened from
    `border-r-4`/`font-bold` to `border-r-2`/`font-semibold`.
  - **Contrast** — `--color-outline`/`--color-fg-dim`/`--color-muted` darkened `#75777e`→`#5f636c`
    so dim meta labels clear AA on tinted fills (the grey-on-grey complaint).
  - **Decorative gradients removed** — the `IntelligenceSummary` fade overlay and the
    politician-card gradient stripe (→ solid `bg-primary`). Kept functional gradients (search-composer
    scrim fade, explorer graph dot-grid).
  - **EmptyState** rewritten to actually match its documented spec (dashed border + icon + concrete
    sentence); `MetricCard` label promoted to `label-caps` and dim greys → `on-surface-variant`.
  - **Icons** — replaced the hand-drawn `<svg>` arrow in `SectorCard` with a Material Symbol
    (`arrow_forward`); the topbar "History" button (which actually printed) relabelled to
    "Print this view" with the `print` glyph.
- **Prior pass:** `--font-data-tabular` switched from Public Sans to JetBrains Mono (the face was
  already loaded and unused) so data/IDs/citations read as mono everywhere `font-data-tabular`/
  `.mono` is used. `CanadaMap` choropleth moved off a navy→gold two-hue lerp onto a single-hue
  navy sequential scale. Record page "Strategic Read" and `RelatedItems`/`EmptyState` empty
  treatments softened to dashed/muted instead of full-weight. Watchlist page grid no longer
  stretches the shorter card. Added a branded `app/not-found.tsx`.
