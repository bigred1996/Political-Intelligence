"""Shared API response contracts for Nessus backend surfaces.

These models cover the shapes reused across routes. They are intentionally small:
typed enough to catch drift, flexible enough for the MVP's heterogeneous sources.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class APIModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class EvidenceReference(APIModel):
    table: str = Field(min_length=1)
    pk: int | str
    id: int | str
    source: str = Field(min_length=1)
    title: str = Field(min_length=1)
    date: str | None = None
    url: str | None = None
    record_type: str = "record"
    sector: str | None = None
    confidence: str = "linked"


class IntelligenceEvidence(APIModel):
    source_name: str = Field(min_length=1)
    source_type: str = "record"
    title: str = Field(min_length=1)
    publication_date: str | None = None
    ingestion_date: str | None = None
    coverage_status: Literal["strong", "partial", "weak", "unknown"] = "unknown"
    confidence: Literal["low", "medium", "high"] = "medium"
    table: str = Field(min_length=1)
    pk: int | str
    internal_url: str
    external_url: str | None = None


class MovementWindow(APIModel):
    window_days: Literal[7, 30, 90]
    status: Literal["changed", "unchanged", "insufficient_history"]
    direction: Literal["increasing", "decreasing", "stable", "unclear"] = "unclear"
    current: int | float | None = None
    previous: int | float | None = None
    delta: int | float | None = None
    note: str


class IntelligenceFinding(APIModel):
    title: str = Field(min_length=1)
    concise_summary: str = ""
    why_it_matters: str = ""
    primary_sector: dict[str, Any] | None = None
    related_sectors: list[dict[str, str]] = Field(default_factory=list)
    signal_type: Literal[
        "diligence risk",
        "portfolio monitoring",
        "regulatory watch",
        "lobbying intensity",
        "political attention",
        "stakeholder signal",
        "policy opportunity",
        "sector momentum",
        "reputational risk",
    ] = "portfolio monitoring"
    risk_direction: Literal["increasing", "decreasing", "stable", "unclear"] = "unclear"
    risk_level: Literal["low", "moderate", "elevated", "high", "unknown", "insufficient evidence"] = "unknown"
    confidence: Literal["low", "medium", "high"] = "medium"
    source_coverage: Literal["strong", "partial", "weak", "unknown"] = "unknown"
    recency: Literal["fresh", "aging", "stale"] = "aging"
    interpretation_type: Literal["observed", "inferred", "speculative"] = "observed"
    evidence_references: list[IntelligenceEvidence] = Field(default_factory=list)
    related_records: list[EvidenceReference] = Field(default_factory=list)
    related_people: list[dict[str, Any]] = Field(default_factory=list)
    related_organizations: list[dict[str, Any]] = Field(default_factory=list)
    related_bills: list[dict[str, Any]] = Field(default_factory=list)
    related_committees: list[dict[str, Any]] = Field(default_factory=list)
    related_lobbying_activity: list[dict[str, Any]] = Field(default_factory=list)
    related_regulatory_events: list[dict[str, Any]] = Field(default_factory=list)
    suggested_questions: list[str] = Field(default_factory=list)
    created_date: str | None = None
    updated_date: str | None = None


class FindingMetric(APIModel):
    label: str
    value: int | float | str | None = None
    format: str | None = None


class GraphFinding(APIModel):
    title: str = Field(min_length=1)
    summary: str = ""
    severity: Literal["high", "elevated", "watch", "low"]
    type: str = Field(min_length=1)
    sector: dict[str, Any] | None = None
    related_sectors: list[dict[str, str]] = Field(default_factory=list)
    actors: list[dict[str, Any]] = Field(default_factory=list)
    references: list[EvidenceReference] = Field(default_factory=list)
    metrics: list[FindingMetric] = Field(default_factory=list)
    confidence: str = "deterministic"


class CacheInfo(APIModel):
    status: Literal["hit", "miss", "refresh"]
    ttl_seconds: int = Field(ge=1, le=3600)


class ReadinessResponse(APIModel):
    status: Literal["ok", "degraded", "down"]
    reasons: list[str] = Field(default_factory=list)
    checks: dict[str, Any] = Field(default_factory=dict)


class HealthResponse(APIModel):
    status: str
    service: str
    version: str


class SourceRun(APIModel):
    status: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    rows_added: int = 0
    rows_total: int = 0
    error: str | None = None


class SourceStatusItem(APIModel):
    id: str
    label: str
    table: str | None = None
    status: Literal["live", "partial", "empty", "planned"]
    freshness: Literal["current", "stale", "unknown", "missing", "planned"]
    confidence: Literal["high", "medium", "low", "planned"]
    rows: int = Field(ge=0)
    approximate: bool = False
    row_count_method: Literal["exact", "max_id", "planned", "unavailable"] = "exact"
    latest_record_date: str | None = None
    description: str
    known_gaps: list[str] = Field(default_factory=list)
    last_run: SourceRun | None = None


class BreadthSourceStatus(APIModel):
    source: str
    rows: int = Field(ge=0)
    min_date: str | None = None
    max_date: str | None = None
    status: Literal["live", "partial", "empty"]


class SourceStatusResponse(APIModel):
    sources: list[SourceStatusItem] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    breadth_sources: list[BreadthSourceStatus] = Field(default_factory=list)
    summary: dict[str, int] = Field(default_factory=dict)
    quality: dict[str, Any] = Field(default_factory=dict)
    cache: CacheInfo | None = None


class SourceDetailResponse(APIModel):
    id: str
    label: str
    type: str = "Source"
    status: str
    freshness: str
    confidence: str
    summary: str = ""
    why_it_matters: str = ""
    important_data: dict[str, Any] = Field(default_factory=dict)
    affected_sectors: list[dict[str, str]] = Field(default_factory=list)
    related_findings: list[GraphFinding] = Field(default_factory=list)
    connected_people: list[dict[str, Any]] = Field(default_factory=list)
    connected_organizations: list[dict[str, Any]] = Field(default_factory=list)
    connected_records: list[EvidenceReference] = Field(default_factory=list)
    groups: list[dict[str, Any]] = Field(default_factory=list)
    timeline: list[EvidenceReference] = Field(default_factory=list)
    known_gaps: list[str] = Field(default_factory=list)
    original_source_url: str | None = None


class SchedulerRun(APIModel):
    started_at: str | None = None
    finished_at: str | None = None
    status: str = "never"
    rows_added: int = 0
    rows_total: int = 0
    duration_s: float | None = None
    triggered_by: str | None = None
    error: str | None = None


class SchedulerJob(APIModel):
    id: str
    name: str
    cadence: str
    description: str
    typical_rows: int
    next_run: str | None = None
    last_run: SchedulerRun


class SchedulerStatusResponse(APIModel):
    scheduler_running: bool
    timezone: str
    jobs: list[SchedulerJob] = Field(default_factory=list)


class SchedulerHistoryRecord(APIModel):
    id: int
    job_id: str
    source_name: str
    started_at: str
    finished_at: str | None = None
    status: str
    rows_added: int = 0
    rows_total: int = 0
    duration_s: float | None = None
    triggered_by: str | None = None
    error: str | None = None


class SchedulerHistoryResponse(APIModel):
    count: int = Field(ge=0)
    records: list[SchedulerHistoryRecord] = Field(default_factory=list)


class SchedulerTriggerResponse(APIModel):
    status: str
    job_id: str
    name: str
    triggered_at: str
    note: str


class FindingsResponse(APIModel):
    count: int = Field(ge=0)
    findings: list[GraphFinding] = Field(default_factory=list)


class EvidenceGraphResponse(APIModel):
    sector: dict[str, Any] | None = None
    actor: dict[str, Any] | None = None
    record: dict[str, Any] | None = None
    industry: dict[str, Any] | None = None
    entity: dict[str, Any] | None = None
    findings: list[GraphFinding] = Field(default_factory=list)
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    relations: dict[str, Any] = Field(default_factory=dict)


class SearchResult(APIModel):
    source: str
    table: str | None = None
    pk: int | str | None = None
    id: int | str | None = None
    record_type: str | None = None
    title: str
    snippet: str | None = None
    entity: str | None = None
    date: str | None = None
    amount: float | None = None
    url: str | None = None
    match: str | None = None
    score: float | None = None
    reference: EvidenceReference | None = None


class SearchResponse(APIModel):
    query: str
    plan: dict[str, Any]
    counts: dict[str, Any]
    answer: str | None = None
    results: list[SearchResult] = Field(default_factory=list)


class SearchSourcesResponse(APIModel):
    sources: dict[str, int] = Field(default_factory=dict)
    total_records: int = Field(ge=0)
    approximate_sources: list[str] = Field(default_factory=list)
    row_count_methods: dict[str, str] = Field(default_factory=dict)


class SearchIndexStatusResponse(APIModel):
    built: bool
    documents: int = Field(ge=0)
    by_source: dict[str, int] = Field(default_factory=dict)


class SearchReindexResponse(APIModel):
    documents: int = Field(ge=0)
    by_source: dict[str, int] = Field(default_factory=dict)


class RetrievalHit(APIModel):
    id: str
    table: str
    pk: int | str
    record_type: str
    source: str
    title: str
    snippet: str = ""
    score: float = 0.0
    match: str = "deterministic"
    date: str | None = None
    amount: float | None = None
    internal_url: str | None = None
    external_url: str | None = None


class RetrievalResponse(APIModel):
    query: str
    plan: dict[str, Any]
    retrieval_set_id: str
    generated_at: str
    embedding_model: str
    empty: bool
    counts: dict[str, Any]
    results: list[RetrievalHit] = Field(default_factory=list)
    by_type: dict[str, list[RetrievalHit]] = Field(default_factory=dict)


class CitationRef(APIModel):
    table: str
    pk: int | str


class CitationValidationResponse(APIModel):
    retrieval_set_id: str
    all_valid: bool
    valid: list[CitationRef] = Field(default_factory=list)
    invalid: list[CitationRef] = Field(default_factory=list)


class ReportSummary(APIModel):
    id: str
    company_name: str
    report_type: str
    status: str
    generated_by: str
    overall: float | int | None = None
    created_at: str
    approved_at: str | None = None


class ReportSection(APIModel):
    key: str
    title: str
    html: str = ""


class ReportResponse(ReportSummary):
    risk_scores: dict[str, Any] = Field(default_factory=dict)
    evidence: dict[str, Any] = Field(default_factory=dict)
    graph_findings: list[GraphFinding] = Field(default_factory=list)
    source_references: list[EvidenceReference] = Field(default_factory=list)
    analyst_notes: str | None = None
    sections: list[ReportSection] = Field(default_factory=list)


class ReportGenerateResponse(ReportSummary):
    risk_scores: dict[str, Any] = Field(default_factory=dict)
    evidence: dict[str, Any] = Field(default_factory=dict)


class ReportListResponse(APIModel):
    count: int = Field(ge=0)
    reports: list[ReportSummary] = Field(default_factory=list)


class IngestStartedResponse(APIModel):
    status: str
    max_rows: int | str | None = None
    source: str | None = None
    message: str | None = None


class IngestCompletedResponse(APIModel):
    ingested: int = Field(ge=0)
    source: str
    distinct_vendors: int | None = None
    total_value: float | None = None


class StatsResponse(APIModel):
    total: int | None = Field(default=None, ge=0)
    total_records: int | None = Field(default=None, ge=0)
    count: int | None = Field(default=None, ge=0)


class SourceSearchResponse(APIModel):
    query: str | None = None
    company: str | None = None
    canonical_name: str | None = None
    count: int = Field(ge=0)
    total_value: float | None = None


class RecordListResponse(APIModel):
    count: int = Field(ge=0)
    records: list[dict[str, Any]] = Field(default_factory=list)


class ReportRequestSummary(APIModel):
    id: str
    company_name: str
    sector: str | None = None
    report_type: str
    time_horizon: str
    status: str
    created_at: str | None = None


class ReportRequestCreateResponse(APIModel):
    id: str
    status: str
    company_name: str


class ReportRequestListResponse(APIModel):
    count: int = Field(ge=0)
    requests: list[ReportRequestSummary] = Field(default_factory=list)


class EntityProfileResponse(APIModel):
    entity: dict[str, Any] | None = None
    sector: dict[str, Any] | None = None
    risk_scores: dict[str, Any] = Field(default_factory=dict)
    reports: list[ReportSummary] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)


class OrganizationProfileResponse(APIModel):
    kind: str
    name: str
    title: str
    summary: str = ""
    why_it_matters: str = ""
    metrics: list[dict[str, Any]] = Field(default_factory=list)
    affected_sectors: list[dict[str, str]] = Field(default_factory=list)
    related_findings: list[GraphFinding] = Field(default_factory=list)
    connected_people: list[dict[str, Any]] = Field(default_factory=list)
    connected_organizations: list[dict[str, Any]] = Field(default_factory=list)
    connected_records: list[EvidenceReference] = Field(default_factory=list)
    groups: list[dict[str, Any]] = Field(default_factory=list)
    timeline: list[EvidenceReference] = Field(default_factory=list)


class PoliticianListResponse(APIModel):
    count: int = Field(ge=0)
    politicians: list[dict[str, Any]] = Field(default_factory=list)
    parties: list[dict[str, Any]] = Field(default_factory=list)
    provinces: list[dict[str, Any]] = Field(default_factory=list)


class PoliticianProfileResponse(APIModel):
    slug: str
    name: str
    party: str | None = None
    riding: str | None = None
    province: str | None = None
    role: str | None = None
    photo_url: str | None = None
    photo_source: str | None = None
    photo_attribution: str | None = None
    photo_source_url: str | None = None
    summary: str
    industries: list[dict[str, str]] = Field(default_factory=list)
    bills: list[dict[str, Any]] = Field(default_factory=list)
    speeches: list[dict[str, Any]] = Field(default_factory=list)


class ParliamentListResponse(APIModel):
    count: int = Field(ge=0)


class CommitteeProfileResponse(APIModel):
    slug: str
    name: str
    chamber: str = "House of Commons"
    summary: str = ""
    why_it_matters: str = ""
    affected_sectors: list[dict[str, str]] = Field(default_factory=list)
    related_findings: list[GraphFinding] = Field(default_factory=list)
    connected_people: list[dict[str, Any]] = Field(default_factory=list)
    connected_organizations: list[dict[str, Any]] = Field(default_factory=list)
    connected_records: list[EvidenceReference] = Field(default_factory=list)
    groups: list[dict[str, Any]] = Field(default_factory=list)
    timeline: list[EvidenceReference] = Field(default_factory=list)


class ParliamentSeedResponse(APIModel):
    seeded: int = Field(ge=0)
    new: int = Field(ge=0)


class SpeechSearchResponse(APIModel):
    keyword: str
    canonical_name: str
    count: int = Field(ge=0)
    speeches: list[dict[str, Any]] = Field(default_factory=list)


class BriefingResponse(APIModel):
    sectors: list[dict[str, Any]] = Field(default_factory=list)
    streams: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)


class OverviewResponse(APIModel):
    regional_exposure: list[dict[str, Any]] = Field(default_factory=list)
    regulatory_movement: list[dict[str, Any]] = Field(default_factory=list)
    activity: list[dict[str, Any]] = Field(default_factory=list)
    signals: list[dict[str, Any]] = Field(default_factory=list)
    dashboard_signals: list[dict[str, Any]] = Field(default_factory=list)
    intelligence_findings: list[IntelligenceFinding] = Field(default_factory=list)
    sector_watchlist: list[dict[str, Any]] = Field(default_factory=list)
    sector_comparison: list[dict[str, Any]] = Field(default_factory=list)
    actor_movement: list[dict[str, Any]] = Field(default_factory=list)
    what_changed: dict[str, Any] = Field(default_factory=dict)
    ticker: dict[str, Any] = Field(default_factory=dict)
    cache: CacheInfo | None = None


class SectorListResponse(APIModel):
    count: int = Field(ge=0)
    sectors: list[dict[str, Any]] = Field(default_factory=list)
    provinces: list[dict[str, str]] = Field(default_factory=list)


class SectorOverviewResponse(APIModel):
    sector: dict[str, Any]
    evidence: dict[str, Any] = Field(default_factory=dict)
    risk_scores: dict[str, Any] = Field(default_factory=dict)
    risk_band: str | None = None
    movement: list[MovementWindow] = Field(default_factory=list)
    findings: list[IntelligenceFinding] = Field(default_factory=list)
    suggested_questions: list[str] = Field(default_factory=list)
    intelligence_brief: dict[str, Any] = Field(default_factory=dict)
    source_coverage: list[dict[str, Any]] = Field(default_factory=list)
    source_status: SourceStatusResponse | None = None
    graph: EvidenceGraphResponse | dict[str, Any] | None = None
    cache: CacheInfo | None = None


class RecordDetailResponse(APIModel):
    table: str
    pk: int | str
    record: dict[str, Any]
    entity: dict[str, Any] = Field(default_factory=dict)
    industry: dict[str, Any] | None = None
    impact: dict[str, Any] | None = None
    players: list[dict[str, Any]] = Field(default_factory=list)
    relations: dict[str, Any] = Field(default_factory=dict)
