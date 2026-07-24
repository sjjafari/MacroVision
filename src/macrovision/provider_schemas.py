from datetime import date
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from macrovision.macro_data_models import SeriesCategory


class ProviderSeriesSyncRequest(BaseModel):
    internal_series_code: str | None = Field(
        default=None,
        min_length=1,
        max_length=120,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )
    category: SeriesCategory | None = None
    geography: str | None = Field(default=None, min_length=1, max_length=120)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    is_active: bool | None = None
    metadata_notes: str | None = Field(default=None, max_length=1000)
    observation_start: date | None = None
    observation_end: date | None = None
    realtime_start: date | None = None
    realtime_end: date | None = None
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=160)
    expected_lock_version: int | None = Field(default=None, gt=0)

    @field_validator("observation_end")
    @classmethod
    def validate_observation_range(cls, value: date | None, info: Any) -> date | None:
        start = info.data.get("observation_start")
        if value is not None and start is not None and value < start:
            raise ValueError("observation_end cannot precede observation_start")
        return value

    @field_validator("realtime_end")
    @classmethod
    def validate_realtime_range(cls, value: date | None, info: Any) -> date | None:
        start = info.data.get("realtime_start")
        if value is not None and start is not None and value < start:
            raise ValueError("realtime_end cannot precede realtime_start")
        return value


class FREDSeriesSyncRequest(ProviderSeriesSyncRequest):
    @model_validator(mode="after")
    def require_point_in_time_vintage(self) -> "FREDSeriesSyncRequest":
        if self.realtime_start is None and self.realtime_end is None:
            return self
        if (
            self.realtime_start is None
            or self.realtime_end is None
            or self.realtime_start != self.realtime_end
        ):
            raise ValueError("Historical FRED synchronization supports one exact realtime date")
        return self


class ProviderSyncResult(BaseModel):
    provider: str
    provider_series_id: str
    source_id: int
    series_id: int
    import_batch_id: int
    synchronization_status: str
    observations_received: int
    observations_accepted: int
    observations_revised: int
    observations_missing: int
    observations_rejected: int
    idempotent_replay: bool
    warnings: list[str]
    request_metadata: dict[str, Any]
