"""Goal B6 — chart series + static SVG for the PDF memo.

The derivation half is a direct Python port of `web/lib/workspace-charts.ts`
(Goal B5): same algorithm, same input shape (`workspace.findings` /
`.connected` / `.source_coverage` straight from `get_review_response()`), so
the numbers in the PDF are provably identical to the ones on the workspace
page — there is no second source of truth. Nothing here re-derives a number
from anywhere else; an empty input yields an empty series, rendered as a
"No data" placeholder, never a fabricated bar.

The SVG half has no frontend equivalent to call (no JS runtime in the FastAPI
process) — it's a small static re-implementation of `components/dataviz.tsx`'s
visual primitives (BarList / TrendBars / RadialNetwork) using the new
memo-specific branding (warm off-white, forest green, amber), with all
interactivity (onSelect/activeKey) dropped since a PDF page cannot be clicked.
"""
from __future__ import annotations

import re
from html import escape
from typing import Any

# ── Brand palette (the PDF's own surface — distinct from both the dark
# terminal workspace and the navy/parchment Report briefing reader) ─────────
BG = "#FAF7F0"
PANEL_BG = "#FFFFFF"
BORDER = "#DDD5C2"
TEXT = "#21281F"
TEXT_DIM = "#6E6A5C"
PRIMARY = "#1F5C40"      # forest green — the single brand accent
PRIMARY_DARK = "#163F2C"
AMBER = "#C8842E"

# Severity → color (functional palette, warmed to fit the parchment-free
# off-white memo surface: calm=green, caution=amber, acute=rust, not red).
RISK_ORDER = ("high", "elevated", "watch")
RISK_LABEL = {"high": "High", "elevated": "Elevated", "watch": "Watch"}
RISK_COLOR = {"high": "#A8431E", "elevated": AMBER, "watch": PRIMARY}

# Connected-entity kind → network edge color bucket (mirrors dataviz.tsx's
# EDGE_COLOR, recolored to the memo palette).
NET_EDGE_COLOR = {
    "regulatory": AMBER, "funding": PRIMARY, "policy": "#3B5A7A", "partnership": "#7A5C3E",
}
KIND_TO_TYPE = {
    "politicians": "policy", "committees": "policy",
    "organizations": "partnership", "entities": "partnership",
}

ChartBar = dict[str, Any]   # {key, label, value}
YearBar = dict[str, Any]    # {year, count}
NetNode = dict[str, Any]    # {label, sub, type}


# ── Derivation (port of web/lib/workspace-charts.ts) ────────────────────────

def risk_distribution(findings: list[dict[str, Any]]) -> list[ChartBar]:
    counts: dict[str, int] = {}
    for f in findings:
        lvl = f.get("meta", {}).get("risk_level")
        lvl = lvl if lvl in RISK_ORDER else "watch"
        counts[lvl] = counts.get(lvl, 0) + 1
    return [
        {"key": lvl, "label": RISK_LABEL[lvl], "value": counts[lvl]}
        for lvl in RISK_ORDER if lvl in counts
    ]


def sector_exposure(findings: list[dict[str, Any]]) -> list[ChartBar]:
    counts: dict[str, int] = {}
    names: dict[str, str] = {}
    for f in findings:
        slug = f.get("meta", {}).get("sector_slug")
        if not slug:
            continue
        counts[slug] = counts.get(slug, 0) + 1
        names[slug] = f.get("meta", {}).get("sector_name") or slug
    return [
        {"key": slug, "label": names[slug], "value": v}
        for slug, v in sorted(counts.items(), key=lambda kv: (-kv[1], names[kv[0]]))
    ]


_YEAR_RE = re.compile(r"^(\d{4})")


def year_of(date: str | None) -> str | None:
    if not date:
        return None
    m = _YEAR_RE.match(str(date))
    if not m:
        return None
    y = int(m.group(1))
    return m.group(1) if 1900 <= y <= 2100 else None


def findings_by_year(findings: list[dict[str, Any]]) -> list[YearBar]:
    counts: dict[str, int] = {}
    for f in findings:
        y = year_of(f.get("meta", {}).get("date"))
        if not y:
            continue
        counts[y] = counts.get(y, 0) + 1
    if not counts:
        return []
    years = sorted(int(y) for y in counts)
    return [{"year": str(y), "count": counts.get(str(y), 0)} for y in range(years[0], years[-1] + 1)]


def source_coverage_bars(coverage: list[dict[str, Any]]) -> list[ChartBar]:
    return [{"key": c["source_type"], "label": c["label"], "value": c["count"]} for c in coverage]


def connected_network(connected: list[dict[str, Any]], cap: int = 14) -> list[NetNode]:
    out = []
    for c in connected[:cap]:
        kind = c.get("kind", "")
        out.append({
            "label": c.get("title") or f"{c.get('table')}:{c.get('pk')}",
            "sub": kind,
            "type": KIND_TO_TYPE.get(kind, "partnership"),
        })
    return out


# ── Static SVG rendering (no interactivity — print-only) ───────────────────

def _esc(s: str) -> str:
    return escape(str(s), quote=True)


_SVG_DIM = re.compile(r'(<svg\b[^>]*?)\s+width="[\d.]+"\s+height="[\d.]+"')


def responsive(svg: str) -> str:
    """Strip the fixed px width/height (keeping viewBox) so a chart scales to
    its container instead of overflowing a flex/grid column. The memo's CSS
    sets the column width; the SVG just fills it and keeps its aspect ratio."""
    return _SVG_DIM.sub(r'\1 style="width:100%;height:auto"', svg)


# category × severity heat matrix — the memo's signature exhibit (KPMG-style,
# one company's exposure read across diligence categories and severity bands).
def render_matrix_svg(
    row_labels: list[str], col_labels: list[str], values: list[list[int]],
    colors: list[str], *, width: int = 520, label_w: int = 170,
) -> str:
    if not row_labels or not col_labels:
        return '<div class="chart-empty">No data</div>'
    head_h, row_h, gap = 26, 30, 3
    grid_w = width - label_w
    cell_w = (grid_w - gap * (len(col_labels) - 1)) / len(col_labels)
    height = head_h + len(row_labels) * (row_h + gap)
    parts = []
    # column headers
    for j, c in enumerate(col_labels):
        x = label_w + j * (cell_w + gap) + cell_w / 2
        parts.append(
            f'<text x="{x:.1f}" y="16" font-size="10" font-weight="700" '
            f'text-anchor="middle" fill="{TEXT_DIM}">{_esc(c)}</text>'
        )
    max_v = max((max(r) for r in values if r), default=0) or 1
    for i, r in enumerate(row_labels):
        y = head_h + i * (row_h + gap)
        parts.append(
            f'<text x="0" y="{y + row_h/2 + 4:.1f}" font-size="10.5" font-weight="600" '
            f'fill="{TEXT}">{_esc(r[:26])}</text>'
        )
        for j, c in enumerate(col_labels):
            v = values[i][j]
            x = label_w + j * (cell_w + gap)
            base = colors[j] if j < len(colors) else PRIMARY
            if v <= 0:
                fill, txt_fill, label = PANEL_BG, "#C9C2B0", "·"
                stroke = f' stroke="{BORDER}"'
            else:
                # shade intensity scales with count within the column's max
                op = 0.45 + 0.55 * (v / max_v)
                fill, txt_fill, label, stroke = base, "#FFFFFF", str(v), ""
                parts.append(
                    f'<rect x="{x:.1f}" y="{y:.1f}" width="{cell_w:.1f}" height="{row_h}" '
                    f'rx="3" fill="{base}" opacity="{op:.2f}"/>'
                )
                parts.append(
                    f'<text x="{x + cell_w/2:.1f}" y="{y + row_h/2 + 4:.1f}" font-size="11" '
                    f'font-weight="700" text-anchor="middle" fill="{txt_fill}">{label}</text>'
                )
                continue
            parts.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{cell_w:.1f}" height="{row_h}" '
                f'rx="3" fill="{fill}"{stroke}/>'
                f'<text x="{x + cell_w/2:.1f}" y="{y + row_h/2 + 4:.1f}" font-size="11" '
                f'text-anchor="middle" fill="{txt_fill}">{label}</text>'
            )
    return (
        f'<svg viewBox="0 0 {width} {height:.0f}" width="{width}" height="{height:.0f}" '
        f'xmlns="http://www.w3.org/2000/svg">' + "".join(parts) + "</svg>"
    )


def render_bar_list_svg(bars: list[ChartBar], *, color: str = PRIMARY, width: int = 480) -> str:
    """Horizontal bar list, one row per bar — static counterpart of BarList."""
    if not bars:
        return '<div class="chart-empty">No data</div>'
    row_h, label_w, val_w, pad = 20, 130, 50, 4
    bar_w = width - label_w - val_w - pad * 2
    h = row_h * len(bars)
    max_v = max(b["value"] for b in bars) or 1
    rows = []
    for i, b in enumerate(bars):
        y = i * row_h
        w = max(2, (b["value"] / max_v) * bar_w)
        label = b["label"][:22]
        rows.append(
            f'<text x="0" y="{y + 13}" font-size="10" fill="{TEXT}">{_esc(label)}</text>'
            f'<rect x="{label_w}" y="{y + 3}" width="{bar_w}" height="13" rx="2" fill="{PANEL_BG}" stroke="{BORDER}"/>'
            f'<rect x="{label_w}" y="{y + 3}" width="{w}" height="13" rx="2" fill="{color}"/>'
            f'<text x="{label_w + bar_w + val_w - pad}" y="{y + 13}" font-size="10" '
            f'text-anchor="end" fill="{TEXT_DIM}">{b["value"]}</text>'
        )
    return (
        f'<svg viewBox="0 0 {width} {h}" width="{width}" height="{h}" xmlns="http://www.w3.org/2000/svg">'
        + "".join(rows) + "</svg>"
    )


def render_trend_bars_svg(years: list[YearBar], *, color: str = PRIMARY, width: int = 480, height: int = 110) -> str:
    """Year-bucketed column chart — static counterpart of TrendBars."""
    if not years:
        return '<div class="chart-empty">No data</div>'
    pad_l, pad_r, pad_t, pad_b = 4, 4, 12, 18
    plot_w, plot_h = width - pad_l - pad_r, height - pad_t - pad_b
    max_v = max(y["count"] for y in years) or 1
    bw = plot_w / len(years)
    bars = []
    label_idx = {0, len(years) - 1}
    for i, y in enumerate(years):
        bh = (y["count"] / max_v) * plot_h
        x = pad_l + i * bw
        bars.append(
            f'<rect x="{x + bw * 0.12:.1f}" y="{pad_t + plot_h - bh:.1f}" '
            f'width="{bw * 0.76:.1f}" height="{bh:.1f}" rx="1" fill="{color}"/>'
        )
        if i in label_idx:
            anchor = "start" if i == 0 else "end"
            bars.append(
                f'<text x="{x + bw / 2:.1f}" y="{height - 4}" font-size="9" text-anchor="{anchor}" '
                f'fill="{TEXT_DIM}">{_esc(y["year"])}</text>'
            )
    axis = f'<line x1="{pad_l}" y1="{pad_t + plot_h}" x2="{width - pad_r}" y2="{pad_t + plot_h}" stroke="{BORDER}"/>'
    return (
        f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">'
        + axis + "".join(bars) + "</svg>"
    )


def render_radial_network_svg(center: str, nodes: list[NetNode], *, size: int = 360) -> str:
    """Center node + radial spokes to connected entities — static counterpart
    of RadialNetwork."""
    if not nodes:
        return '<div class="chart-empty">No data</div>'
    import math

    cx, cy, r = size / 2, size / 2, size / 2 - 64
    n = len(nodes)
    parts = []
    for i, node in enumerate(nodes):
        a = (i / n) * 2 * math.pi - math.pi / 2
        x, y = cx + r * math.cos(a), cy + r * math.sin(a)
        col = NET_EDGE_COLOR.get(node["type"], "#7A5C3E")
        right = x >= cx
        anchor = "start" if right else "end"
        dx = 9 if right else -9
        label = node["label"][:22] + ("…" if len(node["label"]) > 22 else "")
        parts.append(
            f'<line x1="{cx:.1f}" y1="{cy:.1f}" x2="{x:.1f}" y2="{y:.1f}" stroke="{col}" stroke-width="1.2" opacity="0.55"/>'
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="{PANEL_BG}" stroke="{col}" stroke-width="2"/>'
            f'<text x="{x + dx:.1f}" y="{y - 1:.1f}" font-size="10" text-anchor="{anchor}" fill="{TEXT}">{_esc(label)}</text>'
        )
        if node.get("sub"):
            parts.append(
                f'<text x="{x + dx:.1f}" y="{y + 10:.1f}" font-size="8" text-anchor="{anchor}" '
                f'fill="{TEXT_DIM}">{_esc(node["sub"])}</text>'
            )
    center_label = center[:14] + ("…" if len(center) > 14 else "")
    parts.append(
        f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="30" fill="{BG}" stroke="{PRIMARY}" stroke-width="1.5"/>'
        f'<text x="{cx:.1f}" y="{cy:.1f}" font-size="11" text-anchor="middle" dominant-baseline="middle" '
        f'fill="{PRIMARY_DARK}" font-weight="600">{_esc(center_label)}</text>'
    )
    return (
        f'<svg viewBox="0 0 {size} {size}" width="{size}" height="{size}" xmlns="http://www.w3.org/2000/svg">'
        + "".join(parts) + "</svg>"
    )
