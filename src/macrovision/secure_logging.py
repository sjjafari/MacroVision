import logging
import re
from collections.abc import Mapping
from typing import Any

import httpx

REDACTION_MARKER = "[REDACTED]"
REDACTION_FAILURE_MESSAGE = "[LOG REDACTION FAILED]"

_SENSITIVE_NAMES = (
    "api_key",
    "apikey",
    "access_token",
    "token",
    "client_secret",
    "secret",
    "password",
    "authorization",
)
_NAME_PATTERN = "|".join(re.escape(name).replace("_", r"(?:_|%5f)") for name in _SENSITIVE_NAMES)
_KEY_VALUE_PATTERN = re.compile(
    rf"(?i)(\b(?:{_NAME_PATTERN})\b\s*(?::|=|%3a|%3d)\s*)"
    r"(?:bearer(?:\s+|%20)+)?"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,;&#]+)"
)
_QUERY_PATTERN = re.compile(rf"(?i)([?&](?:{_NAME_PATTERN})(?:=|%3d))[^&#\s]*")
_BEARER_PATTERN = re.compile(r"(?i)(\bbearer(?:\s+|%20)+)[^\s,;]+")
_URL_USERINFO_PATTERN = re.compile(r"(?i)(https?://)[^/@\s]+@")


def redact_text(value: str) -> str:
    """Remove credential values while retaining useful request context."""

    redacted = _URL_USERINFO_PATTERN.sub(rf"\1{REDACTION_MARKER}@", value)
    redacted = _QUERY_PATTERN.sub(rf"\1{REDACTION_MARKER}", redacted)
    redacted = _KEY_VALUE_PATTERN.sub(rf"\1{REDACTION_MARKER}", redacted)
    return _BEARER_PATTERN.sub(rf"\1{REDACTION_MARKER}", redacted)


def _is_sensitive_name(value: object) -> bool:
    normalized = str(value).strip().lower().replace("%5f", "_")
    return normalized in _SENSITIVE_NAMES


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, httpx.URL):
        return redact_text(str(value))
    if isinstance(value, httpx.Request):
        return f"<Request({value.method!r}, {redact_text(str(value.url))!r})>"
    if isinstance(value, Mapping):
        return {
            key: REDACTION_MARKER if _is_sensitive_name(key) else _redact_value(item)
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return tuple(_redact_value(item) for item in value)
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    return value


class SensitiveDataFilter(logging.Filter):
    """Sanitize a record in place before a handler formats or emits it."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = redact_text(record.getMessage())
            record.args = ()
            for name, value in tuple(record.__dict__.items()):
                if name in {"msg", "args", "exc_info", "exc_text"}:
                    continue
                record.__dict__[name] = _redact_value(value)
            if record.exc_info is not None:
                record.exc_info = None
                record.exc_text = None
                record.msg = f"{record.msg} [exception details redacted]"
        except Exception:
            record.msg = REDACTION_FAILURE_MESSAGE
            record.args = ()
            record.exc_info = None
            record.exc_text = None
        return True


def _attach_filter(handler: logging.Handler) -> None:
    if not any(isinstance(item, SensitiveDataFilter) for item in handler.filters):
        handler.addFilter(SensitiveDataFilter())


def install_secure_logging() -> None:
    """Protect handlers already configured by MacroVision or an embedding process."""

    root = logging.getLogger()
    for handler in root.handlers:
        _attach_filter(handler)
    for logger_name in ("httpx", "httpcore"):
        third_party = logging.getLogger(logger_name)
        third_party.setLevel(logging.WARNING)
        for handler in third_party.handlers:
            _attach_filter(handler)


def configure_secure_logging(*, level: str, format_string: str) -> None:
    logging.basicConfig(level=level, format=format_string)
    install_secure_logging()
