"""Bulk Open Data ingestion (the real data path).

Architecture decision: Nessus does NOT scrape government HTML per request. It
ingests the authoritative Government of Canada bulk Open Data files once, streams
them, normalizes each entity to a canonical key, and loads rows into the local DB.
Per-company queries then hit the DB — fast, complete, and the foundation for the
entity-resolution moat.

Datasets are discovered via the CKAN API on open.canada.ca so resource URLs stay
current even when the gov rotates them.
"""
from __future__ import annotations

import csv
import io
import re
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator

import httpx
import structlog

from pipeline.entity_resolver import normalize

log = structlog.get_logger()

CKAN_API = "https://open.canada.ca/data/api/3/action"
CACHE_DIR = Path("./data/cache")

# CKAN dataset id → the resource we want. Resolved to a live download URL at runtime.
CONTRACTS_DATASET = "d8f85d91-7dec-4fd1-8055-483b77225d8b"
CONTRACTS_RESOURCE_NAME = "Contracts over $10,000"  # excludes legacy/nil/aggregate files

# Elections Canada contributions (as reviewed). Large ZIP on elections.ca; cached.
DONATIONS_ZIP_URL = "https://www.elections.ca/fin/oda/od_cntrbtn_audt_e.zip"
DONATIONS_CACHE = CACHE_DIR / "donations_ec.zip"
# Positional column indices (header names carry BOM/whitespace, so index by position).
_EC = {
    "recipient": 2, "party": 6, "fiscal_date": 9, "contributor_type": 14,
    "contributor_name": 15, "city": 19, "province": 20,
    "received_date": 22, "monetary": 23,
}

# LEGISinfo bills — clean public JSON API.
LEGISINFO_JSON = "https://www.parl.ca/legisinfo/en/bills/json"


async def resolve_resource_url(dataset_id: str, resource_name: str) -> str:
    """Look up a dataset's resource download URL via the CKAN API."""
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
        r = await c.get(f"{CKAN_API}/package_show", params={"id": dataset_id})
        r.raise_for_status()
        resources = r.json()["result"]["resources"]
    for res in resources:
        if res.get("format") == "CSV" and res.get("name") == resource_name:
            return res["url"]
    raise ValueError(f"Resource {resource_name!r} not found in dataset {dataset_id}")


async def stream_csv_rows(url: str, max_rows: int) -> AsyncIterator[dict[str, str]]:
    """Stream a (large) remote CSV and yield parsed dict rows.

    Memory stays flat: we only hold one partial record + the current row.
    max_rows <= 0 means no cap (full corpus).
    """
    header: list[str] | None = None
    buf = ""
    rows = 0
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as c:
        async with c.stream("GET", url) as resp:
            resp.raise_for_status()
            async for chunk in resp.aiter_text():
                buf += chunk
                search_from = 0
                while True:
                    nl = buf.find("\n", search_from)
                    if nl == -1:
                        break
                    # A `\n` inside an open quote (e.g. an embedded newline in a
                    # bilingual description field) isn't a record boundary — an
                    # odd quote count up to here means we're still inside one,
                    # so keep scanning forward instead of splitting here.
                    if buf.count('"', 0, nl) % 2 != 0:
                        search_from = nl + 1
                        continue
                    line, buf = buf[:nl], buf[nl + 1:]
                    search_from = 0
                    if not line.strip():
                        continue
                    vals = next(csv.reader([line]))
                    if header is None:
                        header = vals
                        continue
                    if len(vals) != len(header):
                        continue
                    yield dict(zip(header, vals))
                    rows += 1
                    if max_rows and rows >= max_rows:
                        return


def _to_float(v: str | None) -> float | None:
    if not v:
        return None
    try:
        return float(v.replace(",", "").replace("$", "").strip())
    except ValueError:
        return None


def _sane_year_date(v: str | None) -> str | None:
    """Reject dirty source dates with an obviously-wrong year (same bound as
    the documented Hansard year-4043 workaround) rather than storing them."""
    v = (v or "").strip()
    if not v:
        return None
    try:
        year = int(v[:4])
    except ValueError:
        return None
    return v if 1990 <= year <= 2035 else None


async def iter_contract_rows(max_rows: int = 0) -> AsyncIterator[dict[str, Any]]:
    """Stream federal contract rows, normalized and ready for DB insert.

    Yields one mapped dict at a time so a full-corpus (~1M row) ingest never
    holds the whole dataset in memory. max_rows<=0 → full.
    """
    url = await resolve_resource_url(CONTRACTS_DATASET, CONTRACTS_RESOURCE_NAME)
    log.info("contracts_ingest_start", url=url, max_rows=max_rows)
    async for row in stream_csv_rows(url, max_rows):
        vendor = (row.get("vendor_name") or "").strip()
        if not vendor:
            continue
        yield {
            "reference_number": (row.get("reference_number") or "").strip() or None,
            "vendor_name": vendor,
            "canonical_name": normalize(vendor),
            "description": (row.get("description_en") or "").strip() or None,
            "contract_value": _to_float(row.get("contract_value")),
            "contract_date": (row.get("contract_date") or "").strip() or None,
            "owner_org": (row.get("owner_org") or "").strip() or None,
            "owner_org_title": (row.get("owner_org_title") or "").strip() or None,
        }


async def fetch_contract_rows(max_rows: int = 20000) -> list[dict[str, Any]]:
    """List wrapper around iter_contract_rows (routes/tests). Prefer the iterator
    for large/full ingests."""
    out = [r async for r in iter_contract_rows(max_rows)]
    log.info("contracts_ingest_parsed", count=len(out))
    return out


async def _ensure_donations_cache() -> Path:
    """Download the Elections Canada contributions ZIP once into the cache."""
    if DONATIONS_CACHE.exists() and DONATIONS_CACHE.stat().st_size > 1_000_000:
        return DONATIONS_CACHE
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    log.info("donations_download_start", url=DONATIONS_ZIP_URL)
    async with httpx.AsyncClient(timeout=600, follow_redirects=True) as c:
        async with c.stream("GET", DONATIONS_ZIP_URL) as resp:
            resp.raise_for_status()
            with open(DONATIONS_CACHE, "wb") as fh:
                async for chunk in resp.aiter_bytes():
                    fh.write(chunk)

    from pipeline.raw_storage import save_raw
    save_raw("elections-canada", "donations_quarterly", "od_cntrbtn_audt_e.zip",
              DONATIONS_CACHE.read_bytes(), source_url=DONATIONS_ZIP_URL)

    return DONATIONS_CACHE


async def iter_donation_rows(max_rows: int = 0) -> AsyncIterator[dict[str, Any]]:
    """Stream contribution rows from the cached Elections Canada ZIP.

    Yields one mapped dict at a time. Uncompressed the CSV is multi-GB and the
    full corpus is millions of rows, so the iterator is the only safe path for a
    full ingest. max_rows<=0 → full.
    """
    zip_path = await _ensure_donations_cache()
    yielded = 0
    with zipfile.ZipFile(zip_path) as z:
        member = z.namelist()[0]
        with z.open(member) as f:
            # The source file is UTF-8 with a BOM (confirmed: accented names
            # decode cleanly as UTF-8) — decoding as latin-1 silently mojibakes
            # every accented name instead of erroring, which is why this went
            # unnoticed. utf-8-sig strips the BOM if present.
            text = io.TextIOWrapper(f, encoding="utf-8-sig", newline="")
            reader = csv.reader(text)
            next(reader, None)  # header
            for vals in reader:
                if len(vals) <= _EC["monetary"]:
                    continue
                name = (vals[_EC["contributor_name"]] or "").strip()
                if not name:
                    continue
                yield {
                    "contributor_name": name,
                    "canonical_name": normalize(name),
                    "recipient": (vals[_EC["recipient"]] or "").strip() or None,
                    "party": (vals[_EC["party"]] or "").strip() or None,
                    "contributor_city": (vals[_EC["city"]] or "").strip() or None,
                    "contributor_province": (vals[_EC["province"]] or "").strip() or None,
                    "received_date": _sane_year_date(vals[_EC["received_date"]]),
                    "amount": _to_float(vals[_EC["monetary"]]),
                }
                yielded += 1
                if max_rows and yielded >= max_rows:
                    break


async def fetch_donation_rows(max_rows: int = 50000) -> list[dict[str, Any]]:
    """List wrapper around iter_donation_rows (routes/tests)."""
    out = [r async for r in iter_donation_rows(max_rows)]
    log.info("donations_ingest_parsed", count=len(out))
    return out


OCL_COMMS_DATASET = "a34eb330-7136-4f5e-9f5f-3ba41df58b06"  # "Monthly Communication Reports" on open.canada.ca
OCL_COMMS_URL_FALLBACK = "https://lobbycanada.gc.ca/media/mqbbmaqk/communications_ocl_cal.zip"
OCL_COMMS_CACHE = CACHE_DIR / "ocl_communications.zip"
_OCL_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


async def _resolve_ocl_comms_url() -> str:
    """Resolve the communications ZIP URL via CKAN — same rot risk as the
    registrations ZIP (see _resolve_ocl_reg_url), just not yet broken."""
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(f"{CKAN_API}/package_show", params={"id": OCL_COMMS_DATASET})
            r.raise_for_status()
            for res in r.json()["result"]["resources"]:
                if (res.get("format") or "").upper() == "CSV":
                    return res["url"]
    except Exception as exc:
        log.warning("ocl_comms_url_resolve_failed", error=str(exc))
    return OCL_COMMS_URL_FALLBACK


async def _ensure_ocl_cache() -> Path:
    """Download the OCL monthly communications ZIP once into the cache."""
    if OCL_COMMS_CACHE.exists() and OCL_COMMS_CACHE.stat().st_size > 1_000_000:
        return OCL_COMMS_CACHE
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    OCL_COMMS_URL = await _resolve_ocl_comms_url()
    log.info("ocl_download_start", url=OCL_COMMS_URL)
    headers = {"User-Agent": _OCL_UA, "Accept": "*/*"}
    async with httpx.AsyncClient(timeout=180, headers=headers, follow_redirects=True) as c:
        async with c.stream("GET", OCL_COMMS_URL) as resp:
            resp.raise_for_status()
            with open(OCL_COMMS_CACHE, "wb") as fh:
                async for chunk in resp.aiter_bytes():
                    fh.write(chunk)
    log.info("ocl_download_done", size=OCL_COMMS_CACHE.stat().st_size)

    from pipeline.raw_storage import save_raw
    save_raw("lobbying", "ocl_monthly", "communications_ocl_cal.zip",
              OCL_COMMS_CACHE.read_bytes(), source_url=OCL_COMMS_URL)

    return OCL_COMMS_CACHE


async def fetch_ocl_communication_rows(max_rows: int = 0) -> list[dict[str, Any]]:
    """Bulk-ingest OCL monthly communication reports.

    Downloads and caches the 22 MB OCL communications ZIP, then:
    1. Builds a DPOH lookup (who was lobbied per communication).
    2. Builds a subject-matter lookup.
    3. Streams the primary export, normalizes company names, joins the lookups.

    max_rows=0 means no cap (full corpus ~369 k rows).
    """
    zip_path = await _ensure_ocl_cache()

    with zipfile.ZipFile(zip_path) as zf:
        # Build subject matter code → human-readable label lookup
        smt_labels: dict[str, str] = {}
        with zf.open("Codes_SubjectMatterTypesExport.csv") as f:
            for row in csv.DictReader(io.TextIOWrapper(f, encoding="latin-1")):
                code = (row.get("SUBJECT_CODE_OBJET") or "").strip()
                label = (row.get("SMT_EN_DESC") or "").strip()
                if code and label:
                    smt_labels[code] = label

        # Build DPOH lookup: comlog_id → list of contact dicts
        dpoh: dict[str, list[dict[str, str]]] = {}
        with zf.open("Communication_DpohExport.csv") as f:
            for row in csv.DictReader(io.TextIOWrapper(f, encoding="latin-1")):
                cid = row["COMLOG_ID"]
                dpoh.setdefault(cid, []).append(
                    {
                        "name": f"{row.get('DPOH_FIRST_NM_PRENOM_TCPD','').strip()} {row.get('DPOH_LAST_NM_TCPD','').strip()}".strip(),
                        "title": (row.get("DPOH_TITLE_TITRE_TCPD") or "").strip(),
                        "institution": (row.get("INSTITUTION") or "").strip(),
                    }
                )

        # Build subject-matter lookup: comlog_id → [human-readable label, ...]
        subjects: dict[str, list[str]] = {}
        with zf.open("Communication_SubjectMattersExport.csv") as f:
            for row in csv.DictReader(io.TextIOWrapper(f, encoding="latin-1")):
                cid = row["COMLOG_ID"]
                code = (row.get("SUBJECT_CODE_OBJET") or "").strip()
                if code:
                    label = smt_labels.get(code, code)  # fall back to code if no label
                    subjects.setdefault(cid, []).append(label)

        # Stream primary communications
        out: list[dict[str, Any]] = []
        with zf.open("Communication_PrimaryExport.csv") as f:
            for row in csv.DictReader(io.TextIOWrapper(f, encoding="latin-1")):
                client = (row.get("EN_CLIENT_ORG_CORP_NM_AN") or "").strip()
                if not client:
                    continue
                cid = row["COMLOG_ID"]
                contacts = dpoh.get(cid, [])
                registrant = (
                    f"{row.get('RGSTRNT_1ST_NM_PRENOM_DCLRNT','').strip()} "
                    f"{row.get('RGSTRNT_LAST_NM_DCLRNT','').strip()}"
                ).strip()
                out.append(
                    {
                        "comlog_id": cid,
                        "client_org": client,
                        "canonical_name": normalize(client),
                        "registrant": registrant,
                        "comm_date": (row.get("COMM_DATE") or "").strip() or None,
                        "reg_type": (row.get("REG_TYPE_ENR") or "").strip() or None,
                        "institutions": sorted({c["institution"] for c in contacts if c["institution"]}),
                        "dpoh_contacts": contacts,
                        "subject_codes": subjects.get(cid, []),
                    }
                )
                if max_rows and len(out) >= max_rows:
                    break

    log.info("ocl_ingest_parsed", count=len(out))
    return out


async def fetch_bill_rows(max_rows: int = 1000) -> list[dict[str, Any]]:
    """Pull current bills from the LEGISinfo JSON API."""
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as c:
        r = await c.get(LEGISINFO_JSON)
        r.raise_for_status()
        data = r.json()
    out: list[dict[str, Any]] = []
    for b in data[:max_rows]:
        out.append(
            {
                "bill_number": b.get("BillNumberFormatted") or str(b.get("BillNumber", "")),
                "parliament": b.get("ParlSessionCode") or None,
                "title_en": (b.get("LongTitleEn") or b.get("ShortTitleEn") or "").strip() or None,
                "status": (b.get("CurrentStatusEn") or b.get("LatestCompletedMajorStageEn") or "").strip() or None,
                "sponsor": (b.get("SponsorEn") or "").strip() or None,
                "latest_activity": (b.get("LatestActivityEn") or "").strip() or None,
                "introduced_date": (b.get("LatestActivityDateTime") or "")[:10] or None,
            }
        )
    log.info("bills_ingest_parsed", count=len(out))
    return out


# ── Grants & Contributions ────────────────────────────────────────────────────
GRANTS_DATASET = "432527ab-7aac-45b5-81d6-7597107a7013"
GRANTS_RESOURCE_NAME = "grants"  # CKAN resource name contains "grants"

# Positional fallback if headers differ; we prefer header names.
_GRANTS_HEADER_MAP = {
    "ref_number": ["ref_number", "reference_number"],
    "recipient_name": ["recipient_legal_name", "recipient_name", "legal_name"],
    "recipient_city": ["recipient_city", "city"],
    "recipient_province": ["recipient_province", "province"],
    "owner_org": ["owner_org", "org"],
    "owner_org_title": ["owner_org_title", "department"],
    "program_name": ["prog_name_en", "program_name_en", "program_name"],
    "agreement_type": ["agreement_type", "type"],
    "agreement_value": ["agreement_value", "value", "amount"],
    "agreement_start": ["agreement_start_date", "start_date"],
    "agreement_end": ["agreement_end_date", "end_date"],
    "description": ["description_en", "description"],
}


def _pick(row: dict, keys: list[str]) -> str:
    for k in keys:
        if k in row and row[k]:
            return row[k].strip()
    return ""


async def _resolve_grants_url() -> str:
    # Search for the CSV resource in the grants dataset.
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
        r = await c.get(f"{CKAN_API}/package_show", params={"id": GRANTS_DATASET})
        if r.status_code != 200:
            # Try search fallback
            r2 = await c.get(f"{CKAN_API}/package_search", params={"q": "grants contributions proactive disclosure"})
            r2.raise_for_status()
            results = r2.json()["result"]["results"]
            if not results:
                raise ValueError("Grants dataset not found via CKAN API")
            resources = results[0]["resources"]
        else:
            resources = r.json()["result"]["resources"]

    # Pick by size, not "first match" — this dataset also publishes a tiny
    # "Nothing to Report" placeholder CSV whose name matches the same
    # grant/contrib keywords as the real ~2GB resource, and used to win just
    # by appearing first in the CKAN response.
    candidates = [
        res for res in resources
        if (res.get("format") or "").upper() == "CSV"
        and ("grant" in (res.get("name") or "").lower() or "contrib" in (res.get("name") or "").lower())
    ]
    if not candidates:
        candidates = [res for res in resources if (res.get("format") or "").upper() == "CSV"]
    if not candidates:
        raise ValueError("No CSV resource found in grants dataset")
    return max(candidates, key=lambda res: res.get("size") or 0)["url"]


async def iter_grant_rows(max_rows: int = 0) -> AsyncIterator[dict[str, Any]]:
    """Stream federal Grants & Contributions rows, normalized and ready for DB
    insert. Yields one mapped dict at a time so a full-corpus (~2.25GB CSV)
    ingest never holds the whole dataset in memory — same risk class as
    contracts/donations, fixed 2026-06-22 (was fetch_grant_rows, which
    materialized everything into a list; see DATA_CHECKLIST.md "Goal 6").
    max_rows<=0 → full.
    """
    url = await _resolve_grants_url()
    log.info("grants_ingest_start", url=url, max_rows=max_rows)
    async for row in stream_csv_rows(url, max_rows):
        name = _pick(row, _GRANTS_HEADER_MAP["recipient_name"])
        if not name:
            continue
        raw_val = _pick(row, _GRANTS_HEADER_MAP["agreement_value"])
        yield {
            "ref_number": _pick(row, _GRANTS_HEADER_MAP["ref_number"]) or None,
            "recipient_name": name,
            "canonical_name": normalize(name),
            "recipient_city": _pick(row, _GRANTS_HEADER_MAP["recipient_city"]) or None,
            "recipient_province": _pick(row, _GRANTS_HEADER_MAP["recipient_province"]) or None,
            "owner_org": _pick(row, _GRANTS_HEADER_MAP["owner_org"]) or None,
            "owner_org_title": _pick(row, _GRANTS_HEADER_MAP["owner_org_title"]) or None,
            "program_name": _pick(row, _GRANTS_HEADER_MAP["program_name"]) or None,
            "agreement_type": _pick(row, _GRANTS_HEADER_MAP["agreement_type"]) or None,
            "agreement_value": _to_float(raw_val),
            "agreement_start": _pick(row, _GRANTS_HEADER_MAP["agreement_start"]) or None,
            "agreement_end": _pick(row, _GRANTS_HEADER_MAP["agreement_end"]) or None,
            "description": _pick(row, _GRANTS_HEADER_MAP["description"]) or None,
        }


async def fetch_grant_rows(max_rows: int = 30000) -> list[dict[str, Any]]:
    """List wrapper around iter_grant_rows (routes/tests/small callers).
    Prefer the iterator for large/full ingests."""
    out = [r async for r in iter_grant_rows(max_rows)]
    log.info("grants_ingest_parsed", count=len(out))
    return out


# ── GIC Appointments ──────────────────────────────────────────────────────────
# open.canada.ca's standalone GIC Appointments CKAN dataset (id below) is dead —
# package_show returns 404 and the package_search fallback finds nothing either
# (confirmed live). Real fix: derive appointments from the `précis` free text of
# Orders in Council we already ingest (pipeline/connector_orders_in_council.py
# → source_records, source="orders_in_council") — every PC-number appointment
# OIC carries a highly templated sentence ("Appointment of NAME of CITY,
# Province, to be POSITION...") that's reliably regex-extractable. No network
# call needed; this parses data already in the DB.
GIC_DATASET = "58b10b98-acab-458a-9e7a-fc1a1c2b1a58"  # dead; kept for the yaml/audit trail, not called

_PROVINCES = {
    "alberta", "british columbia", "manitoba", "new brunswick",
    "newfoundland and labrador", "northwest territories", "nova scotia",
    "nunavut", "ontario", "prince edward island", "quebec", "saskatchewan", "yukon",
}
_APPT_LEAD_RE = re.compile(r"^(re-?appointment|appointment|designation)\s+of\s+", re.IGNORECASE)
_APPT_CONNECTOR_RE = re.compile(r"\s+(?:to be|as)\s+", re.IGNORECASE)
_APPT_PERSON_RE = re.compile(
    r"([A-ZÀ-Ý][^,]*?)\s+of\s+([^,]+?),\s+([A-Za-zÀ-ÿ ]+?)(?=,\s+(?:and\s+)?[A-Z]|$)"
)
_APPT_EFFECTIVE_RE = re.compile(r"effective\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})", re.IGNORECASE)
_APPT_POSITION_STOP_RE = re.compile(
    r"\s+to\s+hold\s+office.*$|\s+for\s+a\s+term.*$|\s+effective\b.*$|\.$"
)
_APPT_ORG_RE = re.compile(r"\bof\s+(?:the\s+)?([A-ZÀ-Ý][\w&,'.\-() ]+?)(?:,|\.|$)")


def parse_appointments_from_precis(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract one Appointment row per appointee named in an Order in Council's
    précis (raw OIC dict per pipeline/connector_orders_in_council.py's shape:
    pc_number/date_made/department/precis/...). Best-effort: OICs that don't
    match the templated "Appointment/Re-appointment/Designation of NAME ... to
    be/as POSITION" pattern (amendments, repeals, regulatory orders — most OICs
    aren't appointments at all) are skipped, not fabricated."""
    out: list[dict[str, Any]] = []
    for row in records:
        precis = (row.get("precis") or "").strip()
        lead = _APPT_LEAD_RE.match(precis)
        if not lead:
            continue
        appointment_type = lead.group(1)
        rest = precis[lead.end():]
        conn = _APPT_CONNECTOR_RE.search(rest)
        # rest[:conn.start()] includes the comma immediately before " to be"/
        # " as" (e.g. "...Quebec, to be ...") — strip it so the trailing
        # province doesn't fail to match the person regex's lookahead.
        people_clause = (rest[:conn.start()] if conn else rest).rstrip(", ")
        position_clause = rest[conn.end():] if conn else ""

        people = list(_APPT_PERSON_RE.finditer(people_clause))
        if not people:
            # No "of CITY, Province" found (e.g. a foreign posting or a firm
            # named as auditor) — still record the appointee with no
            # city/province rather than dropping the row entirely.
            name = re.split(r",| and ", people_clause)[0].strip()
            if not name:
                continue
            people_data = [(name, None, None)]
        else:
            people_data = []
            for m in people:
                name = m.group(1).strip().rstrip(",")
                city = m.group(2).strip()
                province = m.group(3).strip()
                if province.lower() not in _PROVINCES:
                    province = None
                people_data.append((name, city, province))

        position_title = _APPT_POSITION_STOP_RE.sub("", position_clause).strip(", ") or None
        # Search the already-truncated title, not the raw clause — otherwise
        # the lazy org match runs past "of the Board" into the un-stripped
        # "to hold office..." tail with nothing to stop it.
        org_match = _APPT_ORG_RE.search(position_title or "")
        organization = org_match.group(1).strip(", ") if org_match else row.get("department")
        eff_match = _APPT_EFFECTIVE_RE.search(position_clause)
        appointment_date = row.get("date_made")
        if eff_match:
            try:
                appointment_date = datetime.strptime(eff_match.group(1), "%B %d, %Y").strftime("%Y-%m-%d")
            except ValueError:
                pass

        for name, city, province in people_data:
            if not name:
                continue
            out.append({
                "appointee_name": name,
                "canonical_name": normalize(name),
                "position_title": position_title,
                "organization": organization,
                "appointment_date": appointment_date,
                "end_date": None,
                "order_in_council": row.get("pc_number"),
                "appointment_type": appointment_type,
                "remuneration": None,
                "province": province,
            })
    log.info("appointments_parsed_from_oic", count=len(out), source_records=len(records))
    return out


# ── Canada Gazette RSS ────────────────────────────────────────────────────────
GAZETTE_RSS = {
    "I": "https://gazette.gc.ca/rss/p1-eng.xml",
    "II": "https://gazette.gc.ca/rss/p2-eng.xml",
}
_GAZETTE_UA = "Mozilla/5.0 (compatible; Nessus/1.0)"
_DEPT_RE = re.compile(r"^([A-Z][^:]+?)(?:\s*—|\s*:)", re.MULTILINE)


def _extract_dept(title: str, desc: str) -> str | None:
    for text in (title, desc):
        m = _DEPT_RE.search(text)
        if m:
            return m.group(1).strip()
    return None


async def fetch_gazette_entries() -> list[dict[str, Any]]:
    """Pull Canada Gazette Part I (proposed) and Part II (final) from RSS feeds."""
    out: list[dict[str, Any]] = []
    headers = {"User-Agent": _GAZETTE_UA, "Accept": "application/rss+xml,application/xml,text/xml"}
    for part, url in GAZETTE_RSS.items():
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=headers) as c:
                r = await c.get(url)
                r.raise_for_status()
                root = ET.fromstring(r.text)
        except Exception as exc:
            log.warning("gazette_rss_failed", part=part, error=str(exc))
            continue

        ns = ""
        channel = root.find("channel")
        if channel is None:
            channel = root

        for item in channel.findall("item"):
            def _t(tag: str) -> str:
                el = item.find(tag)
                return (el.text or "").strip() if el is not None else ""

            title = _t("title")
            if not title:
                continue
            desc_raw = _t("description")
            # Strip HTML tags from description
            desc = re.sub(r"<[^>]+>", " ", desc_raw).strip()
            pub_date_raw = _t("pubDate")
            # Parse RFC 2822 → YYYY-MM-DD ("Sat, 13 Jun 2026 00:00:00 -0400")
            pub_date = None
            if pub_date_raw:
                try:
                    from email.utils import parsedate
                    parsed = parsedate(pub_date_raw)
                    if parsed:
                        pub_date = f"{parsed[0]:04d}-{parsed[1]:02d}-{parsed[2]:02d}"
                except Exception:
                    pub_date = pub_date_raw[:10]
            guid = _t("guid") or _t("link")
            dept = _extract_dept(title, desc)
            # Extract SOR/CIF number if present
            reg_match = re.search(r"\bSOR[/-]\d{4}-\d+\b|\bSI[/-]\d{4}-\d+\b", title + " " + desc)
            reg_id = reg_match.group(0) if reg_match else None

            out.append({
                "gazette_part": part,
                "title": title,
                "published_date": pub_date,
                "description": desc[:2000] if desc else None,
                "url": _t("link"),
                "guid": guid,
                "department": dept,
                "regulation_id": reg_id,
            })

    log.info("gazette_ingest_parsed", count=len(out))
    return out


# ── CRTC Decisions ────────────────────────────────────────────────────────────
# Moved to pipeline/connector_crtc_decisions.py:fetch_crtc_decisions — the
# BroadcastDecisions/TelecomDecisions RSS URLs this used to hit return an
# HTML 404 page with HTTP 200 (confirmed dead; see that module's docstring
# for the working replacement source and why).


# ── OCL Registrations ─────────────────────────────────────────────────────────
OCL_REG_DATASET = "70ef2117-1095-4d77-80eb-b87f2bada2a4"  # "Lobbying Registrations" on open.canada.ca
OCL_REG_URL_FALLBACK = "https://lobbycanada.gc.ca/media/mqbbmaqk/registrations_oct_cal.zip"
OCL_REG_CACHE = CACHE_DIR / "ocl_registrations.zip"


async def _resolve_ocl_reg_url() -> str:
    """Resolve the registrations ZIP URL via CKAN rather than hardcoding it.

    lobbycanada.gc.ca rotates the media-asset path component (it moved from
    /media/mqbbmaqk/ to /media/zwcjycef/ at some point, breaking the old
    hardcoded URL) — same class of rot as the other CKAN-catalogued bulk files
    in this module. Falls back to the last known-good hardcoded URL if the
    CKAN lookup itself fails.
    """
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(f"{CKAN_API}/package_show", params={"id": OCL_REG_DATASET})
            r.raise_for_status()
            for res in r.json()["result"]["resources"]:
                if (res.get("format") or "").upper() == "CSV":
                    return res["url"]
    except Exception as exc:
        log.warning("ocl_reg_url_resolve_failed", error=str(exc))
    return OCL_REG_URL_FALLBACK


async def _ensure_ocl_reg_cache() -> Path:
    if OCL_REG_CACHE.exists() and OCL_REG_CACHE.stat().st_size > 1_000_000:
        return OCL_REG_CACHE
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    OCL_REG_URL = await _resolve_ocl_reg_url()
    log.info("ocl_reg_download_start", url=OCL_REG_URL)
    headers = {"User-Agent": _OCL_UA, "Accept": "*/*"}
    async with httpx.AsyncClient(timeout=360, headers=headers, follow_redirects=True) as c:
        async with c.stream("GET", OCL_REG_URL) as resp:
            if resp.status_code == 404:
                log.warning("ocl_reg_not_found", url=OCL_REG_URL)
                return OCL_REG_CACHE  # caller must check .exists()
            resp.raise_for_status()
            with open(OCL_REG_CACHE, "wb") as fh:
                async for chunk in resp.aiter_bytes():
                    fh.write(chunk)
    log.info("ocl_reg_download_done", size=OCL_REG_CACHE.stat().st_size if OCL_REG_CACHE.exists() else 0)

    if OCL_REG_CACHE.exists():
        from pipeline.raw_storage import save_raw
        save_raw("lobbying", "ocl_registrations", "registrations_enregistrements_ocl_cal.zip",
                  OCL_REG_CACHE.read_bytes(), source_url=OCL_REG_URL)

    return OCL_REG_CACHE


async def fetch_ocl_registration_rows(max_rows: int = 0) -> list[dict[str, Any]]:
    """Bulk-ingest OCL Registrations (the filing-level data, not communications).

    The registrations ZIP contains the who/what/why of each lobbying registration:
    the client organization, the lobbying firm, subject matters, and federal benefits sought.
    """
    zip_path = await _ensure_ocl_reg_cache()
    if not zip_path.exists() or zip_path.stat().st_size < 1_000_000:
        log.warning("ocl_reg_cache_unavailable")
        return []

    out: list[dict[str, Any]] = []
    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            log.info("ocl_reg_zip_contents", files=names)

            # Find the primary registration export. Every file in this ZIP has
            # "registration" in its name (Beneficiaries, GovtFunding, SubjectMatters,
            # etc. are all "Registration_*Export.csv" too) so "primary" must be
            # checked first, or the wrong-schema file wins by being first in the zip.
            primary = next((n for n in names if "primary" in n.lower()), None)
            if not primary:
                primary = next((n for n in names if "registration" in n.lower()), None)
            if not primary:
                primary = names[0]

            def _clean(val: str | None) -> str | None:
                v = (val or "").strip()
                return v if v and v.lower() != "null" else None

            with zf.open(primary) as f:
                for row in csv.DictReader(io.TextIOWrapper(f, encoding="latin-1")):
                    # Real column names per Registration_PrimaryExport.csv (verified
                    # 2026-06-21) — the previous names (REG_NUM, CLIENT_ORG, STATUS,
                    # EFFECTIVE_DATE, FIRM_NAME, ...) never matched any header in the
                    # actual export, so every row used to get skipped or stored blank.
                    client = _clean(row.get("EN_CLIENT_ORG_CORP_NM_AN"))
                    reg_num = _clean(row.get("REG_NUM_ENR"))
                    if not client or not reg_num:  # reg_num is the dedup/unique key
                        continue
                    registrant = (
                        f"{(row.get('RGSTRNT_1ST_NM_PRENOM_DCLRNT') or '').strip()} "
                        f"{(row.get('RGSTRNT_LAST_NM_DCLRNT') or '').strip()}"
                    ).strip()
                    out.append({
                        "registration_num": reg_num,
                        "client_org": client,
                        "canonical_name": normalize(client),
                        "registrant_name": registrant or None,
                        "firm_name": _clean(row.get("EN_FIRM_NM_FIRME_AN")),
                        "registration_type": _clean(row.get("REG_TYPE_ENR")),
                        # Primary export has no direct status column; would need to
                        # derive from END_DATE_FIN (blank = active) or join another
                        # export file — left None rather than guessing.
                        "status": None,
                        "effective_date": _clean(row.get("EFFECTIVE_DATE_VIGUEUR")),
                        "end_date": _clean(row.get("END_DATE_FIN")),
                        # subject matters / federal benefits / private interests live
                        # in separate export files within the same ZIP, not joined yet.
                        "subject_matters": [],
                        "federal_benefits": None,
                        "private_interests": None,
                        "government_funding": _clean(row.get("GOVT_FUND_IND_FIN_GOUV")),
                    })
                    if max_rows and len(out) >= max_rows:
                        break
    except Exception as exc:
        log.error("ocl_reg_parse_failed", error=str(exc))
        return []

    log.info("ocl_reg_ingest_parsed", count=len(out))
    return out
