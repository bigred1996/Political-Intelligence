"""Central settings, loaded from .env."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    database_url: str = "sqlite+aiosqlite:///./polaris.db"
    report_storage_path: str = "./reports"

    ocl_base_url: str = "https://lobbycanada.gc.ca"
    elections_canada_base_url: str = "https://www.elections.ca"
    contracts_base_url: str = "https://search.open.canada.ca"

    anthropic_api_key: str | None = None
    # Default model for the high-volume structured steps (B2 interpretation,
    # B3 planner). Sonnet is the quality/cost workhorse for per-record extraction.
    claude_model: str = "claude-sonnet-4-6"
    # The single cross-finding synthesis call (B3) is where report quality is
    # decided, so it runs on the stronger model. One call per report, so the
    # extra cost is negligible. Override via SYNTHESIS_MODEL in .env.
    synthesis_model: str = "claude-opus-4-8"


settings = Settings()
