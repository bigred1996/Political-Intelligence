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
    claude_model: str = "claude-sonnet-4-6"


settings = Settings()
