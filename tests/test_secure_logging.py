import io
import logging
from collections.abc import Callable, Generator
from typing import Any

import httpx
import pytest

from macrovision.config import Settings
from macrovision.fred_provider import FREDProvider
from macrovision.provider_contracts import ProviderError
from macrovision.scheduler_worker import configure_worker_logging
from macrovision.secure_logging import (
    REDACTION_FAILURE_MESSAGE,
    REDACTION_MARKER,
    SensitiveDataFilter,
    configure_secure_logging,
    redact_text,
)

SYNTHETIC_CANARY = "macrovision-test-secret-never-log-7F4C2A"


@pytest.fixture
def captured_logging() -> Generator[io.StringIO, None, None]:
    root = logging.getLogger()
    original_level = root.level
    original_disable = root.manager.disable
    logger_state = {
        name: (
            logging.getLogger(name).level,
            logging.getLogger(name).disabled,
            logging.getLogger(name).propagate,
        )
        for name in ("httpx", "httpcore", "macrovision.scheduler")
    }
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    logging.disable(logging.NOTSET)
    for name in logger_state:
        target = logging.getLogger(name)
        target.disabled = False
        target.propagate = True
    configure_secure_logging(level="DEBUG", format_string="%(levelname)s %(name)s %(message)s")
    try:
        yield stream
    finally:
        root.removeHandler(handler)
        handler.close()
        root.setLevel(original_level)
        logging.disable(original_disable)
        for name, (level, disabled, propagate) in logger_state.items():
            target = logging.getLogger(name)
            target.setLevel(level)
            target.disabled = disabled
            target.propagate = propagate


@pytest.mark.parametrize(
    ("unsafe", "safe_fragment"),
    [
        (
            f"https://api.example.test/data?api_key={SYNTHETIC_CANARY}&series_id=GDP",
            "series_id=GDP",
        ),
        (
            f"https://api.example.test/data?series_id=GDP&ApiKey={SYNTHETIC_CANARY}",
            "series_id=GDP",
        ),
        (
            f"https://api.example.test/data?ACCESS_TOKEN={SYNTHETIC_CANARY}&limit=10",
            "limit=10",
        ),
        (
            f"https://api.example.test/data?api%5Fkey={SYNTHETIC_CANARY}%2Fencoded",
            "api%5Fkey=",
        ),
        (
            f"https://api.example.test/data?api%5Fkey%3D{SYNTHETIC_CANARY}%2Fencoded",
            "api%5Fkey%3D",
        ),
        (
            f"client_secret={SYNTHETIC_CANARY}, provider=fred",
            "provider=fred",
        ),
        (
            f"Authorization: Bearer {SYNTHETIC_CANARY}",
            "Authorization:",
        ),
        (
            f"Bearer {SYNTHETIC_CANARY}",
            "Bearer ",
        ),
        (
            f"Authorization%3ABearer%20{SYNTHETIC_CANARY}",
            "Authorization%3A",
        ),
        (
            f"https://user:{SYNTHETIC_CANARY}@api.example.test/safe/path?series_id=GDP",
            "/safe/path?series_id=GDP",
        ),
    ],
)
def test_redact_text_covers_url_and_authorization_forms(
    unsafe: str,
    safe_fragment: str,
) -> None:
    result = redact_text(unsafe)
    assert SYNTHETIC_CANARY not in result
    assert REDACTION_MARKER in result
    assert safe_fragment in result


def test_filter_handles_printf_args_url_objects_requests_and_extra_fields(
    captured_logging: io.StringIO,
) -> None:
    logger = logging.getLogger("macrovision.security-test")
    url = httpx.URL(f"https://api.example.test/safe/path?api_key={SYNTHETIC_CANARY}&series_id=GDP")
    request = httpx.Request("GET", url)
    logger.info(
        "request_url=%s request=%s fields=%s",
        url,
        request,
        {"authorization": f"Bearer {SYNTHETIC_CANARY}", "status_code": 200},
        extra={"provider_url": url},
    )
    output = captured_logging.getvalue()
    assert SYNTHETIC_CANARY not in output
    assert output.count(REDACTION_MARKER) >= 3
    assert "api.example.test/safe/path" in output
    assert "series_id=GDP" in output
    assert "status_code" in output
    assert "200" in output


def test_filter_fails_closed(
    captured_logging: io.StringIO,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "macrovision.secure_logging.redact_text",
        lambda _: (_ for _ in ()).throw(RuntimeError("synthetic redaction failure")),
    )
    logging.getLogger("macrovision.fail-closed").error(
        "api_key=%s",
        SYNTHETIC_CANARY,
    )
    output = captured_logging.getvalue()
    assert SYNTHETIC_CANARY not in output
    assert REDACTION_FAILURE_MESSAGE in output


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        fred_api_key=SYNTHETIC_CANARY,
        provider_max_retries=1,
    )


def _metadata_response() -> dict[str, Any]:
    return {
        "seriess": [
            {
                "id": "GDP",
                "title": "Gross Domestic Product",
                "frequency_short": "Q",
                "frequency": "Quarterly",
                "units_short": "Billions of Dollars",
                "units": "Billions of Dollars",
                "seasonal_adjustment_short": "SA",
                "seasonal_adjustment": "Seasonally Adjusted",
                "observation_start": "1947-01-01",
                "observation_end": "2026-01-01",
                "realtime_start": "2026-07-26",
                "realtime_end": "2026-07-26",
            }
        ]
    }


def _enable_verbose_http_logging() -> None:
    logging.getLogger("httpx").setLevel(logging.DEBUG)
    logging.getLogger("httpcore").setLevel(logging.DEBUG)


def test_real_fred_path_redacts_logs_without_changing_transport(
    captured_logging: io.StringIO,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_metadata_response())

    provider = FREDProvider(_settings(), transport=httpx.MockTransport(handler))
    _enable_verbose_http_logging()
    try:
        metadata = provider.get_series_metadata("GDP")
    finally:
        provider.close()

    assert metadata.provider_series_id == "GDP"
    assert len(requests) == 1
    assert requests[0].url.params["api_key"] == SYNTHETIC_CANARY
    output = captured_logging.getvalue()
    assert SYNTHETIC_CANARY not in output
    assert REDACTION_MARKER in output
    assert "GET" in output
    assert "HTTP/1.1 200 OK" in output
    assert "api.stlouisfed.org/fred/series" in output
    assert "series_id=GDP" in output


FailureHandler = Callable[[httpx.Request], httpx.Response]


def _failure_handler(case: str) -> FailureHandler:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        logging.getLogger("httpcore").debug("sending request %s", request)
        if case == "timeout":
            raise httpx.ReadTimeout("synthetic timeout", request=request)
        if case == "transport":
            raise httpx.ConnectError("synthetic transport failure", request=request)
        if case == "malformed":
            return httpx.Response(200, content=b"{")
        status = {
            "unauthorized": 401,
            "forbidden": 403,
            "rate_limit": 429,
            "server_error": 500,
            "redirect": 302,
        }[case]
        headers = {"Location": "https://example.test/redirect"} if status == 302 else {}
        return httpx.Response(status, headers=headers)

    return handler


@pytest.mark.parametrize(
    "case",
    [
        "timeout",
        "transport",
        "unauthorized",
        "forbidden",
        "rate_limit",
        "server_error",
        "redirect",
        "malformed",
    ],
)
def test_fred_failure_paths_never_expose_credentials(
    case: str,
    captured_logging: io.StringIO,
    capsys: pytest.CaptureFixture[str],
) -> None:
    provider = FREDProvider(
        _settings(),
        transport=httpx.MockTransport(_failure_handler(case)),
        sleep=lambda _: None,
    )
    _enable_verbose_http_logging()
    try:
        with pytest.raises(ProviderError) as caught:
            provider.get_series_metadata("GDP")
    finally:
        provider.close()

    emitted = captured_logging.getvalue()
    captured = capsys.readouterr()
    assert SYNTHETIC_CANARY not in emitted
    assert SYNTHETIC_CANARY not in str(caught.value)
    assert SYNTHETIC_CANARY not in repr(caught.value)
    assert SYNTHETIC_CANARY not in captured.out
    assert SYNTHETIC_CANARY not in captured.err
    assert REDACTION_MARKER in emitted
    assert "series_id=GDP" in emitted


def test_worker_logging_configuration_is_idempotent_and_preserves_application_info(
    captured_logging: io.StringIO,
) -> None:
    root = logging.getLogger()
    configure_worker_logging(_settings())
    configure_worker_logging(_settings())

    for handler in root.handlers:
        assert sum(isinstance(item, SensitiveDataFilter) for item in handler.filters) == 1
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
    assert logging.getLogger("httpcore").getEffectiveLevel() >= logging.WARNING

    logging.getLogger("macrovision.scheduler").info(
        "provider=fred series_id=GDP authorization=Bearer %s observations=%d",
        SYNTHETIC_CANARY,
        3,
    )
    output = captured_logging.getvalue()
    assert SYNTHETIC_CANARY not in output
    assert REDACTION_MARKER in output
    assert "provider=fred" in output
    assert "series_id=GDP" in output
    assert "observations=3" in output
