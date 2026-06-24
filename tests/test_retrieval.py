"""Tests for the unified retrieval service (search/retrieval.py) and its API.

Semantic search is monkeypatched out (returns []) so these tests are hermetic
and don't depend on whatever happens to be built in data/index/ on disk — the
semantic half is already covered by tests/test_search_index.py. What's under
test here is new: the deterministic pseudo-table sources (politicians, sectors,
entities, organizations/regulators, committees, reports), the merge with the
existing tabular SPECS path, internal-link generation, determinism, and the
explicit empty-retrieval state.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import httpx
import search.retrieval as retrieval_mod
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.database import Base, get_session
from api.main import app
from api.models.contract import Contract
from api.models.donation import Bill
from api.models.entity import LobbyingRecord
from api.models.politician import Politician
from api.models.regulation import GazetteEntry
from api.models.report import Report
from api.models.source_record import SourceRecord
from search.retrieval import retrieve

# Register all model tables on Base.metadata.
from api.models import (  # noqa: F401
    appointment, donation, entity, grant, ocl_registration,
    politician, regulation, report, request, retrieval_set, scheduler_log, source_record,
)


async def _seed(session_maker) -> None:
    async with session_maker() as session:
        session.add(Bill(
            bill_number="C-27", parliament="44-1",
            title_en="An Act respecting Industry and Technology innovation",
            status="Second reading", sponsor="Test Minister",
            introduced_date="2025-01-15",
        ))
        session.add(GazetteEntry(
            gazette_part="I", title="Telecommunications Fees Order",
            description="Sets fees for telecommunications licensing.",
            department="Innovation, Science and Economic Development Canada",
            published_date="2025-02-01", url="https://gazette.gc.ca/example",
        ))
        session.add(LobbyingRecord(
            company_query="acme", canonical_name="acme corp", registration_id="REG-1",
            client="Acme Corp", registrant="Some Registrant",
            subject_matters=["Telecommunications"], institutions=["Innovation, Science and Economic Development Canada"],
            communication_date="2025-03-01",
        ))
        session.add(Contract(
            vendor_name="TELUS Communications Inc.", canonical_name="telus",
            description="Network services contract", contract_value=250_000.0,
            contract_date="2025-04-01", owner_org_title="Innovation, Science and Economic Development Canada",
        ))
        session.add(Contract(
            vendor_name="Local Co", canonical_name="local co",
            description="Generic services", contract_value=10_000.0,
            contract_date="2025-04-02",
            owner_org_title="Canadian Radio-television and Telecommunications Commission",
        ))
        session.add(SourceRecord(
            source="social_statements", record_type="public_statement",
            external_id="statement-1", entity_name=None, canonical_name=None,
            title="Minister statement on competition policy",
            summary="A public statement referencing competition policy in telecommunications markets.",
            event_date="2025-05-01", url="https://example.test/statement",
        ))
        session.add(Politician(
            slug="jane-doe", name="Jane Doe", party="Independent",
            riding="Test Riding", province="ON", role="MP for Test Riding",
        ))
        session.add(Report(
            id="report-acme-1", company_name="Acme Corp", canonical_name="acme corp",
            report_type="deal_due_diligence", status="analyst_review", generated_by="template",
            risk_scores={"overall": 5.0}, evidence={}, sections={},
        ))
        await session.commit()


async def _make_db(tmp_path, name: str):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / name}", future=True)
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _seed(session_maker)
    return engine, session_maker


def test_record_type_coverage_with_internal_links(tmp_path, monkeypatch):
    asyncio.run(_coverage_scenario(tmp_path, monkeypatch))


async def _coverage_scenario(tmp_path, monkeypatch):
    monkeypatch.setattr(retrieval_mod, "semantic_search", lambda *a, **k: [])
    engine, session_maker = await _make_db(tmp_path, "coverage.db")

    cases = [
        ("Industry and Technology innovation act", "bill", "/records/bills/"),
        ("Telecommunications Fees Order", "regulation", "/records/gazette/"),
        ("Acme Corp lobbied", "lobbying_communication", "/records/lobbying/"),
        ("TELUS contract services", "contract", "/records/contracts/"),
        ("competition policy statement", "public_statement", "/records/source_records/"),
        ("Jane Doe", "person", "/politicians/jane-doe"),
        ("telecommunications spectrum wireless", "sector", "/sectors/"),
        ("telus", "entity", "/entities/telus"),
        ("Canadian Radio-television contracts", "regulator", "/organizations/regulator/"),
        ("indu committee", "committee", "/committees/indu"),
        ("Acme Corp report", "report", "/briefings/report-acme-1"),
    ]

    async with session_maker() as session:
        for query, expected_type, expected_href_prefix in cases:
            result = await retrieve(session, query)
            matches = [h for h in result["results"] if h["record_type"] == expected_type]
            assert matches, f"expected a {expected_type!r} hit for query {query!r}, got {result['results']}"
            hit = matches[0]
            assert hit["internal_url"] is not None
            assert hit["internal_url"].startswith(expected_href_prefix), (
                f"{expected_type}: {hit['internal_url']!r} does not start with {expected_href_prefix!r}"
            )
            assert hit["id"] == f"{hit['table']}:{hit['pk']}"

    await engine.dispose()


def test_empty_retrieval_returns_explicit_empty_state(tmp_path, monkeypatch):
    asyncio.run(_empty_scenario(tmp_path, monkeypatch))


async def _empty_scenario(tmp_path, monkeypatch):
    monkeypatch.setattr(retrieval_mod, "semantic_search", lambda *a, **k: [])
    engine, session_maker = await _make_db(tmp_path, "empty.db")

    async with session_maker() as session:
        result = await retrieve(session, "zzqqxx nonexistent gibberish query 999")

    assert result["empty"] is True
    assert result["results"] == []
    assert result["by_type"] == {}
    assert result["counts"]["returned"] == 0
    await engine.dispose()


def test_determinism_same_query_returns_stable_retrieval_set(tmp_path, monkeypatch):
    asyncio.run(_determinism_scenario(tmp_path, monkeypatch))


async def _determinism_scenario(tmp_path, monkeypatch):
    monkeypatch.setattr(retrieval_mod, "semantic_search", lambda *a, **k: [])
    engine, session_maker = await _make_db(tmp_path, "determinism.db")

    async with session_maker() as session:
        first = await retrieve(session, "telecommunications Acme TELUS")
        second = await retrieve(session, "telecommunications Acme TELUS")

    ids_first = [h["id"] for h in first["results"]]
    ids_second = [h["id"] for h in second["results"]]
    assert ids_first == ids_second
    assert ids_first, "expected at least one hit for the determinism check to be meaningful"
    await engine.dispose()


def test_no_ai_provider_imports_in_retrieval_module():
    # Constraint check: this layer must never import or call an AI provider.
    # `make_plan` (search.planner) can call Claude; only the deterministic
    # `fallback_plan` is allowed to be bound as a name in this module.
    import inspect

    source = inspect.getsource(retrieval_mod)
    assert "import anthropic" not in source
    assert not hasattr(retrieval_mod, "make_plan")
    assert hasattr(retrieval_mod, "fallback_plan")
    assert "from search.planner import fallback_plan" in source


def test_retrieve_route_persists_set_and_validate_citations_rejects_outside_id(tmp_path, monkeypatch):
    asyncio.run(_api_scenario(tmp_path, monkeypatch))


async def _api_scenario(tmp_path, monkeypatch):
    # Hermetic like the sibling tests: don't let a real on-disk index (built from
    # the production DB, not this seeded one) leak foreign records into results.
    monkeypatch.setattr(retrieval_mod, "semantic_search", lambda *a, **k: [])
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'api_retrieval.db'}", future=True)
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _seed(session_maker)

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with session_maker() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/api/retrieve", params={"q": "Industry and Technology innovation act"})
            assert res.status_code == 200
            body = res.json()
            assert body["retrieval_set_id"]
            assert body["empty"] is False
            assert body["results"], "expected at least one retrieved record"
            assert "answer" not in body  # no AI synthesis in this layer

            real = body["results"][0]
            validate = await client.post("/api/retrieve/validate-citations", json={
                "retrieval_set_id": body["retrieval_set_id"],
                "cited": [[real["table"], real["pk"]], ["bills", 999999]],
            })
            assert validate.status_code == 200
            validate_body = validate.json()
            assert validate_body["all_valid"] is False
            assert {"table": real["table"], "pk": real["pk"]} in validate_body["valid"]
            assert {"table": "bills", "pk": 999999} in validate_body["invalid"]

            # Every returned record must resolve to a real backend page.
            for hit in body["results"]:
                resolved = await _resolve_internal_page(client, hit)
                assert resolved, f"broken internal link for {hit['table']}:{hit['pk']} -> {hit['internal_url']}"
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


async def _resolve_internal_page(client: httpx.AsyncClient, hit: dict) -> bool:
    table, pk = hit["table"], hit["pk"]
    if table == "politicians":
        res = await client.get(f"/api/politicians/{pk}")
    elif table == "sectors":
        res = await client.get(f"/api/sectors/{pk}/overview")
    elif table == "entities":
        res = await client.get(f"/api/entities/{pk}")
    elif table == "committees":
        res = await client.get(f"/api/parliament/committee/{pk}")
    elif table == "reports":
        res = await client.get(f"/api/reports/{pk}")
    elif table == "organizations":
        kind, _, name = str(pk).partition(":")
        res = await client.get(f"/api/organizations/{kind}/{name}")
    else:
        res = await client.get(f"/api/records/{table}/{pk}")
    return res.status_code == 200


def test_retrieve_route_is_published_with_response_model():
    paths = {route.path: route for route in app.routes if isinstance(route, APIRoute)}
    assert "/api/retrieve" in paths
    assert paths["/api/retrieve"].response_model is not None
    assert "/api/retrieve/validate-citations" in paths
