from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol


class ProviderErrorCode(StrEnum):
    configuration_error = "provider_configuration_error"
    authentication_failed = "provider_authentication_failed"
    series_not_found = "provider_series_not_found"
    timeout = "provider_timeout"
    rate_limited = "provider_rate_limited"
    unavailable = "provider_unavailable"
    malformed_response = "provider_malformed_response"
    unsupported_metadata = "provider_unsupported_metadata"
    response_too_large = "provider_response_too_large"


class ProviderFrequency(StrEnum):
    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"
    quarterly = "quarterly"
    annual = "annual"
    irregular = "irregular"


class ProviderSeasonalAdjustment(StrEnum):
    adjusted = "adjusted"
    not_adjusted = "not_adjusted"
    not_applicable = "not_applicable"
    unknown = "unknown"


class ProviderError(Exception):
    def __init__(self, code: ProviderErrorCode, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class ProviderIdentity:
    code: str
    name: str
    reference_url: str


@dataclass(frozen=True)
class ProviderSeriesMetadata:
    provider_series_id: str
    title: str
    description: str
    frequency: ProviderFrequency
    unit: str
    seasonal_adjustment: ProviderSeasonalAdjustment
    observation_start: date | None
    observation_end: date | None
    realtime_start: date | None
    realtime_end: date | None
    provider_metadata: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProviderObservation:
    observed_on: date
    value: Decimal | None
    is_missing: bool
    publication_timestamp: datetime | None
    vintage_start: date | None
    vintage_end: date | None
    source_reference: str
    provider_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ObservationQuery:
    observation_start: date | None = None
    observation_end: date | None = None
    realtime_start: date | None = None
    realtime_end: date | None = None


@dataclass(frozen=True)
class SeriesMetadataQuery:
    realtime_start: date | None = None
    realtime_end: date | None = None


@dataclass(frozen=True)
class ProviderHealth:
    available: bool
    checked_at: datetime


class ExternalDataProvider(Protocol):
    @property
    def identity(self) -> ProviderIdentity: ...

    def get_series_metadata(
        self, series_id: str, query: SeriesMetadataQuery | None = None
    ) -> ProviderSeriesMetadata: ...

    def get_observations(
        self, series_id: str, query: ObservationQuery
    ) -> Sequence[ProviderObservation]: ...

    def check_health(self) -> ProviderHealth: ...
