"""Small in-process cache invalidation helpers.

Nessus intentionally avoids Redis or a second cache service in the MVP. The
workspace caches are short-lived process memory, so ingestion jobs just clear
them after successful writes.
"""
from __future__ import annotations

import structlog

log = structlog.get_logger()


def invalidate_workspace_caches(reason: str = "data_refresh") -> None:
    """Clear all API caches that summarize mutable source data."""
    try:
        from api.routes.overview import clear_overview_cache
        from api.routes.sectors import clear_sector_cache
        from api.routes.sources import clear_sources_status_cache

        clear_overview_cache()
        clear_sector_cache()
        clear_sources_status_cache()
        log.info("workspace_caches_invalidated", reason=reason)
    except Exception as exc:  # defensive: cache clearing must not fail ingest jobs
        log.warning("workspace_cache_invalidation_failed", reason=reason, error=str(exc))
