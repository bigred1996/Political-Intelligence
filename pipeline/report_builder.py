"""Report builder — generate the 9 report sections from gathered evidence.

Two paths, same output shape:
- Claude path (when ANTHROPIC_API_KEY is set): one API call per section, using the
  prompts in /prompts (never hardcoded), per CLAUDE.md conventions.
- Template path (no key): deterministic, evidence-driven HTML so the full product is
  testable now. Marked as generated_by="template" so analysts know to review harder.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger()

PROMPTS = Path("prompts")
SECTION_ORDER = [
    "executive_summary", "risk_scorecard", "regulatory_landscape", "political_stakeholders",
    "lobbying_activity", "political_donations", "government_contracts", "bills_policy", "deal_impact",
]
SECTION_TITLES = {
    "executive_summary": "Executive Summary",
    "risk_scorecard": "Risk Scorecard",
    "regulatory_landscape": "Regulatory Landscape",
    "political_stakeholders": "Political Stakeholders",
    "lobbying_activity": "Lobbying Activity",
    "political_donations": "Political Donations",
    "government_contracts": "Government Contracts",
    "bills_policy": "Bills & Policy Exposure",
    "deal_impact": "Deal Impact Summary",
}


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _fmt_money(v: float | None) -> str:
    return f"${v:,.0f}" if v else "$0"


# ── Template (no-key) renderers ──────────────────────────────────────────────
def _t_executive_summary(ev, scores) -> str:
    c = ev["contracts"]; l = ev["lobbying"]; b = ev["bills"]
    return (
        f"<p><strong>{ev['company']}</strong> presents an overall political-risk score of "
        f"<strong>{scores['overall']}/10</strong>. The federal record shows "
        f"<strong>{l['count']}</strong> lobbying registration(s), "
        f"<strong>{c['count']}</strong> federal contract(s) totalling <strong>{_fmt_money(c['total_value'])}</strong>, "
        f"and <strong>{b['count']}</strong> potentially relevant bill(s) before Parliament. "
        f"Regulatory risk is rated {scores['regulatory_risk']}/10 and lobbying intensity {scores['lobbying_intensity']}/10. "
        f"{'Engagement with Ottawa is material and should be diligenced directly.' if l['count'] else 'Limited direct federal lobbying footprint — engagement appears low.'}</p>"
    )


def _t_risk_scorecard(ev, scores) -> str:
    rows = "".join(
        f"<tr><td>{label}</td><td><strong>{scores[key]}/10</strong></td><td>{scores['drivers'].get(key,'')}</td></tr>"
        for key, label in [
            ("regulatory_risk", "Regulatory risk"), ("policy_volatility", "Policy volatility"),
            ("election_sensitivity", "Election sensitivity"), ("lobbying_intensity", "Lobbying intensity"),
        ]
    )
    return (
        f"<table><thead><tr><th>Dimension</th><th>Score</th><th>Driver</th></tr></thead><tbody>{rows}</tbody></table>"
        f"<p><strong>Overall: {scores['overall']}/10</strong> (weighted).</p>"
    )


def _t_regulatory_landscape(ev, scores) -> str:
    depts = ev["contracts"]["by_department"]
    items = "".join(f"<li>{d['dept']} — {_fmt_money(d['value'])} across {d['count']} contract(s)</li>" for d in depts)
    body = f"<p>Departmental exposure inferred from federal contracting:</p><ul>{items}</ul>" if items else \
        "<p>No federal contracting footprint found for this entity, limiting visible departmental exposure.</p>"
    return body


def _t_political_stakeholders(ev, scores) -> str:
    # Build stakeholder list from Hansard mentions + DPOH contacts from lobbying records
    stakeholders = ev.get("stakeholders", [])

    # Also pull DPOH contacts from lobbying records as stakeholders
    dpoh_contacts: dict[str, dict] = {}
    for rec in ev["lobbying"]["records"][:50]:
        for contact in (rec.get("dpoh_contacts") or []):
            name = contact.get("name", "").strip()
            if name and name not in dpoh_contacts:
                dpoh_contacts[name] = {
                    "name": name,
                    "role": f"{contact.get('title','').strip()} — {contact.get('institution','').strip()}".strip(" —"),
                    "position": "neutral",
                    "source": "OCL DPOH (lobbied official)",
                }

    all_stakeholders = list(stakeholders)
    for name, s in list(dpoh_contacts.items())[:10]:
        if not any(x["name"] == name for x in all_stakeholders):
            all_stakeholders.append(s)

    insts = ev["lobbying"]["institutions"]
    inst_html = f"<p><strong>Institutions lobbied (OCL registry):</strong> {', '.join(insts[:8])}.</p>" if insts else ""

    items = "".join(
        f"<tr><td><strong>{s['name']}</strong></td><td>{s.get('role','')}</td>"
        f"<td>{s.get('position','neutral')}</td>"
        f"<td style='font-size:11px;color:var(--muted,#888)'>{s.get('source','') or s.get('date','') or ''}</td></tr>"
        for s in all_stakeholders[:15]
    )
    table = (f"<table><thead><tr><th>Name</th><th>Role / Title</th><th>Position</th><th>Source</th></tr></thead>"
             f"<tbody>{items}</tbody></table>") if items else "<p>Stakeholder data not available.</p>"
    return f"{inst_html}{table}"


def _t_lobbying_activity(ev, scores) -> str:
    lob = ev["lobbying"]
    recs = lob["records"]
    if not recs:
        return "<p>No federal lobbying communications found for this entity in the OCL registry.</p>"

    # Aggregate subject matters and institutions
    all_subjects: dict[str, int] = {}
    all_insts: dict[str, int] = {}
    registrant_set: set[str] = set()
    for r in recs:
        for sm in (r.get("subject_matters") or []):
            all_subjects[sm] = all_subjects.get(sm, 0) + 1
        for inst in (r.get("institutions") or []):
            all_insts[inst] = all_insts.get(inst, 0) + 1
        if r.get("registrant"):
            registrant_set.add(r["registrant"])

    top_subjects = sorted(all_subjects.items(), key=lambda x: -x[1])[:8]
    top_insts = sorted(all_insts.items(), key=lambda x: -x[1])[:8]

    subj_html = " ".join(f"<span style='display:inline-block;background:rgba(79,124,255,.15);border:1px solid rgba(79,124,255,.3);border-radius:4px;padding:2px 7px;margin:2px;font-size:11px'>{s} ({n})</span>" for s, n in top_subjects)
    inst_html = " ".join(f"<span style='display:inline-block;background:rgba(41,211,168,.1);border:1px solid rgba(41,211,168,.25);border-radius:4px;padding:2px 7px;margin:2px;font-size:11px'>{i} ({n})</span>" for i, n in top_insts)

    rows = "".join(
        f"<tr><td>{r.get('registrant','')}</td>"
        f"<td>{', '.join((r.get('subject_matters') or [])[:3])}</td>"
        f"<td>{', '.join((r.get('institutions') or [])[:2])}</td>"
        f"<td>{r.get('communication_date','')}</td></tr>"
        for r in sorted(recs, key=lambda x: x.get('communication_date',''), reverse=True)[:15]
    )

    return (
        f"<p>{lob['count']} lobbying communication(s) on record. "
        f"<strong>{len(registrant_set)}</strong> registrant(s) active. Source: OCL Monthly Communications.</p>"
        f"<p><strong>Subject matters lobbied:</strong><br>{subj_html}</p>"
        f"<p><strong>Institutions approached:</strong><br>{inst_html}</p>"
        f"<table><thead><tr><th>Registrant</th><th>Subjects</th><th>Institutions</th><th>Date</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


def _t_political_donations(ev, scores) -> str:
    d = ev["donations"]
    if not d["count"]:
        return ("<p>No matching federal political contributions found. Note: federal law bans corporate "
                "and union donations, so an absence here is expected; relevant signals would come from named individuals.</p>")
    rows = "".join(f"<tr><td>{r['contributor_name']}</td><td>{r.get('party','')}</td><td>{_fmt_money(r.get('amount'))}</td><td>{r.get('received_date','')}</td></tr>" for r in d["records"])
    return f"<p>Total matched: {_fmt_money(d['total_value'])} across {d['count']} record(s).</p><table><thead><tr><th>Contributor</th><th>Party</th><th>Amount</th><th>Date</th></tr></thead><tbody>{rows}</tbody></table>"


def _t_government_contracts(ev, scores) -> str:
    c = ev["contracts"]
    if not c["count"]:
        return "<p>No federal contracts found for this entity in the ingested data.</p>"
    rows = "".join(f"<tr><td>{r['vendor_name']}</td><td>{_fmt_money(r.get('contract_value'))}</td><td>{(r.get('description') or '')[:80]}</td><td>{r.get('owner_org_title','')}</td></tr>" for r in c["records"])
    return f"<p>{c['count']} contract(s), total {_fmt_money(c['total_value'])}.</p><table><thead><tr><th>Vendor</th><th>Value</th><th>Description</th><th>Department</th></tr></thead><tbody>{rows}</tbody></table>"


def _t_bills_policy(ev, scores) -> str:
    b = ev["bills"]
    if not b["count"]:
        return "<p>No bills before the current Parliament matched this company/sector by keyword.</p>"
    rows = "".join(f"<tr><td>{r['bill_number']}</td><td>{(r.get('title_en') or '')[:90]}</td><td>{r.get('status','')}</td><td>{r.get('sponsor','')}</td></tr>" for r in b["records"])
    return f"<table><thead><tr><th>Bill</th><th>Title</th><th>Status</th><th>Sponsor</th></tr></thead><tbody>{rows}</tbody></table>"


def _t_deal_impact(ev, scores) -> str:
    lob = ev["lobbying"]
    con = ev["contracts"]
    bil = ev["bills"]
    risks, assets, flags = [], [], []

    if scores["regulatory_risk"] >= 7:
        risks.append("High regulatory exposure — active oversight likely affects deal structure or timeline")
    elif scores["regulatory_risk"] >= 5:
        risks.append("Moderate regulatory exposure for the sector — monitor pending approvals")

    if scores["policy_volatility"] >= 6:
        risks.append("Active legislation could shift the policy baseline before deal close")

    if bil["count"]:
        risks.append(f"{bil['count']} bill(s) before Parliament touching this sector or company")

    # Lobbying-specific risk signals — institutions come from both records and aggregated list
    insts = lob.get("institutions", [])
    all_insts_text = " ".join(insts) + " ".join(r.get("institutions", []) for r in lob.get("records", []) if False)
    if any("CRTC" in i or "Competition" in i or "Tribunal" in i for i in insts):
        flags.append("Regulatory tribunal contact on record (CRTC / Competition Bureau) — review filings")
    if any("Finance" in i or "Treasury" in i for i in insts):
        flags.append("Finance Canada / Treasury Board engagement on record — potential budget sensitivity")
    if lob["count"] >= 20:
        flags.append(f"Heavy lobbying footprint ({lob['count']} communications) — Ottawa relationships are a key deal asset or liability")

    if not risks:
        risks.append("No acute federal political risks surfaced in the data at this time")

    if con.get("total_value", 0) > 0:
        assets.append(f"Established federal customer relationship — {_fmt_money(con['total_value'])} in contracts")
    if lob["count"]:
        assets.append(f"Active government-relations channel ({len(lob.get('registrants',[]))} registrant(s)) — existing Ottawa access")
    if not assets:
        assets.append("Clean federal footprint — limited political entanglement risk")

    risks_html = "".join(f"<li>{r}</li>" for r in risks[:3])
    assets_html = "".join(f"<li>{a}</li>" for a in assets[:3])
    flags_html = f"<p><strong>Key flags for due diligence</strong></p><ul>{''.join(f'<li>{f}</li>' for f in flags[:3])}</ul>" if flags else ""
    return (
        f"<p><strong>Top political risks</strong></p><ul>{risks_html}</ul>"
        f"<p><strong>Top political assets</strong></p><ul>{assets_html}</ul>"
        f"{flags_html}"
    )


_TEMPLATES = {
    "executive_summary": _t_executive_summary, "risk_scorecard": _t_risk_scorecard,
    "regulatory_landscape": _t_regulatory_landscape, "political_stakeholders": _t_political_stakeholders,
    "lobbying_activity": _t_lobbying_activity, "political_donations": _t_political_donations,
    "government_contracts": _t_government_contracts, "bills_policy": _t_bills_policy,
    "deal_impact": _t_deal_impact,
}


# ── Claude path ──────────────────────────────────────────────────────────────
def _claude_section(client, model: str, section: str, ev: dict, scores: dict) -> str:
    system = _read(PROMPTS / "system.md")
    framing = _read(PROMPTS / "report_types" / f"{ev['report_type']}.md")
    section_prompt = _read(PROMPTS / "sections" / f"{section}.md")
    payload = {"evidence": ev, "risk_scores": scores}
    msg = client.messages.create(
        model=model, max_tokens=1200, system=system,
        messages=[{"role": "user", "content":
            f"{framing}\n\n{section_prompt}\n\nEVIDENCE (JSON):\n{json.dumps(payload, default=str)[:12000]}"}],
    )
    return "".join(block.text for block in msg.content if getattr(block, "type", "") == "text")


def build_sections(ev: dict[str, Any], scores: dict[str, Any]) -> tuple[dict[str, str], str]:
    """Return ({section_key: html}, generated_by)."""
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    use_claude = api_key and not api_key.startswith("sk-ant-...")
    sections: dict[str, str] = {}

    if use_claude:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            model = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
            for key in SECTION_ORDER:
                sections[key] = _claude_section(client, model, key, ev, scores)
            log.info("report_built", path="claude", sections=len(sections))
            return sections, "claude"
        except Exception as exc:  # noqa: BLE001
            log.warning("claude_build_failed_fallback_template", error=str(exc))

    for key in SECTION_ORDER:
        sections[key] = _TEMPLATES[key](ev, scores)
    log.info("report_built", path="template", sections=len(sections))
    return sections, "template"
