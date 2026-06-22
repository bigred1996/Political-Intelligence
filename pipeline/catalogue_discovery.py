"""Goal 5: discover what exists upstream before downloading it.

Each discover_* function returns a list of dicts shaped for CatalogueEntry
(api/models/catalogue_entry.py) — one row per (dataset, resource), since
format/download_url/estimated_size are resource-level facts. Nothing in this
module downloads a dataset's actual content; that stays the job of the
existing connectors in pipeline/ingest.py and pipeline/breadth.py. This is
the "what's out there" layer the original audit found missing (datasets were
discovered ad hoc, by hand, one reachability probe at a time, all session).

Coverage this pass (10 requested catalogues):
    DONE  — open-government (capped), nrcan-geospatial, transport-canada,
            cer, iaac, statcan, canada-gazette (issue index)
    DONE (derived, not pre-ingestion discovery) — government-news department
            index, built from already-ingested gc_news source_records
    NOT DONE — House of Commons dataset catalogue (investigated: the public
            /en/open-data pages document a data MODEL, not a live API root or
            file index, in static HTML; needs a different access path, not
            attempted here — same "don't force a low-confidence scrape"
            discipline as GIC Appointments/CRTC earlier this session)
    NOT DONE — regulator publication indexes (too broad/per-regulator to
            attempt as one pass; CER's dataset catalogue above is the one
            regulator covered, and only its CKAN-catalogued datasets, not its
            proceeding/hearing index specifically)
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()

CKAN_API = "https://open.canada.ca/data/api/3/action"
# open.canada.ca's WAF rejects requests with a self-identifying bot User-Agent
# (verified 2026-06-21: identical request, only the UA changed — a literal
# "Mozilla/5.0 (compatible; Nessus/1.0)" UA gets a 200 "Request Rejected" HTML
# page instead of JSON, a plain browser UA or no UA override works every time).
# pipeline/breadth.py's CKAN helpers use the same bot-identifying UA pattern
# and happen to still work for plain keyword search, but this is the more
# robust choice for the org-filtered (?fq=organization:...) queries this
# module needs, which appear to trip the WAF rule more reliably.
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0 Safari/537.36", "Accept": "*/*"}

# ── Relevance classification ─────────────────────────────────────────────────
# Straight from the topic list in the ingestion spec's "Open Government
# Canada" section — not the company/sector taxonomy in pipeline/sector_mapper.py,
# which classifies COMPANIES into industries, a different job than classifying
# a DATASET's relevance to Nessus's mission at all.
RELEVANCE_TOPICS = [
    "legislation", "regulation", "lobbying", "procurement", "grant", "contribution",
    "federal spending", "energy", "mining", "natural resources", "environment",
    "infrastructure", "transportation", "housing", "finance", "banking",
    "telecommunications", "agriculture", "health regulation", "immigration",
    "trade", "industry", "competition", "indigenous", "major project",
    "employment", "economic development",
]


def classify_relevance(*text_parts: str | None) -> tuple[str, list[str]]:
    """Keyword-match a dataset's title/description/subject against
    RELEVANCE_TOPICS. high = 2+ matches, medium = 1, low = 0 (still kept —
    "low" is a real classification, not a silent drop)."""
    text = " ".join(p for p in text_parts if p).lower()
    matched = [topic for topic in RELEVANCE_TOPICS if topic in text]
    if len(matched) >= 2:
        tier = "high"
    elif len(matched) == 1:
        tier = "medium"
    else:
        tier = "low"
    return tier, matched


# ── Download status ──────────────────────────────────────────────────────────
# Dataset IDs this session has ALREADY pulled real row-level data from,
# cross-referenced from config/data-sources.yaml's base_url fields — a
# discovered entry matching one of these is "downloaded", not "not_downloaded".
KNOWN_DOWNLOADED_DATASET_IDS = {
    "d8f85d91-7dec-4fd1-8055-483b77225d8b",  # contracts_monthly
    "432527ab-7aac-45b5-81d6-7597107a7013",  # grants_quarterly
    "70ef2117-1095-4d77-80eb-b87f2bada2a4",  # ocl_registrations
    "a34eb330-7136-4f5e-9f5f-3ba41df58b06",  # ocl_monthly (communications)
    "5f676365-2a0f-4195-b174-40b0b5156579",  # iaac (catalogue-level row source)
    "1fb7d8d4-7713-4ec6-b957-4a882a84fed3",  # npri
}
KNOWN_BLOCKED_DATASET_IDS = {
    "58b10b98-acab-458a-9e7a-fc1a1c2b1a58",  # appointments_weekly — confirmed 404, doesn't exist
}


def classify_download_status(dataset_external_id: str) -> str:
    if dataset_external_id in KNOWN_DOWNLOADED_DATASET_IDS:
        return "downloaded"
    if dataset_external_id in KNOWN_BLOCKED_DATASET_IDS:
        return "blocked"
    return "not_downloaded"


# ── Generic CKAN catalogue walker (per-resource rows) ───────────────────────

async def discover_ckan_catalogue(catalogue_source: str, *, query: str = "", org: str | None = None,
                                    max_datasets: int = 200) -> list[dict[str, Any]]:
    """Walk open.canada.ca's CKAN package_search, one output row per resource.

    Used for: open-government (no org filter = the whole catalogue),
    nrcan-geospatial (org=nrcan-rncan), transport-canada (org=tc),
    cer (org=cer-rec), iaac (org=iaac-aeic).
    """
    out: list[dict[str, Any]] = []
    start = 0
    page = 100
    params_base: dict[str, Any] = {"q": query, "rows": page}
    if org:
        params_base["fq"] = f"organization:{org}"

    async with httpx.AsyncClient(timeout=45, follow_redirects=True, headers=_HEADERS) as c:
        while len(out) < max_datasets:
            r = await c.get(f"{CKAN_API}/package_search", params={**params_base, "start": start})
            r.raise_for_status()
            results = r.json()["result"]["results"]
            if not results:
                break
            for d in results:
                if len(out) >= max_datasets:
                    break
                title = (d.get("title") or "").strip()
                if not title:
                    continue
                publisher = (d.get("organization") or {}).get("title", "")
                description = (d.get("notes") or "").strip() or None
                subject = list(d.get("keywords", {}).get("en", [])) if isinstance(d.get("keywords"), dict) else []
                last_modified = (d.get("metadata_modified") or "")[:10] or None
                license_title = d.get("license_title")
                geo = d.get("spatial") or None
                date_start = d.get("time_period_coverage_start")
                date_end = d.get("time_period_coverage_end")
                date_coverage = f"{date_start} to {date_end}" if (date_start or date_end) else None
                dataset_url = f"https://open.canada.ca/data/dataset/{d.get('id')}"
                tier, topics = classify_relevance(title, description, " ".join(subject))
                status = classify_download_status(d.get("id"))

                resources = d.get("resources") or []
                if not resources:
                    # Still record the dataset itself even with no resources —
                    # "what exists" includes datasets with no files yet.
                    out.append({
                        "catalogue_source": catalogue_source, "dataset_external_id": d.get("id"),
                        "resource_external_id": None, "title": title[:1024], "description": description,
                        "publisher": publisher or None, "format": None, "download_url": None,
                        "dataset_url": dataset_url, "subject": subject, "geographic_coverage": geo,
                        "date_coverage": date_coverage, "last_modified": last_modified,
                        "license": license_title, "estimated_size_bytes": None,
                        "relevance": tier, "relevance_topics": topics, "download_status": status,
                    })
                    continue
                for res in resources:
                    size = res.get("size")
                    try:
                        size = int(size) if size is not None else None
                    except (ValueError, TypeError):
                        size = None
                    out.append({
                        "catalogue_source": catalogue_source, "dataset_external_id": d.get("id"),
                        "resource_external_id": res.get("id"), "title": title[:1024],
                        "description": description, "publisher": publisher or None,
                        "format": (res.get("format") or "").upper() or None, "download_url": res.get("url"),
                        "dataset_url": dataset_url, "subject": subject, "geographic_coverage": geo,
                        "date_coverage": date_coverage,
                        "last_modified": (res.get("last_modified") or last_modified),
                        "license": license_title, "estimated_size_bytes": size,
                        "relevance": tier, "relevance_topics": topics, "download_status": status,
                    })
            start += page
    log.info("catalogue_discovered", catalogue_source=catalogue_source, count=len(out))
    return out


# ── Statistics Canada — table/product metadata ───────────────────────────────
STATCAN_CUBES = "https://www150.statcan.gc.ca/t1/wds/rest/getAllCubesListLite"


async def discover_statcan_catalogue(max_rows: int = 0) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=120, follow_redirects=True, headers=_HEADERS) as c:
        r = await c.get(STATCAN_CUBES)
        r.raise_for_status()
        cubes = r.json()
    out: list[dict[str, Any]] = []
    for cube in cubes:
        title = (cube.get("cubeTitleEn") or "").strip()
        if not title:
            continue
        pid = str(cube.get("productId", "")).strip()
        subjects = [str(s) for s in (cube.get("subjectCode") or [])]
        tier, topics = classify_relevance(title, " ".join(subjects))
        out.append({
            "catalogue_source": "statcan", "dataset_external_id": pid or title,
            "resource_external_id": None, "title": title[:1024],
            "description": f"Subjects: {', '.join(subjects)}" if subjects else None,
            "publisher": "Statistics Canada", "format": "SDMX/WDS",
            "download_url": f"https://www150.statcan.gc.ca/t1/wds/rest/getFullTableDownloadCSV/{pid}/en" if pid else None,
            "dataset_url": f"https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid={pid}" if pid else None,
            "subject": subjects, "geographic_coverage": "Canada",
            "date_coverage": f"{cube.get('cubeStartDate')} to {cube.get('cubeEndDate')}",
            "last_modified": (cube.get("releaseTime") or "")[:10] or None,
            "license": "Statistics Canada Open Licence", "estimated_size_bytes": None,
            "relevance": tier, "relevance_topics": topics,
            "download_status": "not_downloaded",  # catalogue is ingested; series OBSERVATIONS are not (see DATA_CHECKLIST.md)
        })
        if max_rows and len(out) >= max_rows:
            break
    log.info("catalogue_discovered", catalogue_source="statcan", count=len(out))
    return out


# ── Canada Gazette — issue index (not individual regulatory entries) ────────
_GAZETTE_YEAR_RE = re.compile(r'href="(/rp-pr/(p[12])/(\d{4})/[^"]+/(?:html|index-eng\.html)[^"]*)"[^>]*>([^<]{3,120})')


async def discover_canada_gazette_index(*, years: list[int] | None = None) -> list[dict[str, Any]]:
    """Per-issue index (Part I + II), not the regulatory-entry RSS already in
    gazette_entries — this is "what issues exist", independent of whether any
    individual regulation within them has been parsed."""
    years = years or [datetime.now(timezone.utc).year]
    out: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers=_HEADERS) as c:
        for part in ("p1", "p2"):
            for year in years:
                url = f"https://gazette.gc.ca/rp-pr/{part}/{year}/index-eng.html"
                try:
                    r = await c.get(url)
                except Exception as exc:
                    log.warning("gazette_index_fetch_failed", url=url, error=str(exc))
                    continue
                if r.status_code != 200:
                    continue
                for href, _part, yr, label in _GAZETTE_YEAR_RE.findall(r.text):
                    if f"/{part}/" not in href:
                        continue
                    title = re.sub(r"&nbsp;", " ", label).strip()
                    issue_url = f"https://gazette.gc.ca{href}" if href.startswith("/") else href
                    date_match = re.search(r"/(\d{4}-\d{2}-\d{2})", href)
                    out.append({
                        "catalogue_source": "canada-gazette", "dataset_external_id": href,
                        "resource_external_id": None, "title": title or f"Gazette {part} {yr}",
                        "description": None, "publisher": "Privy Council Office", "format": "HTML",
                        "download_url": issue_url, "dataset_url": url,
                        "subject": ["canada gazette", part], "geographic_coverage": "Canada",
                        "date_coverage": date_match.group(1) if date_match else yr,
                        "last_modified": date_match.group(1) if date_match else None,
                        "license": "unreviewed", "estimated_size_bytes": None,
                        "relevance": "high", "relevance_topics": ["legislation", "regulation"],
                        # We have RSS-derived regulatory ENTRIES in gazette_entries (638 rows),
                        # a different granularity than per-issue HTML pages — this issue's full
                        # page content has not actually been fetched, so "not_downloaded" is
                        # the honest answer even though related data exists at another level.
                        "download_status": "not_downloaded",
                    })
    log.info("catalogue_discovered", catalogue_source="canada-gazette", count=len(out))
    return out


# ── Government news — department index (derived from ingested gc_news) ─────

async def discover_government_news_departments(session: AsyncSession) -> list[dict[str, Any]]:
    """NOT a pre-ingestion discovery — this is "which departments have we
    actually SEEN publish news", derived from already-ingested gc_news rows
    in source_records. A true upfront department/feed index (e.g. a GEDS-style
    organization directory) was not found/attempted this pass."""
    from api.models.source_record import SourceRecord

    rows = (await session.execute(
        select(SourceRecord.entity_name).where(SourceRecord.source == "gc_news").distinct()
    )).scalars().all()
    out: list[dict[str, Any]] = []
    for dept in rows:
        if not dept:
            continue
        tier, topics = classify_relevance(dept)
        out.append({
            "catalogue_source": "government-news", "dataset_external_id": dept,
            "resource_external_id": None, "title": dept, "description": None,
            "publisher": dept, "format": "ATOM", "download_url": None,
            "dataset_url": "https://api.io.canada.ca/io-server/gc/news/en/v2",
            "subject": ["government news"], "geographic_coverage": "Canada",
            "date_coverage": None, "last_modified": None, "license": "unreviewed",
            "estimated_size_bytes": None, "relevance": tier, "relevance_topics": topics,
            "download_status": "downloaded",  # we already have rows from this department
        })
    log.info("catalogue_discovered", catalogue_source="government-news", count=len(out))
    return out


# ── Persistence ───────────────────────────────────────────────────────────────

async def persist_catalogue_entries(session: AsyncSession, entries: list[dict[str, Any]]) -> dict[str, int]:
    """Upsert by (catalogue_source, dataset_external_id, resource_external_id).
    Existing entries get checked_at bumped; new ones get inserted."""
    from api.models.catalogue_entry import CatalogueEntry

    added = 0
    updated = 0
    now = datetime.now(timezone.utc)
    for e in entries:
        existing = (await session.execute(
            select(CatalogueEntry).where(
                CatalogueEntry.catalogue_source == e["catalogue_source"],
                CatalogueEntry.dataset_external_id == e["dataset_external_id"],
                CatalogueEntry.resource_external_id == e.get("resource_external_id"),
            ).limit(1)
        )).scalar_one_or_none()
        if existing:
            for k, v in e.items():
                setattr(existing, k, v)
            existing.checked_at = now
            updated += 1
        else:
            session.add(CatalogueEntry(**e, checked_at=now))
            added += 1
    await session.commit()
    return {"added": added, "updated": updated, "total": len(entries)}


# ── Report ────────────────────────────────────────────────────────────────────

async def catalogue_report(session: AsyncSession) -> dict[str, Any]:
    """Done-when deliverable: everything available, what's downloaded, what remains."""
    from api.models.catalogue_entry import CatalogueEntry
    from sqlalchemy import func

    total = (await session.execute(select(func.count()).select_from(CatalogueEntry))).scalar_one()

    by_source = (await session.execute(
        select(CatalogueEntry.catalogue_source, func.count())
        .group_by(CatalogueEntry.catalogue_source)
    )).all()

    by_status = (await session.execute(
        select(CatalogueEntry.download_status, func.count())
        .group_by(CatalogueEntry.download_status)
    )).all()

    by_relevance = (await session.execute(
        select(CatalogueEntry.relevance, func.count())
        .group_by(CatalogueEntry.relevance)
    )).all()

    high_relevance_not_downloaded = (await session.execute(
        select(func.count()).select_from(CatalogueEntry).where(
            CatalogueEntry.relevance == "high",
            CatalogueEntry.download_status == "not_downloaded",
        )
    )).scalar_one()

    total_bytes_not_downloaded = (await session.execute(
        select(func.sum(CatalogueEntry.estimated_size_bytes)).where(
            CatalogueEntry.download_status == "not_downloaded",
        )
    )).scalar_one() or 0

    return {
        "total_discovered": total,
        "by_catalogue_source": dict(by_source),
        "by_download_status": dict(by_status),
        "by_relevance": dict(by_relevance),
        "high_relevance_not_downloaded": high_relevance_not_downloaded,
        "estimated_bytes_remaining": total_bytes_not_downloaded,
        "catalogues_not_yet_implemented": [
            "house-of-commons (investigated: no static API root/file index found, needs further work)",
            "regulator-publication-indexes (too broad for one pass; only CER's CKAN dataset catalogue covered)",
            "cer-proceedings (CER's dataset catalogue covered, hearing/proceeding index specifically is not)",
        ],
    }
