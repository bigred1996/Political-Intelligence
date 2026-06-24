"""Goal B6 — branded PDF memo: section content, built ONLY from a stored
Review's workspace (Goal B4) + research run (Goal B3). No model call, no new
retrieval, no recomputed evidence — every number and every cited record here
already exists in `get_review_response()`'s output. The PDF's data IS the
workspace's data.

Two layers, like `pipeline/report_builder.py`'s split, but adapted (not
reused) because the data shape and the no-AI-call constraint are both
different here:

  * `build_sections()` is PURE (no DB, no AI) — one function per section,
    assembled into a dict, the same "dict-of-renderers" shape
    `report_builder.build_sections` uses. Fully unit-testable on a literal
    workspace dict.
  * `get_memo_response()` is the only async/DB-touching piece: it rehydrates
    the review+run+workspace (`pipeline.diligence.get_review_response`,
    itself zero model calls) and re-validates every record this module is
    about to cite against the run's OWN retrieval sets, reusing
    `pipeline.citation_registry.validate_citations` exactly as B3's synthesis
    validator does — never reimplemented. Anything that fails (would only
    happen on a corrupted/forged input) is silently dropped from the
    rendered output, never shown, never crashes.
"""
from __future__ import annotations

import re
from html import escape
from typing import Any

import structlog

from pipeline.citation_registry import get_retrieval_set, validate_citations
from pipeline.diligence import get_review_response
from pipeline.memo_charts import (
    AMBER,
    PRIMARY,
    connected_network,
    findings_by_year,
    render_bar_list_svg,
    render_radial_network_svg,
    render_trend_bars_svg,
    risk_distribution,
    sector_exposure,
    source_coverage_bars,
)

log = structlog.get_logger()

# Source-table category → diligence section key (CATEGORY values come from
# pipeline.diligence.CATEGORY; mirrored here as a lookup, not redefined).
_LEGISLATIVE = "legislative_regulatory"
_GOVT_SUPPORT = "govt_support"
_LOBBYING = "lobbying_stakeholders"
_POLITICAL = "political_attention"

SECTION_ORDER = [
    "exec_summary", "overall_risk", "company_sector_exposure", "material_developments",
    "legislative_regulatory", "govt_support_dependencies", "lobbying_stakeholders",
    "political_reputational_attention", "key_actors", "cross_source_connections",
    "upcoming_events", "risks", "opportunities", "questions_for_management",
    "further_investigation", "evidence_appendix", "coverage_limitations",
]
SECTION_TITLES = {
    "exec_summary": "Executive Summary",
    "overall_risk": "Overall Risk",
    "company_sector_exposure": "Company & Sector Exposure",
    "material_developments": "Material Developments",
    "legislative_regulatory": "Legislative & Regulatory",
    "govt_support_dependencies": "Government Support & Dependencies",
    "lobbying_stakeholders": "Lobbying & Stakeholders",
    "political_reputational_attention": "Political & Reputational Attention",
    "key_actors": "Key Actors",
    "cross_source_connections": "Cross-Source Connections",
    "upcoming_events": "Upcoming Events",
    "risks": "Risks",
    "opportunities": "Opportunities",
    "questions_for_management": "Questions for Management",
    "further_investigation": "Further Investigation",
    "evidence_appendix": "Evidence Appendix",
    "coverage_limitations": "Coverage & Limitations",
}

INSUFFICIENT = '<p class="insufficient">Insufficient evidence in this run for this section.</p>'
NO_RUN = '<p class="insufficient">No completed research run for this review.</p>'

EXEC_SUMMARY_WORD_CAP = 300
SECTION_WORD_CAP = 500  # analytical sections: 300–500 words MAX (appendix is unbounded)


# ── word-cap enforcement (generic — trims trailing <li> items, never mid-sentence) ──

_TAG_RE = re.compile(r"<[^>]+>")
_LI_RE = re.compile(r"<li>.*?</li>", re.S)


def _word_count(html: str) -> int:
    return len(_TAG_RE.sub(" ", html).split())


def _cap_words(html: str, max_words: int) -> str:
    """Trim trailing list items until under the cap, never truncate mid-item.
    A non-list section that's already over cap is left alone — its content is
    a handful of fixed sentences by construction, not an unbounded list."""
    if _word_count(html) <= max_words:
        return html
    items = _LI_RE.findall(html)
    if not items:
        return html
    prefix = html[: html.index(items[0])]
    suffix = html[html.index(items[-1]) + len(items[-1]):]
    used = _word_count(prefix) + _word_count(suffix)
    kept: list[str] = []
    for it in items:
        w = _word_count(it)
        if kept and used + w > max_words:
            break
        kept.append(it)
        used += w
    dropped = len(items) - len(kept)
    note = f'<p class="more-note">+{dropped} more finding(s) — see Evidence appendix.</p>' if dropped else ""
    return prefix + "".join(kept) + suffix + note


# ── shared render helpers ───────────────────────────────────────────────────

def _tag(value: str, kind: str = "") -> str:
    cls = f"tag tag-{escape(value)}" if not kind else f"tag tag-{kind}-{escape(value)}"
    return f'<span class="{cls}">{escape(value)}</span>'


def _finding_bullet(f: dict[str, Any]) -> str:
    """claim → evidence → so-what, one bullet per finding: source_fact is the
    claim/evidence, interpretation+impact is the so-what, the link is the
    underlying evidentiary record."""
    meta = f.get("meta", {})
    bits = [escape(f.get("source_fact") or f.get("title") or "")]
    if f.get("interpretation"):
        bits.append(escape(f["interpretation"]))
    if f.get("impact"):
        bits.append(f'<span class="so-what">{escape(f["impact"])}</span>')
    link = (
        f' <a class="rec-link" href="{escape(f["internal_url"])}">{escape(f["table"])}:{escape(str(f["pk"]))}</a>'
        if f.get("internal_url") else ""
    )
    risk_html = _tag(meta.get("risk_level", "watch"), "risk")
    return f"<li>{risk_html} {' — '.join(bits)}{link}</li>"


def _synthesis_list(items: list[dict[str, Any]]) -> str:
    rows = []
    for it in items:
        label = it.get("label", "observed")
        title = f'<strong>{escape(it["title"])}</strong> — ' if it.get("title") else ""
        links = "".join(
            f'<a class="rec-link" href="{escape(fd["internal_url"])}">{escape(fd["table"])}:{escape(str(fd["pk"]))}</a>'
            for fd in it.get("findings", []) if fd.get("internal_url")
        )
        rows.append(f"<li>{_tag(label, 'label')} {title}{escape(it.get('text', ''))} {links}</li>")
    return f"<ul>{''.join(rows)}</ul>"


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

def _s_exec_summary(ctx: dict[str, Any]) -> str:
    run, findings, synthesis = ctx["run"], ctx["findings"], ctx["synthesis"]
    if run is None:
        return NO_RUN
    bars = risk_distribution(findings)
    top_risk = bars[0]["label"] if bars else "none observed"
    parts = [
        f"<p><strong>{escape(ctx['review']['company'])}</strong> — "
        f"{escape(ctx['review'].get('depth_tier', 'standard')).title()}-tier diligence review. "
        f"{len(findings)} finding(s) across {len(ctx['coverage'])} source(s), "
        f"{run.get('rounds_used', 0)} research round(s). Overall confidence: "
        f"<strong>{escape(synthesis.get('overall_confidence', 'low'))}</strong>. "
        f"Highest risk band observed: <strong>{escape(top_risk)}</strong>.</p>"
    ]
    if synthesis.get("coverage_summary"):
        parts.append(f"<p>{escape(synthesis['coverage_summary'])}</p>")
    if synthesis.get("material_risks") or synthesis.get("opportunities"):
        parts.append(
            f"<p>{len(synthesis.get('material_risks', []))} material risk(s) and "
            f"{len(synthesis.get('opportunities', []))} opportunity(ies) identified "
            "— see Risks / Opportunities.</p>"
        )
    return "".join(parts)


def _s_overall_risk(ctx: dict[str, Any]) -> str:
    findings = ctx["findings"]
    if not findings:
        return INSUFFICIENT
    bars = risk_distribution(findings)
    chart = render_bar_list_svg(bars, color=PRIMARY)
    counts = ", ".join(f"{b['value']} {b['label'].lower()}" for b in bars)
    high = sorted(
        (f for f in findings if f["meta"].get("risk_level") == "high"),
        key=lambda f: f["meta"].get("date") or "", reverse=True,
    )
    body = f'<div class="chart">{chart}</div><p>{len(findings)} finding(s): {counts}.</p>'
    if high:
        body += f'<p class="lead">Highest-severity findings:</p><ul>{"".join(_finding_bullet(f) for f in high)}</ul>'
    return body


def _s_company_sector_exposure(ctx: dict[str, Any]) -> str:
    declared = ctx["review"].get("sectors") or []
    bars = sector_exposure(ctx["findings"])
    declared_html = ", ".join(escape(s) for s in declared) if declared else "none declared"
    if bars:
        touched_html = ", ".join(f"{escape(b['label'])} ({b['value']})" for b in bars)
        chart = f'<div class="chart">{render_bar_list_svg(bars, color=PRIMARY)}</div>'
    else:
        touched_html = "no tracked sector resolved from retrieved evidence"
        chart = ""
    return f"<p>Declared scope: {declared_html}.</p><p>Evidence touches: {touched_html}.</p>{chart}"


def _s_material_developments(ctx: dict[str, Any]) -> str:
    findings = ctx["findings"]
    if not findings:
        return INSUFFICIENT
    years = findings_by_year(findings)
    chart = f'<div class="chart">{render_trend_bars_svg(years, color=PRIMARY)}</div>' if years else ""
    ordered = sorted(findings, key=lambda f: f["meta"].get("date") or "", reverse=True)
    return f"{chart}<ul>{''.join(_finding_bullet(f) for f in ordered)}</ul>"


def _category_section(category: str):
    def _builder(ctx: dict[str, Any]) -> str:
        items = [f for f in ctx["findings"] if f.get("category") == category]
        if not items:
            return INSUFFICIENT
        return f"<ul>{''.join(_finding_bullet(f) for f in items)}</ul>"
    return _builder


def _s_key_actors(ctx: dict[str, Any]) -> str:
    actors = [c for c in ctx["connected"] if c["kind"] in ("politicians", "committees")]
    if not actors:
        return INSUFFICIENT
    items = "".join(
        f'<li><a href="{escape(c["internal_url"])}">{escape(c["title"])}</a> {_tag(c["kind"])}</li>'
        for c in actors
    )
    return f"<ul>{items}</ul>"


def _s_cross_source_connections(ctx: dict[str, Any]) -> str:
    connected = ctx["connected"]
    if not connected:
        return INSUFFICIENT
    nodes = connected_network(connected)
    chart = render_radial_network_svg(ctx["review"].get("company") or "Subject", nodes)
    items = "".join(
        f'<li><a href="{escape(c["internal_url"])}">{escape(c["title"])}</a> {_tag(c["kind"])}</li>'
        for c in connected
    )
    return f'<div class="chart">{chart}</div><ul>{items}</ul>'


def _s_upcoming_events(ctx: dict[str, Any]) -> str:
    dated = [f for f in ctx["findings"] if f["meta"].get("date")]
    if not dated:
        return INSUFFICIENT
    ordered = sorted(dated, key=lambda f: f["meta"]["date"], reverse=True)[:10]
    note = (
        '<p class="note">Nessus retrieves historical public records, not a forward calendar — '
        "the most recently dated activity is shown as the closest available signal for "
        "forthcoming developments.</p>"
    )
    return f"{note}<ul>{''.join(_finding_bullet(f) for f in ordered)}</ul>"


def _s_risks(ctx: dict[str, Any]) -> str:
    items = ctx["synthesis"].get("material_risks", [])
    return _synthesis_list(items) if items else INSUFFICIENT


def _s_opportunities(ctx: dict[str, Any]) -> str:
    items = ctx["synthesis"].get("opportunities", [])
    return _synthesis_list(items) if items else INSUFFICIENT


def _s_questions_for_management(ctx: dict[str, Any]) -> str:
    qs = ctx["synthesis"].get("diligence_questions", [])
    if not qs:
        return INSUFFICIENT
    return f"<ol>{''.join(f'<li>{escape(q)}</li>' for q in qs)}</ol>"


def _s_further_investigation(ctx: dict[str, Any]) -> str:
    gaps = ctx["further"]
    if not gaps:
        return INSUFFICIENT
    items = []
    for g in gaps:
        label = _tag(str(g.get("type", "")).replace("_", " "))
        title = escape(g.get("title") or g.get("type", ""))
        if g.get("internal_url"):
            items.append(f'<li><a href="{escape(g["internal_url"])}">{title}</a> {label}</li>')
        else:
            items.append(f"<li>{title} {label}</li>")
    return f"<ul>{''.join(items)}</ul>"


def _s_evidence_appendix(ctx: dict[str, Any]) -> str:
    findings = ctx["findings"]
    if not findings:
        return INSUFFICIENT
    rows = []
    for f in sorted(findings, key=lambda f: (f["meta"].get("source_label", ""), f["meta"].get("date") or "")):
        link = f'<a href="{escape(f["internal_url"])}">record</a>' if f.get("internal_url") else ""
        rows.append(
            f"<tr><td>{escape(f['meta'].get('source_label', ''))}</td>"
            f"<td>{escape(f['table'])}:{escape(str(f['pk']))}</td>"
            f"<td>{escape(f['meta'].get('date') or '')}</td><td>{link}</td></tr>"
        )
    return (
        "<table><thead><tr><th>Source</th><th>Record</th><th>Date</th><th>Link</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _s_coverage_limitations(ctx: dict[str, Any]) -> str:
    run, synthesis = ctx["run"], ctx["synthesis"]
    if run is None:
        return NO_RUN
    bars = source_coverage_bars(ctx["coverage"])
    chart = f'<div class="chart">{render_bar_list_svg(bars, color=AMBER)}</div>' if bars else ""
    method = (
        "AI-assisted (Claude)" if synthesis.get("generated_by") == "claude"
        else "Deterministic fallback — analyst review required"
    )
    stats = (
        f"<p>Rounds: {run.get('rounds_used', 0)}/{run.get('max_rounds', 0)} &middot; "
        f"Interpretations: {run.get('interpretations_used', 0)}/{run.get('max_interpretations', 0)} &middot; "
        f"Model calls: {run.get('model_call_count', 0)} &middot; Provider: {escape(run.get('provider', 'none'))} "
        f"&middot; Synthesis method: {method}.</p>"
    )
    return f"{chart}{stats}"


_BUILDERS = {
    "exec_summary": _s_exec_summary,
    "overall_risk": _s_overall_risk,
    "company_sector_exposure": _s_company_sector_exposure,
    "material_developments": _s_material_developments,
    "legislative_regulatory": _category_section(_LEGISLATIVE),
    "govt_support_dependencies": _category_section(_GOVT_SUPPORT),
    "lobbying_stakeholders": _category_section(_LOBBYING),
    "political_reputational_attention": _category_section(_POLITICAL),
    "key_actors": _s_key_actors,
    "cross_source_connections": _s_cross_source_connections,
    "upcoming_events": _s_upcoming_events,
    "risks": _s_risks,
    "opportunities": _s_opportunities,
    "questions_for_management": _s_questions_for_management,
    "further_investigation": _s_further_investigation,
    "evidence_appendix": _s_evidence_appendix,
    "coverage_limitations": _s_coverage_limitations,
}


def build_sections(
    review: dict[str, Any], run: dict[str, Any] | None, workspace: dict[str, Any],
    valid_keys: set[tuple[str, str]],
) -> dict[str, str]:
    """Pure: every section built only from the (already-validated) workspace
    + run dicts already returned by `get_review_response`. No DB, no AI."""
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

    out: dict[str, str] = {}
    for key in SECTION_ORDER:
        html = _BUILDERS[key](ctx)
        if key == "exec_summary":
            html = _cap_words(html, EXEC_SUMMARY_WORD_CAP)
        elif key != "evidence_appendix":
            html = _cap_words(html, SECTION_WORD_CAP)
        out[key] = html
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
    """The PDF memo's data: rehydrated review/run/workspace + every cited
    record re-validated against the run's own retrieval sets (defense in
    depth — every finding already passed this check once at B2/B3 time; this
    is the same primitive, re-run, never a second implementation)."""
    resp = await get_review_response(session, review_id)
    if resp is None:
        return None
    review, run, workspace = resp["review"], resp["run"], resp["workspace"]

    if run is None:
        sections = {key: NO_RUN for key in SECTION_ORDER}
        return {
            "review": review, "run": None, "sections": sections,
            "section_titles": SECTION_TITLES, "section_order": SECTION_ORDER,
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
    }
