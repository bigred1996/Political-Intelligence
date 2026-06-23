"""Conditional-fetch gate: skip a full bulk download when the source hasn't
changed (Goal 11).

Every full-snapshot bulk source in this codebase (contracts, donations,
grants, OCL communications/registrations, GIC appointments) re-downloads and
re-parses its ENTIRE upstream file on every scheduled run, even though the
government republishes most of these on a monthly/quarterly cycle — DATA_
CHECKLIST.md flagged this explicitly: "no connector does a real conditional
fetch ... real ETag/Last-Modified/cursor-based incremental fetch is still
unbuilt everywhere." Tasks.md is equally direct: "Prefer release-driven
checks, ETags, Last-Modified headers and source metadata over unnecessary
full downloads."

This module is that check. A connector calls `fingerprint_ckan_resource()` or
`fingerprint_url()` BEFORE downloading — both are single cheap requests (CKAN
package_show already returns resource metadata; a plain HEAD for direct
URLs) — then `unchanged(source_id, fp)` against the last recorded fingerprint
in pipeline.raw_storage's checkpoint store. Tightening a source's cadence
(e.g. lobbying communications from monthly to daily, per Goal 11's policy
table) is then safe and cheap: most scheduled fires are a single HEAD/
package_show call that finds nothing new and returns immediately, instead of
a full multi-hundred-MB re-pull.

This does NOT replace per-row dedup (existence-check upserts, delete-then-
reinsert) — those still apply to whatever the connector decides IS new
content. It only decides whether to bother fetching that content at all.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
import structlog

from pipeline.raw_storage import read_checkpoint, write_checkpoint

log = structlog.get_logger()

CKAN_API = "https://open.canada.ca/data/api/3/action"


@dataclass(frozen=True)
class ResourceFingerprint:
    """The cheap signal used to decide whether a resource is worth downloading.

    `last_modified` and `size` are the two fields government CKAN resources
    and plain HTTP servers actually populate reliably; `etag`/`hash` are used
    when present but never required. `url` is included because a rotated
    resource URL (these do rotate — see ingest.py's _resolve_ocl_reg_url) is
    itself a signal of change even if every other field is missing.
    """
    url: str | None
    last_modified: str | None = None
    size: int | None = None
    etag: str | None = None
    hash: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"url": self.url, "last_modified": self.last_modified,
                "size": self.size, "etag": self.etag, "hash": self.hash}


async def fingerprint_ckan_resource(dataset_id: str, *, fmt: str = "CSV",
                                     name_hint: str | None = None,
                                     pick: str = "first") -> ResourceFingerprint:
    """Resolve a CKAN dataset's resource and fingerprint it from package_show
    metadata alone — no extra HEAD request, since CKAN already returns
    `last_modified`/`size`/`hash` per resource in the same call every
    resolve_resource_url()-style helper in this codebase already makes.

    `pick="largest"` mirrors the grants/registrations "don't grab the tiny
    placeholder CSV" fix; `pick="first"` mirrors the simpler contracts/OCL
    comms resolvers that match by name or take the first CSV.

    A failed CKAN call (timeout, non-200, rotated dataset id) returns a
    blank fingerprint rather than raising — same fail-open rule as
    fingerprint_url(): an unreadable signal must never be mistaken for "no
    change", or a real fetch silently stops happening.
    """
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
            r = await c.get(f"{CKAN_API}/package_show", params={"id": dataset_id})
            r.raise_for_status()
            resources = r.json()["result"]["resources"]
    except Exception as exc:
        log.warning("fingerprint_ckan_resource_failed", dataset_id=dataset_id, error=str(exc))
        return ResourceFingerprint(url=None)

    candidates = [res for res in resources if (res.get("format") or "").upper() == fmt.upper()]
    if name_hint:
        named = [res for res in candidates if name_hint.lower() in (res.get("name") or "").lower()]
        if named:
            candidates = named
    if not candidates:
        return ResourceFingerprint(url=None)

    res = max(candidates, key=lambda r: r.get("size") or 0) if pick == "largest" else candidates[0]
    return ResourceFingerprint(
        url=res.get("url"), last_modified=res.get("last_modified") or res.get("metadata_modified"),
        size=res.get("size"), hash=res.get("hash") or None,
    )


async def fingerprint_url(url: str, *, headers: dict[str, str] | None = None) -> ResourceFingerprint:
    """Fingerprint a direct (non-CKAN) URL via HTTP HEAD — e.g. Elections
    Canada's hardcoded donations ZIP, which has no CKAN dataset record."""
    try:
        async with httpx.AsyncClient(timeout=20, headers=headers, follow_redirects=True) as c:
            r = await c.head(url)
            if r.status_code >= 400:
                return ResourceFingerprint(url=url)
            size = int(r.headers["content-length"]) if "content-length" in r.headers else None
            return ResourceFingerprint(url=url, last_modified=r.headers.get("last-modified"),
                                       size=size, etag=r.headers.get("etag"))
    except Exception as exc:
        log.warning("fingerprint_url_head_failed", url=url, error=str(exc))
        return ResourceFingerprint(url=url)


_KEY = "_conditional_fetch_fingerprint"


def unchanged(source_id: str, fp: ResourceFingerprint) -> bool:
    """True if `fp` matches the fingerprint recorded after the last
    successful fetch for this source — i.e. nothing worth downloading.

    A fingerprint with every comparable field None (HEAD blocked, CKAN
    lookup failed) is never treated as "unchanged" — an unreadable signal
    must fail open to a real fetch, not silently skip one.
    """
    if fp.last_modified is None and fp.size is None and fp.etag is None and fp.hash is None:
        return False
    checkpoint = read_checkpoint(source_id)
    if not checkpoint or _KEY not in checkpoint:
        return False
    prev = checkpoint[_KEY]
    return (prev.get("url") == fp.url and prev.get("last_modified") == fp.last_modified
            and prev.get("size") == fp.size and prev.get("etag") == fp.etag
            and prev.get("hash") == fp.hash)


def record(source_id: str, fp: ResourceFingerprint, **extra: Any) -> None:
    """Record `fp` as the fingerprint of the last successful fetch, so the
    next sync's unchanged() check has something to compare against."""
    write_checkpoint(source_id, {_KEY: fp.as_dict(), **extra})
