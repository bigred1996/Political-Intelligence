"""ASGI smoke tests for critical backend routes.

These exercise FastAPI routing and dependency injection against a temporary
SQLite database. They do not touch the local Nessus corpus.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import httpx
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.database import Base, get_session
from api.main import app
from api.models.donation import Bill
from api.models.report import Report
from api.models.source_record import SourceRecord

# Register all model tables on Base.metadata.
from api.models import (  # noqa: F401
    appointment,
    contract,
    donation,
    entity,
    grant,
    ocl_registration,
    politician,
    regulation,
    report,
    request,
    scheduler_log,
    source_record,
)


def test_openapi_publishes_shared_backend_contracts():
    schemas = app.openapi().get("components", {}).get("schemas", {})
    assert "EvidenceReference" in schemas
    assert "IntelligenceEvidence" in schemas
    assert "IntelligenceFinding" in schemas
    assert "MovementWindow" in schemas
    assert "GraphFinding" in schemas
    assert "HealthResponse" in schemas
    assert "FindingsResponse" in schemas
    assert "ReadinessResponse" in schemas
    assert "SourceStatusResponse" in schemas
    assert "SourceDetailResponse" in schemas
    assert "SchedulerStatusResponse" in schemas
    assert "SchedulerHistoryResponse" in schemas
    assert "SchedulerTriggerResponse" in schemas
    assert "SearchResponse" in schemas
    assert "SearchReindexResponse" in schemas
    assert "ReportResponse" in schemas
    assert "ReportListResponse" in schemas
    assert "SourceSearchResponse" in schemas
    assert "RecordListResponse" in schemas
    assert "StatsResponse" in schemas
    assert "ReportRequestListResponse" in schemas
    assert "PoliticianListResponse" in schemas
    assert "PoliticianProfileResponse" in schemas
    assert "BriefingResponse" in schemas
    assert "OverviewResponse" in schemas
    assert "SectorListResponse" in schemas
    assert "SectorOverviewResponse" in schemas
    assert "RecordDetailResponse" in schemas
    assert "CommitteeProfileResponse" in schemas


def test_json_api_routes_publish_response_contracts():
    missing = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if not route.path.startswith("/api"):
            continue
        if route.response_model is None:
            missing.append(route.path)
    assert missing == []


def test_health_and_sources_endpoints_smoke(tmp_path):
    asyncio.run(_health_and_sources_endpoints_smoke(tmp_path))


async def _health_and_sources_endpoints_smoke(tmp_path):
    db_path = tmp_path / "smoke.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with session_maker() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            health = await client.get("/api/health/ready")
            assert health.status_code == 200
            health_body = health.json()
            assert health_body["status"] in {"ok", "degraded"}
            assert "source_quality" in health_body["checks"]

            sources = await client.get("/api/sources/status")
            assert sources.status_code == 200
            body = sources.json()
            assert "sources" in body
            assert "summary" in body
            assert "quality" in body
            assert body["summary"]["empty"] >= 1

            source_detail = await client.get("/api/sources/contracts")
            assert source_detail.status_code == 200
            source_body = source_detail.json()
            assert source_body["id"] == "contracts"
            assert source_body["label"] == "Federal contracts"
            assert "connected_records" in source_body

            scheduler = await client.get("/api/scheduler/status")
            assert scheduler.status_code == 200
            scheduler_body = scheduler.json()
            assert "jobs" in scheduler_body
            assert any(j["id"] == "hansard_search" for j in scheduler_body["jobs"])

            history = await client.get("/api/scheduler/history")
            assert history.status_code == 200
            assert history.json()["count"] == 0
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


def test_overview_and_sector_endpoints_smoke_on_empty_db(tmp_path):
    asyncio.run(_overview_and_sector_endpoints_smoke_on_empty_db(tmp_path))


async def _overview_and_sector_endpoints_smoke_on_empty_db(tmp_path):
    db_path = tmp_path / "overview.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with session_maker() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            overview = await client.get("/api/overview")
            assert overview.status_code == 200
            overview_body = overview.json()
            assert "sector_watchlist" in overview_body
            assert "intelligence_findings" in overview_body
            assert "sector_comparison" in overview_body
            assert "what_changed" in overview_body
            assert "cache" in overview_body

            sector = await client.get("/api/sectors/energy/overview")
            assert sector.status_code == 200
            sector_body = sector.json()
            assert sector_body["sector"]["slug"] == "energy"
            assert "risk_band" in sector_body
            assert "movement" in sector_body
            assert "findings" in sector_body
            assert "suggested_questions" in sector_body
            assert "intelligence_brief" in sector_body
            assert "graph" in sector_body
            assert "cache" in sector_body

            graph = await client.get("/api/graph/sector/energy")
            assert graph.status_code == 200
            graph_body = graph.json()
            assert graph_body["sector"]["slug"] == "energy"
            assert "nodes" in graph_body

            findings = await client.get("/api/graph/findings")
            assert findings.status_code == 200
            assert "findings" in findings.json()
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


def test_record_detail_resolves_linkable_record(tmp_path):
    asyncio.run(_record_detail_resolves_linkable_record(tmp_path))


async def _record_detail_resolves_linkable_record(tmp_path):
    db_path = tmp_path / "records.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_maker() as session:
        bill = Bill(
            bill_number="C-99",
            parliament="45-1",
            title_en="An Act respecting telecommunications infrastructure",
            status="Introduced",
            sponsor="Test Sponsor",
            latest_activity="First reading",
            introduced_date="2026-06-01",
        )
        session.add(bill)
        statement = SourceRecord(
            source="social_statements",
            record_type="public_statement",
            external_id="statement-1",
            entity_name="TELUS",
            canonical_name="telus",
            title="Minister statement on telecommunications competition",
            summary="A public statement referencing telecom market competition.",
            event_date="2026-06-02",
            url="https://example.test/statement",
        )
        session.add(statement)
        await session.commit()
        bill_id = bill.id
        statement_id = statement.id

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with session_maker() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            detail = await client.get(f"/api/records/bills/{bill_id}")
            assert detail.status_code == 200
            body = detail.json()
            assert body["table"] == "bills"
            assert body["pk"] == bill_id
            assert body["record"]["title"].startswith("C-99")
            assert body["record"]["date"] == "2026-06-01"

            statement_detail = await client.get(f"/api/records/social_statements/{statement_id}")
            assert statement_detail.status_code == 200
            statement_body = statement_detail.json()
            assert statement_body["table"] == "source_records"
            assert statement_body["record"]["source"] == "social_statements"
            assert statement_body["record"]["type_label"] == "Public statement"
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


def test_search_and_report_endpoints_smoke_on_empty_db(tmp_path):
    asyncio.run(_search_and_report_endpoints_smoke_on_empty_db(tmp_path))


async def _search_and_report_endpoints_smoke_on_empty_db(tmp_path):
    db_path = tmp_path / "search_reports.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    report = Report(
        id="smoke-report",
        company_name="TELUS",
        canonical_name="telus",
        report_type="deal_due_diligence",
        time_horizon="current",
        status="analyst_review",
        generated_by="template",
        risk_scores={"overall": 4.2},
        evidence={"source_references": []},
        sections={"executive_summary": "<p>Smoke</p>"},
    )
    async with session_maker() as session:
        session.add(report)
        await session.commit()

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with session_maker() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            search = await client.get("/api/search", params={"q": "telecom policy", "answer": "false"})
            assert search.status_code == 200
            search_body = search.json()
            assert search_body["query"] == "telecom policy"
            assert "results" in search_body

            index = await client.get("/api/search/index/status")
            assert index.status_code == 200
            assert index.json()["built"] in {True, False}

            search_sources = await client.get("/api/search/sources")
            assert search_sources.status_code == 200
            search_sources_body = search_sources.json()
            assert "approximate_sources" in search_sources_body
            assert "row_count_methods" in search_sources_body

            reports = await client.get("/api/reports")
            assert reports.status_code == 200
            assert reports.json()["count"] == 1

            detail = await client.get("/api/reports/smoke-report")
            assert detail.status_code == 200
            detail_body = detail.json()
            assert detail_body["company_name"] == "TELUS"
            assert detail_body["sections"][0]["key"] == "executive_summary"

            entity = await client.get("/api/entities/telus")
            assert entity.status_code == 200
            entity_body = entity.json()
            assert entity_body["reports"][0]["id"] == "smoke-report"
            assert entity_body["reports"][0]["company_name"] == "TELUS"
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


def test_legacy_source_utility_routes_smoke_on_empty_db(tmp_path):
    asyncio.run(_legacy_source_utility_routes_smoke_on_empty_db(tmp_path))


async def _legacy_source_utility_routes_smoke_on_empty_db(tmp_path):
    db_path = tmp_path / "legacy_routes.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with session_maker() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            for path in [
                "/api/contracts/stats",
                "/api/grants/stats",
                "/api/appointments/stats",
                "/api/ocl-registrations/stats",
                "/api/regulations/stats",
            ]:
                res = await client.get(path)
                assert res.status_code == 200

            searches = [
                ("/api/contracts/search", {"company": "telus"}),
                ("/api/grants/search", {"q": "telus"}),
                ("/api/appointments/search", {"q": "crtc"}),
                ("/api/ocl-registrations/search", {"q": "telus"}),
                ("/api/regulations/gazette/search", {"q": "telecom"}),
                ("/api/regulations/decisions/search", {"q": "telecom"}),
            ]
            for path, params in searches:
                res = await client.get(path, params=params)
                assert res.status_code == 200
                assert res.json()["count"] == 0
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


def test_remaining_product_routes_smoke_on_empty_db(tmp_path):
    asyncio.run(_remaining_product_routes_smoke_on_empty_db(tmp_path))


async def _remaining_product_routes_smoke_on_empty_db(tmp_path):
    db_path = tmp_path / "remaining_routes.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with session_maker() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            create_req = await client.post("/api/requests", json={"company_name": "TELUS"})
            assert create_req.status_code == 200
            assert create_req.json()["company_name"] == "TELUS"

            list_req = await client.get("/api/requests")
            assert list_req.status_code == 200
            assert list_req.json()["count"] == 1

            briefing = await client.get("/api/briefing")
            assert briefing.status_code == 200
            assert "streams" in briefing.json()

            politicians = await client.get("/api/politicians")
            assert politicians.status_code == 200
            assert politicians.json()["count"] == 0

            schemas = app.openapi().get("components", {}).get("schemas", {})
            politician_props = schemas["PoliticianProfileResponse"].get("properties", {})
            assert "photo_attribution" in politician_props
            assert "photo_source_url" in politician_props

            parliament_politicians = await client.get("/api/parliament/politicians")
            assert parliament_politicians.status_code == 200
            assert parliament_politicians.json()["count"] == 0

            committee = await client.get("/api/parliament/committee/indu")
            assert committee.status_code == 200
            committee_body = committee.json()
            assert committee_body["slug"] == "indu"
            assert committee_body["name"] == "Standing Committee on Industry and Technology"
            assert "connected_records" in committee_body

            entity = await client.get("/api/entities/telus")
            assert entity.status_code == 200
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


def test_report_response_schema_exposes_linkable_findings():
    schema = app.openapi()["components"]["schemas"]["ReportResponse"]
    props = schema.get("properties", {})
    assert "graph_findings" in props
    assert "source_references" in props


def test_reports_by_finding_route_is_published_before_report_id_route():
    paths = [route.path for route in app.routes if isinstance(route, APIRoute)]
    assert "/api/reports/by-finding/{slug}" in paths
    assert paths.index("/api/reports/by-finding/{slug}") < paths.index("/api/reports/{report_id}")


def test_committee_route_is_published_before_committee_list_route():
    paths = [route.path for route in app.routes if isinstance(route, APIRoute)]
    assert "/api/parliament/committee/{slug}" in paths
    assert "/api/parliament/committees" in paths
    assert paths.index("/api/parliament/committee/{slug}") < paths.index("/api/parliament/committees")
