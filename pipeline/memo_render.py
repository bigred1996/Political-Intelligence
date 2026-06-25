"""Goal B6 — HTML/CSS shell for the branded diligence memo.

Pure templating: takes the dict from `pipeline.memo_builder.get_memo_response`
(section HTML already built) and wraps it in the Nessus memo brand surface —
warm off-white, forest-green primary, amber accents, Inter. Computes nothing;
mirrors the split `api/routes/report_view.py` uses for the older Report model
(data layer vs. template layer stay separate).

Redesigned (2026-06): a full cover page (wordmark, big company name, the
at-a-glance stat band, a contents list and a methodology note), then 7
action-titled sections instead of 17 dense cards.
"""
from __future__ import annotations

from html import escape
from typing import Any

_CSS = """
*{box-sizing:border-box}
body{font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;
  background:#FAF7F0;color:#21281F;margin:0;font-size:13px;line-height:1.55}
/* cover */
.cover{background:#1F5C40;color:#FAF7F0;padding:48px 56px 32px;min-height:34vh}
.cover .brand{font-size:11px;letter-spacing:.18em;text-transform:uppercase;opacity:.78;font-weight:600}
.cover h1{font-size:40px;font-weight:800;margin:14px 0 4px;letter-spacing:-.5px;line-height:1.05}
.cover .sub{font-size:13px;opacity:.85}
.statband{display:flex;background:#163F2C;color:#FAF7F0}
.stat{flex:1;padding:16px 20px;border-right:1px solid #2c6b4d}
.stat:last-child{border-right:none}
.stat-n{font-size:21px;font-weight:800;letter-spacing:-.3px}
.stat-l{font-size:9.5px;text-transform:uppercase;letter-spacing:.07em;opacity:.7;margin-top:2px}
.cover-foot{padding:22px 56px 0}
.cover-foot .toc{margin:6px 0 18px}
.cover-foot .toc span{font-size:12px;color:#4a4d40;margin-right:26px;display:inline-block;line-height:1.9}
.cover-foot .toc b{color:#1F5C40;margin-right:5px}
.method{background:#FFFFFF;border:1px solid #DDD5C2;border-left:3px solid #C8842E;border-radius:4px;
  padding:12px 16px;font-size:11.5px;color:#5d5a4e;max-width:680px}
.method b{color:#1F5C40}
.banner{background:#FBEFD8;color:#8A5A1E;border-bottom:1px solid #E9D2A6;font-size:11.5px;padding:9px 56px}
/* body */
main{padding:30px 56px 40px;max-width:920px;margin:0 auto}
section{margin-bottom:26px}
.exrow,.netwrap,ul.takes li,table.exec tr,.twocol>div{page-break-inside:avoid}
h2{break-after:avoid}
.kicker{font-size:10px;text-transform:uppercase;letter-spacing:.12em;color:#C8842E;font-weight:700;margin-bottom:3px}
h2{font-size:21px;font-weight:800;color:#1F5C40;margin:0 0 12px;letter-spacing:-.3px;line-height:1.15}
.lead{font-size:14px;line-height:1.6;margin:0 0 16px;color:#2a3326}
.muted,.insufficient{color:#8a8675;font-style:italic;font-size:12px}
p{margin:7px 0}
/* exec table */
table.exec{width:100%;border-collapse:collapse;margin-top:6px}
table.exec th{background:#1F5C40;color:#FAF7F0;text-align:left;font-size:10px;text-transform:uppercase;
  letter-spacing:.05em;padding:8px 12px}
table.exec td{padding:11px 12px;border-bottom:1px solid #E4DDCB;vertical-align:top;font-size:12.5px}
table.exec td.th-cell{width:32%;color:#1F5C40}
.links{display:inline}
.links a,.rec{color:#1F5C40;font-size:9.5px;border-bottom:1px dotted #9bbfa9;text-decoration:none;
  margin-right:5px;white-space:nowrap;display:inline-block}
.rec-more{font-size:9.5px;color:#8a8675}
/* exhibits */
.exhibit{margin:4px 0 18px;max-width:560px}
.exhibit-sm{max-width:420px}
.exrow{display:flex;gap:26px;flex-wrap:nowrap;align-items:flex-start;margin-top:6px}
.ex{flex:1 1 0;min-width:0;max-width:33%}
.ex-t{font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:#8a8675;font-weight:700;margin-bottom:6px}
/* takeaways */
ul.takes{list-style:none;padding:0;margin:0}
ul.takes li{display:flex;gap:10px;padding:11px 0;border-bottom:1px solid #Eae3d2}
.dot{width:9px;height:9px;border-radius:50%;margin-top:5px;flex-shrink:0}
.take-h{font-weight:700;font-size:13px;color:#21281F}
.take-d{font-weight:400;color:#a09a86;font-size:10.5px;margin-left:8px}
.take-s{font-size:12px;color:#4a4d40;margin-top:2px}
/* two col */
.twocol{display:flex;gap:30px}
.twocol>div{flex:1}
.col-t{font-size:11px;text-transform:uppercase;letter-spacing:.05em;font-weight:700;margin:0 0 8px;
  padding-bottom:5px;border-bottom:2px solid #C8842E;color:#1F5C40}
.col-t.risk{border-color:#A8431E;color:#A8431E}
.col-t.opp{border-color:#1F5C40}
.twocol ul,.qs,ol.qs{padding-left:18px;margin:6px 0}
.twocol li,.qs li{font-size:12px;margin-bottom:7px;line-height:1.5}
/* network */
.netwrap{display:flex;gap:24px;align-items:flex-start}
.net{flex:0 0 300px;max-width:300px}
.actors{list-style:none;padding:0;margin:6px 0 0;flex:1}
.actors li{font-size:12px;margin-bottom:8px}
/* tags */
.tag{display:inline-block;font-size:8.5px;text-transform:uppercase;letter-spacing:.03em;padding:1px 6px;
  border:1px solid #DDD5C2;border-radius:3px;color:#6E6A5C;margin-left:4px;background:#F1ECDF}
.tag-risk-high{background:#F6E2DA;color:#A8431E;border-color:#E7B9A6}
.tag-risk-elevated{background:#F6ECDA;color:#C8842E;border-color:#E9D2A6}
.tag-risk-watch{background:#E3EEE7;color:#1F5C40;border-color:#BFDACB}
/* appendix */
table.appx{width:100%;border-collapse:collapse;font-size:10.5px;margin-top:6px}
table.appx th{text-align:left;color:#8a8675;text-transform:uppercase;font-size:8.5px;letter-spacing:.05em;
  padding:5px 8px;border-bottom:1px solid #DDD5C2}
table.appx td{padding:5px 8px;border-bottom:1px solid #Eae3d2;vertical-align:top}
.footer{text-align:center;color:#8a8675;font-size:10px;padding:18px}
a{color:#1F5C40}
@page{size:Letter;margin:.55in .5in}
"""


def render_memo_html(memo: dict[str, Any], *, for_pdf: bool = False) -> str:
    review, run = memo["review"], memo.get("run")
    sections, titles, order = memo["sections"], memo["section_titles"], memo["section_order"]
    kickers = memo.get("section_kickers", {})

    used_claude = bool(run) and (run.get("synthesis") or {}).get("generated_by") == "claude"
    banner = "" if used_claude else (
        '<div class="banner">Draft — generated without Claude synthesis (deterministic fallback). '
        "Analyst review required before client delivery.</div>"
    )

    company = escape(review.get("company") or "")
    depth = escape((review.get("depth_tier") or "standard").title())
    generated_at = escape(str(review.get("updated_at") or review.get("created_at") or "")[:10])
    review_id = escape(str(review.get("id") or ""))
    stat_band = sections.get("_stat_band", "")

    toc = "".join(
        f'<span><b>{i}.</b>{escape(titles[key])}</span>'
        for i, key in enumerate(order, start=1)
    )
    method = (
        '<div class="method"><b>Methodology.</b> Every figure and finding below is drawn solely from '
        "public-record evidence retrieved for this review; each is independently verifiable at its own "
        "record page. Synthesis is AI-assisted and analyst-reviewed — never a buy/sell/valuation "
        "conclusion.</div>"
    )

    body = "".join(
        f'<section id="{escape(key)}">'
        f'<div class="kicker">{escape(kickers.get(key, ""))}</div>'
        f"<h2>{i}. {escape(titles[key])}</h2>{sections[key]}</section>"
        for i, key in enumerate(order, start=1)
    )

    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"/>'
        f"<title>Nessus Diligence Memo — {company}</title>"
        f"<style>{_CSS}</style></head><body>"
        '<div class="cover"><div class="brand">Nessus Intelligence · Political Due Diligence</div>'
        f"<h1>{company}</h1>"
        f'<div class="sub">{depth}-tier diligence memo · review {review_id} · {generated_at}</div></div>'
        f"{stat_band}{banner}"
        f'<div class="cover-foot"><div class="toc">{toc}</div>{method}</div>'
        f"<main>{body}</main>"
        '<footer class="footer">Nessus Intelligence — confidential diligence memo. '
        "Every cited record is independently retrievable at /records/&lt;table&gt;/&lt;pk&gt;.</footer>"
        "</body></html>"
    )
