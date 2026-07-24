from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables and an optional .env."""

    environment: str = "development"
    database_url: str = "sqlite:///./macrovision.db"
    log_level: str = "INFO"
    max_import_rows: int = 1000
    max_import_notes_length: int = 2000
    max_import_error_message_length: int = 500

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="MACROVISION_",
        case_sensitive=False,
        extra="forbid",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
