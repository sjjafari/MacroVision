import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from macrovision.provider_registry import normalize_provider_name
from macrovision.scheduler_schemas import (
    MAX_REQUEST_CONFIG_BYTES,
    ProviderSyncTriggerType,
    SafeProviderSyncConfig,
    ScheduleCadence,
    ScheduleCadenceType,
    validate_safe_config,
)

SHA256_HEX_LENGTH = 64
MAX_EXTERNAL_IDEMPOTENCY_KEY_LENGTH = 160


def require_aware_utc(value: datetime, *, field: str = "timestamp") -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def canonicalize_request_config(
    value: SafeProviderSyncConfig | dict[str, Any],
) -> tuple[dict[str, Any], str]:
    config = validate_safe_config(value)
    document = config.model_dump(mode="json", exclude_none=True)
    serialized = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    if len(serialized.encode("utf-8")) > MAX_REQUEST_CONFIG_BYTES:
        raise ValueError("Provider synchronization configuration exceeds the safe size limit")
    return document, serialized


def fingerprint_request_config(value: SafeProviderSyncConfig | dict[str, Any]) -> str:
    _, serialized = canonicalize_request_config(value)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def calculate_initial_next_run_at(cadence: ScheduleCadence, *, now: datetime) -> datetime:
    current = require_aware_utc(now, field="now")
    if cadence.cadence_type == ScheduleCadenceType.fixed_interval:
        assert cadence.interval_minutes is not None
        return current + timedelta(minutes=cadence.interval_minutes)
    assert cadence.daily_time_utc is not None
    candidate = datetime.combine(current.date(), cadence.daily_time_utc, tzinfo=UTC)
    return candidate if candidate > current else candidate + timedelta(days=1)


def calculate_next_future_occurrence(
    cadence: ScheduleCadence,
    *,
    previous: datetime,
    now: datetime,
) -> datetime:
    anchor = require_aware_utc(previous, field="previous")
    current = require_aware_utc(now, field="now")
    if anchor > current:
        return anchor
    if cadence.cadence_type == ScheduleCadenceType.fixed_interval:
        assert cadence.interval_minutes is not None
        interval = timedelta(minutes=cadence.interval_minutes)
        elapsed = current - anchor
        steps = elapsed // interval + 1
        return anchor + steps * interval
    assert cadence.daily_time_utc is not None
    candidate = datetime.combine(current.date(), cadence.daily_time_utc, tzinfo=UTC)
    return candidate if candidate > current else candidate + timedelta(days=1)


def calculate_latest_due_occurrence(
    cadence: ScheduleCadence,
    *,
    next_run_at: datetime,
    now: datetime,
) -> datetime | None:
    first_due = require_aware_utc(next_run_at, field="next_run_at")
    current = require_aware_utc(now, field="now")
    if first_due > current:
        return None
    if cadence.cadence_type == ScheduleCadenceType.fixed_interval:
        assert cadence.interval_minutes is not None
        interval = timedelta(minutes=cadence.interval_minutes)
        return first_due + ((current - first_due) // interval) * interval
    assert cadence.daily_time_utc is not None
    candidate = datetime.combine(current.date(), cadence.daily_time_utc, tzinfo=UTC)
    return candidate if candidate >= first_due and candidate <= current else first_due


def coalesce_due_occurrences(
    cadence: ScheduleCadence,
    *,
    next_run_at: datetime,
    now: datetime,
) -> tuple[datetime | None, datetime]:
    due = calculate_latest_due_occurrence(cadence, next_run_at=next_run_at, now=now)
    if due is None:
        return None, require_aware_utc(next_run_at, field="next_run_at")
    return due, calculate_next_future_occurrence(cadence, previous=due, now=now)


def generate_concurrency_key(provider: str, provider_series_id: str) -> str:
    normalized = normalize_provider_name(provider)
    series = provider_series_id.strip()
    if not series or len(series) > 120:
        raise ValueError("Provider series ID is invalid")
    return hashlib.sha256(f"{normalized}:{series}".encode()).hexdigest()


def hash_external_idempotency_key(value: str) -> str:
    if not value or len(value) > MAX_EXTERNAL_IDEMPOTENCY_KEY_LENGTH:
        raise ValueError("External idempotency key is invalid")
    return hashlib.sha256(value.encode()).hexdigest()


def generate_run_key(
    *,
    schedule_id: int,
    trigger_type: ProviderSyncTriggerType,
    scheduled_for: datetime,
    request_fingerprint: str,
    request_idempotency_hash: str | None = None,
) -> str:
    if schedule_id <= 0:
        raise ValueError("Schedule ID must be positive")
    when = require_aware_utc(scheduled_for, field="scheduled_for").isoformat()
    material = (
        f"{schedule_id}:{trigger_type.value}:{when}:{request_fingerprint}:"
        f"{request_idempotency_hash or ''}"
    )
    return hashlib.sha256(material.encode()).hexdigest()


def generate_sync_idempotency_key(run_key: str) -> str:
    if len(run_key) != SHA256_HEX_LENGTH:
        raise ValueError("Run key must be a SHA-256 hexadecimal value")
    return f"scheduler:{hashlib.sha256(run_key.encode()).hexdigest()}"
