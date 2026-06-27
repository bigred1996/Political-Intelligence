from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import date

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.database import Base, get_session
from api.main import app
from api.models.newsletter import NewsletterIssue
from pipeline import newsletter


def _words(n: int) -> str:
    return " ".join(f"word{i}" for i in range(n))


def _candidate(table: str = "bills", pk: int = 1, **overrides) -> dict:
    base = {
        "table": table,
        "pk": pk,
        "id": f"{table}:{pk}",
        "source": "LEGISinfo",
        "title": "Critical minerals bill",
        "date": "2026-06-15",
        "record_type": "bill",
        "summary": "A bill about critical minerals and supply chains.",
        "url": None,
        "entity": "Natural Resources Canada",
        "canonical": "natural resources canada",
        "source_category": "legislation",
        "sectors": [{"slug": "energy-natural-resources", "name": "Energy and natural resources"}],
        "materiality": 4,
        "internal_url": f"/records/{table}/{pk}",
    }
    base.update(overrides)
    return base


def _story(headline: str, body_words: int, citations: list[dict]) -> dict:
    return {
        "eyebrow": "REGULATORY",
        "headline": headline,
        "standfirst": _words(18),
        "sections": [
            {"label": "The development", "body": _words(body_words)},
            {"label": "What comes next", "body": _words(body_words)},
        ],
        "citations": citations,
    }


def _valid_draft() -> dict:
    cit = [{"table": "bills", "pk": 1}]
    return {
        "title": "Ottawa ties the critical-minerals push to procurement leverage",
        "preheader": "A royal-assent sprint reshapes mining and defence exposure",
        "opening_note": _words(90),
        "key_points": [
            {"development": "Bill C-9 cleared the Senate", "significance": _words(12)},
            {"development": "Lobbying filings spiked", "significance": _words(12)},
        ],
        "lead_story": _story("Minerals bill clears the Senate before recess", 120, cit),
        "supporting_stories": [
            _story("Spectrum auction terms land at the CRTC", 90, cit),
            _story("Shipbuilding contract reopens defence questions", 90, cit),
        ],
        "statistics": [
            {"value": "$3.4B", "label": "Contract value", "significance": _words(12), "citation": cit[0]},
            {"value": "12", "label": "Lobby filings", "significance": _words(12)},
            {"value": "3 days", "label": "To royal assent", "significance": _words(12)},
        ],
        "radar_items": [
            {"headline": "CER hearing scheduled", "summary": _words(14), "next_milestone": "Hearing July 3", "citation": cit[0]},
            {"headline": "Gazette II comment window", "summary": _words(14), "next_milestone": "Comments close July 10"},
            {"headline": "Committee study resumes", "summary": _words(14)},
        ],
        "closing_analysis": {"title": "The Nessus view", "body": _words(70)},
    }


def test_prior_week_window_returns_previous_monday_to_sunday():
    assert newsletter.prior_week_window(today=date(2026, 6, 26)) == ("2026-06-15", "2026-06-21")


def test_sector_mapping_uses_newsletter_taxonomy():
    sectors = newsletter.sectors_for_text("Cybersecurity rules affect telecom, AI, banks and critical minerals.")
    names = {sector["name"] for sector in sectors}
    assert "Technology and innovation" in names
    assert "Energy and natural resources" in names
    assert "Finance and capital markets" in names


def test_valid_draft_passes_and_is_in_word_range():
    result = newsletter.validate_draft(_valid_draft(), [_candidate()])
    assert result["ok"], result["errors"]
    assert 900 <= result["word_count"] <= 1200


def test_validation_rejects_invented_citations():
    draft = _valid_draft()
    draft["lead_story"]["citations"] = [{"table": "bills", "pk": 999}]
    result = newsletter.validate_draft(draft, [_candidate()])
    assert not result["ok"]
    assert any("citations_outside_candidates" in error for error in result["errors"])


def test_validation_requires_lead_and_caps_supporting_stories():
    draft = _valid_draft()
    draft["supporting_stories"] = draft["supporting_stories"] + [_story("Extra", 40, [{"table": "bills", "pk": 1}])] * 2
    result = newsletter.validate_draft(draft, [_candidate()])
    assert not result["ok"]
    assert any("supporting_story_count_invalid" in error for error in result["errors"])


def test_validation_rejects_closing_identical_to_opening():
    draft = _valid_draft()
    draft["closing_analysis"]["body"] = draft["opening_note"]
    result = newsletter.validate_draft(draft, [_candidate()])
    assert not result["ok"]
    assert "closing_duplicates_opening" in result["errors"]


def test_validation_rejects_duplicate_headlines():
    draft = _valid_draft()
    draft["supporting_stories"][0]["headline"] = draft["lead_story"]["headline"]
    result = newsletter.validate_draft(draft, [_candidate()])
    assert not result["ok"]
    assert "duplicate_headlines" in result["errors"]


def test_connection_clusters_link_records_sharing_an_entity():
    candidates = [
        _candidate("bills", 1, source_category="legislation"),
        _candidate("lobbying", 2, source_category="lobbying", record_type="lobbying_communication", title="NRCan lobbying"),
    ]
    clusters = newsletter.connection_clusters(candidates)
    assert any(c["type"] == "same_entity" for c in clusters)


def test_renderer_is_email_safe_and_branded():
    draft = _valid_draft()
    candidates = [_candidate()]
    refs = newsletter._cited_source_references(draft, candidates)
    visuals = newsletter.chart_data(candidates, draft)
    html = newsletter.render_newsletter_html(draft, visuals, refs, "2026-06-15", "2026-06-21")
    assert "Weekly Intelligence Briefing" in html
    assert "nessus-horizontal-on-dark" in html  # masthead logo asset
    assert newsletter.NAVY in html and newsletter.GOLD in html
    assert "By the numbers" in html and "On the radar" in html
    assert "The Nessus view" in html
    assert "/records/bills/1" in html  # source attribution links into the record detail
    assert "[1]" in html  # footnote marker
    assert "max-width:640px" in html
    assert "@media only screen and (max-width:620px)" in html
    assert "<script" not in html.lower()
    assert "<form" not in html.lower()
    assert "stylesheet" not in html.lower()


def test_renderer_escapes_model_text():
    draft = _valid_draft()
    draft["opening_note"] = "<script>alert('x')</script> and <b>bold</b>"
    candidates = [_candidate()]
    html = newsletter.render_newsletter_html(draft, newsletter.chart_data(candidates, draft), [], "2026-06-15", "2026-06-21")
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html


def test_ref_for_candidate_defaults_blank_source_and_title():
    ref = newsletter._ref_for_candidate({"table": "contracts", "pk": 5, "source": "", "title": ""})
    assert ref["source"] and ref["title"]  # non-empty so EvidenceReference validation passes


def test_newsletter_api_list_and_detail_with_mocked_generate(tmp_path, monkeypatch):
    asyncio.run(_newsletter_api_list_and_detail_with_mocked_generate(tmp_path, monkeypatch))


async def _newsletter_api_list_and_detail_with_mocked_generate(tmp_path, monkeypatch):
    db_path = tmp_path / "newsletter.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with session_maker() as session:
            yield session

    async def fake_generate(session, week_start=None, week_end=None):
        draft = _valid_draft()
        candidates = [_candidate()]
        refs = newsletter._cited_source_references(draft, candidates)
        validation = newsletter.validate_draft(draft, candidates)
        visuals = newsletter.chart_data(candidates, draft)
        html = newsletter.render_newsletter_html(draft, visuals, refs, week_start or "2026-06-15", week_end or "2026-06-21")
        issue = NewsletterIssue(
            week_start=week_start or "2026-06-15",
            week_end=week_end or "2026-06-21",
            title=draft["title"],
            status="generated",
            generated_by="claude",
            model="claude-opus-4-8",
            word_count=validation["word_count"],
            sections=draft,
            visuals=visuals,
            evidence={"candidate_count": 1},
            source_references=refs,
            validation=validation,
            html=html,
        )
        session.add(issue)
        await session.commit()
        return issue

    monkeypatch.setattr("api.routes.newsletters.generate_newsletter_issue", fake_generate)
    app.dependency_overrides[get_session] = override_session
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            generated = await client.post("/api/newsletters/generate", json={})
            assert generated.status_code == 200, generated.text
            issue_id = generated.json()["id"]

            listing = await client.get("/api/newsletters")
            assert listing.status_code == 200
            assert listing.json()["count"] == 1

            detail = await client.get(f"/api/newsletters/{issue_id}")
            assert detail.status_code == 200
            body = detail.json()
            assert body["validation"]["ok"] is True
            assert body["sections"]["lead_story"]["headline"]

            html = await client.get(f"/newsletter/{issue_id}")
            assert html.status_code == 200
            assert "Weekly Intelligence Briefing" in html.text
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
