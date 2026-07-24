from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables and an optional .env."""

    environment: str = "development"
    database_url: str = "sqlite:///./macrovision.db"
    log_level: str = "INFO"
    max_import_rows: int = 1000
    max_import_notes_length: int = 2000
    max_import_error_message_length: int = 500
    fred_api_key: str | None = None
    fred_base_url: str = "https://api.stlouisfed.org/fred"
    provider_request_timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    provider_max_observations: int = Field(default=10000, gt=0, le=100000)
    provider_max_response_bytes: int = Field(default=5_000_000, gt=0, le=50_000_000)
    provider_max_retries: int = Field(default=2, ge=0, le=5)
    enable_live_fred_tests: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="MACROVISION_",
        case_sensitive=False,
        extra="forbid",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
