import logging
from collections.abc import Iterator, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from macrovision import macro_data_services
from macrovision.config import Settings, get_settings
from macrovision.fred_provider import FREDProvider
from macrovision.macro_data_models import (
    DataImportBatch,
    DataObservation,
    DataRevision,
    DataSeries,
    DataSource,
    ObservationStatus,
)
from macrovision.macro_data_services import DataConflictError
from macrovision.main import app
from macrovision.provider_api import get_fred_provider
from macrovision.provider_contracts import (
    ObservationQuery,
    ProviderError,
    ProviderErrorCode,
    ProviderFrequency,
    ProviderHealth,
    ProviderIdentity,
    ProviderObservation,
    ProviderSeasonalAdjustment,
    ProviderSeriesMetadata,
    SeriesMetadataQuery,
)
from macrovision.provider_schemas import FREDSeriesSyncRequest
from macrovision.provider_services import synchronize_provider_series


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "fred_api_key": "top-secret",
        "provider_max_retries": 0,
        "provider_max_observations": 100,
        "provider_max_response_bytes": 100_000,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.mark.parametrize(
    "override",
    [
        {"provider_request_timeout_seconds": 0},
        {"provider_request_timeout_seconds": float("nan")},
        {"provider_request_timeout_seconds": 121},
        {"provider_max_observations": 0},
        {"provider_max_observations": 100001},
        {"provider_max_response_bytes": -1},
        {"provider_max_response_bytes": 50_000_001},
        {"provider_max_retries": -1},
        {"provider_max_retries": 6},
    ],
)
def test_provider_configuration_limits_fail_safely(override: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _settings(**override)


def test_unknown_provider_configuration_remains_forbidden() -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({"unknown_provider_setting": "unsafe"})


def _metadata_response(**overrides: Any) -> dict[str, Any]:
    row = {
        "id": "GDP",
        "title": "Gross Domestic Product",
        "notes": "Quarterly GDP",
        "frequency": "Quarterly",
        "frequency_short": "Q",
        "units": "Billions of Dollars",
        "units_short": "Bil. of $",
        "seasonal_adjustment": "Seasonally Adjusted Annual Rate",
        "seasonal_adjustment_short": "SA",
        "observation_start": "1947-01-01",
        "observation_end": "2026-01-01",
        "realtime_start": "2026-07-24",
        "realtime_end": "2026-07-24",
        "last_updated": "2026-07-24 07:45:00-05",
    }
    row.update(overrides)
    return {"seriess": [row]}


def _observations_response(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"count": len(rows), "observations": rows}


def test_fred_metadata_and_decimal_observation_normalization() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.scheme == "https"
        assert request.headers["accept"] == "application/json"
        assert request.url.params["file_type"] == "json"
        if request.url.path.endswith("/series"):
            return httpx.Response(200, json=_metadata_response())
        return httpx.Response(
            200,
            json=_observations_response(
                [
                    {
                        "date": "2025-01-01",
                        "value": "123.12345678",
                        "realtime_start": "2025-02-01",
                        "realtime_end": "2025-03-01",
                    },
                    {
                        "date": "2025-04-01",
                        "value": "-2.50000000",
                        "realtime_start": "2025-05-01",
                        "realtime_end": "2025-05-01",
                    },
                    {
                        "date": "2025-07-01",
                        "value": ".",
                        "realtime_start": "2025-08-01",
                        "realtime_end": "2025-08-01",
                    },
                ]
            ),
        )

    provider = FREDProvider(_settings(), transport=httpx.MockTransport(handler))
    metadata = provider.get_series_metadata("GDP")
    observations = provider.get_observations("GDP", ObservationQuery())
    provider.close()
    assert metadata.frequency == ProviderFrequency.quarterly
    assert metadata.realtime_start == date(2026, 7, 24)
    assert observations[0].value == Decimal("123.12345678")
    assert observations[1].value == Decimal("-2.50000000")
    assert observations[2].value is None
    assert observations[2].is_missing


def test_exponent_notation_is_parsed_as_decimal_without_float() -> None:
    provider = FREDProvider(
        _settings(),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json=_observations_response([{"date": "2025-01-01", "value": "1.25E+2"}]),
            )
        ),
    )
    observation = provider.get_observations("GDP", ObservationQuery())[0]
    assert observation.value == Decimal("125")


def test_precision_beyond_eight_decimals_is_rejected_atomically(
    db_session: Session,
) -> None:
    provider = StubFREDProvider(value=Decimal("1.123456789"))
    with pytest.raises(ProviderError) as caught:
        synchronize_provider_series(db_session, provider, "PRECISION", FREDSeriesSyncRequest())
    assert caught.value.code == ProviderErrorCode.malformed_response
    assert db_session.scalar(select(func.count(DataImportBatch.id))) == 0


@pytest.mark.parametrize("value", ["NaN", "Infinity", "not-a-number"])
def test_fred_rejects_invalid_or_nonfinite_values(value: str) -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            json=_observations_response(
                [
                    {
                        "date": "2025-01-01",
                        "value": value,
                        "realtime_start": "2025-02-01",
                        "realtime_end": "2025-02-01",
                    }
                ]
            ),
        )
    )
    provider = FREDProvider(_settings(), transport=transport)
    with pytest.raises(ProviderError) as caught:
        provider.get_observations("GDP", ObservationQuery())
    assert caught.value.code == ProviderErrorCode.malformed_response
    assert "top-secret" not in str(caught.value)


def test_fred_retries_rate_limit_and_respects_retry_after() -> None:
    attempts = 0
    delays: list[float] = []

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "2"}, text="secret upstream body")
        return httpx.Response(200, json=_metadata_response())

    provider = FREDProvider(
        _settings(provider_max_retries=1),
        transport=httpx.MockTransport(handler),
        sleep=delays.append,
    )
    assert provider.get_series_metadata("GDP").provider_series_id == "GDP"
    assert attempts == 2
    assert delays == [2]


@pytest.mark.parametrize(
    ("retry_after", "expected"),
    [
        ("-1", 0),
        ("nan", 0),
        ("999", 30),
        ("malformed", 0),
    ],
)
def test_fred_malformed_retry_after_is_safely_bounded(retry_after: str, expected: float) -> None:
    attempts = 0
    delays: list[float] = []

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": retry_after})
        return httpx.Response(200, json=_metadata_response())

    provider = FREDProvider(
        _settings(provider_max_retries=1),
        transport=httpx.MockTransport(handler),
        sleep=delays.append,
    )
    provider.get_series_metadata("GDP")
    assert delays == [expected]


def test_fred_http_date_retry_after_is_supported() -> None:
    attempts = 0
    delays: list[float] = []
    retry_at = (datetime.now(UTC) + timedelta(seconds=5)).strftime("%a, %d %b %Y %H:%M:%S GMT")

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, headers={"Retry-After": retry_at})
        return httpx.Response(200, json=_metadata_response())

    provider = FREDProvider(
        _settings(provider_max_retries=1),
        transport=httpx.MockTransport(handler),
        sleep=delays.append,
    )
    provider.get_series_metadata("GDP")
    assert len(delays) == 1
    assert 0 <= delays[0] <= 5


@pytest.mark.parametrize(
    ("status_code", "expected_code"),
    [
        (403, ProviderErrorCode.authentication_failed),
        (400, ProviderErrorCode.series_not_found),
        (429, ProviderErrorCode.rate_limited),
        (503, ProviderErrorCode.unavailable),
    ],
)
def test_fred_sanitizes_permanent_and_exhausted_errors(
    status_code: int, expected_code: ProviderErrorCode
) -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(status_code, text="top-secret raw upstream payload")

    provider = FREDProvider(
        _settings(provider_max_retries=2),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ProviderError) as caught:
        provider.get_series_metadata("GDP")
    assert caught.value.code == expected_code
    assert "top-secret" not in str(caught.value)
    assert "raw upstream" not in str(caught.value)
    expected_attempts = 3 if status_code in {429, 503} else 1
    assert attempts == expected_attempts


def test_fred_timeout_retry_exhaustion() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("contains-secret", request=request)

    provider = FREDProvider(
        _settings(provider_max_retries=1),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ProviderError) as caught:
        provider.get_series_metadata("GDP")
    assert attempts == 2
    assert caught.value.code == ProviderErrorCode.timeout
    assert "contains-secret" not in str(caught.value)


def test_http_exception_and_logging_paths_redact_credentials(
    caplog: pytest.LogCaptureFixture,
) -> None:
    api_key = "credential-that-must-not-appear"

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"failed request {request.url}", request=request)

    provider = FREDProvider(
        _settings(fred_api_key=api_key),
        transport=httpx.MockTransport(handler),
    )
    with caplog.at_level(logging.DEBUG), pytest.raises(ProviderError) as caught:
        provider.get_series_metadata("GDP")
    assert api_key not in str(caught.value)
    assert api_key not in repr(caught.value)
    assert api_key not in caplog.text
    assert caught.value.__cause__ is None


def test_redirect_is_not_followed_and_cannot_forward_credentials() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(302, headers={"Location": "http://attacker.invalid/collect"})

    provider = FREDProvider(
        _settings(),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ProviderError) as caught:
        provider.get_series_metadata("GDP")
    assert caught.value.code == ProviderErrorCode.unavailable
    assert len(requests) == 1
    assert requests[0].url.host == "api.stlouisfed.org"


def test_fred_transient_transport_retry_succeeds() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectError("temporary", request=request)
        return httpx.Response(200, json=_metadata_response())

    provider = FREDProvider(
        _settings(provider_max_retries=1),
        transport=httpx.MockTransport(handler),
    )
    assert provider.get_series_metadata("GDP").title == "Gross Domestic Product"
    assert attempts == 2


def test_fred_rejects_malformed_and_oversized_responses() -> None:
    malformed = FREDProvider(
        _settings(),
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"{")),
    )
    with pytest.raises(ProviderError) as caught:
        malformed.get_series_metadata("GDP")
    assert caught.value.code == ProviderErrorCode.malformed_response

    oversized = FREDProvider(
        _settings(provider_max_response_bytes=3),
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"1234")),
    )
    with pytest.raises(ProviderError) as caught:
        oversized.get_series_metadata("GDP")
    assert caught.value.code == ProviderErrorCode.response_too_large


class CountingStream(httpx.SyncByteStream):
    def __init__(self) -> None:
        self.yielded = 0

    def __iter__(self) -> Iterator[bytes]:
        for chunk in (b"abc", b"def", b"should-not-be-read"):
            self.yielded += 1
            yield chunk


def test_streaming_response_stops_at_byte_limit() -> None:
    stream = CountingStream()
    provider = FREDProvider(
        _settings(provider_max_response_bytes=5),
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream)),
    )
    with pytest.raises(ProviderError) as caught:
        provider.get_series_metadata("GDP")
    assert caught.value.code == ProviderErrorCode.response_too_large
    assert stream.yielded == 2


def test_fred_rejects_excessive_observation_count_and_insecure_url() -> None:
    provider = FREDProvider(
        _settings(provider_max_observations=1),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json=_observations_response(
                    [
                        {"date": "2025-01-01", "value": "1"},
                        {"date": "2025-02-01", "value": "2"},
                    ]
                ),
            )
        ),
    )
    with pytest.raises(ProviderError) as caught:
        provider.get_observations("GDP", ObservationQuery())
    assert caught.value.code == ProviderErrorCode.response_too_large
    with pytest.raises(ProviderError) as caught:
        FREDProvider(_settings(fred_base_url="http://example.test"))
    assert caught.value.code == ProviderErrorCode.configuration_error
    with pytest.raises(ProviderError) as caught:
        FREDProvider(_settings(fred_base_url="https://api.stlouisfed.org.evil/fred"))
    assert caught.value.code == ProviderErrorCode.configuration_error


def test_fred_observation_pagination_and_query_parameters() -> None:
    offsets: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        offsets.append(int(request.url.params["offset"]))
        assert request.url.params["observation_start"] == "2025-01-01"
        assert request.url.params["realtime_start"] == "2025-03-01"
        offset = offsets[-1]
        row = {
            "date": f"2025-0{offset + 1}-01",
            "value": str(offset + 1),
            "realtime_start": "2025-03-01",
            "realtime_end": "2025-03-01",
        }
        return httpx.Response(200, json={"count": 2, "observations": [row]})

    provider = FREDProvider(
        _settings(),
        transport=httpx.MockTransport(handler),
    )
    observations = provider.get_observations(
        "GDP",
        ObservationQuery(
            observation_start=date(2025, 1, 1),
            realtime_start=date(2025, 3, 1),
            realtime_end=date(2025, 3, 1),
        ),
    )
    assert offsets == [0, 1]
    assert [item.value for item in observations] == [Decimal("1"), Decimal("2")]


def test_observation_limit_is_enforced_across_pages() -> None:
    offsets: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params["offset"])
        offsets.append(offset)
        return httpx.Response(
            200,
            json={
                "count": 3,
                "observations": [{"date": f"2025-0{offset + 1}-01", "value": str(offset)}],
            },
        )

    provider = FREDProvider(
        _settings(provider_max_observations=2),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ProviderError) as caught:
        provider.get_observations("GDP", ObservationQuery())
    assert caught.value.code == ProviderErrorCode.response_too_large
    assert offsets == [0, 1, 2]


def test_malformed_pagination_is_rejected_without_looping() -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            200,
            json={"count": "invalid", "observations": [{"date": "2025-01-01", "value": "1"}]},
        )

    provider = FREDProvider(_settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError) as caught:
        provider.get_observations("GDP", ObservationQuery())
    assert caught.value.code == ProviderErrorCode.malformed_response
    assert attempts == 1


def test_fred_rejects_duplicate_observation_dates() -> None:
    rows = [
        {"date": "2025-01-01", "value": "1"},
        {"date": "2025-01-01", "value": "2"},
    ]
    provider = FREDProvider(
        _settings(),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=_observations_response(rows))
        ),
    )
    with pytest.raises(ProviderError) as caught:
        provider.get_observations("GDP", ObservationQuery())
    assert caught.value.code == ProviderErrorCode.malformed_response


def test_fred_rejects_duplicate_metadata_records() -> None:
    first = _metadata_response()["seriess"][0]
    provider = FREDProvider(
        _settings(),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"seriess": [first, dict(first)]})
        ),
    )
    with pytest.raises(ProviderError) as caught:
        provider.get_series_metadata("GDP")
    assert caught.value.code == ProviderErrorCode.malformed_response


def test_fred_rejects_response_scope_mismatch() -> None:
    metadata_provider = FREDProvider(
        _settings(),
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=_metadata_response())),
    )
    with pytest.raises(ProviderError, match="realtime scope"):
        metadata_provider.get_series_metadata(
            "GDP",
            SeriesMetadataQuery(
                realtime_start=date(2020, 1, 1),
                realtime_end=date(2020, 1, 1),
            ),
        )
    observation_provider = FREDProvider(
        _settings(),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json=_observations_response([{"date": "2019-12-01", "value": "1"}]),
            )
        ),
    )
    with pytest.raises(ProviderError, match="outside"):
        observation_provider.get_observations(
            "GDP",
            ObservationQuery(observation_start=date(2020, 1, 1)),
        )


def test_unknown_seasonal_adjustment_is_preserved_with_warning() -> None:
    provider = FREDProvider(
        _settings(),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json=_metadata_response(
                    seasonal_adjustment="Provider-specific method",
                    seasonal_adjustment_short="CUSTOM",
                ),
            )
        ),
    )
    metadata = provider.get_series_metadata("GDP")
    assert metadata.seasonal_adjustment == ProviderSeasonalAdjustment.unknown
    assert metadata.provider_metadata["seasonal_adjustment_label"] == ("Provider-specific method")
    assert metadata.warnings


def test_fred_rejects_unsupported_frequency() -> None:
    provider = FREDProvider(
        _settings(),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json=_metadata_response(frequency="Every lunar cycle", frequency_short="L"),
            )
        ),
    )
    with pytest.raises(ProviderError) as caught:
        provider.get_series_metadata("GDP")
    assert caught.value.code == ProviderErrorCode.unsupported_metadata


class StubFREDProvider:
    identity = ProviderIdentity("FRED", "Federal Reserve Economic Data", "https://fred.test")

    def __init__(
        self,
        *,
        value: Decimal | None = Decimal("100.12500000"),
        frequency: ProviderFrequency = ProviderFrequency.monthly,
    ) -> None:
        self.value = value
        self.frequency = frequency
        self.title = "Consumer Price Index"
        self.vintage = date(2025, 2, 1)

    def get_series_metadata(
        self, series_id: str, query: SeriesMetadataQuery | None = None
    ) -> ProviderSeriesMetadata:
        del query
        return ProviderSeriesMetadata(
            provider_series_id=series_id,
            title=self.title,
            description="CPI",
            frequency=self.frequency,
            unit="Index",
            seasonal_adjustment=ProviderSeasonalAdjustment.not_adjusted,
            observation_start=date(2025, 1, 1),
            observation_end=date(2025, 1, 1),
            realtime_start=self.vintage,
            realtime_end=self.vintage,
            provider_metadata={"safe": "metadata"},
        )

    def get_observations(
        self, series_id: str, query: ObservationQuery
    ) -> Sequence[ProviderObservation]:
        del series_id, query
        return [
            ProviderObservation(
                observed_on=date(2025, 1, 1),
                value=self.value,
                is_missing=self.value is None,
                publication_timestamp=None,
                vintage_start=self.vintage,
                vintage_end=self.vintage,
                source_reference="https://fred.stlouisfed.org/series/CPIAUCSL",
            )
        ]

    def check_health(self) -> ProviderHealth:
        raise NotImplementedError


class MultiObservationProvider(StubFREDProvider):
    def __init__(self) -> None:
        super().__init__()
        self.reverse = False

    def get_observations(
        self, series_id: str, query: ObservationQuery
    ) -> Sequence[ProviderObservation]:
        del series_id, query
        rows = [
            ProviderObservation(
                observed_on=date(2025, month, 1),
                value=Decimal(month),
                is_missing=False,
                publication_timestamp=None,
                vintage_start=self.vintage,
                vintage_end=self.vintage,
                source_reference="https://fred.stlouisfed.org/series/CPI",
            )
            for month in (1, 2)
        ]
        return list(reversed(rows)) if self.reverse else rows


class OtherProvider(StubFREDProvider):
    identity = ProviderIdentity(
        "OTHER",
        "Other Test Provider",
        "https://provider.example/",
    )


class FailingProvider(StubFREDProvider):
    def __init__(self, error: ProviderError) -> None:
        super().__init__()
        self.error = error

    def get_series_metadata(
        self, series_id: str, query: SeriesMetadataQuery | None = None
    ) -> ProviderSeriesMetadata:
        del series_id, query
        raise self.error


def test_sync_api_creates_series_import_and_idempotent_replay(
    client: TestClient, db_session: Session
) -> None:
    provider = StubFREDProvider()
    app.dependency_overrides[get_fred_provider] = lambda: provider
    payload = {
        "category": "inflation",
        "geography": "US",
        "metadata_notes": "User-owned note",
    }
    first = client.post("/api/v1/providers/fred/series/CPIAUCSL/sync", json=payload)
    second = client.post("/api/v1/providers/fred/series/CPIAUCSL/sync", json=payload)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["idempotent_replay"] is False
    assert second.json()["idempotent_replay"] is True
    assert first.json()["import_batch_id"] == second.json()["import_batch_id"]
    assert first.json()["observations_accepted"] == 1
    observation = db_session.scalar(select(DataObservation))
    assert observation is not None
    assert observation.value == Decimal("100.12500000")
    assert observation.publication_timestamp is None
    assert observation.provider_vintage_start == date(2025, 2, 1)
    series = db_session.scalar(select(DataSeries))
    assert series is not None
    assert series.series_metadata["user_notes"] == "User-owned note"


def test_sync_api_maps_idempotency_conflict_to_shared_409(client: TestClient) -> None:
    provider = StubFREDProvider()
    app.dependency_overrides[get_fred_provider] = lambda: provider
    payload = {"idempotency_key": "fixed-sync-key"}
    first = client.post("/api/v1/providers/fred/series/CPI/sync", json=payload)
    assert first.status_code == 200
    provider.value = Decimal("200")
    conflict = client.post("/api/v1/providers/fred/series/CPI/sync", json=payload)
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "conflict"
    assert "database" not in conflict.text.lower()


def test_sync_changed_and_missing_values_create_immutable_revisions(
    db_session: Session,
) -> None:
    provider = StubFREDProvider()
    request = FREDSeriesSyncRequest(category="inflation")
    first = synchronize_provider_series(db_session, provider, "CPIAUCSL", request)
    provider.value = Decimal("101.50000000")
    second = synchronize_provider_series(db_session, provider, "CPIAUCSL", request)
    provider.value = None
    third = synchronize_provider_series(db_session, provider, "CPIAUCSL", request)
    provider.value = Decimal("102.00000000")
    fourth = synchronize_provider_series(db_session, provider, "CPIAUCSL", request)
    assert (
        len(
            {
                first.import_batch_id,
                second.import_batch_id,
                third.import_batch_id,
                fourth.import_batch_id,
            }
        )
        == 4
    )
    revisions = list(db_session.scalars(select(DataRevision).order_by(DataRevision.sequence)))
    assert [item.sequence for item in revisions] == [1, 2, 3]
    assert revisions[0].previous_value == Decimal("100.12500000")
    assert revisions[0].revised_value == Decimal("101.50000000")
    assert revisions[1].revised_status == ObservationStatus.missing
    assert revisions[1].revised_value is None
    assert revisions[2].previous_status == ObservationStatus.missing
    assert revisions[2].revised_value == Decimal("102.00000000")
    observation = db_session.scalar(select(DataObservation))
    assert observation is not None
    initial_state = macro_data_services.observation_to_read(
        observation, as_of=observation.ingestion_timestamp
    )
    changed_state = macro_data_services.observation_to_read(
        observation, as_of=revisions[0].revision_timestamp
    )
    missing_state = macro_data_services.observation_to_read(
        observation, as_of=revisions[1].revision_timestamp
    )
    assert initial_state.value == Decimal("100.12500000")
    assert changed_state.value == Decimal("101.50000000")
    assert missing_state.status == ObservationStatus.missing


def test_unordered_provider_response_has_stable_fingerprint(db_session: Session) -> None:
    provider = MultiObservationProvider()
    request = FREDSeriesSyncRequest()
    first = synchronize_provider_series(db_session, provider, "CPI", request)
    provider.reverse = True
    replay = synchronize_provider_series(db_session, provider, "CPI", request)
    assert replay.idempotent_replay is True
    assert replay.import_batch_id == first.import_batch_id
    assert db_session.scalar(select(func.count(DataObservation.id))) == 2


def test_request_scope_and_overrides_participate_in_fingerprint(
    db_session: Session,
) -> None:
    provider = StubFREDProvider()
    first = synchronize_provider_series(
        db_session,
        provider,
        "CPI",
        FREDSeriesSyncRequest(
            observation_start=date(2020, 1, 1),
            category="inflation",
        ),
    )
    different_range = synchronize_provider_series(
        db_session,
        provider,
        "CPI",
        FREDSeriesSyncRequest(
            observation_start=date(2021, 1, 1),
            category="inflation",
        ),
    )
    different_override = synchronize_provider_series(
        db_session,
        provider,
        "CPI",
        FREDSeriesSyncRequest(
            observation_start=date(2021, 1, 1),
            category="custom",
        ),
    )
    assert (
        len(
            {
                first.import_batch_id,
                different_range.import_batch_id,
                different_override.import_batch_id,
            }
        )
        == 3
    )
    series = db_session.get(DataSeries, first.series_id)
    assert series is not None
    assert series.category.value == "custom"
    assert db_session.scalar(select(func.count(DataRevision.id))) == 0


def test_provider_identity_participates_in_fingerprint(db_session: Session) -> None:
    fred_result = synchronize_provider_series(
        db_session, StubFREDProvider(), "CPI", FREDSeriesSyncRequest()
    )
    other_result = synchronize_provider_series(
        db_session, OtherProvider(), "CPI", FREDSeriesSyncRequest()
    )
    assert fred_result.import_batch_id != other_result.import_batch_id
    assert fred_result.source_id != other_result.source_id


def test_generated_idempotency_key_is_bounded_and_contains_no_credentials(
    db_session: Session,
) -> None:
    provider_series_id = "S" * 120
    result = synchronize_provider_series(
        db_session,
        StubFREDProvider(),
        provider_series_id,
        FREDSeriesSyncRequest(),
    )
    batch = db_session.get(DataImportBatch, result.import_batch_id)
    assert batch is not None
    assert len(batch.idempotency_key) <= 160
    assert batch.idempotency_key.startswith("sync:")
    serialized = f"{batch.idempotency_key}{batch.provider_metadata}"
    assert "top-secret" not in serialized
    assert "api_key" not in serialized.lower()


def test_sync_preserves_same_value_new_vintage_and_provider_metadata_update(
    db_session: Session,
) -> None:
    provider = StubFREDProvider()
    first = synchronize_provider_series(db_session, provider, "CPI", FREDSeriesSyncRequest())
    provider.vintage = date(2025, 3, 1)
    provider.title = "Updated Consumer Price Index"
    second = synchronize_provider_series(db_session, provider, "CPI", FREDSeriesSyncRequest())
    assert first.import_batch_id != second.import_batch_id
    assert second.observations_revised == 1
    revision = db_session.scalar(select(DataRevision))
    assert revision is not None
    assert revision.previous_value == revision.revised_value == Decimal("100.12500000")
    assert revision.provider_vintage_start == date(2025, 3, 1)
    series = db_session.get(DataSeries, second.series_id)
    assert series is not None
    assert series.name == "Updated Consumer Price Index"


def test_metadata_only_change_updates_series_without_observation_revision(
    db_session: Session,
) -> None:
    provider = StubFREDProvider()
    first = synchronize_provider_series(db_session, provider, "CPI", FREDSeriesSyncRequest())
    provider.title = "Renamed CPI"
    second = synchronize_provider_series(db_session, provider, "CPI", FREDSeriesSyncRequest())
    assert second.import_batch_id != first.import_batch_id
    assert second.observations_accepted == 0
    assert second.observations_revised == 0
    assert db_session.scalar(select(func.count(DataRevision.id))) == 0
    series = db_session.get(DataSeries, first.series_id)
    assert series is not None
    assert series.name == "Renamed CPI"


def test_sync_preserves_overrides_and_enforces_stale_series_version(
    db_session: Session,
) -> None:
    provider = StubFREDProvider()
    first = synchronize_provider_series(
        db_session,
        provider,
        "CPI",
        FREDSeriesSyncRequest(
            category="inflation",
            geography="CA",
            currency="CAD",
            metadata_notes="Keep this note",
        ),
    )
    series = db_session.get(DataSeries, first.series_id)
    assert series is not None
    assert series.category.value == "inflation"
    assert series.geography == "CA"
    assert series.currency == "CAD"
    assert series.series_metadata["user_notes"] == "Keep this note"
    provider.value = Decimal("101")
    with pytest.raises(DataConflictError, match="reload and retry"):
        synchronize_provider_series(
            db_session,
            provider,
            "CPI",
            FREDSeriesSyncRequest(expected_lock_version=series.lock_version + 1),
        )
    db_session.expire_all()
    assert db_session.scalar(select(func.count(DataImportBatch.id))) == 1
    unchanged = db_session.get(DataSeries, first.series_id)
    assert unchanged is not None
    assert unchanged.geography == "CA"
    assert unchanged.series_metadata["user_notes"] == "Keep this note"


def test_sync_rejects_unknown_frequency_and_rolls_back_all_state(db_session: Session) -> None:
    provider = FailingProvider(
        ProviderError(
            ProviderErrorCode.unsupported_metadata,
            "Unsupported provider frequency",
            status_code=422,
        )
    )
    with pytest.raises(ProviderError) as caught:
        synchronize_provider_series(
            db_session,
            provider,
            "BAD",
            FREDSeriesSyncRequest(),
        )
    assert caught.value.code == ProviderErrorCode.unsupported_metadata
    assert db_session.scalar(select(func.count(DataSource.id))) == 0
    assert db_session.scalar(select(func.count(DataSeries.id))) == 0
    assert db_session.scalar(select(func.count(DataImportBatch.id))) == 0


def test_oversized_provider_metadata_is_rejected_before_local_writes(
    db_session: Session,
) -> None:
    provider = StubFREDProvider()
    provider.title = "x" * 241
    with pytest.raises(ProviderError) as caught:
        synchronize_provider_series(db_session, provider, "LONG", FREDSeriesSyncRequest())
    assert caught.value.code == ProviderErrorCode.malformed_response
    assert db_session.scalar(select(func.count(DataSource.id))) == 0


def test_sync_overflow_rolls_back_source_series_import_and_observation(
    db_session: Session,
) -> None:
    provider = StubFREDProvider(value=Decimal("999999999999999999"))
    with pytest.raises(ProviderError) as caught:
        synchronize_provider_series(db_session, provider, "HUGE", FREDSeriesSyncRequest())
    assert caught.value.code == ProviderErrorCode.malformed_response
    for model in (DataSource, DataSeries, DataImportBatch, DataObservation):
        assert db_session.scalar(select(func.count(model.id))) == 0


def test_failure_after_batch_creation_rolls_back_every_local_write(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = StubFREDProvider()

    def fail_write(*_: Any, **__: Any) -> Any:
        raise RuntimeError("synthetic local failure")

    monkeypatch.setattr(macro_data_services, "_write_observation", fail_write)
    with pytest.raises(RuntimeError, match="synthetic local failure"):
        synchronize_provider_series(
            db_session,
            provider,
            "CPI",
            FREDSeriesSyncRequest(),
        )
    for model in (DataSource, DataSeries, DataImportBatch, DataObservation, DataRevision):
        assert db_session.scalar(select(func.count(model.id))) == 0


def test_sync_explicit_idempotency_key_conflict(db_session: Session) -> None:
    provider = StubFREDProvider()
    request = FREDSeriesSyncRequest(idempotency_key="caller-key")
    synchronize_provider_series(db_session, provider, "CPI", request)
    provider.value = Decimal("200")
    with pytest.raises(DataConflictError, match="Idempotency key"):
        synchronize_provider_series(db_session, provider, "CPI", request)


def test_database_rejects_duplicate_provider_series_mapping(db_session: Session) -> None:
    provider = StubFREDProvider()
    result = synchronize_provider_series(db_session, provider, "CPI", FREDSeriesSyncRequest())
    existing = db_session.get(DataSeries, result.series_id)
    assert existing is not None
    duplicate = DataSeries(
        source_id=existing.source_id,
        code="FRED.CPI.DUPLICATE",
        provider_series_id="CPI",
        name="Duplicate",
        description="",
        category=existing.category,
        geography=existing.geography,
        frequency=existing.frequency,
        unit=existing.unit,
        currency=None,
        seasonal_adjustment=existing.seasonal_adjustment,
        publication_lag_days=0,
        is_active=True,
        series_metadata={},
        lock_version=1,
    )
    db_session.add(duplicate)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_provider_error_contract_and_missing_credentials(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    app.dependency_overrides.pop(get_fred_provider, None)
    monkeypatch.setenv("MACROVISION_FRED_API_KEY", "")
    get_settings.cache_clear()
    response = client.post("/api/v1/providers/fred/series/GDP/sync", json={})
    assert response.status_code == 503
    assert response.json()["code"] == "provider_configuration_error"
    assert "credential" in response.json()["message"].lower()
    assert "api_key" not in response.text.lower()
    get_settings.cache_clear()


@pytest.mark.parametrize(
    ("error_code", "status_code"),
    [
        (ProviderErrorCode.authentication_failed, 502),
        (ProviderErrorCode.rate_limited, 429),
        (ProviderErrorCode.timeout, 504),
        (ProviderErrorCode.unavailable, 503),
    ],
)
def test_provider_failures_use_shared_safe_error_contract(
    client: TestClient,
    error_code: ProviderErrorCode,
    status_code: int,
) -> None:
    app.dependency_overrides[get_fred_provider] = lambda: FailingProvider(
        ProviderError(error_code, "Safe provider message", status_code=status_code)
    )
    response = client.post("/api/v1/providers/fred/series/GDP/sync", json={})
    assert response.status_code == status_code
    assert response.json() == {
        "code": error_code.value,
        "message": "Safe provider message",
        "details": None,
        "detail": "Safe provider message",
    }


def test_sync_rejects_invalid_series_identifier(client: TestClient) -> None:
    app.dependency_overrides[get_fred_provider] = lambda: StubFREDProvider()
    response = client.post("/api/v1/providers/fred/series/bad%20id/sync", json={})
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    too_long = client.post(
        f"/api/v1/providers/fred/series/{'S' * 121}/sync",
        json={},
    )
    assert too_long.status_code == 422


def test_historical_sync_requires_exact_realtime_date() -> None:
    with pytest.raises(ValueError, match="one exact realtime date"):
        FREDSeriesSyncRequest(
            realtime_start=date(2020, 1, 1),
            realtime_end=date(2020, 1, 2),
        )


def test_fred_openapi_contract_contains_no_credentials(client: TestClient) -> None:
    document = client.get("/openapi.json").json()
    operation = document["paths"]["/api/v1/providers/fred/series/{fred_series_id}/sync"]["post"]
    assert {"200", "404", "409", "422", "429", "502", "503", "504"} <= set(operation["responses"])
    serialized = str(operation).lower()
    assert "api_key" not in serialized
    assert "fred_api_key" not in serialized
    schemas = document["components"]["schemas"]
    observation_write = schemas["ObservationWrite"]
    assert "publication_timestamp" in observation_write["required"]
    assert observation_write["properties"]["publication_timestamp"]["type"] == "string"
    observation_read = schemas["ObservationRead"]["properties"]["publication_timestamp"]
    assert {"string", "null"} == {item["type"] for item in observation_read["anyOf"]}


def test_optional_live_fred_smoke() -> None:
    settings = get_settings()
    if not settings.enable_live_fred_tests or not settings.fred_api_key:
        pytest.skip("Live FRED smoke test is explicitly disabled")
    provider = FREDProvider(settings)
    try:
        metadata = provider.get_series_metadata("GDP")
        assert metadata.provider_series_id == "GDP"
        today = date.today()
        observations = provider.get_observations(
            "GDP",
            ObservationQuery(
                observation_start=today - timedelta(days=31),
                observation_end=today,
            ),
        )
        assert len(observations) <= settings.provider_max_observations
    finally:
        provider.close()
