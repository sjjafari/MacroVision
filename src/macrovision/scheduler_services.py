import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast

from sqlalchemy import Select, exists, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session, aliased
from sqlalchemy.orm.exc import StaleDataError

from macrovision.config import Settings
from macrovision.integrity import IntegrityConflictError
from macrovision.macro_data_services import DataConflictError
from macrovision.provider_contracts import ProviderError, ProviderErrorCode
from macrovision.provider_registry import ProviderRegistry, normalize_provider_name
from macrovision.provider_schemas import (
    FREDSeriesSyncRequest,
    ProviderSeriesSyncRequest,
    ProviderSyncResult,
)
from macrovision.provider_services import synchronize_provider_series
from macrovision.scheduler_models import ProviderSyncRun, ProviderSyncSchedule
from macrovision.scheduler_schemas import (
    MAX_REQUEST_CONFIG_BYTES,
    ProviderSyncRunNowRequest,
    ProviderSyncRunStatus,
    ProviderSyncScheduleCreate,
    ProviderSyncSchedulePatch,
    ProviderSyncTriggerType,
    SafeProviderSyncConfig,
    ScheduleCadence,
    ScheduleCadenceType,
    validate_safe_config,
)

SHA256_HEX_LENGTH = 64
MAX_EXTERNAL_IDEMPOTENCY_KEY_LENGTH = 160
MAX_ERROR_MESSAGE_LENGTH = 500


class SchedulerNotFoundError(Exception):
    pass


class SchedulerConflictError(Exception):
    pass


class SessionFactory(Protocol):
    def __call__(self) -> Session: ...


@dataclass(frozen=True)
class RetryDecision:
    retryable: bool
    error_code: str
    error_message: str


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


def _now(value: datetime | None) -> datetime:
    return require_aware_utc(value or datetime.now(UTC), field="now")


def _cadence_from_schedule(schedule: ProviderSyncSchedule) -> ScheduleCadence:
    return ScheduleCadence(
        cadence_type=schedule.cadence_type,
        interval_minutes=schedule.interval_minutes,
        daily_time_utc=schedule.daily_time_utc,
    )


def _commit(session: Session, message: str) -> None:
    try:
        session.commit()
    except (IntegrityError, StaleDataError) as exc:
        session.rollback()
        raise SchedulerConflictError(message) from exc


def get_schedule(session: Session, schedule_id: int) -> ProviderSyncSchedule:
    schedule = session.get(ProviderSyncSchedule, schedule_id)
    if schedule is None:
        raise SchedulerNotFoundError("Provider synchronization schedule was not found")
    return schedule


def list_schedules(
    session: Session,
    *,
    limit: int,
    offset: int,
) -> list[ProviderSyncSchedule]:
    return list(
        session.scalars(
            select(ProviderSyncSchedule)
            .order_by(ProviderSyncSchedule.id)
            .limit(limit)
            .offset(offset)
        )
    )


def create_schedule(
    session: Session,
    payload: ProviderSyncScheduleCreate,
    *,
    registry: ProviderRegistry,
    now: datetime | None = None,
) -> ProviderSyncSchedule:
    current = _now(now)
    provider = registry.require_supported(payload.provider)
    request_config, _ = canonicalize_request_config(payload.request_config)
    cadence = ScheduleCadence(
        cadence_type=payload.cadence_type,
        interval_minutes=payload.interval_minutes,
        daily_time_utc=payload.daily_time_utc,
    )
    schedule = ProviderSyncSchedule(
        provider=provider,
        provider_series_id=payload.provider_series_id,
        internal_series_code=payload.internal_series_code,
        request_config=request_config,
        request_config_fingerprint=fingerprint_request_config(request_config),
        cadence_type=cadence.cadence_type.value,
        interval_minutes=cadence.interval_minutes,
        daily_time_utc=cadence.daily_time_utc,
        next_run_at=(
            calculate_initial_next_run_at(cadence, now=current) if payload.enabled else None
        ),
        enabled=payload.enabled,
        last_scheduled_at=None,
        created_at=current,
        updated_at=current,
        lock_version=1,
    )
    session.add(schedule)
    _commit(session, "A schedule already exists for this provider series")
    session.refresh(schedule)
    return schedule


def _patched_cadence(
    schedule: ProviderSyncSchedule,
    payload: ProviderSyncSchedulePatch,
) -> ScheduleCadence:
    fields = payload.model_fields_set
    cadence_type = (
        payload.cadence_type
        if "cadence_type" in fields
        else ScheduleCadenceType(schedule.cadence_type)
    )
    if cadence_type == ScheduleCadenceType.fixed_interval:
        interval = (
            payload.interval_minutes
            if "interval_minutes" in fields
            else (
                schedule.interval_minutes
                if schedule.cadence_type == ScheduleCadenceType.fixed_interval.value
                else None
            )
        )
        daily_time = None
    else:
        interval = None
        daily_time = (
            payload.daily_time_utc
            if "daily_time_utc" in fields
            else (
                schedule.daily_time_utc
                if schedule.cadence_type == ScheduleCadenceType.daily_utc.value
                else None
            )
        )
    return ScheduleCadence(
        cadence_type=cadence_type,
        interval_minutes=interval,
        daily_time_utc=daily_time,
    )


def update_schedule(
    session: Session,
    schedule_id: int,
    payload: ProviderSyncSchedulePatch,
    *,
    now: datetime | None = None,
) -> ProviderSyncSchedule:
    current = _now(now)
    schedule = get_schedule(session, schedule_id)
    if schedule.lock_version != payload.expected_lock_version:
        raise SchedulerConflictError("Schedule was changed; reload and retry")
    cadence = _patched_cadence(schedule, payload)
    if "request_config" in payload.model_fields_set:
        assert payload.request_config is not None
        request_config, _ = canonicalize_request_config(payload.request_config)
        schedule.request_config = request_config
        schedule.request_config_fingerprint = fingerprint_request_config(request_config)
    schedule.cadence_type = cadence.cadence_type.value
    schedule.interval_minutes = cadence.interval_minutes
    schedule.daily_time_utc = cadence.daily_time_utc
    schedule.next_run_at = (
        calculate_initial_next_run_at(cadence, now=current) if schedule.enabled else None
    )
    schedule.updated_at = current
    schedule.lock_version += 1
    _commit(session, "Schedule update conflicted with a concurrent change")
    session.refresh(schedule)
    return schedule


def set_schedule_enabled(
    session: Session,
    schedule_id: int,
    *,
    expected_lock_version: int,
    enabled: bool,
    now: datetime | None = None,
) -> ProviderSyncSchedule:
    current = _now(now)
    schedule = get_schedule(session, schedule_id)
    if schedule.lock_version != expected_lock_version:
        raise SchedulerConflictError("Schedule was changed; reload and retry")
    if schedule.enabled == enabled:
        return schedule
    schedule.enabled = enabled
    schedule.next_run_at = (
        calculate_initial_next_run_at(_cadence_from_schedule(schedule), now=current)
        if enabled
        else None
    )
    schedule.updated_at = current
    schedule.lock_version += 1
    _commit(session, "Schedule state change conflicted with a concurrent update")
    session.refresh(schedule)
    return schedule


def _new_run(
    schedule: ProviderSyncSchedule,
    *,
    trigger_type: ProviderSyncTriggerType,
    scheduled_for: datetime,
    created_at: datetime,
    maximum_attempts: int,
    request_idempotency_hash: str | None,
) -> ProviderSyncRun:
    run_key = generate_run_key(
        schedule_id=schedule.id,
        trigger_type=trigger_type,
        scheduled_for=scheduled_for,
        request_fingerprint=schedule.request_config_fingerprint,
        request_idempotency_hash=request_idempotency_hash,
    )
    return ProviderSyncRun(
        schedule_id=schedule.id,
        run_key=run_key,
        trigger_type=trigger_type.value,
        provider=schedule.provider,
        provider_series_id=schedule.provider_series_id,
        concurrency_key=generate_concurrency_key(
            schedule.provider,
            schedule.provider_series_id,
        ),
        request_snapshot=dict(schedule.request_config),
        request_snapshot_fingerprint=schedule.request_config_fingerprint,
        status=ProviderSyncRunStatus.pending.value,
        scheduled_for=scheduled_for,
        created_at=created_at,
        started_at=None,
        completed_at=None,
        attempt_number=0,
        maximum_attempts=maximum_attempts,
        next_attempt_at=scheduled_for,
        lease_owner=None,
        lease_acquired_at=None,
        lease_expires_at=None,
        lease_generation=0,
        request_idempotency_hash=request_idempotency_hash,
        sync_idempotency_key=generate_sync_idempotency_key(run_key),
        import_batch_id=None,
        observations_received=0,
        observations_accepted=0,
        observations_revised=0,
        observations_missing=0,
        observations_rejected=0,
        provider_replay=None,
        error_code=None,
        error_message=None,
    )


def enqueue_run_now(
    session: Session,
    schedule_id: int,
    payload: ProviderSyncRunNowRequest,
    *,
    maximum_attempts: int,
    now: datetime | None = None,
) -> ProviderSyncRun:
    current = _now(now)
    schedule = get_schedule(session, schedule_id)
    request_hash = hash_external_idempotency_key(payload.idempotency_key)
    existing = session.scalar(
        select(ProviderSyncRun).where(
            ProviderSyncRun.schedule_id == schedule_id,
            ProviderSyncRun.request_idempotency_hash == request_hash,
        )
    )
    if existing is not None:
        if existing.request_snapshot_fingerprint != schedule.request_config_fingerprint:
            raise SchedulerConflictError(
                "Run-now idempotency key was used with different schedule configuration"
            )
        return existing
    run = _new_run(
        schedule,
        trigger_type=ProviderSyncTriggerType.manual,
        scheduled_for=current,
        created_at=current,
        maximum_attempts=maximum_attempts,
        request_idempotency_hash=request_hash,
    )
    session.add(run)
    try:
        _commit(session, "Run-now request conflicted with an existing request")
    except SchedulerConflictError:
        existing = session.scalar(
            select(ProviderSyncRun).where(
                ProviderSyncRun.schedule_id == schedule_id,
                ProviderSyncRun.request_idempotency_hash == request_hash,
            )
        )
        if (
            existing is not None
            and existing.request_snapshot_fingerprint == schedule.request_config_fingerprint
        ):
            return existing
        raise
    session.refresh(run)
    return run


def get_run(session: Session, run_id: int) -> ProviderSyncRun:
    run = session.get(ProviderSyncRun, run_id)
    if run is None:
        raise SchedulerNotFoundError("Provider synchronization run was not found")
    return run


def list_runs(
    session: Session,
    *,
    limit: int,
    offset: int,
    schedule_id: int | None = None,
    provider: str | None = None,
    provider_series_id: str | None = None,
    status: ProviderSyncRunStatus | None = None,
) -> list[ProviderSyncRun]:
    statement: Select[tuple[ProviderSyncRun]] = select(ProviderSyncRun)
    if schedule_id is not None:
        statement = statement.where(ProviderSyncRun.schedule_id == schedule_id)
    if provider is not None:
        statement = statement.where(ProviderSyncRun.provider == normalize_provider_name(provider))
    if provider_series_id is not None:
        statement = statement.where(ProviderSyncRun.provider_series_id == provider_series_id)
    if status is not None:
        statement = statement.where(ProviderSyncRun.status == status.value)
    return list(
        session.scalars(
            statement.order_by(
                ProviderSyncRun.created_at.desc(),
                ProviderSyncRun.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
    )


def materialize_due_schedules(
    session: Session,
    *,
    now: datetime,
    limit: int,
    maximum_attempts: int,
) -> list[ProviderSyncRun]:
    current = require_aware_utc(now, field="now")
    statement = (
        select(ProviderSyncSchedule)
        .where(
            ProviderSyncSchedule.enabled.is_(True),
            ProviderSyncSchedule.next_run_at.is_not(None),
            ProviderSyncSchedule.next_run_at <= current,
        )
        .order_by(ProviderSyncSchedule.next_run_at, ProviderSyncSchedule.id)
        .limit(limit)
    )
    if session.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update(skip_locked=True)
    schedules = list(session.scalars(statement))
    created: list[ProviderSyncRun] = []
    for schedule in schedules:
        assert schedule.next_run_at is not None
        due, following = coalesce_due_occurrences(
            _cadence_from_schedule(schedule),
            next_run_at=schedule.next_run_at,
            now=current,
        )
        if due is None:
            continue
        run = _new_run(
            schedule,
            trigger_type=ProviderSyncTriggerType.scheduled,
            scheduled_for=due,
            created_at=current,
            maximum_attempts=maximum_attempts,
            request_idempotency_hash=None,
        )
        existing = session.scalar(
            select(ProviderSyncRun).where(ProviderSyncRun.run_key == run.run_key)
        )
        if existing is None:
            session.add(run)
            created.append(run)
        schedule.last_scheduled_at = due
        schedule.next_run_at = following
        schedule.updated_at = current
        schedule.lock_version += 1
    try:
        _commit(session, "Due schedule materialization conflicted with another worker")
    except SchedulerConflictError:
        return []
    for run in created:
        session.refresh(run)
    return created


def claim_pending_runs(
    session: Session,
    *,
    worker_id: str,
    now: datetime,
    lease_seconds: int,
    limit: int,
) -> list[ProviderSyncRun]:
    if not worker_id or len(worker_id) > 128:
        raise ValueError("Worker ID is invalid")
    current = require_aware_utc(now, field="now")
    effective_limit = 1 if session.get_bind().dialect.name == "sqlite" else limit
    running = aliased(ProviderSyncRun)
    statement = (
        select(ProviderSyncRun)
        .where(
            ProviderSyncRun.status == ProviderSyncRunStatus.pending.value,
            or_(
                ProviderSyncRun.next_attempt_at.is_(None),
                ProviderSyncRun.next_attempt_at <= current,
            ),
            ProviderSyncRun.attempt_number < ProviderSyncRun.maximum_attempts,
            ~exists(
                select(1).where(
                    running.concurrency_key == ProviderSyncRun.concurrency_key,
                    running.status == ProviderSyncRunStatus.running.value,
                )
            ),
        )
        .order_by(
            ProviderSyncRun.next_attempt_at,
            ProviderSyncRun.scheduled_for,
            ProviderSyncRun.id,
        )
        .limit(effective_limit)
    )
    if session.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update(skip_locked=True)
    candidates = list(session.scalars(statement))
    distinct_candidates: list[ProviderSyncRun] = []
    concurrency_keys: set[str] = set()
    for candidate in candidates:
        if candidate.concurrency_key in concurrency_keys:
            continue
        concurrency_keys.add(candidate.concurrency_key)
        distinct_candidates.append(candidate)
    claimed: list[ProviderSyncRun] = []
    try:
        for run in distinct_candidates:
            result = cast(
                CursorResult[Any],
                session.execute(
                    update(ProviderSyncRun)
                    .where(
                        ProviderSyncRun.id == run.id,
                        ProviderSyncRun.status == ProviderSyncRunStatus.pending.value,
                        ProviderSyncRun.lease_generation == run.lease_generation,
                    )
                    .values(
                        status=ProviderSyncRunStatus.running.value,
                        attempt_number=run.attempt_number + 1,
                        lease_generation=run.lease_generation + 1,
                        started_at=run.started_at or current,
                        lease_owner=worker_id,
                        lease_acquired_at=current,
                        lease_expires_at=current + timedelta(seconds=lease_seconds),
                        next_attempt_at=None,
                    )
                ),
            )
            if result.rowcount == 1:
                claimed.append(run)
        session.commit()
    except IntegrityError:
        session.rollback()
        return []
    return [get_run(session, run.id) for run in claimed]


def _fenced_running_predicate(
    run_id: int,
    *,
    worker_id: str,
    lease_generation: int,
    now: datetime,
) -> tuple[Any, ...]:
    return (
        ProviderSyncRun.id == run_id,
        ProviderSyncRun.status == ProviderSyncRunStatus.running.value,
        ProviderSyncRun.lease_owner == worker_id,
        ProviderSyncRun.lease_generation == lease_generation,
        ProviderSyncRun.lease_expires_at > now,
    )


def renew_lease(
    session: Session,
    run_id: int,
    *,
    worker_id: str,
    lease_generation: int,
    now: datetime,
    lease_seconds: int,
) -> bool:
    current = require_aware_utc(now, field="now")
    result = cast(
        CursorResult[Any],
        session.execute(
            update(ProviderSyncRun)
            .where(
                *_fenced_running_predicate(
                    run_id,
                    worker_id=worker_id,
                    lease_generation=lease_generation,
                    now=current,
                )
            )
            .values(
                lease_acquired_at=current,
                lease_expires_at=current + timedelta(seconds=lease_seconds),
            )
        ),
    )
    session.commit()
    return result.rowcount == 1


def complete_run_success(
    session: Session,
    run_id: int,
    *,
    worker_id: str,
    lease_generation: int,
    result: ProviderSyncResult,
    now: datetime,
) -> bool:
    current = require_aware_utc(now, field="now")
    update_result = cast(
        CursorResult[Any],
        session.execute(
            update(ProviderSyncRun)
            .where(
                *_fenced_running_predicate(
                    run_id,
                    worker_id=worker_id,
                    lease_generation=lease_generation,
                    now=current,
                )
            )
            .values(
                status=ProviderSyncRunStatus.succeeded.value,
                completed_at=current,
                lease_owner=None,
                lease_acquired_at=None,
                lease_expires_at=None,
                import_batch_id=result.import_batch_id,
                observations_received=result.observations_received,
                observations_accepted=result.observations_accepted,
                observations_revised=result.observations_revised,
                observations_missing=result.observations_missing,
                observations_rejected=result.observations_rejected,
                provider_replay=result.idempotent_replay,
                error_code=None,
                error_message=None,
            )
        ),
    )
    session.commit()
    return update_result.rowcount == 1


def deterministic_retry_delay(
    run_id: int,
    attempt_number: int,
    *,
    base_seconds: int,
    maximum_seconds: int,
) -> int:
    exponential = min(base_seconds * (2 ** max(attempt_number - 1, 0)), maximum_seconds)
    digest = hashlib.sha256(f"{run_id}:{attempt_number}".encode()).digest()
    spread = (int.from_bytes(digest[:2], "big") % 101) / 1000
    return int(min(maximum_seconds, exponential + int(exponential * spread)))


def classify_failure(exc: Exception) -> RetryDecision:
    if isinstance(exc, ProviderError):
        retryable = exc.code in {
            ProviderErrorCode.timeout,
            ProviderErrorCode.unavailable,
            ProviderErrorCode.rate_limited,
        }
        messages = {
            ProviderErrorCode.timeout: "External provider timed out",
            ProviderErrorCode.unavailable: "External provider is unavailable",
            ProviderErrorCode.rate_limited: "External provider rate limit was exhausted",
            ProviderErrorCode.configuration_error: "Provider configuration is unavailable",
            ProviderErrorCode.authentication_failed: "Provider authentication failed",
            ProviderErrorCode.series_not_found: "Provider series was not found",
            ProviderErrorCode.unsupported_metadata: "Provider metadata is unsupported",
            ProviderErrorCode.malformed_response: "Provider response was invalid",
            ProviderErrorCode.response_too_large: "Provider response exceeded safety limits",
        }
        return RetryDecision(retryable, exc.code.value, messages[exc.code])
    if isinstance(exc, (DataConflictError, IntegrityConflictError)):
        return RetryDecision(False, "synchronization_conflict", "Synchronization conflicted")
    if isinstance(exc, DBAPIError):
        return RetryDecision(True, "database_unavailable", "Database operation was unavailable")
    return RetryDecision(True, "internal_error", "Scheduled synchronization failed safely")


def schedule_run_retry(
    session: Session,
    run_id: int,
    *,
    worker_id: str,
    lease_generation: int,
    now: datetime,
    base_seconds: int,
    maximum_seconds: int,
) -> bool:
    current = require_aware_utc(now, field="now")
    run = session.get(ProviderSyncRun, run_id)
    if run is None:
        return False
    delay = deterministic_retry_delay(
        run.id,
        run.attempt_number,
        base_seconds=base_seconds,
        maximum_seconds=maximum_seconds,
    )
    result = cast(
        CursorResult[Any],
        session.execute(
            update(ProviderSyncRun)
            .where(
                *_fenced_running_predicate(
                    run_id,
                    worker_id=worker_id,
                    lease_generation=lease_generation,
                    now=current,
                )
            )
            .values(
                status=ProviderSyncRunStatus.pending.value,
                next_attempt_at=current + timedelta(seconds=delay),
                lease_owner=None,
                lease_acquired_at=None,
                lease_expires_at=None,
                error_code=None,
                error_message=None,
            )
        ),
    )
    session.commit()
    return result.rowcount == 1


def complete_run_failure(
    session: Session,
    run_id: int,
    *,
    worker_id: str,
    lease_generation: int,
    now: datetime,
    error_code: str,
    error_message: str,
) -> bool:
    current = require_aware_utc(now, field="now")
    safe_code = error_code[:64] or "scheduled_sync_failed"
    safe_message = error_message[:MAX_ERROR_MESSAGE_LENGTH] or "Scheduled synchronization failed"
    result = cast(
        CursorResult[Any],
        session.execute(
            update(ProviderSyncRun)
            .where(
                *_fenced_running_predicate(
                    run_id,
                    worker_id=worker_id,
                    lease_generation=lease_generation,
                    now=current,
                )
            )
            .values(
                status=ProviderSyncRunStatus.failed.value,
                completed_at=current,
                next_attempt_at=None,
                lease_owner=None,
                lease_acquired_at=None,
                lease_expires_at=None,
                error_code=safe_code,
                error_message=safe_message,
            )
        ),
    )
    session.commit()
    return result.rowcount == 1


def recover_expired_runs(
    session: Session,
    *,
    now: datetime,
    limit: int,
    base_seconds: int,
    maximum_seconds: int,
) -> int:
    current = require_aware_utc(now, field="now")
    statement = (
        select(ProviderSyncRun)
        .where(
            ProviderSyncRun.status == ProviderSyncRunStatus.running.value,
            ProviderSyncRun.lease_expires_at <= current,
        )
        .order_by(ProviderSyncRun.lease_expires_at, ProviderSyncRun.id)
        .limit(limit)
    )
    if session.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update(skip_locked=True)
    expired = list(session.scalars(statement))
    recovered = 0
    for run in expired:
        predicate = (
            ProviderSyncRun.id == run.id,
            ProviderSyncRun.status == ProviderSyncRunStatus.running.value,
            ProviderSyncRun.lease_generation == run.lease_generation,
            ProviderSyncRun.lease_expires_at <= current,
        )
        if run.attempt_number < run.maximum_attempts:
            delay = deterministic_retry_delay(
                run.id,
                run.attempt_number,
                base_seconds=base_seconds,
                maximum_seconds=maximum_seconds,
            )
            values: dict[str, Any] = {
                "status": ProviderSyncRunStatus.pending.value,
                "next_attempt_at": current + timedelta(seconds=delay),
                "lease_owner": None,
                "lease_acquired_at": None,
                "lease_expires_at": None,
                "error_code": None,
                "error_message": None,
            }
        else:
            values = {
                "status": ProviderSyncRunStatus.failed.value,
                "completed_at": current,
                "next_attempt_at": None,
                "lease_owner": None,
                "lease_acquired_at": None,
                "lease_expires_at": None,
                "error_code": "lease_expired",
                "error_message": "Worker lease expired before synchronization completed",
            }
        result = cast(
            CursorResult[Any],
            session.execute(update(ProviderSyncRun).where(*predicate).values(**values)),
        )
        recovered += int(result.rowcount == 1)
    session.commit()
    return recovered


def _sync_request_for_run(
    *,
    provider: str,
    request_snapshot: dict[str, Any],
    sync_idempotency_key: str,
    internal_series_code: str | None,
) -> ProviderSeriesSyncRequest:
    config = validate_safe_config(request_snapshot)
    values = config.model_dump(exclude_none=True)
    values["internal_series_code"] = internal_series_code
    values["idempotency_key"] = sync_idempotency_key
    if provider == "fred":
        return FREDSeriesSyncRequest.model_validate(values)
    return ProviderSeriesSyncRequest.model_validate(values)


def execute_claimed_run(
    session_factory: SessionFactory,
    run_id: int,
    *,
    worker_id: str,
    lease_generation: int,
    registry: ProviderRegistry,
    settings: Settings,
    now: datetime | None = None,
) -> bool:
    current = _now(now)
    with session_factory() as read_session:
        run = get_run(read_session, run_id)
        if (
            run.status != ProviderSyncRunStatus.running.value
            or run.lease_owner != worker_id
            or run.lease_generation != lease_generation
            or run.lease_expires_at is None
            or run.lease_expires_at <= current
        ):
            return False
        schedule = get_schedule(read_session, run.schedule_id)
        detached = {
            "provider": run.provider,
            "provider_series_id": run.provider_series_id,
            "request_snapshot": dict(run.request_snapshot),
            "sync_idempotency_key": run.sync_idempotency_key,
            "internal_series_code": schedule.internal_series_code,
        }
    provider = None
    try:
        provider_name = cast(str, detached["provider"])
        provider_series_id = cast(str, detached["provider_series_id"])
        provider = registry.create(provider_name, settings)
        request = _sync_request_for_run(
            provider=provider_name,
            request_snapshot=cast(dict[str, Any], detached["request_snapshot"]),
            sync_idempotency_key=cast(str, detached["sync_idempotency_key"]),
            internal_series_code=cast(str | None, detached["internal_series_code"]),
        )
        with session_factory() as sync_session:
            result = synchronize_provider_series(
                sync_session,
                provider,
                provider_series_id,
                request,
            )
        with session_factory() as completion_session:
            return complete_run_success(
                completion_session,
                run_id,
                worker_id=worker_id,
                lease_generation=lease_generation,
                result=result,
                now=_now(now),
            )
    except Exception as exc:
        decision = classify_failure(exc)
        with session_factory() as failure_session:
            persisted = failure_session.get(ProviderSyncRun, run_id)
            if persisted is None:
                return False
            can_retry = decision.retryable and persisted.attempt_number < persisted.maximum_attempts
            if can_retry:
                return schedule_run_retry(
                    failure_session,
                    run_id,
                    worker_id=worker_id,
                    lease_generation=lease_generation,
                    now=_now(now),
                    base_seconds=settings.scheduler_retry_base_seconds,
                    maximum_seconds=settings.scheduler_retry_max_seconds,
                )
            return complete_run_failure(
                failure_session,
                run_id,
                worker_id=worker_id,
                lease_generation=lease_generation,
                now=_now(now),
                error_code=decision.error_code,
                error_message=decision.error_message,
            )
    finally:
        close = getattr(provider, "close", None)
        if callable(close):
            close()
