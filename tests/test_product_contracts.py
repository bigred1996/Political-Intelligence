"""Product-contract guardrails for the build-on-existing MVP pass."""
from __future__ import annotations

from types import SimpleNamespace
from datetime import datetime, timezone
from pathlib import Path

from api.cache import invalidate_workspace_caches
from api.routes.health import readiness_status
from api.routes.overview import _OVERVIEW_CACHE, _OVERVIEW_CACHE_TTL_SECONDS
from api.routes.records import _spec_for
from api.routes.report_view import render_report_html
from api.routes.sectors import _SECTOR_CACHE, _SECTOR_CACHE_TTL_SECONDS
from api.routes.sources import (
    SOURCE_DEFS,
    _SOURCE_STATUS_CACHE,
    _SOURCE_STATUS_CACHE_TTL_SECONDS,
    _confidence,
    _coverage_status,
    _freshness_status,
    _known_gaps,
    source_quality_summary,
)
from api.schemas import EvidenceReference, GraphFinding, IntelligenceEvidence, IntelligenceFinding, MovementWindow, ReadinessResponse
from api.scheduler import JOB_RUNNERS, SOURCE_CONFIGS
from pipeline.evidence_graph import normalize_reference, parse_speaker_name, ref, sectors_for_text
from pipeline.evidence_graph import build_report_findings
from pipeline.sector_intel import (
    _coverage,
    _ref,
    build_sector_signals,
    enrich_sector_coverage,
    finding_from_signal,
    movement_windows,
    risk_band_from_score,
    sector_brief,
)
from pipeline.sector_mapper import Sector
from search.engine import _normalize_hit


def test_source_status_labels_cover_live_empty_and_planned():
    ids = {s["id"] for s in SOURCE_DEFS}
    assert {"contracts", "grants", "appointments", "ocl_registrations", "tribunal_decisions"} <= ids
    assert _coverage_status(10, "live") == "live"
    assert _coverage_status(1, "partial") == "partial"
    assert _coverage_status(0, "live") == "empty"
    assert _coverage_status(0, "planned") == "planned"


def test_source_row_count_methods_make_approximations_explicit():
    by_id = {source["id"]: source for source in SOURCE_DEFS}
    assert by_id["contracts"].get("approx") is True
    assert by_id["donations"].get("approx") is True
    assert by_id["lobbying_communications"].get("approx") is not True


def test_source_quality_summary_rolls_up_confidence_caveats():
    quality = source_quality_summary([
        {
            "id": "contracts",
            "label": "Federal contracts",
            "status": "live",
            "freshness": "unknown",
            "approximate": True,
            "known_gaps": ["Freshness unknown."],
        },
        {
            "id": "grants",
            "label": "Grants",
            "status": "empty",
            "freshness": "missing",
            "approximate": False,
            "known_gaps": ["No rows loaded yet."],
        },
    ])
    assert quality["approximate_sources"] == ["contracts"]
    assert quality["unknown_freshness_sources"] == ["contracts"]
    assert quality["empty_sources"] == ["grants"]
    assert quality["explicit_gaps"][0]["id"] == "contracts"


def test_source_job_ids_are_runnable_or_explicitly_planned():
    runner_ids = set(JOB_RUNNERS)
    config_ids = {cfg["id"] for cfg in SOURCE_CONFIGS}
    for source in SOURCE_DEFS:
        job_id = source.get("job_id")
        if source["status_when_rows"] == "planned":
            assert job_id is None
            continue
        if job_id:
            assert job_id in runner_ids
            assert job_id in config_ids


def test_source_freshness_and_gap_labels_are_explicit():
    now = datetime(2026, 6, 16, tzinfo=timezone.utc)
    assert _freshness_status(
        status="live",
        latest_record_date="2026-06-01",
        last_success_at=None,
        fresh_days=45,
        now=now,
    ) == "current"
    assert _freshness_status(
        status="live",
        latest_record_date="2025-01-01",
        last_success_at=None,
        fresh_days=45,
        now=now,
    ) == "stale"
    assert _freshness_status(
        status="empty",
        latest_record_date=None,
        last_success_at=None,
        fresh_days=45,
        now=now,
    ) == "missing"
    assert _confidence("live", "current") == "high"
    assert _confidence("empty", "missing") == "low"
    gaps = _known_gaps({"id": "grants"}, "empty", "missing")
    assert any("Explicit MVP data gap" in g for g in gaps)


def test_overview_cache_ttl_is_short_lived_for_operator_dashboard():
    assert 30 <= _OVERVIEW_CACHE_TTL_SECONDS <= 300
    assert 30 <= _SECTOR_CACHE_TTL_SECONDS <= 300
    assert 30 <= _SOURCE_STATUS_CACHE_TTL_SECONDS <= 300


def test_workspace_cache_invalidation_clears_overview_and_sector_caches():
    _OVERVIEW_CACHE["payload"] = {"stale": True}
    _OVERVIEW_CACHE["expires_at"] = 999999.0
    _SECTOR_CACHE[("energy", None)] = {"payload": {"stale": True}, "expires_at": 999999.0}
    _SOURCE_STATUS_CACHE["payload"] = {"stale": True}
    _SOURCE_STATUS_CACHE["expires_at"] = 999999.0

    invalidate_workspace_caches("test")

    assert _OVERVIEW_CACHE["payload"] is None
    assert _OVERVIEW_CACHE["expires_at"] == 0.0
    assert _SECTOR_CACHE == {}
    assert _SOURCE_STATUS_CACHE["payload"] is None
    assert _SOURCE_STATUS_CACHE["expires_at"] == 0.0


def test_records_and_sources_indexes_use_live_source_status_not_fake_record_ids():
    records_page = Path("web/app/records/page.tsx").read_text()
    sources_page = Path("web/app/sources/page.tsx").read_text()
    audit = Path("CONNECTED_INTELLIGENCE_AUDIT.md").read_text()

    for page in (records_page, sources_page):
        assert "useApi<SourceStatusResponse>(\"/api/sources/status\")" in page
        assert "sourceHref(source.id)" in page
        assert "CoverageBadge" in page
        assert "Design-to-match" not in page
        assert "static for now" not in page

    assert "/records/${s.table}/1" not in records_page
    assert "Source profile" in records_page
    assert "Open records" in records_page
    assert "no guessed sample record IDs" in audit
    assert "Live `/api/sources/status` table" in audit


def test_sector_evidence_refs_are_linkable():
    ref = _ref(table="bills", pk=123, source="LEGISinfo", title="C-1 — Test bill", date="2026-01-01")
    assert ref["table"] == "bills"
    assert ref["id"] == 123
    assert ref["pk"] == 123
    assert ref["source"]
    assert ref["title"]


def test_sector_configuration_supports_configurable_metadata_and_disable():
    sector = Sector(
        "test-sector",
        "Test Sector",
        "Configurable sector.",
        entities=["test co"],
        keywords=["permit"],
        regulators=["Test Regulator"],
        parent="infrastructure",
        subsectors=["subsector"],
        topics=["permits"],
        organizations=["Test Co"],
        departments=["Test Department"],
        enabled=False,
        display_priority=5,
    )
    data = sector.to_dict()
    assert data["enabled"] is False
    assert data["parent"] == "infrastructure"
    assert data["associated_topics"] == ["permits"]
    assert data["associated_government_departments"] == ["Test Department"]
    assert data["associated_regulators"] == ["Test Regulator"]


def test_intelligence_finding_schema_distinguishes_inference_and_evidence():
    evidence = IntelligenceEvidence.model_validate({
        "source_name": "LEGISinfo",
        "source_type": "bill",
        "title": "C-1 — Test",
        "coverage_status": "partial",
        "confidence": "medium",
        "table": "bills",
        "pk": 1,
        "internal_url": "/records/bills/1",
    })
    finding = IntelligenceFinding.model_validate({
        "title": "Test finding",
        "concise_summary": "Observed bill movement.",
        "why_it_matters": "It may affect diligence.",
        "primary_sector": {"slug": "technology", "name": "Technology"},
        "related_sectors": [{"slug": "telecommunications", "name": "Telecommunications"}],
        "signal_type": "regulatory watch",
        "risk_direction": "unclear",
        "risk_level": "elevated",
        "confidence": "medium",
        "source_coverage": "partial",
        "recency": "fresh",
        "interpretation_type": "inferred",
        "evidence_references": [evidence.model_dump()],
    })
    assert finding.interpretation_type == "inferred"
    assert finding.evidence_references[0].internal_url == "/records/bills/1"


def test_movement_windows_are_explicit_when_history_is_missing():
    windows = [MovementWindow.model_validate(w) for w in movement_windows(12)]
    assert [w.window_days for w in windows] == [7, 30, 90]
    assert all(w.status == "insufficient_history" for w in windows)
    assert risk_band_from_score(0, evidence_count=0) == "insufficient evidence"


def test_signal_to_finding_reuses_evidence_and_decision_questions():
    signal = {
        "theme": "Regulatory movement",
        "title": "Bill activity touches the sector",
        "summary": "A bill moved.",
        "why": "Bill movement can change market access.",
        "severity": "elevated",
        "sectors": [{"slug": "technology", "name": "Technology"}, {"slug": "telecommunications", "name": "Telecommunications"}],
        "references": [_ref(table="bills", pk=10, source="LEGISinfo", title="C-10 — Test")],
    }
    finding = finding_from_signal(signal)
    assert finding["signal_type"] == "regulatory watch"
    assert finding["interpretation_type"] == "observed"
    assert finding["related_sectors"][1]["slug"] == "telecommunications"
    assert finding["evidence_references"][0]["internal_url"] == "/records/bills/10"
    assert finding["suggested_questions"]


def test_sector_brief_reuses_findings_and_source_limits():
    payload = {
        "sector": {"name": "Technology"},
        "narrative": "Technology carries a watch profile.",
        "findings": [{"title": "Finding"}],
        "source_coverage": [{"id": "bills", "status": "live"}],
        "suggested_questions": ["What evidence should be reviewed?"],
    }
    brief = sector_brief(payload)
    assert brief["title"] == "Technology intelligence brief"
    assert brief["top_findings"] == [{"title": "Finding"}]
    assert "Period-over-period" in brief["what_changed"]


def test_sector_signals_are_ranked_and_linkable():
    bill = _ref(table="bills", pk=11, source="LEGISinfo", title="S-1 — Test", date="2026-01-01")
    lobbying = _ref(table="lobbying", pk=22, source="OCL", title="Lobbying communication")
    contract = _ref(table="contracts", pk=33, source="Contracts", title="Vendor — Fuel")
    ev = {
        "contracts": {"count": 2, "total_value": 1000000, "by_department": [{"dept": "Natural Resources Canada", "value": 1000000, "count": 2}], "records": [contract]},
        "lobbying": {"count": 50, "top_institutions": [{"institution": "Natural Resources Canada", "count": 20}], "records": [lobbying]},
        "donations": {"count": 0, "total_value": 0, "records": []},
        "bills": {"count": 1, "records": [bill]},
        "regulations": {"count": 0, "records": []},
        "tribunal_decisions": {"count": 0, "records": []},
        "breadth": {"count": 0, "records": []},
    }
    signals = build_sector_signals(ev, [{
        "title": "Active lobbying alongside live legislation",
        "detail": "Lobbying and legislation coincide.",
        "sources": ["lobbying", "bills"],
        "severity": "high",
        "references": [bill, lobbying],
    }])
    assert signals[0]["severity"] == "high"
    assert signals[0]["references"][0]["table"] == "bills"
    assert all("why" in s and "metrics" in s for s in signals)


def test_entity_source_coverage_marks_empty_tables():
    ev = {
        "contracts": {"count": 3},
        "lobbying": {"count": 2},
        "donations": {"count": 0},
        "bills": {"count": 1},
        "regulations": {"count": 0},
        "tribunal_decisions": {"count": 0},
        "appointments": {"count": 0},
        "breadth": {"count": 4},
    }
    rows = _coverage(ev)
    by_id = {r["id"]: r for r in rows}
    assert by_id["contracts"]["status"] == "live"
    assert by_id["breadth"]["status"] == "partial"
    assert by_id["tribunal_decisions"]["status"] == "empty"


def test_sector_source_coverage_distinguishes_global_health_from_sector_hits():
    rows = [{"id": "tribunal_decisions", "label": "Tribunal decisions", "status": "empty", "rows": 0}]
    source_status = {
        "sources": [
            {
                "id": "tribunal_decisions",
                "label": "Tribunal decisions",
                "table": "tribunal_decisions",
                "status": "live",
                "freshness": "current",
                "confidence": "high",
                "rows": 125,
                "known_gaps": [],
                "description": "Loaded tribunal decisions.",
                "approximate": False,
                "latest_record_date": "2026-06-01",
            }
        ]
    }
    enriched = enrich_sector_coverage(rows, source_status)
    assert enriched[0]["rows"] == 0
    assert enriched[0]["sector_rows"] == 0
    assert enriched[0]["sector_status"] == "no_sector_hits"
    assert enriched[0]["global_status"] == "live"
    assert enriched[0]["global_rows"] == 125


def test_report_output_includes_source_references():
    report = SimpleNamespace(
        id="r1",
        company_name="TELUS",
        report_type="deal_due_diligence",
        time_horizon="current",
        status="draft",
        generated_by="template",
        risk_scores={"overall": 5.0, "regulatory_risk": 5.0, "policy_volatility": 4.0, "election_sensitivity": 3.0, "lobbying_intensity": 6.0},
        sections={"executive_summary": "<p>Test</p>"},
        evidence={
            "source_references": [
                {"source": "LEGISinfo", "title": "C-1 — Test bill", "date": "2026-01-01", "url": "https://example.test"}
            ]
        },
    )
    html = render_report_html(report)
    assert "Sources Used" in html
    assert "C-1" in html


def test_report_output_includes_connected_findings_and_internal_record_links():
    report = SimpleNamespace(
        id="r2",
        company_name="TELUS",
        report_type="deal_due_diligence",
        time_horizon="current",
        status="draft",
        generated_by="template",
        risk_scores={"overall": 5.0, "regulatory_risk": 5.0, "policy_volatility": 4.0, "election_sensitivity": 3.0, "lobbying_intensity": 6.0},
        sections={"executive_summary": "<p>Test</p>"},
        evidence={
            "graph_findings": [
                {
                    "severity": "elevated",
                    "title": "Lobbying and legislative exposure overlap",
                    "summary": "Evidence crosses sources.",
                    "references": [{"source": "LEGISinfo"}],
                }
            ],
            "source_references": [
                {"table": "bills", "pk": 42, "source": "LEGISinfo", "title": "C-42 — Test", "date": "2026-01-01"}
            ],
        },
    )
    html = render_report_html(report)
    assert "Connected Findings" in html
    assert "/records/bills/42" in html


def test_report_findings_reuse_normalized_source_references():
    ev = {
        "lobbying": {"count": 30},
        "bills": {"count": 1},
        "regulations": {"count": 0},
        "tribunal_decisions": {"count": 0},
        "contracts": {"count": 0, "total_value": 0},
        "breadth": {"count": 0},
        "source_references": [
            {"table": "lobbying", "pk": 5, "source": "OCL", "title": "Lobbying", "date": "2026-01-01"},
            {"table": "bills", "pk": 6, "source": "LEGISinfo", "title": "Bill", "date": "2026-01-02"},
        ],
    }
    findings = build_report_findings(ev)
    assert findings[0]["type"] == "report_lobbying_legislation_overlap"
    assert findings[0]["references"][0]["pk"] == 5


def test_record_aliases_resolve_to_existing_specs():
    assert _spec_for("gazette_entries")[1] == "gazette"
    assert _spec_for("tribunal_decisions")[1] == "tribunal"
    assert _spec_for("lobbying_records")[1] == "lobbying"
    assert _spec_for("hansard_mentions")[1] == "hansard_mentions"


def test_bill_records_derive_legisinfo_original_source_url():
    spec = _spec_for("bills")[0]

    class _Row:
        parliament = "45-1"
        bill_number = "C-219"

    # Original source resolves to the canonical LEGISinfo bill page so the
    # evidence record can offer a secondary "View original source" action.
    assert spec.url_fn(_Row()) == "https://www.parl.ca/legisinfo/en/bill/45-1/c-219"

    class _Partial:
        parliament = None
        bill_number = "C-219"

    # Missing parliament -> no dead link rather than a malformed URL.
    assert spec.url_fn(_Partial()) is None


def test_evidence_graph_reference_shape_is_canonical():
    row = normalize_reference({
        "table": "bills",
        "id": 44,
        "source": "LEGISinfo",
        "title": "C-44 — Test",
        "date": "2026-06-01",
    })
    assert row == {
        "table": "bills",
        "pk": 44,
        "id": 44,
        "source": "LEGISinfo",
        "title": "C-44 — Test",
        "date": "2026-06-01",
        "url": None,
        "record_type": "record",
        "sector": None,
        "confidence": "linked",
        "amount": None,
    }
    assert ref("gazette", 7, "Canada Gazette", "Regulation")["pk"] == 7


def test_hansard_speaker_parser_handles_parenthetical_names():
    assert parse_speaker_name("The Assistant Deputy Speaker (John Nater):") == "John Nater"
    assert parse_speaker_name("Hon. Chrystia Freeland") == "Chrystia Freeland"
    assert parse_speaker_name("House") is None


def test_sector_text_matching_returns_sector_edges():
    matches = sectors_for_text("The committee discussed spectrum, wireless access, and CRTC oversight.")
    assert matches[0]["slug"] == "telecommunications"


def test_search_hits_include_canonical_reference_shape():
    hit = _normalize_hit({
        "table": "hansard_mentions",
        "pk": 9,
        "source": "openparliament.ca",
        "title": "Speaker — telecom",
        "date": "2026-06-12",
        "record_type": "hansard_mention",
    })
    assert hit["id"] == 9
    assert hit["reference"]["table"] == "hansard_mentions"
    assert hit["reference"]["pk"] == 9
    assert hit["reference"]["record_type"] == "hansard_mention"


def test_search_result_context_is_preserved_on_record_detail_links():
    search_page = Path("web/app/search/page.tsx").read_text()
    record_page = Path("web/app/records/[table]/[pk]/page.tsx").read_text()
    # The adaptive record dossier (shared by the record + meeting pages) holds the
    # rendering; the route file is a thin fetch-and-delegate shell.
    dossier = Path("web/components/record-dossier.tsx").read_text()
    ui = Path("web/components/ui.tsx").read_text()
    audit = Path("CONNECTED_INTELLIGENCE_AUDIT.md").read_text()
    assert "?from=search&q=" in search_page
    assert "export function OriginalSourceLink" in ui
    assert 'label = "View original source"' in ui
    assert "OriginalSourceLink" in search_page
    assert "OriginalSourceLink" in dossier
    assert "sourceLabel(hit.table ?? hit.source, hit.source)" in search_page
    assert "searchParams" in record_page
    assert "investigationContext" in record_page
    assert "Investigation context" in dossier
    assert "from=search" in dossier
    # The five-beat editorial spine: a strategic read up top, then the analysis beats.
    assert "Strategic Read" in dossier
    assert "What this means" in dossier
    assert "Why it matters" in dossier
    assert "How It Connects" in dossier
    # No generated document-thumbnail placeholder: real full text inline where the
    # source has one (record.body), real structured fields otherwise.
    assert "DocumentThumbnail" not in record_page
    assert "DocumentThumbnail" not in dossier
    assert "record.body" in dossier
    assert "Full Text" in dossier
    assert "Record Details" in dossier
    assert "`OriginalSourceLink`" in audit
    assert "withContext(sectorHref(slug), context)" in dossier
    assert "recordTypeLabel(detail.record.record_type, detail.record.source, detail.table)" in record_page
    assert "return \"Public statement\"" in dossier


def test_live_feed_uses_graph_findings_not_placeholder_records():
    page = Path("web/app/signals/page.tsx").read_text()
    assert "/api/graph/findings" in page
    assert "findingHref" in page
    assert "evidenceHref" in page
    assert "/records/news/1" not in page
    assert "Static for now" not in page


def test_explorer_uses_live_graph_findings_and_internal_links():
    page = Path("web/app/explorer/page.tsx").read_text()
    assert "/api/graph/findings" in page
    assert "FindingsResponse" in page
    assert "findingHref" in page
    assert "evidenceHref" in page
    assert "personHref" in page
    assert "sectorHref" in page
    assert "finding supported by record" in page
    assert "Static for now" not in page


def test_dashboard_uses_live_overview_and_internal_links():
    page = Path("web/app/dashboard/page.tsx").read_text()
    home = Path("web/app/page.tsx").read_text()
    assert "/api/overview" in page
    assert "OverviewResponse" in page
    assert "findingHref" in page
    assert "from=dashboard" in page
    assert "from=briefing" in home
    assert "recordHref" in page
    assert "sectorHref" in page
    assert "sourceHref" in page
    assert "View all records" in page
    assert 'href="/records/bills/1"' not in page
    assert 'href="/records/bills/1"' not in home
    assert "Static for now" not in page


def test_shared_api_schemas_accept_core_contracts():
    ref_obj = EvidenceReference.model_validate({
        "table": "bills",
        "pk": 1,
        "id": 1,
        "source": "LEGISinfo",
        "title": "C-1 — Test",
    })
    finding = GraphFinding.model_validate({
        "title": "Test finding",
        "summary": "Evidence connected.",
        "severity": "watch",
        "type": "test",
        "references": [ref_obj.model_dump()],
    })
    ready = ReadinessResponse.model_validate({"status": "degraded", "reasons": ["semantic_index_missing"], "checks": {}})
    assert finding.references[0].table == "bills"
    assert ready.status == "degraded"


def test_readiness_status_reports_degraded_not_down_when_optional_layers_missing():
    status, reasons = readiness_status(
        db_ok=True,
        sources={"summary": {"live": 3, "empty": 4}},
        index={"built": False, "documents": 0},
    )
    assert status == "degraded"
    assert "multiple_empty_sources" in reasons
    assert "semantic_index_missing" in reasons

    status, reasons = readiness_status(db_ok=False, sources={"summary": {}}, index={"built": False})
    assert status == "down"
    assert "database_unreachable" in reasons

def test_frontend_navigation_registry_keeps_record_aliases_and_internal_routes():
    registry = Path("web/lib/navigation.ts").read_text()
    for token in [
        '"lobbying_records"',
        '"gazette_entries"',
        '"tribunal_decisions"',
        'key: "social_statements"',
        'aliases: ["public_statements", "social_posts"]',
        'key: "reports"',
        'aliases: ["briefings"]',
        'key: "sources"',
        'if (canonical === "meetings") return meetingHref(pk);',
        'return `/records/${encodeURIComponent(canonical)}/${encodeURIComponent(String(pk))}`',
        'export function meetingHref',
        '`/meetings/${encodeURIComponent(String(id))}`',
        'export function reportHref',
        '`/briefings/${encodeURIComponent(id)}`',
        'return title ? `/signals/${encodeURIComponent(slugifyFindingTitle(title))}` : null',
        'return name ? `/entities/${encodeURIComponent(name)}` : null',
        'return slug ? `/politicians/${encodeURIComponent(slug)}` : null',
        'export function organizationHref',
        '`/organizations/${encodeURIComponent(kind)}/${encodeURIComponent(name)}`',
        'export function committeeHref',
        '`/committees/${encodeURIComponent(slug)}`',
        'export function sourceHref',
        '`/sources/${encodeURIComponent(id)}`',
        'export function senatorHref',
        '`/senators/${encodeURIComponent(slug)}`',
        'export function ministerHref',
        '`/ministers/${encodeURIComponent(slug)}`',
    ]:
        assert token in registry


def test_connected_intelligence_audit_tracks_supported_and_unsupported_types():
    audit = Path("CONNECTED_INTELLIGENCE_AUDIT.md").read_text()
    for supported in [
        "`/records/[table]/[pk]`",
        "`/signals/[slug]`",
        "`/api/graph/record/{table}/{pk}`",
        "`/api/organizations/{kind}/{name}`",
        "`/api/parliament/committee/{slug}`",
        "`/api/sources/{source_id}`",
        "`contracts`",
        "`bills`",
        "`source_records`",
        "`social_statements`",
    ]:
        assert supported in audit
    for unsupported in ["Senators", "Committees", "Departments", "Regulators"]:
        assert unsupported in audit
    assert "Social posts/public statements" in audit
    assert "Internal public-statement source profile and `/records/social_statements/{id}` alias are available" in audit



def test_organization_route_is_registered_in_backend_and_frontend():
    main = Path("api/main.py").read_text()
    route = Path("api/routes/organizations.py").read_text()
    page = Path("web/app/organizations/[kind]/[name]/page.tsx").read_text()
    audit = Path("CONNECTED_INTELLIGENCE_AUDIT.md").read_text()
    assert "organizations.router" in main
    assert '@router.get("/{kind}/{name}"' in route
    assert "OrganizationProfileResponse" in route
    assert "owner_org_title" in route
    assert "GazetteEntry.department" in route
    assert "TribunalDecision.body" in route
    assert "LobbyingRecord.institutions" in route
    assert "useApi<OrganizationProfile>(path)" in page
    assert "useSearchParams" in page
    assert "organizationContext(searchParams)" in page
    assert 'if (from === "search")' in page
    assert 'if (from === "sector")' in page
    assert 'if (from === "finding")' in page
    assert "hrefFor={(ref) => withContext(evidenceHref(ref), context)}" in page
    assert "findingRelatedItems(org.related_findings, context)" in page
    assert "href: withContext(findingHref(finding.title), context)" in page
    assert "href: withContext(sectorHref(sector.slug), context)" in page
    assert "AvatarLogo" in page
    assert "RelatedItems" in page
    assert "EvidenceRows" in page
    assert "Official mark not stored yet" in page
    assert "Static" not in page
    assert "Live `/api/organizations/{kind}/{name}` profile" in audit


def test_entity_detail_uses_live_profile_and_logo_fallbacks():
    route = Path("api/routes/entities.py").read_text()
    schemas = Path("api/schemas.py").read_text()
    pipeline = Path("pipeline/sector_intel.py").read_text()
    page = Path("web/app/entities/[canonical]/page.tsx").read_text()
    audit = Path("CONNECTED_INTELLIGENCE_AUDIT.md").read_text()
    assert '@router.get("/{name}"' in route
    assert "EntityProfileResponse" in route
    assert "reports: list[ReportSummary]" in schemas
    assert "gather_entity_data" in route
    assert "async def _entity_reports" in pipeline
    assert "Report.canonical_name == canonical" in pipeline
    assert "useApi<EntityProfile>" in page
    assert "entityContext(searchParams)" in page
    assert 'if (from === "search")' in page
    assert 'if (from === "sector")' in page
    assert 'if (from === "finding")' in page
    assert "AvatarLogo" in page
    assert "SourceCoverageList" in page
    assert "EvidenceRows" in page
    assert "withContext(sectorHref(entity.sector.slug), context)" in page
    assert "Reports including this entity" in page
    assert "reportItems(entity, context)" in page
    assert 'relationship: "report covers entity"' in page
    assert "reportHref(report.id)" in page
    assert "Official logo not stored yet" in page
    assert "Connected bills" in page
    assert "Lobbying & regulations" in page
    assert "Static" not in page
    assert "Live `/api/entities/{name}` profile" in audit
    assert "reports including the entity" in audit


def test_entity_index_uses_graph_findings_and_internal_links():
    page = Path("web/app/entities/page.tsx").read_text()
    audit = Path("CONNECTED_INTELLIGENCE_AUDIT.md").read_text()
    assert 'useApi<FindingsResponse>("/api/graph/findings")' in page
    assert "buildEntityRows(findings)" in page
    assert "AvatarLogo" in page
    assert "entityHref(entity.name)" in page
    assert "findingHref(firstFinding)" in page
    assert "evidenceHref(firstEvidence)" in page
    assert "sectorHref(entity.sector.slug)" in page
    assert "finding affects company" in page
    assert "Design-to-match" not in page
    assert "static for now" not in page
    assert "Live `/api/graph/findings` directory" in audit


def test_meeting_pages_reuse_lobbying_records_as_internal_detail_views():
    registry = Path("web/lib/navigation.ts").read_text()
    page = Path("web/app/meetings/[id]/page.tsx").read_text()
    dossier = Path("web/components/record-dossier.tsx").read_text()
    audit = Path("CONNECTED_INTELLIGENCE_AUDIT.md").read_text()
    assert 'key: "meetings"' in registry
    assert "meetingHref" in registry
    # The meeting view is now a thin wrapper over the shared record dossier, with a
    # meeting-specific lead card; the dossier supplies the connected intelligence.
    assert "/api/records/lobbying/" in page
    assert "/api/graph/record/lobbying/" in page
    assert "useSearchParams" in page
    assert "investigationContext" in page
    assert "RecordDossier" in page
    assert "Registered Communication" in page
    assert 'label: "Meetings"' in page
    # Shared dossier carries the workflow context + connected intelligence.
    assert "Investigation context" in dossier
    assert "How It Connects" in dossier
    assert "OriginalSourceLink" in dossier
    assert "`/meetings/{id}`" in audit
    assert "`/meetings/[id]` is a semantic internal view over `/records/lobbying/{id}`" in audit


def test_senator_and_minister_pages_are_internal_graceful_states():
    registry = Path("web/lib/navigation.ts").read_text()
    senator_page = Path("web/app/senators/[slug]/page.tsx").read_text()
    minister_page = Path("web/app/ministers/[slug]/page.tsx").read_text()
    shared = Path("web/components/planned-political-profile.tsx").read_text()
    audit = Path("CONNECTED_INTELLIGENCE_AUDIT.md").read_text()
    assert 'key: "senators"' in registry
    assert 'key: "ministers"' in registry
    assert 'kind="senator"' in senator_page
    assert 'kind="minister"' in minister_page
    assert "useApi<SearchResponse>(searchPath)" in shared
    assert 'useApi<FindingsResponse>("/api/graph/findings")' in shared
    assert "evidenceFromSearch" in shared
    assert "relatedFindingsFor" in shared
    assert "Official {profile.imageLabel} source metadata is not stored yet" in shared
    assert "No dedicated Senate evidence feed is loaded yet" in shared
    assert "No dedicated ministerial evidence feed is loaded yet" in shared
    assert "Treasury Board Secretariat" not in minister_page + shared
    assert "Attendance" not in senator_page + shared
    assert "`/senators/{slug}`" in audit
    assert "`/ministers/{slug}`" in audit
    assert "search/graph-backed investigation page" in audit


def test_political_portrait_metadata_is_exposed_and_displayed():
    route = Path("api/routes/politicians.py").read_text()
    schemas = Path("api/schemas.py").read_text()
    types = Path("web/lib/api.ts").read_text()
    directory = Path("web/app/politicians/page.tsx").read_text()
    detail = Path("web/app/politicians/[slug]/page.tsx").read_text()
    avatar = Path("web/components/intelligence.tsx").read_text()
    assert "def _photo_metadata" in route
    assert "photo_attribution" in schemas
    assert "photo_source_url" in types
    assert "Portrait: {p.photo_source}" in directory
    assert "Portrait:" in detail
    assert "imageAttribution" in avatar
    assert "export function PartyBadge" in avatar
    assert "export function JurisdictionBadge" in avatar
    assert "Generated party identity fallback; official party logo is not stored." in avatar
    assert "Generated jurisdiction symbol fallback; official flag or symbol is not stored." in avatar
    assert "PartyBadge" in directory
    assert "JurisdictionBadge" in directory
    assert "PartyBadge" in detail
    assert "JurisdictionBadge" in detail


def test_politician_detail_uses_live_api_and_internal_hansard_links():
    route = Path("api/routes/politicians.py").read_text()
    types = Path("web/lib/api.ts").read_text()
    page = Path("web/app/politicians/[slug]/page.tsx").read_text()
    audit = Path("CONNECTED_INTELLIGENCE_AUDIT.md").read_text()

    assert "/api/politicians/${encodeURIComponent(slug)}" in page
    assert "RelatedItems" in page
    assert "AvatarLogo" in page
    assert "useSearchParams" in page
    assert "politicianContext(searchParams)" in page
    assert 'if (from === "search")' in page
    assert 'if (from === "sector")' in page
    assert 'if (from === "finding")' in page
    assert '"table": "hansard_mentions"' in route
    assert "withContext(recordHref(speech.table, speech.pk), context)" in page
    assert "withContext(recordHref(bill.table, bill.pk), context)" in page
    assert "withContext(sectorHref(sector.slug), context)" in page
    assert "committeeItemsFor(mp, context)" in page
    assert "withContext(committeeHref(committee.slug), context)" in page
    assert "Investigation context" in page
    assert "Original source available on evidence record" in page
    assert "View portrait source" in page
    assert "OriginalSourceLink" in page
    assert "table: string; pk: number; keyword" in types
    assert "Live `/api/politicians/{slug}` profile" in audit
    assert "`PartyBadge`" in audit
    assert "`JurisdictionBadge`" in audit
    assert "generated party symbols/color fallbacks" in audit
    assert "Static for now" not in page


def test_source_detail_pages_are_registered_and_linkable():
    schemas = Path("api/schemas.py").read_text()
    route = Path("api/routes/sources.py").read_text()
    record_route = Path("api/routes/records.py").read_text()
    page = Path("web/app/sources/[id]/page.tsx").read_text()
    ui = Path("web/components/ui.tsx").read_text()
    assert "class SourceDetailResponse" in schemas
    assert '@router.get("/sources/{source_id}"' in route
    assert "SourceDetailResponse" in route
    assert "RelatedItems" in page
    assert "EvidenceRows" in page
    assert '"id": "social_statements", "label": "Public statements", "table": "source_records"' in route
    assert '"source_values": ["social_statements", "public_statements"]' in route
    assert "model.source.in_(source_values)" in route
    assert '"social_statements": "source_records"' in record_route
    assert "recordTypeLabel(record.record_type, record.source, record.table)" in page
    assert "sourceHref(s.id)" in ui


def test_sector_detail_uses_live_overview_and_internal_investigation_links():
    page = Path("web/app/sectors/[slug]/page.tsx").read_text()
    types = Path("web/lib/api.ts").read_text()
    audit = Path("CONNECTED_INTELLIGENCE_AUDIT.md").read_text()
    assert "/api/sectors/${encodeURIComponent(slug)}/overview" in page
    assert "SectorOverview" in page
    assert "graph?: EvidenceGraphResponse" in types
    assert "findingHref" in page
    assert "evidenceHref" in page
    assert "recordHref" in page
    assert "sourceHref" in page
    assert "from=sector&sector=" in page
    assert "withSectorContext" in page
    assert "peopleItems(graph, sector.slug)" in page
    assert "organizationItems(data, sector.slug)" in page
    assert "withSectorContext(personHref(slug), sectorSlug)" in page
    assert "withSectorContext(entityHref(row.entity), sectorSlug)" in page
    assert "withSectorContext(committeeHref(committee.slug), sectorSlug)" in page
    assert "hrefFor={(ref) => withSectorContext(evidenceHref(ref), sector.slug)}" in page
    assert "Connected bills, lobbying, regulations & sources" in page
    assert "Static for now" not in page
    assert "preserves `from=sector&sector=...` context into findings, evidence records, people, entities, regulators, and committees" in audit


def test_cross_sector_page_uses_live_graph_and_internal_links():
    page = Path("web/app/cross-sector/page.tsx").read_text()
    audit = Path("CONNECTED_INTELLIGENCE_AUDIT.md").read_text()
    assert 'useApi<SectorsResponse>("/api/sectors")' in page
    assert 'useApi<FindingsResponse>("/api/graph/findings")' in page
    assert "buildConvergencePairs" in page
    assert "findingHref" in page
    assert "evidenceHref" in page
    assert "sectorHref" in page
    assert "No shared files detected." in page
    assert "Static for now" not in page
    assert "Live `/api/sectors` + `/api/graph/findings` view" in audit


def test_watchlists_page_uses_live_targets_and_internal_links():
    page = Path("web/app/watchlists/page.tsx").read_text()
    audit = Path("CONNECTED_INTELLIGENCE_AUDIT.md").read_text()
    assert 'useApi<SectorsResponse>("/api/sectors")' in page
    assert 'useApi<FindingsResponse>("/api/graph/findings")' in page
    assert "buildWatchlists" in page
    assert "RelatedItems" in page
    assert "findingHref" in page
    assert "evidenceHref" in page
    assert "sectorHref" in page
    assert 'action="/search"' in page
    assert "Push alerts are a planned workflow" in page
    assert "Static for now" not in page
    assert "Live `/api/sectors` + `/api/graph/findings` monitoring workspace" in audit


def test_committee_pages_are_registered_and_linked_from_findings():
    schemas = Path("api/schemas.py").read_text()
    route = Path("api/routes/parliament.py").read_text()
    page = Path("web/app/committees/[slug]/page.tsx").read_text()
    finding_page = Path("web/app/signals/[slug]/page.tsx").read_text()
    audit = Path("CONNECTED_INTELLIGENCE_AUDIT.md").read_text()
    assert "class CommitteeProfileResponse" in schemas
    assert '@router.get("/committee/{slug}"' in route
    assert "Standing Committee on Industry and Technology" in route
    assert "useApi<CommitteeProfile>" in page
    assert "/api/parliament/committee/" in page
    assert "AvatarLogo" in page
    assert "RelatedItems" in page
    assert "EvidenceRows" in page
    assert "useSearchParams" in page
    assert "committeeContext(searchParams)" in page
    assert 'if (from === "sector")' in page
    assert "Investigation context" in page
    assert "hrefFor={(ref) => withContext(evidenceHref(ref), context)}" in page
    assert "peopleRelatedItems(committee.connected_people, context)" in page
    assert "findingRelatedItems(committee.related_findings, context)" in page
    assert "sourceGroupItems(committee.groups, context)" in page
    assert "recordsRelatedItems(committee.connected_records, context)" in page
    assert "person mentioned committee" in page
    assert "committee studied bill" in page
    assert "Official committee mark not stored yet" in page
    assert "Live `/api/parliament/committee/{slug}` profile" in audit
    assert "preserved search/sector/finding context" in audit
    assert "committeeHref" in finding_page
    assert "committeeItem(item, index, findingSlug)" in finding_page


def test_finding_detail_preserves_context_into_evidence_records():
    page = Path("web/app/signals/[slug]/page.tsx").read_text()
    record_page = Path("web/app/records/[table]/[pk]/page.tsx").read_text()
    entity_page = Path("web/app/entities/[canonical]/page.tsx").read_text()
    politician_page = Path("web/app/politicians/[slug]/page.tsx").read_text()
    audit = Path("CONNECTED_INTELLIGENCE_AUDIT.md").read_text()
    assert "useSearchParams" in page
    assert "findingContext(searchParams)" in page
    assert "withFindingContext(evidenceHref(ref), findingSlug)" in page
    assert "withFindingContext(entityHref(ref.entity), findingSlug)" in page
    assert "withFindingContext(personHref(slug), findingSlug)" in page
    assert "sectorRelatedItems(finding, findingSlug)" in page
    assert "committeeRelatedItems(finding, findingSlug)" in page
    assert "withFindingContext(sectorHref(sector.slug), findingSlug)" in page
    assert "withFindingContext(committeeHref(item.slug), findingSlug)" in page
    assert "withFindingContext(reportHref(report.id), findingSlug)" in page
    assert "from=finding&finding=" in page
    assert 'relationship: "finding supported by record"' in page
    dossier = Path("web/components/record-dossier.tsx").read_text()
    assert "from=finding" in dossier
    assert "personHref(p.slug)" in dossier
    assert "entityContext(searchParams)" in entity_page
    assert "hrefFor={(ref) => withContext(evidenceHref(ref), context)}" in entity_page
    assert "Investigation context" in entity_page
    assert "politicianContext(searchParams)" in politician_page
    assert "withContext(recordHref(speech.table, speech.pk), context)" in politician_page
    assert "Dashboard/Morning Brief finding cards preserve context" in audit
    assert "dashboard finding → finding detail → connected bill/person/company → evidence record → original source" in audit


def test_search_context_preserves_through_connected_entities_people_and_organizations():
    dossier = Path("web/components/record-dossier.tsx").read_text()
    entity_page = Path("web/app/entities/[canonical]/page.tsx").read_text()
    politician_page = Path("web/app/politicians/[slug]/page.tsx").read_text()
    organization_page = Path("web/app/organizations/[kind]/[name]/page.tsx").read_text()
    audit = Path("CONNECTED_INTELLIGENCE_AUDIT.md").read_text()

    assert 'if (context.from === "search")' in dossier
    assert 'return `${href}${glue}from=search${q ? `&q=${encodeURIComponent(q)}` : ""}`' in dossier
    for page in (entity_page, politician_page, organization_page):
        assert 'if (from === "search")' in page
        assert 'if (from === "sector")' in page
        assert 'if (from === "finding")' in page
        assert 'if (context.from === "search")' in page
        assert "Investigation context" in page
    assert "search result → evidence record → connected entity/person/organization → related records" in audit
    assert "related-finding, sector, entity-profile evidence links" in audit


def test_finding_detail_promotes_connected_bills_companies_and_source_groups():
    page = Path("web/app/signals/[slug]/page.tsx").read_text()
    audit = Path("CONNECTED_INTELLIGENCE_AUDIT.md").read_text()
    assert "companyRelatedItems(finding, findingSlug)" in page
    assert "actorRelatedItems(finding, findingSlug)" in page
    assert 'recordRelatedItems(finding, findingSlug, ["bills"])' in page
    assert 'recordRelatedItems(finding, findingSlug, ["lobbying", "ocl_registrations", "gazette", "tribunal", "source_records"])' in page
    assert "Companies & organizations" in page
    assert "Connected bills" in page
    assert "Lobbying, regulations & sources" in page
    assert 'relationship: "finding affects company"' in page
    assert 'if (table === "bills") return "bill affects sector"' in page
    assert 'if (table === "lobbying" || table === "ocl_registrations") return "organization registered lobbying activity"' in page
    assert 'if (table === "gazette" || table === "tribunal") return "regulator opened consultation"' in page
    assert "Finding-detail supporting-evidence, sector, committee, report, company/entity, and political-figure links append `from=finding&finding=...`" in audit


def test_report_api_and_reader_expose_internal_findings_and_evidence():
    schemas = Path("api/schemas.py").read_text()
    route = Path("api/routes/reports.py").read_text()
    hub = Path("web/app/briefings/page.tsx").read_text()
    reader = Path("web/app/briefings/[id]/page.tsx").read_text()
    audit = Path("CONNECTED_INTELLIGENCE_AUDIT.md").read_text()
    assert "graph_findings: list[GraphFinding]" in schemas
    assert "source_references: list[EvidenceReference]" in schemas
    assert "_report_graph_findings" in route
    assert "_report_source_references" in route
    assert 'useApi<ReportsResponse>("/api/reports")' in hub
    assert "reportHref(report.id)" in hub
    assert "No generated briefings yet." in hub
    assert "Static for now" not in hub
    assert "Live `/api/reports` hub" in audit
    assert "useSearchParams" in reader
    assert "briefingContext(searchParams)" in reader
    assert "reportFindingItems(data.graph_findings ?? [], context)" in reader
    assert "href: withContext(findingHref(finding.title), context)" in reader
    assert "hrefFor={(ref) => withContext(evidenceHref(ref), context)}" in reader
    assert 'if (from === "search")' in reader
    assert 'if (from === "sector")' in reader
    assert 'if (from === "finding")' in reader
    assert 'relationship: "report includes finding"' in reader
    assert "report covers entity" in audit
    assert "Connected findings" in reader
    assert "Supporting evidence" in reader
    assert "OriginalSourceLink" in reader
    assert "Report detail preserves incoming search, sector, or finding context into connected findings and supporting evidence records." in audit


def test_finding_pages_link_back_to_reports_that_include_them():
    route = Path("api/routes/reports.py").read_text()
    page = Path("web/app/signals/[slug]/page.tsx").read_text()
    assert '@router.get("/by-finding/{slug}"' in route
    assert "_report_matches_finding_slug" in route
    assert "Reports including this finding" in page
    assert 'relationship: "report includes finding"' in page
    assert "withFindingContext(reportHref(report.id), findingSlug)" in page
