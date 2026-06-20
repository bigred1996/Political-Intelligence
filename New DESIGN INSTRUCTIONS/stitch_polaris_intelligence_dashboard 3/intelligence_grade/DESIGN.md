---
name: Intelligence Grade
colors:
  surface: '#f7f9fb'
  surface-dim: '#d8dadc'
  surface-bright: '#f7f9fb'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f2f4f6'
  surface-container: '#eceef0'
  surface-container-high: '#e6e8ea'
  surface-container-highest: '#e0e3e5'
  on-surface: '#191c1e'
  on-surface-variant: '#44474d'
  inverse-surface: '#2d3133'
  inverse-on-surface: '#eff1f3'
  outline: '#75777e'
  outline-variant: '#c5c6ce'
  surface-tint: '#4f5e7e'
  primary: '#041632'
  on-primary: '#ffffff'
  primary-container: '#1b2b48'
  on-primary-container: '#8393b5'
  inverse-primary: '#b7c7eb'
  secondary: '#505f76'
  on-secondary: '#ffffff'
  secondary-container: '#d0e1fb'
  on-secondary-container: '#54647a'
  tertiary: '#151717'
  on-tertiary: '#ffffff'
  tertiary-container: '#2a2b2b'
  on-tertiary-container: '#929292'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#d7e2ff'
  primary-fixed-dim: '#b7c7eb'
  on-primary-fixed: '#091b37'
  on-primary-fixed-variant: '#374765'
  secondary-fixed: '#d3e4fe'
  secondary-fixed-dim: '#b7c8e1'
  on-secondary-fixed: '#0b1c30'
  on-secondary-fixed-variant: '#38485d'
  tertiary-fixed: '#e3e2e2'
  tertiary-fixed-dim: '#c6c6c6'
  on-tertiary-fixed: '#1a1c1c'
  on-tertiary-fixed-variant: '#464747'
  background: '#f7f9fb'
  on-background: '#191c1e'
  surface-variant: '#e0e3e5'
typography:
  display-lg:
    fontFamily: Source Serif 4
    fontSize: 48px
    fontWeight: '600'
    lineHeight: 56px
    letterSpacing: -0.02em
  headline-md:
    fontFamily: Source Serif 4
    fontSize: 32px
    fontWeight: '600'
    lineHeight: 40px
  headline-sm:
    fontFamily: Source Serif 4
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
  memo-body:
    fontFamily: Source Serif 4
    fontSize: 18px
    fontWeight: '400'
    lineHeight: 28px
  body-lg:
    fontFamily: Public Sans
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  body-md:
    fontFamily: Public Sans
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  data-tabular:
    fontFamily: Public Sans
    fontSize: 13px
    fontWeight: '500'
    lineHeight: 18px
    letterSpacing: 0.01em
  label-caps:
    fontFamily: Public Sans
    fontSize: 11px
    fontWeight: '700'
    lineHeight: 16px
    letterSpacing: 0.05em
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  unit: 4px
  container-max: 1440px
  gutter: 24px
  margin-desktop: 40px
  margin-mobile: 16px
  density-compact: 8px
  density-comfortable: 16px
---

## Brand & Style
The design system is engineered for "Intelligence Grade" clarity, serving as a high-fidelity interface for political and regulatory monitoring. The brand personality is authoritative, evidence-backed, and precise. It targets analysts, lobbyists, and executives who require a sophisticated environment for complex data synthesis.

The design style is **Corporate Modern with subtle Tonal Layering**. It prioritizes data density and legibility, utilizing vast whitespace to evoke a sense of northern clarity and institutional stability. Visual cues are understated, relying on structural alignment and refined typography rather than decorative elements to convey a sense of Canadian institutional professionalism.

## Colors
The palette is anchored by "Parliament Navy" (#1B2B48), providing a foundation of authority and depth. Secondary Slate Grey handles UI metadata and inactive states, while metallic accents (Silver/Chrome) are used sparingly for dividers and high-level status indicators.

Semantic colors for 'Materiality' and 'Risk' signals are intentionally muted. Instead of vibrant tones, we use desaturated "oxblood" reds, "ochre" ambers, and "forest" greens. These ensure that critical alerts are visible without disrupting the professional, serious tone of the platform. Surfaces should primarily use off-whites and cool greys to maintain a clean, document-like feel.

## Typography
This design system employs a dual-typeface strategy to balance data density with narrative authority. 

**Public Sans** is the functional workhorse, used for all data-heavy grids, navigation elements, and interface controls. It is chosen for its institutional clarity and neutral tone. **Source Serif 4** is reserved for high-level headlines and "Diligence Memo" sections, providing a tactile, editorial quality that mirrors formal regulatory reports. 

For mobile, `display-lg` should scale down to 32px and `headline-md` to 24px to maintain readability within narrow viewports.

## Layout & Spacing
The layout follows a **Fixed Grid** philosophy for desktop to ensure long-form reports remain readable, centered within a 1440px max-width container. A 12-column system is used, with 24px gutters providing significant breathing room between data modules.

In data-dense views (like bill trackers or regulatory feeds), the spacing rhythm shifts to a compact 8px baseline. For editorial or "Memo" views, vertical rhythm expands to 16px or 24px to allow for focused reading. Transitions between mobile and desktop involve collapsing sidebars into bottom-anchored sheets and reducing horizontal margins to 16px.

## Elevation & Depth
Depth is conveyed through **Tonal Layers** and **Low-Contrast Outlines** rather than aggressive shadows. 
- **Level 0 (Background):** Neutral light grey (#F1F5F9) acting as the canvas.
- **Level 1 (Cards/Surface):** Pure white surfaces with a subtle 1px border in a soft metallic grey (#E2E8F0).
- **Level 2 (Hover/Active):** A very soft, diffused ambient shadow (4px blur, 5% opacity) and a primary-color accent border.

To show connectivity between legislative items, we use "layered" glassmorphism—semi-transparent overlays with a backdrop blur of 8px—primarily for fly-out panels and search modals, suggesting a system that is interconnected and deep.

## Shapes
The shape language is **Soft (0.25rem)**. This slight rounding takes the edge off the institutional rigidity without appearing overly casual or consumer-focused. Sharp corners are avoided to prevent a "brutalist" feel, while large radii are avoided to maintain the professional "Intelligence Grade" persona. Form inputs and primary buttons use the base `rounded` (4px), while larger content containers and cards may use `rounded-lg` (8px).

## Components
- **Buttons:** Primary buttons are solid Parliament Navy with white text. Secondary buttons use a ghost style with a subtle Slate Grey border. High-density views use "Small" variants (28px height).
- **Cards:** Content is grouped in bordered cards with a dedicated "Header" area in a slightly darker off-white to separate metadata from body content.
- **Diligence Memos:** A specialized component using Source Serif 4, featuring wide margins and integrated "Materiality" tags.
- **Status Chips:** Small, pill-shaped indicators using the muted semantic palette. Backgrounds are 10% opacity of the semantic color with high-contrast text.
- **Data Grids:** Highly structured with "Zebra" striping using a 2% tint of the primary color. Headers are always sticky and use the `label-caps` typography style.
- **Risk Indicators:** A custom component featuring a 3-step vertical bar (Muted Green, Amber, Red) to visualize regulatory impact at a glance.