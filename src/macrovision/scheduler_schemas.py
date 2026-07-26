from datetime import date, datetime, time
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from macrovision.macro_data_models import SeriesCategory

MIN_INTERVAL_MINUTES = 5
MAX_INTERVAL_MINUTES = 525_600
MAX_REQUEST_CONFIG_BYTES = 4096


class ScheduleCadenceType(StrEnum):
    fixed_interval = "fixed_interval"
    daily_utc = "daily_utc"


class ProviderSyncRunStatus(StrEnum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class ProviderSyncTriggerType(StrEnum):
    scheduled = "scheduled"
    manual = "manual"


class SafeProviderSyncConfig(BaseModel):
    """Allowlisted provider synchronization configuration safe for persistence."""

    model_config = ConfigDict(extra="forbid")

    category: SeriesCategory | None = None
    geography: str | None = Field(default=None, min_length=1, max_length=120)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    is_active: bool | None = None
    metadata_notes: str | None = Field(default=None, max_length=1000)
    observation_start: date | None = None
    observation_end: date | None = None
    realtime_start: date | None = None
    realtime_end: date | None = None

    @model_validator(mode="after")
    def validate_ranges(self) -> "SafeProviderSyncConfig":
        if (
            self.observation_start is not None
            and self.observation_end is not None
            and self.observation_end < self.observation_start
        ):
            raise ValueError("observation_end cannot precede observation_start")
        if self.realtime_start is None and self.realtime_end is None:
            return self
        if (
            self.realtime_start is None
            or self.realtime_end is None
            or self.realtime_start != self.realtime_end
        ):
            raise ValueError("Historical synchronization requires one exact realtime date")
        return self


class ScheduleCadence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cadence_type: ScheduleCadenceType
    interval_minutes: int | None = Field(
        default=None,
        ge=MIN_INTERVAL_MINUTES,
        le=MAX_INTERVAL_MINUTES,
    )
    daily_time_utc: time | None = None

    @field_validator("daily_time_utc")
    @classmethod
    def validate_daily_time(cls, value: time | None) -> time | None:
        if value is None:
            return None
        if value.tzinfo is not None:
            raise ValueError("daily_time_utc is already expressed in UTC and cannot have an offset")
        if value.second != 0 or value.microsecond != 0:
            raise ValueError("daily_time_utc must use whole-minute precision")
        return value

    @model_validator(mode="after")
    def validate_shape(self) -> "ScheduleCadence":
        if self.cadence_type == ScheduleCadenceType.fixed_interval:
            if self.interval_minutes is None or self.daily_time_utc is not None:
                raise ValueError("fixed_interval requires only interval_minutes")
        elif self.daily_time_utc is None or self.interval_minutes is not None:
            raise ValueError("daily_utc requires only daily_time_utc")
        return self


class ProviderSyncScheduleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1, max_length=40)
    provider_series_id: str = Field(
        min_length=1,
        max_length=120,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )
    internal_series_code: str | None = Field(
        default=None,
        min_length=1,
        max_length=120,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )
    request_config: SafeProviderSyncConfig = Field(default_factory=SafeProviderSyncConfig)
    cadence_type: ScheduleCadenceType
    interval_minutes: int | None = Field(
        default=None,
        ge=MIN_INTERVAL_MINUTES,
        le=MAX_INTERVAL_MINUTES,
    )
    daily_time_utc: time | None = None
    enabled: bool = True

    @model_validator(mode="after")
    def validate_cadence(self) -> "ProviderSyncScheduleCreate":
        ScheduleCadence(
            cadence_type=self.cadence_type,
            interval_minutes=self.interval_minutes,
            daily_time_utc=self.daily_time_utc,
        )
        return self


class ProviderSyncSchedulePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_lock_version: int = Field(gt=0)
    request_config: SafeProviderSyncConfig | None = None
    cadence_type: ScheduleCadenceType | None = None
    interval_minutes: int | None = Field(
        default=None,
        ge=MIN_INTERVAL_MINUTES,
        le=MAX_INTERVAL_MINUTES,
    )
    daily_time_utc: time | None = None


class ProviderSyncScheduleStateChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_lock_version: int = Field(gt=0)


class ProviderSyncRunNowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=160)


class ProviderSyncScheduleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    provider: str
    provider_series_id: str
    internal_series_code: str | None
    request_config: SafeProviderSyncConfig
    request_config_fingerprint: str
    cadence_type: ScheduleCadenceType
    interval_minutes: int | None
    daily_time_utc: time | None
    next_run_at: datetime | None
    enabled: bool
    last_scheduled_at: datetime | None
    created_at: datetime
    updated_at: datetime
    lock_version: int


class ProviderSyncRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    schedule_id: int
    trigger_type: ProviderSyncTriggerType
    provider: str
    provider_series_id: str
    status: ProviderSyncRunStatus
    scheduled_for: datetime
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    attempt_number: int
    maximum_attempts: int
    next_attempt_at: datetime | None
    observations_received: int
    observations_accepted: int
    observations_revised: int
    observations_missing: int
    observations_rejected: int
    provider_replay: bool | None
    error_code: str | None
    error_message: str | None


def validate_safe_config(value: SafeProviderSyncConfig | dict[str, Any]) -> SafeProviderSyncConfig:
    if isinstance(value, SafeProviderSyncConfig):
        return value
    return SafeProviderSyncConfig.model_validate(value)
