"""Goal 6 continuation: backfill the 5 sources not attempted in the first pass
(see DATA_CHECKLIST.md "Goal 6" — Public Accounts/GC InfoBase, StatCan, Bank
of Canada, NRCan geospatial, Transport Canada had no connector or no actual
file backfill yet, only catalogues from Goal 5).

Every source here is a one-time historical load, not a recurring scheduled
job — these datasets don't have a typed DB table or a production fetch_*
function, so this script talks to raw_storage.py primitives directly rather
than going through pipeline/ingest.py. "Selected" sources (StatCan, Bank of
Canada, NRCan, Transport Canada) use a hand-curated list, not their full
catalogue — picking representative tables/datasets across sectors the
platform actually covers, not an exhaustive dump of everything upstream
publishes (StatCan alone has 8,213 cubes; downloading all of them is a
different-scoped project).

Usage:
    .venv/bin/python scripts/backfill_remaining_sources.py gc_infobase
    .venv/bin/python scripts/backfill_remaining_sources.py public_accounts
    .venv/bin/python scripts/backfill_remaining_sources.py statcan
    .venv/bin/python scripts/backfill_remaining_sources.py bank_of_canada
    .venv/bin/python scripts/backfill_remaining_sources.py nrcan_geospatial
    .venv/bin/python scripts/backfill_remaining_sources.py transport_canada
    .venv/bin/python scripts/backfill_remaining_sources.py all
"""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

import httpx

from pipeline import raw_storage as rs

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
_HEADERS = {"User-Agent": _UA, "Accept": "*/*"}


async def _get_bytes(client: httpx.AsyncClient, url: str) -> bytes:
    r = await client.get(url)
    r.raise_for_status()
    return r.content


def _years_from_text(text: str) -> list[int]:
    return sorted({int(y) for y in re.findall(r"(?:19|20)\d{2}", text)})


# ── GC InfoBase ───────────────────────────────────────────────────────────
# 6 CKAN datasets under org tbs-sct. 18 of the 79 catalogued CSV resources
# have no `url` in CKAN's metadata at all (confirmed via resource_show, not a
# fetch bug on this end) — those are recorded as not-downloadable, not forced.
GC_INFOBASE_DATASETS = {
    "gc_infobase_open_datasets": "a35cf382-690c-4221-a971-cf0fd189a46f",
    "gc_infobase_authorities_expenditures": "fc6ba156-a167-4abd-b172-d1293efebe55",
    "gc_infobase_departmental_plans_results": "b15ee8d7-2ac0-4656-8330-6c60d085cda8",
    "gc_infobase_covid_authorities_expenditures": "9fa1da9a-8c0f-493e-b207-0cc95889823e",
    "gc_infobase_covid_estimates_initiatives": "80ae9905-9034-4cf7-9057-d34af6065561",
    "gc_infobase_budget_measures": "a4c77b24-96a6-4c83-a3a6-f9dd32325e3a",
}


async def backfill_gc_infobase() -> None:
    async with httpx.AsyncClient(timeout=60, headers=_HEADERS, follow_redirects=True) as client:
        for source_id, dataset_id in GC_INFOBASE_DATASETS.items():
            r = await client.get("https://open.canada.ca/data/api/3/action/package_show",
                                  params={"id": dataset_id})
            r.raise_for_status()
            resources = r.json()["result"]["resources"]
            csv_resources = [res for res in resources if (res.get("format") or "").upper() == "CSV"]
            no_url = [res for res in csv_resources if not res.get("url")]
            downloadable = [res for res in csv_resources if res.get("url")]

            total_rows = 0
            saved = 0
            for res in downloadable:
                url = res["url"]
                filename = url.rsplit("/", 1)[-1]
                try:
                    content = await _get_bytes(client, url)
                except Exception as exc:
                    print(f"  [{source_id}] FAILED {filename}: {exc}")
                    continue
                result = rs.save_raw("open-government", source_id, filename, content, source_url=url)
                saved += 1
                try:
                    total_rows += rs.count_csv_rows(Path(result["path"]), encoding="utf-8")
                except Exception:
                    pass

            rs.record_backfill(
                "open-government", source_id,
                row_count=total_rows, extraction_validated=saved > 0,
                notes=(f"{saved}/{len(csv_resources)} CSV resources downloaded "
                       f"(plain CSV, no zip to extract); {len(no_url)} resources "
                       f"catalogued by CKAN with no actual url field (confirmed via "
                       f"resource_show, not downloadable as-is)."),
            )
            print(f"[gc_infobase] {source_id}: saved={saved}/{len(csv_resources)} rows={total_rows} "
                  f"no_url={len(no_url)}")


# ── Public Accounts of Canada ────────────────────────────────────────────
# No bulk CSV/zip exists upstream — Public Accounts is published as PDF
# volumes. publications.gc.ca/site/eng/9.505967/publication.html is a real,
# scrapeable index of those PDFs going back to 1995. "Row count" doesn't
# apply to a PDF financial-statement volume, so file_count is recorded as
# the row-count analog (documented in notes, not silently substituted).
PUBLIC_ACCOUNTS_INDEX = "https://publications.gc.ca/site/eng/9.505967/publication.html"


async def backfill_public_accounts() -> None:
    async with httpx.AsyncClient(timeout=60, headers=_HEADERS, follow_redirects=True) as client:
        r = await client.get(PUBLIC_ACCOUNTS_INDEX)
        r.raise_for_status()
        links = sorted(set(re.findall(r'href="([^"]+\.pdf[^"]*)"', r.text, re.I)))
        if not links:
            print("[public_accounts] no PDF links found on index page — site structure may have changed")
            return

        saved = 0
        blocked = 0
        all_years: set[int] = set()
        for url in links:
            filename = url.rsplit("/", 1)[-1]
            try:
                content = await _get_bytes(client, url)
            except Exception as exc:
                if "unknown url type" in str(exc):
                    # a handful of the regex-scraped hrefs on the index page are
                    # malformed protocol-relative links (missing https:) — a
                    # scrape artifact of the source page, not a download failure.
                    print(f"  [public_accounts] SKIPPED {filename}: malformed href on index page ({exc})")
                else:
                    print(f"  [public_accounts] FAILED {filename}: {exc}")
                continue
            if content[:4] != b"%PDF":
                blocked += 1
                continue
            rs.save_raw("open-government", "public_accounts", filename, content, source_url=url)
            saved += 1
            all_years.update(_years_from_text(filename))

        notes = (f"Public Accounts of Canada has no bulk CSV/zip export — content is PDF "
                 f"financial-statement volumes (Vol I/II/III + sections) per fiscal year. "
                 f"row_count is FILE COUNT (PDFs saved), not a data-row count.")
        if blocked:
            notes += (f" BLOCKED: {blocked}/{len(links)} PDF links on the publications.gc.ca index "
                      f"307-redirect to an 'archived content' interstitial "
                      f"(/site/archivee-archived.html?url=...) that returns an HTML wrapper page "
                      f"instead of the file — confirmed this happens on every linked PDF tested "
                      f"(current and historical), with no server-side bypass found (?wbdisable=true, "
                      f"a second request with the session cookie set, and an Accept: application/pdf "
                      f"header were all tried and still redirect). The interstitial's own HTML "
                      f"contains a link back to the same blocked URL, suggesting the real bypass is a "
                      f"client-side JS interaction (e.g. a one-time consent flag) this scraper can't "
                      f"replicate — same blocker class as NPRI's SPA-gated bulk archive "
                      f"(see DATA_CHECKLIST.md Goal 6). Not forced further.")
        rs.record_backfill(
            "open-government", "public_accounts",
            covered_years=sorted(all_years), row_count=saved,
            extraction_validated=saved > 0,
            notes=notes,
        )
        print(f"[public_accounts] saved={saved}/{len(links)} blocked={blocked} years={sorted(all_years)}")


# ── StatCan — selected bulk tables ───────────────────────────────────────
# Hand-picked across sectors the platform actually covers (mining, energy,
# trade, telecom, transport, housing, agriculture, infrastructure, natural
# resources), drawn from the 277 catalogue entries Goal 5 already classified
# "high" relevance — not the full 8,213-cube catalogue.
STATCAN_TABLES = {
    "16100031": "Mining industries, principal statistics by industry, Canada",
    "16100029": "Mining industries, energy consumption expenses by industry, Canada",
    "10100023": "Canadian government finance statistics for government business enterprises, by industry",
    "36100669": "Wireless telecommunications carriers industry economic impact",
    "12100071": "Trade in goods by importer characteristics, by enterprise employment size and number of partner countries",
    "12100091": "Trade in goods by exporter characteristics, by enterprise employment size and number of partner countries",
    "12100092": "Trade in goods by exporter characteristics, by industry of enterprise and number of partner countries",
    "23100057": "Railway industry summary statistics on freight and passenger transportation",
    "36100679": "Housing Economic Account, economic impact by asset, industry, and housing type",
    "36100213": "Natural resources, the terms of trade, and real income growth in Canada",
    "36100460": "Natural resources satellite account, employment",
    "36100608": "Infrastructure Economic Accounts, investment and net stock by asset, industry, and asset function",
    "32100215": "Employees in the agriculture sector, and agricultural operations with at least one employee, by industry",
    "14100104": "Employment by Indigenous group and occupation",
    "16100032": "Mining industries, principal statistics by industry, by province",
    "27100356": "Innovations with environmental benefits, by industry and enterprise size",
}


async def backfill_statcan() -> None:
    async with httpx.AsyncClient(timeout=120, headers=_HEADERS, follow_redirects=True) as client:
        for pid, title in STATCAN_TABLES.items():
            source_id = f"statcan_{pid}"
            try:
                resolve = await client.get(f"https://www150.statcan.gc.ca/t1/wds/rest/getFullTableDownloadCSV/{pid}/en")
                resolve.raise_for_status()
                payload = resolve.json()
                if payload.get("status") != "SUCCESS":
                    print(f"  [statcan_{pid}] resolve failed: {payload}")
                    continue
                zip_url = payload["object"]
                content = await _get_bytes(client, zip_url)
            except Exception as exc:
                print(f"  [statcan_{pid}] FAILED: {exc}")
                continue

            save_result = rs.save_raw("statcan", source_id, f"{pid}-eng.zip", content, source_url=zip_url)
            save_result["category"], save_result["source_id"] = "statcan", source_id
            extract = rs.extract_zip(save_result)

            row_count = 0
            years: set[int] = set()
            if extract["extraction_validated"]:
                for f in extract["files"]:
                    if f["name"].lower().endswith(".csv"):
                        p = Path(extract["extracted_path"]) / f["name"]
                        try:
                            row_count += rs.count_csv_rows(p, encoding="utf-8")
                        except Exception:
                            pass

            rs.record_backfill(
                "statcan", source_id,
                row_count=row_count, extraction_validated=extract["extraction_validated"],
                source_checksum=save_result["checksum"], source_size_bytes=save_result["size"],
                notes=f"{title} (pid {pid}). {extract.get('reason', '')}",
            )
            print(f"[statcan_{pid}] rows={row_count} validated={extract['extraction_validated']} "
                  f"size={save_result['size']}")


# ── Bank of Canada — selected series groups ──────────────────────────────
# Valet API "groups" are BoC's own curated series bundles (2,445 exist —
# mostly per-speech-chart). These 7 are the genuine macro/political-risk
# bundles: FX rates, CPI, the overnight rate (CORRA), bond and T-bill yields.
BOC_GROUPS = {
    "boc_fx_rates_daily": "FX_RATES_DAILY",
    "boc_fx_rates_monthly": "FX_RATES_MONTHLY",
    "boc_fx_rates_annual": "FX_RATES_ANNUAL",
    "boc_cpi_monthly": "CPI_MONTHLY",
    "boc_corra": "CORRA",
    "boc_bond_yields_benchmark": "bond_yields_benchmark",
    "boc_tbill_yields": "TBILL_ALL",
}


async def backfill_bank_of_canada() -> None:
    async with httpx.AsyncClient(timeout=120, headers=_HEADERS, follow_redirects=True) as client:
        for source_id, group in BOC_GROUPS.items():
            url = f"https://www.bankofcanada.ca/valet/observations/group/{group}/csv"
            try:
                r = await client.get(url, params={"start_date": "1990-01-01"})
                r.raise_for_status()
                content = r.content
            except Exception as exc:
                print(f"  [{source_id}] FAILED: {exc}")
                continue

            result = rs.save_raw("bank-of-canada", source_id, f"{group}.csv", content, source_url=url)
            text = content.decode("utf-8-sig", errors="replace")
            lines = text.splitlines()
            date_lines = [l for l in lines if re.match(r'^"?\d{4}-\d{2}-\d{2}"?,', l)]
            years = sorted({int(l[1:5]) if l.startswith('"') else int(l[:4]) for l in date_lines})
            row_count = len(date_lines)

            rs.record_backfill(
                "bank-of-canada", source_id,
                covered_years=years, row_count=row_count, extraction_validated=row_count > 0,
                source_checksum=result["checksum"], source_size_bytes=result["size"],
                notes=f"Valet group '{group}' bulk observations CSV (plain CSV, no zip).",
            )
            print(f"[{source_id}] rows={row_count} years={years[:1]}..{years[-1:] if years else []} "
                  f"size={result['size']}")


# ── NRCan geospatial — selected tabular datasets ─────────────────────────
# NRCan's geospatial catalogue (301 entries from Goal 5) is dominated by
# raster maps, ESRI REST endpoints, and multi-GB LiDAR point clouds — not
# structured bulk data in the CSV/table sense this goal is backfilling.
# These are the genuinely tabular CSV resources in that catalogue (English
# only where an EN/FR pair exists, by filename prefix).
NRCAN_CSV_URLS = [
    "https://open.canada.ca/data/dataset/98f1a129-f628-4ce4-b24d-6f16bf24dd64/resource/9df1b18d-d036-4783-a61c-99f1f75b3ac5/download/my2026-fuel-consumption-ratings.csv",
    "https://open.canada.ca/data/dataset/98f1a129-f628-4ce4-b24d-6f16bf24dd64/resource/d589f2bc-9a85-4f65-be2f-20f17debfcb1/download/my2025-fuel-consumption-ratings.csv",
    "https://open.canada.ca/data/dataset/98f1a129-f628-4ce4-b24d-6f16bf24dd64/resource/c98b9dc8-b23f-4cd8-8b19-e892da1e4688/download/my2015-2024-fuel-consumption-ratings.csv",
    "https://open.canada.ca/data/dataset/98f1a129-f628-4ce4-b24d-6f16bf24dd64/resource/42495676-28b7-40f3-b0e0-3d7fe005ca56/download/my1995-2014-fuel-consumption-ratings-5-cycle.csv",
    "https://open.canada.ca/data/dataset/98f1a129-f628-4ce4-b24d-6f16bf24dd64/resource/29bcf157-9297-4d6a-9695-dfd816bc32ca/download/original-my1995-2014-fuel-consumption-ratings-2-cycle.csv",
    "https://open.canada.ca/data/dataset/98f1a129-f628-4ce4-b24d-6f16bf24dd64/resource/026e45b4-eb63-451f-b34f-d9308ea3a3d9/download/my2012-2026-battery-electric-vehicles.csv",
    "https://open.canada.ca/data/dataset/98f1a129-f628-4ce4-b24d-6f16bf24dd64/resource/8812228b-a6aa-4303-b3d0-66489225120d/download/my2012-2026-plug-in-hybrid-electric-vehicles.csv",
    "https://ftp.maps.canada.ca/pub/nrcan_rncan/Environmental-programs_Programme-relatif-a-l-environnement/esrf_fee/ESRF_FEE_EN_Levies.csv",
    "https://open.canada.ca/data/dataset/ae59f8ee-42f8-4946-9622-058d1e789113/resource/97fa5898-690d-4c47-a5f2-c40665057ed7/download/gscpermafrostpublicationcompilation-cgccompilationpublicationpergelisol.csv",
]


async def backfill_nrcan_geospatial() -> None:
    await _backfill_csv_list("geospatial", "nrcan_geospatial_selected", NRCAN_CSV_URLS,
                              skip_substring=None)


# ── Transport Canada — selected bulk datasets ────────────────────────────
# Same scoping logic as NRCan: real CSV bulk files (EVAP/iMHZEV/iZEV program
# stats, vehicle recalls, CADORS aviation occurrences, TDG schedule, safety
# mark registry, fleet fuel use, small compliance-audit datasets), excluding
# PDF/XLSX/ESRI-REST/HTML catalogue noise. English only where an EN/FR pair
# exists.
TRANSPORT_CSV_URLS = [
    "https://opendatatc.tc.canada.ca/CADORS_Occurrence_Category.csv",
    "https://opendatatc.tc.canada.ca/CADORS_Occurrence_Information.csv",
    "https://opendatatc.tc.canada.ca/vrdb_full_monthly.csv",
    "https://opendatatc.tc.canada.ca/vrdb_60days_daily.csv",
    "https://opendatatc.tc.canada.ca/VMRTCDaily.csv",
    "https://opendatatc.tc.canada.ca/TDGR_SCHEDULE1_ENG.csv",
    "https://open.canada.ca/data/dataset/23344072-7118-4715-84a9-daf630ec76c8/resource/4252857a-9e5f-47f9-98b1-1291e8f9f692/download/evap-may-2026-webstats-en.csv",
    "https://open.canada.ca/data/dataset/d99abc15-afb0-471e-b2a2-8d00d8caac2d/resource/35f22f26-ab26-401b-8609-34f2f85b8a7c/download/imhzev-webstats_fy-2024-25_en_updated-november-2025.csv",
    "https://open.canada.ca/data/dataset/d99abc15-afb0-471e-b2a2-8d00d8caac2d/resource/7f5c8098-2edc-4b49-9112-37c0e149f7c5/download/imhzev-webstats_fy-2025-26_en_updated-february-2026.csv",
    "https://open.canada.ca/data/dataset/42986a95-be23-436e-af15-7c6bf292a2e1/resource/bba4c959-53ca-4d23-9cde-da3ce771bba2/download/izev-webstats_fy-2019-20-to-fy-2022-23_en_updated-november-2025.csv",
    "https://open.canada.ca/data/dataset/42986a95-be23-436e-af15-7c6bf292a2e1/resource/33f35447-fd93-45bc-866c-866aba4b2f4e/download/izev-webstats_fy-2023-24_en_updated-november-2025.csv",
    "https://open.canada.ca/data/dataset/42986a95-be23-436e-af15-7c6bf292a2e1/resource/167cec08-777a-4b29-a3a7-eda79f799bae/download/izev-webstats_fy-2024-25_en_updated-november-2025.csv",
    "https://open.canada.ca/data/dataset/2142e30d-9275-424d-be43-f5cc7ec91916/resource/958ae878-72c6-42d8-b59a-f63a6a161b5f/download/aircraft-fleet-monthly-fuel-cost-and-consumption-by-region-or-group.csv",
    "https://open.canada.ca/data/dataset/4eb6f99f-fbe6-43d9-95c1-4c623cc747e5/resource/a5fba6c4-4dcd-4876-92bd-335b634c4710/download/recycle-stations-and-waste-bins-audits.csv",
    "https://open.canada.ca/data/dataset/ef91d197-7cdc-4864-a8c3-5dbbd88154e2/resource/0b42da56-13bd-4d41-b0e4-75c5c0d840a0/download/whmis-label-and-cleaning-room-audits.csv",
    "https://open.canada.ca/data/dataset/24bb7612-4483-43cd-a469-11d8d4c20f2e/resource/9e4a87ba-6965-48f0-9514-53c48efad21c/download/hazardous-waste-station-audits.csv",
    "https://open.canada.ca/data/dataset/e718cfd5-206f-44c0-b8bb-ebe475a578f4/resource/5e34d392-9ce4-4fc1-ba4f-9fb686df91ca/download/hazardous-waste-inventory-audit.csv",
]


async def backfill_transport_canada() -> None:
    await _backfill_csv_list("transport-canada", "transport_canada_selected", TRANSPORT_CSV_URLS,
                              skip_substring=None)


async def _backfill_csv_list(category: str, source_id: str, urls: list[str], *, skip_substring: str | None) -> None:
    saved = 0
    total_rows = 0
    all_years: set[int] = set()
    failures: list[str] = []
    async with httpx.AsyncClient(timeout=120, headers=_HEADERS, follow_redirects=True) as client:
        for url in urls:
            filename = url.rsplit("/", 1)[-1].split("?")[0]
            try:
                content = await _get_bytes(client, url)
            except Exception as exc:
                print(f"  [{source_id}] FAILED {filename}: {exc}")
                failures.append(filename)
                continue
            if content[:1] == b"<":
                print(f"  [{source_id}] SKIPPED {filename}: looks like an HTML page, not CSV data")
                failures.append(filename)
                continue
            result = rs.save_raw(category, source_id, filename, content, source_url=url)
            try:
                rows = rs.count_csv_rows(Path(result["path"]), encoding="utf-8")
            except Exception:
                try:
                    rows = rs.count_csv_rows(Path(result["path"]), encoding="latin-1")
                except Exception:
                    rows = 0
            total_rows += rows
            all_years.update(_years_from_text(filename))
            saved += 1
            print(f"  [{source_id}] saved {filename}: rows={rows} size={result['size']}")

    rs.record_backfill(
        category, source_id,
        covered_years=sorted(all_years), row_count=total_rows,
        extraction_validated=saved > 0,
        notes=(f"Hand-curated selection of real tabular CSV datasets from the Goal 5 "
               f"catalogue (not the full catalogue — see module docstring). "
               f"{saved}/{len(urls)} files saved. Failures: {failures or 'none'}."),
    )
    print(f"[{source_id}] TOTAL saved={saved}/{len(urls)} rows={total_rows} years={sorted(all_years)}")


SOURCES = {
    "gc_infobase": backfill_gc_infobase,
    "public_accounts": backfill_public_accounts,
    "statcan": backfill_statcan,
    "bank_of_canada": backfill_bank_of_canada,
    "nrcan_geospatial": backfill_nrcan_geospatial,
    "transport_canada": backfill_transport_canada,
}


async def main(which: str) -> None:
    targets = list(SOURCES) if which == "all" else [which]
    for name in targets:
        if name not in SOURCES:
            print(f"Unknown source {name!r}. Valid: {', '.join(SOURCES)}, all")
            raise SystemExit(2)
        print(f"=== {name} ===")
        await SOURCES[name]()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "all"))
