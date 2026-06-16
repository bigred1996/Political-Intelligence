"""Pipeline orchestrator — request → evidence → scores → sections → stored report."""
from __future__ import annotations

from datetime import datetime, timezone

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.report import Report
from pipeline.entity_resolver import normalize
from pipeline.gather import gather_company_data
from pipeline.report_builder import build_sections
from pipeline.risk_scorer import score

log = structlog.get_logger()


async def generate_report(
    session: AsyncSession,
    company: str,
    sector: str | None = None,
    report_type: str = "deal_due_diligence",
    time_horizon: str = "current",
    request_id: str | None = None,
) -> Report:
    """Run the full pipeline and persist a draft report (status: analyst_review)."""
    report = Report(
        request_id=request_id, company_name=company, canonical_name=normalize(company),
        report_type=report_type, time_horizon=time_horizon, status="drafting",
    )
    session.add(report)
    await session.commit()

    log.info("pipeline_start", report_id=report.id, company=company, type=report_type)
    evidence = await gather_company_data(session, company, sector, report_type)
    scores = score(evidence)
    sections, generated_by = build_sections(evidence, scores)

    report.sections = sections
    report.risk_scores = scores
    report.evidence = {
        "lobbying_count": evidence["lobbying"]["count"],
        "lobbying_registrants": list(evidence["lobbying"]["registrants"])[:10],
        "lobbying_institutions": evidence["lobbying"]["institutions"][:10],
        "contracts_count": evidence["contracts"]["count"],
        "contracts_total_value": evidence["contracts"]["total_value"],
        "contracts_by_dept": evidence["contracts"]["by_department"][:5],
        "donations_count": evidence["donations"]["count"],
        "donations_total": evidence["donations"]["total_value"],
        "bills_count": evidence["bills"]["count"],
        "stakeholders_count": len(evidence["stakeholders"]),
    }
    report.generated_by = generated_by
    report.status = "analyst_review"
    await session.commit()
    log.info("pipeline_done", report_id=report.id, generated_by=generated_by, overall=scores["overall"])
    return report
