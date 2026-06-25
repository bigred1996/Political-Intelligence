"""Goal B6 — branded diligence memo: section content, built ONLY from a stored
Review's workspace (Goal B4) + research run (Goal B3). No model call, no new
retrieval, no recomputed evidence — every number and every cited record here
already exists in `get_review_response()`'s output. The memo's data IS the
workspace's data.

Redesigned (2026-06) from 17 dense category sections into 7 consolidated,
exec-facing sections — KPMG/BCG-style: a stat band, a category × severity heat
matrix, one-line "so-what" takeaways, a Risks|Opportunities split, and the full
record list pushed to an appendix. The *data contract* and the B7 citation
safety path are unchanged:

  * `build_sections()` is PURE (no DB, no AI) — one function per section,
    assembled into a dict keyed by SECTION_ORDER. Fully unit-testable on a
    literal workspace dict.
  * `get_memo_response()` is the only async/DB-touching piece: it rehydrates
    the review+run+workspace (`pipeline.diligence.get_review_response`, itself
    zero model calls) and re-validates every record this module is about to
    cite against the run's OWN retrieval sets, reusing
    `pipeline.citation_registry.validate_citations` exactly as B3's synthesis
    validator does — never reimplemented. Anything that fails (would only
    happen on a corrupted/forged input) is silently dropped, never shown.
"""
from __future__ import annotations

from html import escape
from typing import Any

import structlog

from pipeline.citation_registry import get_retrieval_set, validate_citations
from pipeline.diligence import get_review_response
from pipeline.memo_charts import (
    AMBER, PRIMARY, RISK_COLOR, RISK_LABEL, RISK_ORDER,
    connected_network, findings_by_year, render_bar_list_svg,
    render_matrix_svg, render_radial_network_svg, render_trend_bars_svg,
    responsive, risk_distribution, sector_exposure, source_coverage_bars,
)

log = structlog.get_logger()

# Source-table category → diligence section key (CATEGORY values come from
# pipeline.diligence.CATEGORY; mirrored here as a lookup, not redefined).
_LEGISLATIVE = "legislative_regulatory"
_GOVT_SUPPORT = "govt_support"
_LOBBYING = "lobbying_stakeholders"
_POLITICAL = "political_attention"

CAT_LABEL = {
    _POLITICAL: "Political & reputational",
    _LEGISLATIVE: "Legislative & regulatory",
    _GOVT_SUPPORT: "Government support",
    _LOBBYING: "Lobbying & stakeholders",
    "other": "Other signals",
}
CAT_ORDER = [_POLITICAL, _LEGISLATIVE, _GOVT_SUPPORT, _LOBBYING, "other"]
RISK_RANK = {"high": 3, "elevated": 2, "watch": 1}

# 7 consolidated sections (was 17). Order is the reading order of the memo.
SECTION_ORDER = [
    "exec_summary", "risk_snapshot", "material_developments",
    "risks_opportunities", "stakeholders", "diligence_actions", "appendix",
]
SECTION_TITLES = {
    "exec_summary": "Executive summary",
    "risk_snapshot": "Where the exposure concentrates",
    "material_developments": "Material developments",
    "risks_opportunities": "Material risks & opportunities",
    "stakeholders": "Political stakeholders & connections",
    "diligence_actions": "Diligence actions",
    "appendix": "Evidence appendix & coverage",
}
SECTION_KICKERS = {
    "exec_summary": "Bottom line",
    "risk_snapshot": "Risk snapshot",
    "material_developments": "What's moving",
    "risks_opportunities": "So what",
    "stakeholders": "Who",
    "diligence_actions": "Next",
    "appendix": "Evidence",
}

INSUFFICIENT = '<p class="insufficient">Insufficient evidence in this run for this section.</p>'
NO_RUN = '<p class="insufficient">No completed research run for this review.</p>'

# How many findings render in the body before the rest fall to the appendix.
DEV_TAKEAWAY_LIMIT = 7
RISK_OPP_LIMIT = 6


# ── small text/markup helpers ───────────────────────────────────────────────

def _clean(s: Any) -> str:
    return escape(str(s or "").strip())


def _trim(text: Any, words: int) -> str:
    parts = str(text or "").split()
    return str(text or "") if len(parts) <= words else " ".join(parts[:words]) + "…"


def _links(findings: list[dict[str, Any]], cap: int = 3) -> str:
    shown = [f for f in findings if f.get("internal_url")][:cap]
    html = "".join(
        f'<a class="rec" href="{escape(f["internal_url"])}">{escape(str(f["table"]))}:{escape(str(f["pk"]))}</a>'
        for f in shown
    )
    extra = len([f for f in findings if f.get("internal_url")]) - len(shown)
    if extra > 0:
        html += f'<span class="rec-more">+{extra}</span>'
    return html


def _tag(value: str, kind: str = "") -> str:
    cls = f"tag tag-{escape(value)}" if not kind else f"tag tag-{kind}-{escape(value)}"
    return f'<span class="{cls}">{escape(value)}</span>'


def _strip_provider_error(text: str) -> str:
    """Never leak a raw API/provider error string into the deliverable."""
    if text and any(m in text for m in ("provider_error", "credit balance", "invalid_request_error", "request_id")):
        return ""
    return text or ""


# noise the deterministic-fallback paths emit that must never reach the page
_NOISE = ("interpretation_cap_reached", "interpretation cap reached", "non evidentiary", "non_evidentiary")


def _is_noise(s: Any) -> bool:
    low = str(s or "").lower()
    return any(n in low for n in _NOISE)


# ── synthesis citation filter (B7) ──────────────────────────────────────────

def _filtered_synthesis(synthesis: dict[str, Any], valid_keys: set[tuple[str, str]]) -> dict[str, Any]:
    """Drop a synthesis item entirely once its citations are filtered down to
    nothing — an unsupported claim must never render as fact, just minus its
    link (Goal B7)."""
    out = dict(synthesis)
    for key in ("themes", "material_risks", "opportunities"):
        items = []
        for it in synthesis.get(key, []) or []:
            findings = [
                fd for fd in it.get("findings", [])
                if (str(fd.get("table")), str(fd.get("pk"))) in valid_keys
            ]
            if not findings:
                log.warning("memo_dropped_unsupported_synthesis_item", title=it.get("title") or it.get("text"))
                continue
            items.append({**it, "findings": findings})
        out[key] = items
    return out


# ── section builders (pure: ctx in, html out) ───────────────────────────────

def _stat_band(ctx: dict[str, Any]) -> str:
    """The 'answer in five numbers' strip under the cover (rendered by the shell,
    returned here so the data stays in the pure layer)."""
    run, findings, synthesis = ctx["run"], ctx["findings"], ctx["synthesis"]
    bars = risk_distribution(findings)
    top = bars[0]["label"] if bars else "None"
    years = [y["year"] for y in findings_by_year(findings)]
    span = f"{years[0]}–{years[-1]}" if len(years) > 1 else (years[0] if years else "—")
    conf = (synthesis.get("overall_confidence") or "low").title() if run else "—"
    stats = [
        (str(len(findings)), "Findings"),
        (str(len(ctx["coverage"])), "Sources"),
        (span, "Period"),
        (top, "Top risk band"),
        (conf, "Confidence"),
    ]
    cells = "".join(
        f'<div class="stat"><div class="stat-n">{escape(v)}</div><div class="stat-l">{escape(label)}</div></div>'
        for v, label in stats
    )
    return f'<div class="statband">{cells}</div>'


def _s_exec_summary(ctx: dict[str, Any]) -> str:
    run, findings, synthesis = ctx["run"], ctx["findings"], ctx["synthesis"]
    if run is None:
        return NO_RUN
    narrative = _strip_provider_error(synthesis.get("coverage_summary") or "")
    if narrative:
        narrative = escape(_trim(narrative, 75))
    else:
        bars = risk_distribution(findings)
        top = bars[0]["label"].lower() if bars else "no"
        narrative = (
            f"Across {len(findings)} retrieved finding(s) from {len(ctx['coverage'])} source(s), the "
            f"highest observed risk band is <strong>{escape(top)}</strong>. Synthesis below is drawn "
            "only from records retrieved in this run."
        )
    rows = ""
    for t in (synthesis.get("themes") or [])[:5]:
        rows += (
            f'<tr><td class="th-cell"><strong>{_clean(t.get("title") or "Theme")}</strong></td>'
            f'<td>{_clean(_trim(t.get("text"), 45))} <span class="links">{_links(t.get("findings", []))}</span></td></tr>'
        )
    table = (
        '<table class="exec"><thead><tr><th>What we found</th><th>Why it matters</th></tr></thead>'
        f"<tbody>{rows}</tbody></table>" if rows else ""
    )
    return f'<p class="lead">{narrative}</p>{table}'


def _heat_matrix(findings: list[dict[str, Any]]) -> str:
    """Category (rows) × severity (cols) count matrix — the memo's signature
    exhibit. Only categories that appear get a row; absent ones are summarized
    in one muted line, never four empty cards."""
    grid: dict[str, dict[str, int]] = {}
    for f in findings:
        c = f.get("category", "other")
        lvl = f["meta"].get("risk_level", "watch")
        lvl = lvl if lvl in RISK_ORDER else "watch"
        grid.setdefault(c, {k: 0 for k in RISK_ORDER})[lvl] += 1
    present = [c for c in CAT_ORDER if c in grid]
    absent = [CAT_LABEL[c] for c in CAT_ORDER if c not in grid and c != "other"]
    if not present:
        return INSUFFICIENT
    cols = list(RISK_ORDER)  # high, elevated, watch
    col_labels = [RISK_LABEL[c] for c in cols]
    colors = [RISK_COLOR[c] for c in cols]
    values = [[grid[c][lvl] for lvl in cols] for c in present]
    matrix = responsive(render_matrix_svg([CAT_LABEL[c] for c in present], col_labels, values, colors))
    muted = (
        f'<p class="muted">Not observed in this run: {escape(", ".join(absent).lower())}.</p>'
        if absent else ""
    )
    return f'<div class="exhibit">{matrix}</div>{muted}'


def _s_risk_snapshot(ctx: dict[str, Any]) -> str:
    findings = ctx["findings"]
    if not findings:
        return INSUFFICIENT
    heat = _heat_matrix(findings)
    dist = responsive(render_bar_list_svg(risk_distribution(findings), color=PRIMARY, width=380))
    years = findings_by_year(findings)
    tl = responsive(render_trend_bars_svg(years, color=PRIMARY, width=380, height=120)) if years else ""
    sect = sector_exposure(findings)
    sect_svg = responsive(render_bar_list_svg(sect, color=AMBER, width=380)) if sect else ""
    cols = (
        f'<div class="ex"><div class="ex-t">Severity mix</div>{dist}</div>'
        f'<div class="ex"><div class="ex-t">Activity over time</div>{tl}</div>'
    )
    if sect_svg:
        cols += f'<div class="ex"><div class="ex-t">Sector exposure</div>{sect_svg}</div>'
    return f'{heat}<div class="exrow">{cols}</div>'


def _takeaway(f: dict[str, Any]) -> str:
    lvl = f["meta"].get("risk_level", "watch")
    date = f["meta"].get("date") or ""
    headline = _clean(_trim(f.get("source_fact") or f.get("title"), 26))
    sowhat = _clean(_trim(f.get("impact") or f.get("interpretation") or "", 40))
    dot = f'<span class="dot" style="background:{RISK_COLOR.get(lvl, PRIMARY)}"></span>'
    link = _links([f], cap=1)
    so_html = f'<div class="take-s">{sowhat} {link}</div>' if sowhat else (f'<div class="take-s">{link}</div>' if link else "")
    return (
        f'<li>{dot}<div class="take"><div class="take-h">{headline}'
        f'<span class="take-d">{escape(date)}</span></div>{so_html}</div></li>'
    )


def _s_material_developments(ctx: dict[str, Any]) -> str:
    findings = ctx["findings"]
    if not findings:
        return INSUFFICIENT
    ordered = sorted(
        findings,
        key=lambda f: (RISK_RANK.get(f["meta"].get("risk_level"), 1), f["meta"].get("date") or ""),
        reverse=True,
    )
    top = ordered[:DEV_TAKEAWAY_LIMIT]
    items = "".join(_takeaway(f) for f in top)
    more = len(findings) - len(top)
    note = f'<p class="muted">+{more} further finding(s) in the evidence appendix.</p>' if more > 0 else ""
    return f'<ul class="takes">{items}</ul>{note}'


def _synthesis_bullets(items: list[dict[str, Any]]) -> str:
    out = ""
    for it in items[:RISK_OPP_LIMIT]:
        txt = _clean(_trim(it.get("text") or it.get("title"), 40))
        if not txt:
            continue
        out += f'<li>{txt} <span class="links">{_links(it.get("findings", []))}</span></li>'
    return f"<ul>{out}</ul>" if out else '<p class="muted">None identified in this run.</p>'


def _s_risks_opportunities(ctx: dict[str, Any]) -> str:
    syn = ctx["synthesis"]
    risks, opps = syn.get("material_risks") or [], syn.get("opportunities") or []
    if not risks and not opps:
        return INSUFFICIENT
    return (
        '<div class="twocol">'
        f'<div><div class="col-t risk">Material risks</div>{_synthesis_bullets(risks)}</div>'
        f'<div><div class="col-t opp">Opportunities &amp; angles</div>{_synthesis_bullets(opps)}</div>'
        "</div>"
    )


def _s_stakeholders(ctx: dict[str, Any]) -> str:
    connected = ctx["connected"]
    if not connected:
        return INSUFFICIENT
    nodes = connected_network(connected)
    chart = responsive(render_radial_network_svg(ctx["review"].get("company") or "Subject", nodes, size=300))
    actors = "".join(
        f'<li><a href="{escape(c["internal_url"])}">{escape(c["title"])}</a> {_tag(c.get("kind", ""))}</li>'
        for c in connected[:10]
    )
    return f'<div class="netwrap"><div class="net">{chart}</div><ul class="actors">{actors}</ul></div>'


def _s_diligence_actions(ctx: dict[str, Any]) -> str:
    qs = [q for q in (ctx["synthesis"].get("diligence_questions") or []) if not _is_noise(q)]
    gaps = [
        g for g in ctx["further"]
        if g.get("title") and not _is_noise(g.get("title")) and not _is_noise(g.get("type"))
    ]
    parts = ""
    if qs:
        q_html = "".join(f"<li>{_clean(q)}</li>" for q in qs[:6])
        parts += f'<div class="col-t">Questions for management</div><ol class="qs">{q_html}</ol>'
    if gaps:
        g_html = ""
        for g in gaps[:6]:
            title = _clean(g.get("title") or g.get("type"))
            g_html += (
                f'<li><a href="{escape(g["internal_url"])}">{title}</a></li>'
                if g.get("internal_url") else f"<li>{title}</li>"
            )
        parts += f'<div class="col-t">Lines to pursue</div><ul>{g_html}</ul>'
    return parts or INSUFFICIENT


def _s_appendix(ctx: dict[str, Any]) -> str:
    findings, run, synthesis = ctx["findings"], ctx["run"], ctx["synthesis"]
    if not findings:
        return INSUFFICIENT
    rows = ""
    for f in sorted(findings, key=lambda f: (f["meta"].get("source_label", ""), f["meta"].get("date") or "")):
        link = f'<a href="{escape(f["internal_url"])}">open</a>' if f.get("internal_url") else ""
        lvl = f["meta"].get("risk_level", "watch")
        rows += (
            f'<tr><td>{escape(f["meta"].get("source_label", ""))}</td>'
            f'<td>{_tag(lvl, "risk")}</td>'
            f'<td>{_clean(_trim(f.get("source_fact") or f.get("title"), 32))}</td>'
            f'<td>{escape(f["meta"].get("date") or "")}</td><td>{link}</td></tr>'
        )
    table = (
        '<table class="appx"><thead><tr><th>Source</th><th>Risk</th><th>Record</th>'
        f'<th>Date</th><th></th></tr></thead><tbody>{rows}</tbody></table>'
    )
    cov = source_coverage_bars(ctx["coverage"])
    cov_svg = responsive(render_bar_list_svg(cov, color=AMBER, width=380)) if cov else ""
    cov_block = f'<div class="ex-t">Source coverage</div><div class="exhibit-sm">{cov_svg}</div>' if cov_svg else ""
    method = "AI-assisted (Claude)" if synthesis.get("generated_by") == "claude" else "Deterministic fallback — analyst review required"
    meta = (
        f'<p class="muted">Method: {method} · {run.get("rounds_used", 0)}/{run.get("max_rounds", 0)} rounds · '
        f'{run.get("model_call_count", 0)} model calls · provider {escape(run.get("provider", "none"))}. '
        "Every cited record is independently retrievable at /records/&lt;table&gt;/&lt;pk&gt;.</p>"
    )
    return f"{cov_block}{table}{meta}"


_BUILDERS = {
    "exec_summary": _s_exec_summary,
    "risk_snapshot": _s_risk_snapshot,
    "material_developments": _s_material_developments,
    "risks_opportunities": _s_risks_opportunities,
    "stakeholders": _s_stakeholders,
    "diligence_actions": _s_diligence_actions,
    "appendix": _s_appendix,
}


def build_sections(
    review: dict[str, Any], run: dict[str, Any] | None, workspace: dict[str, Any],
    valid_keys: set[tuple[str, str]],
) -> dict[str, str]:
    """Pure: every section built only from the (already-validated) workspace +
    run dicts already returned by `get_review_response`. No DB, no AI. The
    `valid_keys` gate is the B7 guarantee — a record absent from it can never
    reach a rendered section."""
    findings = [f for f in workspace.get("findings", []) if (str(f["table"]), str(f["pk"])) in valid_keys]
    connected = [c for c in workspace.get("connected", []) if (str(c["table"]), str(c["pk"])) in valid_keys]
    further = [
        g for g in workspace.get("further_research", [])
        if not g.get("table") or (str(g["table"]), str(g.get("pk"))) in valid_keys
    ]
    synthesis = _filtered_synthesis((run or {}).get("synthesis") or {}, valid_keys)

    ctx = {
        "review": review, "run": run, "findings": findings, "connected": connected,
        "synthesis": synthesis, "coverage": workspace.get("source_coverage", []), "further": further,
    }
    out: dict[str, str] = {key: _BUILDERS[key](ctx) for key in SECTION_ORDER}
    out["_stat_band"] = _stat_band(ctx)  # not a section; the shell consumes it
    return out


# ── orchestrator (the only DB-touching part) ────────────────────────────────

async def _collect_run_allowed_ids(session, run: dict[str, Any]) -> set[tuple[str, str]]:
    """The union of every (table, pk) this run actually retrieved, rebuilt
    straight from its persisted retrieval sets — the same definition of
    "in-run" that B3's synthesis validator uses."""
    allowed: set[tuple[str, str]] = set()
    for rd in run.get("rounds", []):
        for rs in rd.get("retrieval_sets", []):
            sid = rs.get("id")
            if not sid:
                continue
            row = await get_retrieval_set(session, sid)
            if row is None:
                continue
            for t, p in row.record_ids:
                allowed.add((str(t), str(p)))
    return allowed


async def get_memo_response(session, review_id: str) -> dict[str, Any] | None:
    """The memo's data: rehydrated review/run/workspace + every cited record
    re-validated against the run's own retrieval sets (defense in depth — every
    finding already passed this check once at B2/B3 time; this is the same
    primitive, re-run, never a second implementation)."""
    resp = await get_review_response(session, review_id)
    if resp is None:
        return None
    review, run, workspace = resp["review"], resp["run"], resp["workspace"]

    if run is None:
        sections = {key: NO_RUN for key in SECTION_ORDER}
        sections["_stat_band"] = _stat_band({
            "run": None, "findings": [], "synthesis": {}, "coverage": [],
        })
        return {
            "review": review, "run": None, "sections": sections,
            "section_titles": SECTION_TITLES, "section_order": SECTION_ORDER,
            "section_kickers": SECTION_KICKERS,
        }

    allowed = await _collect_run_allowed_ids(session, run)

    cited: list[tuple[str, str]] = []
    cited += [(str(f["table"]), str(f["pk"])) for f in workspace.get("findings", [])]
    cited += [(str(c["table"]), str(c["pk"])) for c in workspace.get("connected", [])]
    cited += [
        (str(g["table"]), str(g["pk"]))
        for g in workspace.get("further_research", []) if g.get("table") and g.get("pk")
    ]
    synthesis = run.get("synthesis") or {}
    for key in ("themes", "material_risks", "opportunities"):
        for it in synthesis.get(key, []) or []:
            cited += [(str(fd["table"]), str(fd["pk"])) for fd in it.get("findings", [])]

    check = validate_citations(allowed, cited)
    if check["invalid"]:
        log.warning("memo_dropped_out_of_run_citations", review_id=review_id, dropped=len(check["invalid"]))
    valid_keys = set(check["valid"])

    sections = build_sections(review, run, workspace, valid_keys)
    return {
        "review": review, "run": run, "sections": sections,
        "section_titles": SECTION_TITLES, "section_order": SECTION_ORDER,
        "section_kickers": SECTION_KICKERS,
    }
