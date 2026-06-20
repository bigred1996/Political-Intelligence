"""Render a stored Report as a polished, branded HTML page (web + print/PDF)."""
from __future__ import annotations

from pipeline.report_builder import SECTION_ORDER, SECTION_TITLES

_SCORE_LABELS = [
    ("regulatory_risk", "Regulatory Risk"), ("policy_volatility", "Policy Volatility"),
    ("election_sensitivity", "Election Sensitivity"), ("lobbying_intensity", "Lobbying Intensity"),
]


def _score_color(v: float) -> str:
    if v >= 7: return "#c0392b"
    if v >= 4: return "#e08e0b"
    return "#1e8e5a"


def render_report_html(report, for_pdf: bool = False) -> str:
    scores = report.risk_scores or {}
    overall = scores.get("overall", 0)
    evidence = report.evidence or {}

    cards = "".join(
        f"""<div class="score">
              <div class="score-val" style="color:{_score_color(scores.get(k,0))}">{scores.get(k,0)}<span>/10</span></div>
              <div class="score-label">{label}</div>
            </div>""" for k, label in _SCORE_LABELS
    )

    sections_html = "".join(
        f"""<section><h2>{i+1}. {SECTION_TITLES[k]}</h2><div class="body">{report.sections.get(k,'') or '<p>—</p>'}</div></section>"""
        for i, k in enumerate(SECTION_ORDER)
    )
    findings = evidence.get("graph_findings") or []
    findings_html = ""
    if findings:
        items = "".join(
            f"""<tr>
                  <td>{f.get('severity','').title()}</td>
                  <td><strong>{f.get('title','')}</strong><br><span>{f.get('summary','')}</span></td>
                  <td>{', '.join(r.get('source','') for r in (f.get('references') or [])[:3])}</td>
                </tr>"""
            for f in findings[:8]
        )
        findings_html = f"""<section><h2>Connected Findings</h2>
          <div class="body"><p>These are deterministic cross-source patterns generated from the same evidence layer that powers the Nessus workspace.</p>
          <table><thead><tr><th>Severity</th><th>Finding</th><th>Evidence</th></tr></thead><tbody>{items}</tbody></table></div>
        </section>"""
    refs = evidence.get("source_references") or []
    sources_html = ""
    if refs:
        def _reference_cell(r: dict) -> str:
            table = r.get("table")
            pk = r.get("pk") or r.get("id")
            if table and pk:
                return f'<a href="/records/{table}/{pk}">Nessus record</a>'
            if r.get("url"):
                return f'<a href="{r.get("url")}">source</a>'
            return "Nessus record"

        rows = "".join(
            f"""<tr>
                  <td>{(r.get('source') or '').replace('_', ' ')}</td>
                  <td>{r.get('title') or ''}</td>
                  <td>{r.get('date') or ''}</td>
                  <td>{_reference_cell(r)}</td>
                </tr>"""
            for r in refs[:30]
        )
        sources_html = f"""<section><h2>Sources Used</h2>
          <div class="body"><p>This brief is grounded in the records below. Nessus keeps the underlying source rows available for analyst review.</p>
          <table><thead><tr><th>Source</th><th>Record</th><th>Date</th><th>Reference</th></tr></thead><tbody>{rows}</tbody></table></div>
        </section>"""

    draft_banner = "" if report.status == "approved" else \
        '<div class="banner">DRAFT — pending analyst approval</div>'
    method = "AI-drafted (Claude)" if report.generated_by == "claude" else "Evidence template (analyst-review required)"

    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Nessus — {report.company_name} Political Risk Report</title>
<style>
  body {{ font: 15px/1.65 Georgia, "Times New Roman", serif; color:#1a1f2b; margin:0; background:#f4f5f7; }}
  .page {{ max-width: 820px; margin: 0 auto; background:#fff; }}
  .masthead {{ background:#0b1020; color:#fff; padding:36px 48px; }}
  .masthead .brand {{ font-family:-apple-system,Segoe UI,sans-serif; letter-spacing:.5px; font-size:13px; color:#7f9cff; text-transform:uppercase; }}
  .masthead h1 {{ margin:8px 0 4px; font-size:28px; }}
  .masthead .meta {{ font-family:-apple-system,Segoe UI,sans-serif; color:#9aa6c0; font-size:13px; }}
  .banner {{ background:#fff3cd; color:#8a6d00; text-align:center; padding:8px; font-family:-apple-system,sans-serif; font-size:12px; font-weight:600; letter-spacing:.5px; }}
  .overall {{ display:flex; align-items:center; gap:16px; padding:24px 48px; border-bottom:1px solid #eee; }}
  .overall .big {{ font-family:-apple-system,sans-serif; font-size:46px; font-weight:700; color:{_score_color(overall)}; }}
  .overall .big span {{ font-size:20px; color:#aaa; }}
  .scores {{ display:grid; grid-template-columns:repeat(4,1fr); gap:0; border-bottom:1px solid #eee; }}
  .score {{ padding:18px; text-align:center; border-right:1px solid #f0f0f0; }}
  .score-val {{ font-family:-apple-system,sans-serif; font-size:26px; font-weight:700; }}
  .score-val span {{ font-size:13px; color:#bbb; }}
  .score-label {{ font-family:-apple-system,sans-serif; font-size:11px; color:#777; text-transform:uppercase; letter-spacing:.5px; margin-top:4px; }}
  section {{ padding:22px 48px; border-bottom:1px solid #f2f2f2; }}
  section h2 {{ font-family:-apple-system,Segoe UI,sans-serif; font-size:17px; color:#0b1020; margin:0 0 10px; }}
  .body table {{ width:100%; border-collapse:collapse; font-family:-apple-system,sans-serif; font-size:12.5px; margin-top:6px; }}
  .body th {{ text-align:left; background:#f7f8fa; padding:7px 9px; border-bottom:2px solid #e6e8ee; font-size:11px; text-transform:uppercase; letter-spacing:.4px; color:#667; }}
  .body td {{ padding:7px 9px; border-bottom:1px solid #f0f1f4; vertical-align:top; }}
  .footer {{ padding:24px 48px; font-family:-apple-system,sans-serif; font-size:11px; color:#99a; }}
  .actions {{ padding:16px 48px; font-family:-apple-system,sans-serif; }}
  .actions a {{ color:#4f7cff; text-decoration:none; font-size:13px; }}
  @media print {{ body {{ background:#fff; }} .actions {{ display:none; }} }}
</style></head><body><div class="page">
  {draft_banner}
  <div class="masthead">
    <div class="brand">Nessus Intelligence · Political Due Diligence</div>
    <h1>{report.company_name}</h1>
    <div class="meta">{report.report_type.replace('_',' ').title()} · Horizon: {report.time_horizon} · Report {report.id}</div>
  </div>
  <div class="overall">
    <div class="big">{overall}<span>/10</span></div>
    <div style="font-family:-apple-system,sans-serif"><strong>Overall Political Risk</strong><br>
      <span style="color:#778;font-size:13px">Generated via: {method}</span></div>
  </div>
  <div class="scores">{cards}</div>
  {findings_html}
  {sections_html}
  {sources_html}
  <div class="actions">{'' if for_pdf else f'<a href="/report/{report.id}/pdf">⬇ Download / Print PDF</a>'}</div>
  <div class="footer">Nessus Intelligence — sourced from Government of Canada open data (lobbying registry, federal contracts, Elections Canada contributions, LEGISinfo). For institutional due-diligence use.</div>
</div></body></html>"""
