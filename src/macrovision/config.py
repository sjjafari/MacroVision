from functools import lru_cache

from pydantic import Field, model_validator
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
    scheduler_lease_seconds: int = Field(default=300, ge=60, le=1800)
    scheduler_heartbeat_seconds: int = Field(default=60, ge=1, le=599)
    scheduler_poll_seconds: int = Field(default=5, ge=1, le=60)
    scheduler_claim_limit: int = Field(default=10, ge=1, le=10)
    scheduler_maximum_attempts: int = Field(default=2, ge=1, le=3)
    scheduler_retry_base_seconds: int = Field(default=30, ge=1, le=300)
    scheduler_retry_max_seconds: int = Field(default=300, ge=1, le=300)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="MACROVISION_",
        case_sensitive=False,
        extra="forbid",
    )

    @model_validator(mode="after")
    def validate_scheduler_bounds(self) -> "Settings":
        if self.scheduler_heartbeat_seconds * 3 >= self.scheduler_lease_seconds:
            raise ValueError(
                "Scheduler heartbeat interval must be less than one-third of lease duration"
            )
        if self.scheduler_retry_base_seconds > self.scheduler_retry_max_seconds:
            raise ValueError("Scheduler retry base cannot exceed its maximum delay")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
