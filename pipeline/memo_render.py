"""Goal B6 — HTML/CSS shell for the branded PDF memo.

Pure templating: takes the dict from `pipeline.memo_builder.get_memo_response`
(section HTML already built) and wraps it in the Nessus memo brand surface —
warm off-white, forest-green primary, amber accents, thin-border cards, Inter.
Computes nothing; mirrors the split `api/routes/report_view.py` uses for the
older Report model (data layer vs. template layer stay separate).
"""
from __future__ import annotations

from html import escape
from typing import Any

_CSS = """
* { box-sizing: border-box; }
body {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
  background: #FAF7F0; color: #21281F; margin: 0; padding: 0; font-size: 13px;
}
.memo-header {
  background: #1F5C40; color: #FAF7F0; padding: 28px 40px;
}
.memo-header .brand {
  font-size: 11px; letter-spacing: .14em; text-transform: uppercase; opacity: .8; font-weight: 600;
}
.memo-header h1 { margin: 6px 0 8px; font-size: 24px; font-weight: 700; }
.memo-header .meta { font-size: 11px; opacity: .85; }
.memo-banner {
  background: #FBEFD8; color: #8A5A1E; border-bottom: 1px solid #E9D2A6;
  font-size: 11.5px; padding: 8px 40px;
}
main { padding: 22px 40px 36px; max-width: 760px; margin: 0 auto; }
.memo-section {
  background: #FFFFFF; border: 1px solid #DDD5C2; border-radius: 6px;
  padding: 16px 20px; margin-bottom: 14px;
}
.memo-section h2 {
  font-size: 13px; text-transform: uppercase; letter-spacing: .04em; color: #1F5C40;
  border-bottom: 2px solid #C8842E; padding-bottom: 6px; margin: 0 0 10px;
}
ul, ol { padding-left: 18px; margin: 6px 0; }
li { margin-bottom: 6px; font-size: 12px; line-height: 1.5; }
p { margin: 6px 0; line-height: 1.5; }
.so-what { color: #6E6A5C; font-style: italic; }
a, .rec-link { color: #1F5C40; text-decoration: none; border-bottom: 1px dotted #1F5C40; font-size: 11px; }
.tag {
  display: inline-block; font-size: 9px; text-transform: uppercase; letter-spacing: .03em;
  padding: 1px 6px; border-radius: 3px; margin-right: 4px; background: #F1ECDF; color: #6E6A5C;
  border: 1px solid #DDD5C2; white-space: nowrap;
}
.tag-risk-high { background: #F6E2DA; color: #A8431E; border-color: #E7B9A6; }
.tag-risk-elevated { background: #F6ECDA; color: #C8842E; border-color: #E9D2A6; }
.tag-risk-watch { background: #E3EEE7; color: #1F5C40; border-color: #BFDACB; }
.tag-label-observed { background: #E3EEE7; color: #1F5C40; border-color: #BFDACB; }
.tag-label-inferred { background: #F6ECDA; color: #C8842E; border-color: #E9D2A6; }
.tag-label-speculative { background: #F1ECDF; color: #6E6A5C; }
.insufficient { color: #6E6A5C; font-style: italic; font-size: 12px; }
.more-note { color: #C8842E; font-size: 11px; font-style: italic; }
.chart-empty { color: #6E6A5C; font-style: italic; font-size: 12px; }
.chart { margin: 6px 0 12px; }
.note { color: #6E6A5C; font-size: 11px; }
.lead { font-weight: 600; margin-top: 10px; }
table { width: 100%; border-collapse: collapse; font-size: 11px; }
th, td { text-align: left; padding: 5px 8px; border-bottom: 1px solid #DDD5C2; }
th { color: #6E6A5C; text-transform: uppercase; font-size: 9px; letter-spacing: .04em; }
.memo-footer { text-align: center; font-size: 10px; color: #6E6A5C; padding: 18px 40px 26px; }
@page { size: Letter; margin: 0.6in 0.55in; }
"""


def render_memo_html(memo: dict[str, Any], *, for_pdf: bool = False) -> str:
    review, run = memo["review"], memo.get("run")
    sections, titles, order = memo["sections"], memo["section_titles"], memo["section_order"]

    used_claude = bool(run) and (run.get("synthesis") or {}).get("generated_by") == "claude"
    banner = ""
    if not used_claude:
        banner = (
            '<div class="memo-banner">Generated without Claude synthesis — deterministic fallback '
            "content. Analyst review required before client delivery.</div>"
        )

    body = "".join(
        f'<section class="memo-section" id="{escape(key)}"><h2>{i}. {escape(titles[key])}</h2>{sections[key]}</section>'
        for i, key in enumerate(order, start=1)
    )

    company = escape(review.get("company") or "")
    depth = escape((review.get("depth_tier") or "standard").title())
    generated_at = escape(str(review.get("updated_at") or review.get("created_at") or ""))
    review_id = escape(str(review.get("id") or ""))

    return (
        "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\"/>"
        f"<title>Nessus Diligence Memo — {company}</title>"
        f"<style>{_CSS}</style></head><body>"
        '<header class="memo-header"><div class="brand">Nessus Intelligence</div>'
        f"<h1>{company}</h1>"
        f'<div class="meta">{depth} diligence memo &middot; review {review_id} &middot; generated {generated_at}</div>'
        f"</header>{banner}"
        f"<main>{body}</main>"
        '<footer class="memo-footer">Nessus Intelligence — confidential diligence memo. '
        "Every cited record is independently retrievable at /records/&lt;table&gt;/&lt;pk&gt;.</footer>"
        "</body></html>"
    )
