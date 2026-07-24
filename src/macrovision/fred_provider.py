import email.utils
import json
import math
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from macrovision.config import Settings
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

FRED_IDENTITY = ProviderIdentity(
    code="FRED",
    name="Federal Reserve Economic Data",
    reference_url="https://fred.stlouisfed.org/",
)
_TRANSIENT_STATUSES = {429, 500, 502, 503, 504}
_MISSING_MARKERS = {".", ""}
_FREQUENCIES = {
    "D": ProviderFrequency.daily,
    "W": ProviderFrequency.weekly,
    "W-WE": ProviderFrequency.weekly,
    "BW": ProviderFrequency.weekly,
    "M": ProviderFrequency.monthly,
    "Q": ProviderFrequency.quarterly,
    "SA": ProviderFrequency.irregular,
    "A": ProviderFrequency.annual,
}
_SEASONAL = {
    "SA": ProviderSeasonalAdjustment.adjusted,
    "SAA": ProviderSeasonalAdjustment.adjusted,
    "NSA": ProviderSeasonalAdjustment.not_adjusted,
    "NA": ProviderSeasonalAdjustment.not_applicable,
    "Not Seasonally Adjusted": ProviderSeasonalAdjustment.not_adjusted,
    "Seasonally Adjusted": ProviderSeasonalAdjustment.adjusted,
}


class ProviderHttpClient:
    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float,
        max_response_bytes: int,
        max_retries: int,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not base_url.lower().startswith("https://"):
            raise ProviderError(
                ProviderErrorCode.configuration_error,
                "Provider base URL must use HTTPS",
                status_code=503,
            )
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            transport=transport,
            follow_redirects=False,
        )
        self._max_response_bytes = max_response_bytes
        self._max_retries = max_retries
        self._sleep = sleep

    def close(self) -> None:
        self._client.close()

    def get_json(self, path: str, params: Mapping[str, str | int]) -> dict[str, Any]:
        for attempt in range(self._max_retries + 1):
            try:
                with self._client.stream(
                    "GET",
                    path,
                    params=params,
                    headers={"Accept": "application/json"},
                ) as response:
                    if response.status_code in _TRANSIENT_STATUSES:
                        if attempt < self._max_retries:
                            self._sleep(_retry_delay(response.headers.get("Retry-After")))
                            continue
                        code = (
                            ProviderErrorCode.rate_limited
                            if response.status_code == 429
                            else ProviderErrorCode.unavailable
                        )
                        status_code = 429 if response.status_code == 429 else 503
                        raise ProviderError(
                            code,
                            "External data provider request could not be completed",
                            status_code=status_code,
                        )
                    if response.status_code in {401, 403}:
                        raise ProviderError(
                            ProviderErrorCode.authentication_failed,
                            "External data provider authentication failed",
                            status_code=502,
                        )
                    if 300 <= response.status_code < 400:
                        raise ProviderError(
                            ProviderErrorCode.unavailable,
                            "External data provider returned an unsupported redirect",
                            status_code=502,
                        )
                    if response.status_code == 400:
                        raise ProviderError(
                            ProviderErrorCode.series_not_found,
                            "FRED series was not found or the request was invalid",
                            status_code=404,
                        )
                    if response.status_code >= 400:
                        raise ProviderError(
                            ProviderErrorCode.unavailable,
                            "External data provider returned an unexpected error",
                            status_code=502,
                        )
                    declared_length = response.headers.get("Content-Length")
                    if declared_length is not None:
                        try:
                            if int(declared_length) > self._max_response_bytes:
                                raise ProviderError(
                                    ProviderErrorCode.response_too_large,
                                    "External data provider response exceeded the configured "
                                    "size limit",
                                    status_code=502,
                                )
                        except ValueError:
                            pass
                    content = bytearray()
                    for chunk in response.iter_bytes():
                        content.extend(chunk)
                        if len(content) > self._max_response_bytes:
                            raise ProviderError(
                                ProviderErrorCode.response_too_large,
                                "External data provider response exceeded the configured size "
                                "limit",
                                status_code=502,
                            )
            except httpx.TimeoutException:
                if attempt < self._max_retries:
                    continue
                raise ProviderError(
                    ProviderErrorCode.timeout,
                    "External data provider timed out",
                    status_code=504,
                ) from None
            except httpx.TransportError:
                if attempt < self._max_retries:
                    continue
                raise ProviderError(
                    ProviderErrorCode.unavailable,
                    "External data provider is unavailable",
                    status_code=503,
                ) from None

            try:
                payload = json.loads(content)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise ProviderError(
                    ProviderErrorCode.malformed_response,
                    "External data provider returned malformed JSON",
                    status_code=502,
                ) from exc
            if not isinstance(payload, dict):
                raise ProviderError(
                    ProviderErrorCode.malformed_response,
                    "External data provider returned an invalid response shape",
                    status_code=502,
                )
            return payload
        raise AssertionError("retry loop did not return or raise")


def _retry_delay(value: str | None) -> float:
    if value is None:
        return 0
    try:
        seconds = float(value)
        return min(max(seconds, 0), 30) if math.isfinite(seconds) else 0
    except ValueError:
        try:
            parsed = email.utils.parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return 0
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return 0
        return min(max((parsed - datetime.now(UTC)).total_seconds(), 0), 30)


def _date(value: object) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ProviderError(
            ProviderErrorCode.malformed_response,
            "FRED returned an invalid date",
            status_code=502,
        ) from exc


def _required_text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProviderError(
            ProviderErrorCode.malformed_response,
            f"FRED series metadata contained an invalid {field}",
            status_code=502,
        )
    return value


def _finite_decimal(value: object) -> tuple[Decimal | None, bool]:
    text = str(value).strip()
    if text in _MISSING_MARKERS:
        return None, True
    try:
        parsed = Decimal(text)
    except InvalidOperation as exc:
        raise ProviderError(
            ProviderErrorCode.malformed_response,
            "FRED returned an invalid numeric observation",
            status_code=502,
        ) from exc
    if not parsed.is_finite():
        raise ProviderError(
            ProviderErrorCode.malformed_response,
            "FRED returned a non-finite numeric observation",
            status_code=502,
        )
    return parsed, False


def _frequency(value: str) -> ProviderFrequency:
    try:
        return _FREQUENCIES[value]
    except KeyError as exc:
        raise ProviderError(
            ProviderErrorCode.unsupported_metadata,
            "FRED series frequency is not supported",
            status_code=422,
        ) from exc


def _seasonal(
    value: str,
) -> tuple[ProviderSeasonalAdjustment, tuple[str, ...]]:
    mapped = _SEASONAL.get(value)
    if mapped is not None:
        return mapped, ()
    return ProviderSeasonalAdjustment.unknown, (
        "FRED seasonal-adjustment value was preserved as provider metadata",
    )


class FREDProvider:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        api_key = settings.fred_api_key
        if api_key is None or not api_key.strip():
            raise ProviderError(
                ProviderErrorCode.configuration_error,
                "FRED credentials are not configured",
                status_code=503,
            )
        parsed_base_url = urlsplit(settings.fred_base_url)
        try:
            base_port = parsed_base_url.port
        except ValueError:
            base_port = -1
        if (
            parsed_base_url.scheme.lower() != "https"
            or parsed_base_url.hostname != "api.stlouisfed.org"
            or base_port not in {None, 443}
            or parsed_base_url.username is not None
            or parsed_base_url.password is not None
            or parsed_base_url.query
            or parsed_base_url.fragment
            or parsed_base_url.path.rstrip("/") != "/fred"
        ):
            raise ProviderError(
                ProviderErrorCode.configuration_error,
                "FRED base URL must use the official HTTPS API endpoint",
                status_code=503,
            )
        self._api_key = api_key.strip()
        self._max_observations = settings.provider_max_observations
        self._http = ProviderHttpClient(
            base_url=settings.fred_base_url,
            timeout_seconds=settings.provider_request_timeout_seconds,
            max_response_bytes=settings.provider_max_response_bytes,
            max_retries=settings.provider_max_retries,
            transport=transport,
            sleep=sleep,
        )

    @property
    def identity(self) -> ProviderIdentity:
        return FRED_IDENTITY

    def close(self) -> None:
        self._http.close()

    def _params(self, series_id: str) -> dict[str, str | int]:
        return {
            "api_key": self._api_key,
            "file_type": "json",
            "series_id": series_id,
        }

    def get_series_metadata(
        self, series_id: str, query: SeriesMetadataQuery | None = None
    ) -> ProviderSeriesMetadata:
        params = self._params(series_id)
        if query is not None:
            if query.realtime_start is not None:
                params["realtime_start"] = query.realtime_start.isoformat()
            if query.realtime_end is not None:
                params["realtime_end"] = query.realtime_end.isoformat()
        payload = self._http.get_json("series", params)
        rows = payload.get("seriess")
        if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
            raise ProviderError(
                ProviderErrorCode.malformed_response,
                "FRED returned invalid series metadata",
                status_code=502,
            )
        row = rows[0]
        try:
            provider_id = _required_text(row["id"], field="series ID")
            title = _required_text(row["title"], field="title")
            frequency = _required_text(row["frequency_short"], field="frequency")
            unit = _required_text(
                row.get("units_short") or row["units"],
                field="unit",
            )
            seasonal = str(
                row.get("seasonal_adjustment_short") or row.get("seasonal_adjustment") or "Unknown"
            )
        except KeyError as exc:
            raise ProviderError(
                ProviderErrorCode.malformed_response,
                "FRED series metadata omitted a required field",
                status_code=502,
            ) from exc
        if provider_id != series_id:
            raise ProviderError(
                ProviderErrorCode.malformed_response,
                "FRED returned metadata for an unexpected series",
                status_code=502,
            )
        normalized_seasonal, warnings = _seasonal(seasonal)
        realtime_start = _date(row.get("realtime_start"))
        realtime_end = _date(row.get("realtime_end"))
        if query is not None and (
            (query.realtime_start is not None and realtime_start != query.realtime_start)
            or (query.realtime_end is not None and realtime_end != query.realtime_end)
        ):
            raise ProviderError(
                ProviderErrorCode.malformed_response,
                "FRED metadata realtime scope did not match the request",
                status_code=502,
            )
        return ProviderSeriesMetadata(
            provider_series_id=provider_id,
            title=title,
            description=str(row.get("notes") or ""),
            frequency=_frequency(frequency),
            unit=unit,
            seasonal_adjustment=normalized_seasonal,
            observation_start=_date(row.get("observation_start")),
            observation_end=_date(row.get("observation_end")),
            realtime_start=realtime_start,
            realtime_end=realtime_end,
            provider_metadata={
                "last_updated": str(row.get("last_updated") or ""),
                "frequency_label": str(row.get("frequency") or ""),
                "units_label": str(row.get("units") or ""),
                "seasonal_adjustment_label": str(row.get("seasonal_adjustment") or ""),
            },
            warnings=warnings,
        )

    def get_observations(
        self, series_id: str, query: ObservationQuery
    ) -> Sequence[ProviderObservation]:
        offset = 0
        observations: list[ProviderObservation] = []
        observed_dates: set[date] = set()
        while True:
            params = self._params(series_id)
            params.update({"limit": min(100000, self._max_observations), "offset": offset})
            for name, value in (
                ("observation_start", query.observation_start),
                ("observation_end", query.observation_end),
                ("realtime_start", query.realtime_start),
                ("realtime_end", query.realtime_end),
            ):
                if value is not None:
                    params[name] = value.isoformat()
            payload = self._http.get_json("series/observations", params)
            rows = payload.get("observations")
            if not isinstance(rows, list):
                raise ProviderError(
                    ProviderErrorCode.malformed_response,
                    "FRED returned invalid observations",
                    status_code=502,
                )
            for row in rows:
                if not isinstance(row, dict):
                    raise ProviderError(
                        ProviderErrorCode.malformed_response,
                        "FRED returned an invalid observation row",
                        status_code=502,
                    )
                parsed_value, missing = _finite_decimal(row.get("value"))
                observed_on = _date(row.get("date"))
                if observed_on is None:
                    raise ProviderError(
                        ProviderErrorCode.malformed_response,
                        "FRED observation omitted its date",
                        status_code=502,
                    )
                if observed_on in observed_dates:
                    raise ProviderError(
                        ProviderErrorCode.malformed_response,
                        "FRED returned duplicate observation dates",
                        status_code=502,
                    )
                observed_dates.add(observed_on)
                if (
                    query.observation_start is not None and observed_on < query.observation_start
                ) or (query.observation_end is not None and observed_on > query.observation_end):
                    raise ProviderError(
                        ProviderErrorCode.malformed_response,
                        "FRED observation date fell outside the requested scope",
                        status_code=502,
                    )
                vintage_start = _date(row.get("realtime_start"))
                vintage_end = _date(row.get("realtime_end"))
                if (query.realtime_start is not None and vintage_start != query.realtime_start) or (
                    query.realtime_end is not None and vintage_end != query.realtime_end
                ):
                    raise ProviderError(
                        ProviderErrorCode.malformed_response,
                        "FRED observation realtime scope did not match the request",
                        status_code=502,
                    )
                observations.append(
                    ProviderObservation(
                        observed_on=observed_on,
                        value=parsed_value,
                        is_missing=missing,
                        publication_timestamp=None,
                        vintage_start=vintage_start,
                        vintage_end=vintage_end,
                        source_reference=(
                            f"https://fred.stlouisfed.org/series/{quote(series_id, safe='')}"
                        ),
                        provider_metadata={},
                    )
                )
                if len(observations) > self._max_observations:
                    raise ProviderError(
                        ProviderErrorCode.response_too_large,
                        "FRED observation count exceeded the configured limit",
                        status_code=502,
                    )
            try:
                count = int(payload.get("count", len(rows)))
            except (TypeError, ValueError) as exc:
                raise ProviderError(
                    ProviderErrorCode.malformed_response,
                    "FRED returned invalid pagination metadata",
                    status_code=502,
                ) from exc
            offset += len(rows)
            if not rows or offset >= count:
                break
        return observations

    def check_health(self) -> ProviderHealth:
        self._http.get_json(
            "series",
            {
                **self._params("GDP"),
                "limit": 1,
            },
        )
        return ProviderHealth(available=True, checked_at=datetime.now(UTC))
