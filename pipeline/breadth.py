"""Breadth data-source fetchers → unified SourceRecord rows.

Each function here pulls one government source and returns a list of dicts shaped
for the `source_records` table (see api/models/source_record.py). They share two
helpers:

  * `ckan_dataset_csv()` — resolve a CKAN dataset's flagship CSV and stream it.
  * `ckan_org_catalog()` — ingest dataset-level metadata for an organization as
    records (used where there is no single clean row-level CSV).

Endpoints were each verified live against open.canada.ca / source APIs before
being wired here. Row-bearing sources (NPRI, CER, IAAC) pull real records;
catalog sources (geospatial, parts of Transport) pull dataset metadata, which is
still fully searchable and entity-linkable.
"""
from __future__ import annotations

import csv
import io
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate
from typing import Any, AsyncIterator

import httpx
import structlog

from pipeline.entity_resolver import normalize
from pipeline.ingest import _to_float  # reuse the money parser

log = structlog.get_logger()

CKAN_API = "https://open.canada.ca/data/api/3/action"
_UA = "Mozilla/5.0 (compatible; Polaris/1.0; +https://polaris.intelligence)"
_HEADERS = {"User-Agent": _UA, "Accept": "*/*"}


# ── Shared CKAN helpers ───────────────────────────────────────────────────────

async def _ckan_package(dataset_id: str) -> dict[str, Any] | None:
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=_HEADERS) as c:
        r = await c.get(f"{CKAN_API}/package_show", params={"id": dataset_id})
        if r.status_code != 200:
            return None
        return r.json()["result"]


def _best_csv_url(resources: list[dict], hint: str | None) -> str | None:
    """Pick the most relevant CSV resource from a CKAN dataset."""
    csvs = [r for r in resources if (r.get("format") or "").upper() == "CSV" and r.get("url")]
    if not csvs:
        return None
    if hint:
        h = hint.lower()
        for r in csvs:
            if h in (r.get("name") or "").lower() or h in (r.get("url") or "").lower():
                return r["url"]
    return csvs[0]["url"]


async def _stream_csv(url: str, max_rows: int = 0) -> AsyncIterator[dict[str, str]]:
    """Stream a remote CSV row-by-row as dicts. max_rows=0 → no cap.

    Memory stays flat; tolerates latin-1/utf-8 government encodings.
    """
    header: list[str] | None = None
    buf = ""
    rows = 0
    first = True
    async with httpx.AsyncClient(timeout=300, follow_redirects=True, headers=_HEADERS) as c:
        async with c.stream("GET", url) as resp:
            resp.raise_for_status()
            async for chunk in resp.aiter_bytes():
                if first:
                    first = False
                    head = chunk[:64].lstrip()
                    # Government "CSV" links sometimes serve an HTML catalogue
                    # page (200 OK) or a zipped/XLSX payload. Bail so the caller
                    # can fall back instead of parsing garbage.
                    if head[:1] == b"<" or head[:2] == b"PK":
                        log.warning("csv_not_tabular", url=url[:120],
                                    ct=resp.headers.get("content-type"))
                        return
                buf += chunk.decode("latin-1", errors="replace")
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    line = line.rstrip("\r")
                    if not line.strip():
                        continue
                    try:
                        vals = next(csv.reader([line]))
                    except Exception:
                        continue
                    if header is None:
                        header = [h.strip().lstrip("﻿") for h in vals]
                        continue
                    if len(vals) != len(header):
                        continue
                    yield dict(zip(header, vals))
                    rows += 1
                    if max_rows and rows >= max_rows:
                        return


async def ckan_org_catalog(query: str, source: str, max_datasets: int = 200) -> list[dict[str, Any]]:
    """Ingest dataset-level metadata for an org/topic as SourceRecords.

    Used for breadth sources where the value is "what data exists and who owns
    it" rather than a single row-level table (geospatial catalogues, Transport
    Canada's many small datasets).
    """
    out: list[dict[str, Any]] = []
    start = 0
    page = 100
    async with httpx.AsyncClient(timeout=45, follow_redirects=True, headers=_HEADERS) as c:
        while len(out) < max_datasets:
            r = await c.get(f"{CKAN_API}/package_search",
                            params={"q": query, "rows": page, "start": start})
            r.raise_for_status()
            results = r.json()["result"]["results"]
            if not results:
                break
            for d in results:
                org = (d.get("organization") or {}).get("title", "")
                notes = (d.get("notes") or "").strip()
                title = (d.get("title") or "").strip()
                if not title:
                    continue
                formats = sorted({(res.get("format") or "").upper()
                                  for res in d.get("resources", []) if res.get("format")})
                out.append({
                    "source": source,
                    "record_type": "dataset",
                    "external_id": d.get("id"),
                    "entity_name": org or None,
                    "canonical_name": normalize(org) if org else None,
                    "title": title[:1024],
                    "summary": notes[:4000] or None,
                    "full_text": f"{title}\n{notes}"[:6000],
                    "event_date": (d.get("metadata_modified") or "")[:10] or None,
                    "amount": None,
                    "province": None,
                    "url": f"https://open.canada.ca/data/dataset/{d.get('id')}",
                    "raw": {"org": org, "formats": formats, "num_resources": len(d.get("resources", []))},
                })
                if len(out) >= max_datasets:
                    break
            start += page
    log.info("ckan_catalog_parsed", source=source, count=len(out))
    return out


# ── 1. Statistics Canada — WDS cube catalogue ────────────────────────────────
STATCAN_CUBES = "https://www150.statcan.gc.ca/t1/wds/rest/getAllCubesListLite"


async def fetch_statcan_records(max_rows: int = 0) -> list[dict[str, Any]]:
    """StatCan Web Data Service — full catalogue of data cubes (tables).

    Each cube is an economic/social dataset (GDP, CPI, trade, employment by
    sector …). Ingesting the catalogue gives the platform a searchable map of
    every StatCan series it can pull figures from for sector context.
    """
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
        subjects = ", ".join(str(s) for s in (cube.get("subjectCode") or []))
        out.append({
            "source": "statcan",
            "record_type": "data_cube",
            "external_id": pid or None,
            "entity_name": "Statistics Canada",
            "canonical_name": "statistics canada",
            "title": title[:1024],
            "summary": f"StatCan table {pid}. Coverage {cube.get('cubeStartDate')} → "
                       f"{cube.get('cubeEndDate')}. Subjects: {subjects}".strip(),
            "full_text": title,
            "event_date": (cube.get("releaseTime") or "")[:10] or None,
            "amount": None,
            "province": None,
            "url": f"https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid={pid}" if pid else None,
            "raw": {"frequency": cube.get("frequencyCode"), "subjects": cube.get("subjectCode")},
        })
        if max_rows and len(out) >= max_rows:
            break
    log.info("statcan_parsed", count=len(out))
    return out


# ── 2. Impact Assessment Agency (IAAC) ───────────────────────────────────────
IAAC_DATASET = "5f676365-2a0f-4195-b174-40b0b5156579"  # Screenings & class-screenings


async def fetch_iaac_records(max_rows: int = 0) -> list[dict[str, Any]]:
    """Federal impact-assessment project records (project-level political risk).

    Pulls the IAAC screenings CSV; falls back to the IAAC org catalogue if the
    flagship resource has moved.
    """
    pkg = await _ckan_package(IAAC_DATASET)
    url = _best_csv_url(pkg.get("resources", []), hint="dataset") if pkg else None
    if not url:
        log.warning("iaac_csv_unresolved_fallback_catalog")
        return await ckan_org_catalog("impact assessment agency of canada", "iaac", max_datasets=200)

    out: list[dict[str, Any]] = []
    async for row in _stream_csv(url, max_rows):
        name = (row.get("Proponent") or row.get("Proponent Name") or
                row.get("Project Name") or "").strip()
        title = (row.get("Project Name") or row.get("Title") or name or "").strip()
        if not title:
            continue
        out.append({
            "source": "iaac",
            "record_type": "impact_assessment",
            "external_id": (row.get("Reference Number") or row.get("Registry Reference Number") or "").strip() or None,
            "entity_name": name or None,
            "canonical_name": normalize(name) if name else None,
            "title": title[:1024],
            "summary": (row.get("Project Description") or row.get("Status") or "")[:4000] or None,
            "full_text": " ".join(str(v) for v in row.values())[:6000],
            "event_date": (row.get("Posted Date") or row.get("Decision Date") or "").strip()[:10] or None,
            "amount": None,
            "province": (row.get("Province") or row.get("Location") or "").strip() or None,
            "url": (row.get("Link") or row.get("URL") or "").strip() or None,
            "raw": row,
        })
    if not out:
        # CSV headers shifted or resource is non-tabular — fall back to the
        # IAAC dataset catalogue so the source is never empty.
        log.warning("iaac_rows_empty_fallback_catalog")
        return await ckan_org_catalog("impact assessment agency of canada", "iaac", max_datasets=200)
    log.info("iaac_parsed", count=len(out))
    return out


# ── 3. Canada Energy Regulator (CER) ─────────────────────────────────────────
CER_INCIDENTS_CSV = "https://www.cer-rec.gc.ca/open/incident/pipeline-incidents-data.csv"


async def fetch_cer_records(max_rows: int = 0) -> list[dict[str, Any]]:
    """CER-regulated pipeline incidents — company, substance, location, what happened."""
    out: list[dict[str, Any]] = []
    async for row in _stream_csv(CER_INCIDENTS_CSV, max_rows):
        company = (row.get("Company") or row.get("Company Name") or "").strip()
        inc_type = (row.get("Incident Types") or row.get("Incident Type") or "").strip()
        substance = (row.get("Substance") or "").strip()
        if not company:
            continue
        title = f"{company} — {inc_type or 'pipeline incident'}".strip(" —")
        out.append({
            "source": "cer",
            "record_type": "pipeline_incident",
            "external_id": (row.get("Incident Number") or row.get("IncidentNumber") or "").strip() or None,
            "entity_name": company,
            "canonical_name": normalize(company),
            "title": title[:1024],
            "summary": (row.get("Brief Description") or
                        f"{inc_type}. Substance: {substance}. Status: {row.get('Status','')}")[:4000] or None,
            "full_text": " ".join(str(v) for v in row.values())[:6000],
            "event_date": (row.get("Reported Date") or row.get("Occurrence Date") or "").strip()[:10] or None,
            "amount": _to_float(row.get("Approximate Volume Released (m3)")),
            "province": (row.get("Province") or "").strip() or None,
            "url": "https://www.cer-rec.gc.ca/en/safety-environment/industry-performance/interactive-pipeline/",
            "raw": row,
        })
    log.info("cer_parsed", count=len(out))
    return out


# ── 4. National Pollutant Release Inventory (NPRI) ───────────────────────────
NPRI_DATASET = "1fb7d8d4-7713-4ec6-b957-4a882a84fed3"  # Single-year-by-facility tables


def _bil(row: dict[str, str], *needles: str) -> str:
    """Tolerant lookup over bilingual NPRI headers (e.g. 'Entreprise / Company Name')."""
    for key, val in row.items():
        kl = key.lower()
        if all(n.lower() in kl for n in needles):
            return (val or "").strip()
    return ""


async def fetch_npri_records(max_rows: int = 200000) -> list[dict[str, Any]]:
    """NPRI facility-level pollutant releases — who releases what, where, how much.

    NPRI publishes per-year facility files; some "CSV" resources are actually
    HTML catalogue pages or zipped XLSX, so we try CSV resources newest-first and
    keep the first that yields real rows. Falls back to the NPRI catalogue if none
    parse. Capped by default (a representative slice pending a full background run).
    """
    pkg = await _ckan_package(NPRI_DATASET)
    resources = (pkg or {}).get("resources", [])
    csv_urls = [r["url"] for r in resources
                if (r.get("format") or "").upper() == "CSV" and r.get("url")]
    # Prefer recent years (names contain the year).
    csv_urls.sort(key=lambda u: u, reverse=True)

    out: list[dict[str, Any]] = []
    for url in csv_urls:
        async for row in _stream_csv(url, max_rows):
            company = _bil(row, "company") or _bil(row, "entreprise")
            facility = _bil(row, "facility", "name") or _bil(row, "installation")
            substance = _bil(row, "substance") or _bil(row, "nom", "substance")
            if not (company or facility):
                continue
            name = company or facility
            year = _bil(row, "year") or _bil(row, "année")
            qty = _bil(row, "quantity") or _bil(row, "quantité")
            units = _bil(row, "units") or _bil(row, "unité")
            out.append({
                "source": "npri",
                "record_type": "pollutant_release",
                "external_id": None,
                "entity_name": name,
                "canonical_name": normalize(name),
                "title": f"{name} — {substance or 'release'} ({year})"[:1024],
                "summary": f"{facility}: released {qty} {units} of {substance}"[:4000] or None,
                "full_text": None,  # structured/numeric — served by SQL, not embeddings
                "event_date": f"{year[:4]}-01-01" if year[:4].isdigit() else None,
                "amount": _to_float(qty),
                "province": _bil(row, "province"),
                "url": "https://pollution-waste.canada.ca/national-release-inventory/",
                "raw": {"substance": substance, "facility": facility, "year": year, "units": units},
            })
        if out:
            break  # first resource that produced rows wins
    if not out:
        log.warning("npri_rows_empty_fallback_catalog")
        return await ckan_org_catalog("national pollutant release inventory", "npri", max_datasets=100)
    log.info("npri_parsed", count=len(out))
    return out


# ── 5. Transport Canada ──────────────────────────────────────────────────────
async def fetch_transport_records(max_rows: int = 0) -> list[dict[str, Any]]:
    """Transport Canada open data + Transportation Safety Board investigations.

    Transport Canada publishes many small datasets rather than one master table,
    so we ingest the org catalogue (searchable, entity-linkable).
    """
    recs = await ckan_org_catalog("transport canada", "transport", max_datasets=300)
    if max_rows:
        recs = recs[:max_rows]
    return recs


# ── 6. NRCan / GeoGratis federal geospatial ──────────────────────────────────
async def fetch_geospatial_records(max_rows: int = 0) -> list[dict[str, Any]]:
    """Federal geospatial data catalogue (NRCan / GeoGratis / CGDI)."""
    recs = await ckan_org_catalog("natural resources canada geospatial", "geospatial", max_datasets=300)
    if max_rows:
        recs = recs[:max_rows]
    return recs


# ── 7. Government of Canada News / Publications ───────────────────────────────
# The IO news API has no page/offset param, but `pick` (page size) scales freely
# — pick=20000 returns 20k entries. So depth is controlled purely by `pick`:
# a small pick for the daily incremental run, a large one for a history backfill.
GC_NEWS_ATOM = (
    "https://api.io.canada.ca/io-server/gc/news/en/v2"
    "?type=newsreleases&sort=publishedDate&orderBy=desc&format=atom&pick={pick}"
)
_GC_NEWS_DAILY_PICK = 500   # plenty to catch a day's releases across all departments
_ATOM_NS = "{http://www.w3.org/2005/Atom}"


def _atom_date(raw: str) -> str | None:
    if not raw:
        return None
    parsed = parsedate(raw)
    if parsed:
        return f"{parsed[0]:04d}-{parsed[1]:02d}-{parsed[2]:02d}"
    return raw[:10]


async def fetch_gc_news_records(max_rows: int = 0) -> list[dict[str, Any]]:
    """Government of Canada news releases (all departments) via the IO news API.

    `max_rows` drives both the API page size and the output cap: pass a large
    value (e.g. 20000) for a one-time history backfill, or leave it 0 for the
    daily incremental run (small page; the upsert keeps only new ids).
    """
    pick = max_rows if max_rows else _GC_NEWS_DAILY_PICK
    async with httpx.AsyncClient(timeout=120, follow_redirects=True, headers=_HEADERS) as c:
        r = await c.get(GC_NEWS_ATOM.format(pick=pick))
        r.raise_for_status()
        root = ET.fromstring(r.text)
    out: list[dict[str, Any]] = []
    for entry in root.findall(f"{_ATOM_NS}entry"):
        def _t(tag: str) -> str:
            el = entry.find(f"{_ATOM_NS}{tag}")
            return (el.text or "").strip() if el is not None and el.text else ""

        title = _t("title")
        if not title:
            continue
        summary = re.sub(r"<[^>]+>", " ", _t("summary")).strip()
        link_el = entry.find(f"{_ATOM_NS}link")
        url = link_el.get("href") if link_el is not None else None
        author = ""
        a = entry.find(f"{_ATOM_NS}author")
        if a is not None:
            n = a.find(f"{_ATOM_NS}name")
            author = (n.text or "").strip() if n is not None and n.text else ""
        out.append({
            "source": "gc_news",
            "record_type": "news_release",
            "external_id": _t("id") or url,
            "entity_name": author or None,
            "canonical_name": normalize(author) if author else None,
            "title": title[:1024],
            "summary": summary[:4000] or None,
            "full_text": f"{title}\n{summary}"[:6000],
            "event_date": _atom_date(_t("published") or _t("updated")),
            "amount": None,
            "province": None,
            "url": url,
            "raw": {"department": author},
        })
        if max_rows and len(out) >= max_rows:
            break
    log.info("gc_news_parsed", count=len(out))
    return out
