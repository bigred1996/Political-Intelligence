"""BC Registrar of Lobbyists — first provincial source (Goal: provincial
ingestion, priority order ON/QC/BC/AB).

Researched all four target provinces' lobbyist registries before writing
any code: Ontario (lobbyist.oico.on.ca) and Alberta (an Oracle APEX app)
expose only an interactive search UI, no export/API, and neither province's
open-data portal mirrors the registry. Quebec's registry moved to
carrefourlobby.quebec, an Angular SPA with no documented public API; its
companion info site (lobbyisme.quebec) explicitly blocks AI crawlers via
robots.txt. BC is the only one of the four with a real, documented, live
bulk export — confirmed by direct fetch, not just a search hit:

    https://www.lobbyistsregistrar.bc.ca/app/secure/orl/lrs/do/mssDtstRprt?file=ORL_Registration_Data.zip

A 27MB ZIP of 16 CSVs, updated monthly (per the registrar's own open-data
page), no User-Agent or API key required, robots.txt only disallows
`/sitemap/`. ON/QC/AB stay undone until those registries publish a bulk
channel — see GAMEPLAN.md.

This pass uses two of the sixteen CSVs: `Registration_Primary_Export.csv`
(one row per registration — REG_ID, filer, client org, dates; 26,357 real
rows once you parse it as CSV rather than count lines, since several
business-description fields are quoted multi-line text) and
`Registration_SubjectMatterDetails_Export.csv` (REG_ID -> free-text lobbying
topics, joined in for a searchable summary). The other 14 files (lobbyist
name lists, gift/funding disclosures, per-target-agency breakdowns) are
real but out of scope for this MVP pass — `Registration_Target_Contacts_
Export.csv` alone is 94MB/long enough that joining it would meaningfully
slow every ingest for a field not yet used by anything downstream.
"""
from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path
from typing import Any

import httpx
import structlog

from pipeline.entity_resolver import normalize

log = structlog.get_logger()

BC_ZIP_URL = "https://www.lobbyistsregistrar.bc.ca/app/secure/orl/lrs/do/mssDtstRprt?file=ORL_Registration_Data.zip"
CACHE_PATH = Path("./data/cache/bc_lobbyist_registry.zip")
SOURCE_ID = "bc_lobbyist_registry"

PRIMARY_CSV = "Registration_Primary_Export.csv"
SUBJECTS_CSV = "Registration_SubjectMatterDetails_Export.csv"


async def _ensure_cache() -> Path:
    if CACHE_PATH.exists() and CACHE_PATH.stat().st_size > 1_000_000:
        return CACHE_PATH
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    log.info("bc_lobbyist_download_start", url=BC_ZIP_URL)
    async with httpx.AsyncClient(timeout=180, follow_redirects=True) as c:
        async with c.stream("GET", BC_ZIP_URL) as resp:
            resp.raise_for_status()
            with open(CACHE_PATH, "wb") as fh:
                async for chunk in resp.aiter_bytes():
                    fh.write(chunk)
    log.info("bc_lobbyist_download_done", size=CACHE_PATH.stat().st_size)

    from pipeline.raw_storage import save_raw
    save_raw("provincial", SOURCE_ID, "ORL_Registration_Data.zip",
              CACHE_PATH.read_bytes(), source_url=BC_ZIP_URL)
    return CACHE_PATH


def _reader(zf: zipfile.ZipFile, name: str) -> csv.DictReader:
    return csv.DictReader(io.TextIOWrapper(zf.open(name), encoding="utf-8-sig", newline=""))


async def fetch_bc_lobbyist_records(max_rows: int = 0) -> list[dict[str, Any]]:
    """max_rows=0 means no cap (full corpus, ~26k registrations)."""
    zip_path = await _ensure_cache()

    with zipfile.ZipFile(zip_path) as zf:
        topics: dict[str, list[str]] = {}
        for row in _reader(zf, SUBJECTS_CSV):
            reg_id = row.get("REG_ID")
            topic = (row.get("TOPIC_OF_LOBBYING") or "").strip()
            if reg_id and topic:
                topics.setdefault(reg_id, []).append(topic)

        out: list[dict[str, Any]] = []
        for row in _reader(zf, PRIMARY_CSV):
            client = (row.get("CLIENT_ORG_NAME") or "").strip()
            if not client or client.lower() == "null":
                continue
            reg_id = row["REG_ID"]
            firm = (row.get("FIRM_NAME") or "").strip()
            firm = None if not firm or firm.lower() == "null" else firm
            filer = f"{row.get('FILER_FIRST_NAME', '').strip()} {row.get('FILER_LAST_NAME', '').strip()}".strip()
            biz_desc = (row.get("CLIENT_ORG_BUS_DESC") or "").strip()
            biz_desc = None if biz_desc.lower() == "null" else biz_desc
            reg_topics = topics.get(reg_id, [])
            summary = " | ".join(reg_topics)[:4000] if reg_topics else biz_desc
            title = f"{firm} lobbying on behalf of {client}" if firm else f"{client} (in-house lobbying)"

            out.append({
                "source": SOURCE_ID,
                "record_type": "consultant_registration" if firm else "in_house_registration",
                "external_id": reg_id,
                "entity_name": client,
                "canonical_name": normalize(client),
                "title": title[:1024],
                "summary": summary or None,
                "full_text": "\n".join(reg_topics)[:6000] or biz_desc,
                "event_date": (row.get("REG_START_DATE") or "").strip() or None,
                "amount": None,
                "province": "BC",
                "url": "https://www.lobbyistsregistrar.bc.ca/",
                "raw": {
                    "reg_num": row.get("REG_NUM"),
                    "filer": filer or None,
                    "filer_position": (row.get("FILER_POSITION_TITLE") or "").strip() or None,
                    "firm_name": firm,
                    "client_org_address": (row.get("CLIENT_ORG_ADDRESS") or "").strip() or None,
                    "reg_end_date": (row.get("REG_END_DATE") or "").strip() or None,
                    "lobbies_mlas": row.get("CLIENT_LOBBY_MLA_IND"),
                    "topics": reg_topics,
                },
            })
            if max_rows and len(out) >= max_rows:
                break

    log.info("bc_lobbyist_parsed", count=len(out))
    return out
