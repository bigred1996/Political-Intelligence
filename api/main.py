"""Nessus Intelligence — FastAPI entry point.

Serves the JSON API and the lightweight analyst dashboard (frontend/index.html)
so the build is testable end-to-end without a separate frontend server yet.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .database import init_db
from .routes import (
    appointments, briefing, contracts, data_health, entities, grants, health, interpretation, lobbying,
    ocl_registrations, organizations, graph, overview, parliament, politicians, records, regulations,
    reports, requests, retrieval, scheduler, search, sectors, sources,
)
from .schemas import HealthResponse
from .scheduler import start_scheduler, stop_scheduler

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="Nessus Intelligence", version="0.1.0", lifespan=lifespan)

app.include_router(lobbying.router)
app.include_router(contracts.router)
app.include_router(grants.router)
app.include_router(appointments.router)
app.include_router(regulations.router)
app.include_router(ocl_registrations.router)
app.include_router(sources.router)
app.include_router(search.router)
app.include_router(retrieval.router)
app.include_router(interpretation.router)
app.include_router(parliament.router)
app.include_router(reports.router)
app.include_router(reports.view)
app.include_router(requests.router)
app.include_router(scheduler.router)
app.include_router(sectors.router)
app.include_router(briefing.router)
app.include_router(entities.router)
app.include_router(organizations.router)
app.include_router(overview.router)
app.include_router(records.router)
app.include_router(politicians.router)
app.include_router(graph.router)
app.include_router(health.router)
app.include_router(data_health.router)


@app.get("/api/health", response_model=HealthResponse)
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "nessus", "version": "0.1.0"}


@app.get("/")
async def root() -> RedirectResponse:
    """The premium client app (polaris/web) is the product front door; the backend
    root just points at the internal ops console."""
    return RedirectResponse(url="/internal")


@app.get("/internal")
async def internal_console() -> FileResponse:
    """Internal data-ops console (ingests, scheduler, raw tables).

    The premium client app (polaris/web) is the front door; this is the analyst/ops
    surface, intentionally unlinked from it.
    """
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
