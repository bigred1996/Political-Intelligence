---
name: Nessus Intelligence
colors:
  surface: '#f9f9ff'
  surface-dim: '#cfdaf1'
  surface-bright: '#f9f9ff'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f0f3ff'
  surface-container: '#e7eeff'
  surface-container-high: '#dee8ff'
  surface-container-highest: '#d8e3fa'
  on-surface: '#111c2c'
  on-surface-variant: '#44474d'
  inverse-surface: '#263142'
  inverse-on-surface: '#ebf1ff'
  outline: '#75777e'
  outline-variant: '#c5c6ce'
  surface-tint: '#4f5e7e'
  primary: '#041632'
  on-primary: '#ffffff'
  primary-container: '#1b2b48'
  on-primary-container: '#8393b5'
  inverse-primary: '#b7c7eb'
  secondary: '#b52327'
  on-secondary: '#ffffff'
  secondary-container: '#ff5a55'
  on-secondary-container: '#600008'
  tertiary: '#181711'
  on-tertiary: '#ffffff'
  tertiary-container: '#2d2b25'
  on-tertiary-container: '#96928a'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#d7e2ff'
  primary-fixed-dim: '#b7c7eb'
  on-primary-fixed: '#091b37'
  on-primary-fixed-variant: '#374765'
  secondary-fixed: '#ffdad7'
  secondary-fixed-dim: '#ffb3ad'
  on-secondary-fixed: '#410004'
  on-secondary-fixed-variant: '#930113'
  tertiary-fixed: '#e8e2d9'
  tertiary-fixed-dim: '#cbc6bd'
  on-tertiary-fixed: '#1d1b16'
  on-tertiary-fixed-variant: '#494640'
  background: '#f9f9ff'
  on-background: '#111c2c'
  surface-variant: '#d8e3fa'
typography:
  headline-xl:
    fontFamily: Source Serif 4
    fontSize: 48px
    fontWeight: '700'
    lineHeight: 56px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Source Serif 4
    fontSize: 32px
    fontWeight: '600'
    lineHeight: 40px
    letterSpacing: -0.01em
  headline-lg-mobile:
    fontFamily: Source Serif 4
    fontSize: 28px
    fontWeight: '600'
    lineHeight: 34px
  headline-md:
    fontFamily: Source Serif 4
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
  body-lg:
    fontFamily: Source Sans 3
    fontSize: 18px
    fontWeight: '400'
    lineHeight: 28px
  body-md:
    fontFamily: Source Sans 3
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  label-caps:
    fontFamily: JetBrains Mono
    fontSize: 12px
    fontWeight: '600'
    lineHeight: 16px
    letterSpacing: 0.08em
  provenance-tag:
    fontFamily: Source Sans 3
    fontSize: 13px
    fontWeight: '700'
    lineHeight: 16px
    letterSpacing: 0.02em
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  base: 4px
  xs: 8px
  sm: 16px
  md: 24px
  lg: 40px
  xl: 64px
  gutter: 24px
  margin-mobile: 16px
  margin-desktop: 48px
  max-width-content: 800px
---

## Brand & Style
The brand personality is authoritative, institutional, and strategically neutral. As a "Canada-first" regulatory platform, the design system avoids the frantic aesthetics of typical SaaS, opting instead for a **Corporate / Modern** style with strong **Editorial** influences. It evokes the feeling of a high-level briefing document: stable, meticulous, and non-partisan.

The target audience consists of policy advisors, legal counsel, and government relations executives. The UI must facilitate deep focus, prioritizing information density and source hierarchy over decorative elements. The visual language balances the weight of Canadian parliamentary tradition with the precision of modern data intelligence.

## Colors
The palette is anchored by **Nessus Navy** (#1B2B48), representing institutional depth and stability. The primary background is a warm **Heritage Off-White** (#F9F7F2) to reduce eye strain during long-form reading, contrasted against the **Linen** tertiary color (#E8E2D9) for container grouping.

**Materiality & Provenance Signals:**
- **High Risk / Urgent:** A deep, professional red (#C63031) derived from the Canadian ensign, used sparingly for critical alerts.
- **Provenance Categories:**
  - *Federal/Legislative:* Nessus Navy (#1B2B48).
  - *Lobbying/Interest:* A muted Slate (#4A5568).
  - *Provincial/Regional:* A dignified Teal-Grey (#3E5C5F).
- **Materiality Indicators:** Use a saturation scale of the primary Navy to indicate impact depth, ensuring high-contrast legibility for "Likely Impact" signals.

## Typography
The typographic system utilizes a "Serif-to-Sans" hierarchy to distinguish between *content* and *interface*. 

**Source Serif 4** is used for all headlines and editorial summaries to provide an authoritative, scholarly tone. **Source Sans 3** handles the functional body text, optimized for legibility in dense regulatory tables and reports. **JetBrains Mono** is introduced for metadata, timestamps, and "Provenance Indicators" to provide a technical, forensic feel to the data's origin. Large headlines scale down for mobile to maintain a maximum of three lines for titles.

## Layout & Spacing
The design system employs a **Fixed Grid** for content-heavy pages to ensure optimal line lengths for reading. 

- **Editorial View:** Centralized column with a max-width of 800px to maintain a character count of 65-75 per line.
- **Intelligence Dashboard:** A 12-column grid with 24px gutters. Left-hand navigation is narrow (240px) to maximize the data viewing area.
- **Mobile:** Transitions to a single-column stack with 16px side margins. 

Spacing follows a strict 4px base unit. Use `lg` (40px) for section headers and `sm` (16px) for internal card padding to maintain a dense, professional information environment.

## Elevation & Depth
Depth is conveyed through **Tonal Layers** rather than heavy shadows, mimicking the physical stacking of paper dossiers. 

- **Base Layer:** Heritage Off-White (#F9F7F2).
- **Surface Layer:** White (#FFFFFF) with a 1px solid border in Linen (#E8E2D9).
- **Interactive States:** Use a subtle, extra-diffused 4px shadow with a 5% Navy tint only on hover to indicate "lift."
- **Overlays:** Modals use a backdrop blur (12px) with a 20% opacity Navy overlay to maintain focus on the intellectual task at hand without losing context of the dashboard.

## Shapes
The design system uses **Soft** geometry. A corner radius of 4px (`rounded-sm`) is applied to primary UI elements like buttons and input fields to keep the interface feeling precise and institutional. Large containers and cards may use 8px (`rounded-lg`) to soften the overall layout. Avoid pill-shaped buttons; use rectangular shapes with slight rounding to maintain a formal aesthetic.

## Components
- **Buttons:** Primary buttons are solid Nessus Navy with white text. Secondary buttons use a Navy 1px border. No gradients.
- **Provenance Tags:** Small, all-caps labels using JetBrains Mono. They feature a vertical 2px left-border color-coded by source (e.g., Red for Legislative, Teal for Provincial).
- **Materiality Signals:** A vertical "Risk Bar" on the left edge of intelligence cards. High-risk items use a 4px Red border; low-impact items use a subtle Grey border.
- **Intelligence Cards:** Flat white background, Linen border, 16px internal padding. Metadata (date, source) is placed at the very top in Label-Caps.
- **Input Fields:** Squared corners, Heritage Off-White background when inactive, turning white with a 2px Navy bottom border when focused.
- **Lists:** Data-heavy lists use zebra-striping with the Linen color (#E8E2D9) at 30% opacity to assist with horizontal tracking across regulatory data rows.