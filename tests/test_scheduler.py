from collections.abc import Generator
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import cast

import pytest
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import Engine, Table, delete, inspect, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateIndex, CreateTable

from macrovision.config import Settings, get_settings
from macrovision.database import create_database_engine
from macrovision.fred_provider import FREDProvider
from macrovision.provider_contracts import ExternalDataProvider, ProviderError
from macrovision.provider_registry import ProviderRegistry, get_provider_registry
from macrovision.scheduler_models import ProviderSyncRun, ProviderSyncSchedule
from macrovision.scheduler_schemas import (
    MAX_INTERVAL_MINUTES,
    MIN_INTERVAL_MINUTES,
    ProviderSyncRunStatus,
    ProviderSyncTriggerType,
    SafeProviderSyncConfig,
    ScheduleCadence,
    ScheduleCadenceType,
)
from macrovision.scheduler_services import (
    calculate_initial_next_run_at,
    calculate_latest_due_occurrence,
    calculate_next_future_occurrence,
    canonicalize_request_config,
    coalesce_due_occurrences,
    fingerprint_request_config,
    generate_concurrency_key,
    generate_run_key,
    generate_sync_idempotency_key,
    hash_external_idempotency_key,
    require_aware_utc,
)


@pytest.fixture
def scheduler_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[Engine, None, None]:
    database_url = f"sqlite:///{tmp_path / 'scheduler.db'}"
    monkeypatch.setenv("MACROVISION_DATABASE_URL", database_url)
    get_settings.cache_clear()
    command.upgrade(Config("alembic.ini"), "head")
    engine = create_database_engine(database_url)
    try:
        yield engine
    finally:
        engine.dispose()
        get_settings.cache_clear()


def _schedule(
    *,
    provider: str = "fred",
    provider_series_id: str = "GDP",
    now: datetime | None = None,
) -> ProviderSyncSchedule:
    current = now or datetime(2026, 7, 25, 12, tzinfo=UTC)
    config, _ = canonicalize_request_config({"category": "growth", "geography": "US"})
    return ProviderSyncSchedule(
        provider=provider,
        provider_series_id=provider_series_id,
        internal_series_code=f"{provider.upper()}.{provider_series_id}",
        request_config=config,
        request_config_fingerprint=fingerprint_request_config(config),
        cadence_type=ScheduleCadenceType.fixed_interval.value,
        interval_minutes=60,
        daily_time_utc=None,
        next_run_at=current + timedelta(hours=1),
        enabled=True,
        last_scheduled_at=None,
        created_at=current,
        updated_at=current,
        lock_version=1,
    )


def _run(
    schedule: ProviderSyncSchedule,
    *,
    suffix: str,
    status: ProviderSyncRunStatus = ProviderSyncRunStatus.pending,
    trigger: ProviderSyncTriggerType = ProviderSyncTriggerType.scheduled,
    now: datetime | None = None,
) -> ProviderSyncRun:
    current = now or datetime(2026, 7, 25, 12, tzinfo=UTC)
    request_hash = (
        hash_external_idempotency_key(f"request-{suffix}") if trigger == "manual" else None
    )
    run_key = generate_run_key(
        schedule_id=schedule.id,
        trigger_type=trigger,
        scheduled_for=current,
        request_fingerprint=schedule.request_config_fingerprint,
        request_idempotency_hash=request_hash,
    )
    running = status == ProviderSyncRunStatus.running
    failed = status == ProviderSyncRunStatus.failed
    return ProviderSyncRun(
        schedule_id=schedule.id,
        run_key=run_key,
        trigger_type=trigger.value,
        provider=schedule.provider,
        provider_series_id=schedule.provider_series_id,
        concurrency_key=generate_concurrency_key(
            schedule.provider,
            schedule.provider_series_id,
        ),
        request_snapshot=schedule.request_config,
        request_snapshot_fingerprint=schedule.request_config_fingerprint,
        status=status.value,
        scheduled_for=current,
        created_at=current,
        started_at=current if running or failed else None,
        completed_at=current if failed else None,
        attempt_number=1 if running or failed else 0,
        maximum_attempts=2,
        next_attempt_at=current if status == ProviderSyncRunStatus.pending else None,
        lease_owner=f"worker-{suffix}" if running else None,
        lease_acquired_at=current if running else None,
        lease_expires_at=current + timedelta(minutes=5) if running else None,
        lease_generation=1 if running else 0,
        request_idempotency_hash=request_hash,
        sync_idempotency_key=generate_sync_idempotency_key(run_key),
        observations_received=0,
        observations_accepted=0,
        observations_revised=0,
        observations_missing=0,
        observations_rejected=0,
        provider_replay=None,
        error_code="test_failure" if failed else None,
        error_message="Sanitized failure" if failed else None,
    )


def test_provider_registry_is_code_defined_and_safe() -> None:
    registry = get_provider_registry()
    assert registry.supported_providers() == ("fred",)
    provider = registry.create(
        " FRED ",
        Settings(fred_api_key="private-test-credential"),
    )
    try:
        assert isinstance(provider, FREDProvider)
        assert "private-test-credential" not in repr(provider)
    finally:
        cast(FREDProvider, provider).close()

    with pytest.raises(ProviderError, match="not supported"):
        registry.create("unknown", Settings())
    with pytest.raises(ProviderError, match="invalid"):
        registry.create("", Settings())
    with pytest.raises(ProviderError, match="invalid"):
        registry.create("x" * 41, Settings())


def test_provider_registry_rejects_duplicate_registration() -> None:
    registry = ProviderRegistry()

    def factory(_: Settings) -> ExternalDataProvider:
        raise AssertionError("factory must not run during registration")

    registry.register("fred", factory)
    with pytest.raises(ProviderError, match="already registered"):
        registry.register("FRED", factory)


@pytest.mark.parametrize(
    "forbidden",
    [
        {"api_key": "secret"},
        {"authorization": "secret"},
        {"provider_base_url": "https://example.invalid"},
        {"idempotency_key": "raw"},
        {"expected_lock_version": 1},
        {"payload": {"nested": "value"}},
    ],
)
def test_safe_configuration_rejects_secrets_and_arbitrary_fields(
    forbidden: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        SafeProviderSyncConfig.model_validate(forbidden)


def test_request_configuration_is_canonical_and_fingerprinted() -> None:
    first, first_json = canonicalize_request_config(
        {
            "geography": "US",
            "category": "growth",
            "observation_start": "2020-01-01",
            "currency": None,
        }
    )
    second, second_json = canonicalize_request_config(
        {
            "observation_start": "2020-01-01",
            "category": "growth",
            "geography": "US",
        }
    )
    assert first == second
    assert first_json == second_json
    assert first_json == ('{"category":"growth","geography":"US","observation_start":"2020-01-01"}')
    assert fingerprint_request_config(first) == fingerprint_request_config(second)
    assert len(fingerprint_request_config(first)) == 64


def test_request_configuration_size_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("macrovision.scheduler_services.MAX_REQUEST_CONFIG_BYTES", 10)
    with pytest.raises(ValueError, match="size limit"):
        canonicalize_request_config({"metadata_notes": "bounded"})


def test_cadence_validation_boundaries() -> None:
    for minutes in (MIN_INTERVAL_MINUTES, MAX_INTERVAL_MINUTES):
        cadence = ScheduleCadence(
            cadence_type="fixed_interval",
            interval_minutes=minutes,
        )
        assert cadence.interval_minutes == minutes
    for minutes in (MIN_INTERVAL_MINUTES - 1, MAX_INTERVAL_MINUTES + 1):
        with pytest.raises(ValidationError):
            ScheduleCadence(cadence_type="fixed_interval", interval_minutes=minutes)
    with pytest.raises(ValidationError):
        ScheduleCadence(
            cadence_type="fixed_interval",
            interval_minutes=5,
            daily_time_utc=time(12),
        )
    with pytest.raises(ValidationError):
        ScheduleCadence(cadence_type="daily_utc", daily_time_utc=time(12, 0, 1))


def test_aware_utc_and_fixed_interval_calculations() -> None:
    cadence = ScheduleCadence(cadence_type="fixed_interval", interval_minutes=5)
    now = datetime(2026, 7, 25, 12, 2, tzinfo=UTC)
    assert calculate_initial_next_run_at(cadence, now=now) == datetime(
        2026, 7, 25, 12, 7, tzinfo=UTC
    )
    first_due = datetime(2026, 7, 25, 11, 0, tzinfo=UTC)
    assert calculate_latest_due_occurrence(
        cadence,
        next_run_at=first_due,
        now=now,
    ) == datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
    due, following = coalesce_due_occurrences(cadence, next_run_at=first_due, now=now)
    assert due == datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
    assert following == datetime(2026, 7, 25, 12, 5, tzinfo=UTC)
    with pytest.raises(ValueError, match="timezone-aware"):
        require_aware_utc(datetime(2026, 7, 25, 12))


def test_daily_utc_boundaries_and_clock_rollback() -> None:
    cadence = ScheduleCadence(cadence_type="daily_utc", daily_time_utc=time(12))
    before = datetime(2026, 7, 25, 11, 59, tzinfo=UTC)
    exact = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
    assert calculate_initial_next_run_at(cadence, now=before) == exact
    assert calculate_initial_next_run_at(cadence, now=exact) == exact + timedelta(days=1)
    assert calculate_latest_due_occurrence(
        cadence,
        next_run_at=exact,
        now=exact + timedelta(days=3, hours=1),
    ) == exact + timedelta(days=3)
    future = exact + timedelta(days=5)
    rollback_now = exact - timedelta(days=1)
    assert (
        calculate_next_future_occurrence(
            cadence,
            previous=future,
            now=rollback_now,
        )
        == future
    )


def test_deterministic_safe_keys_never_retain_external_idempotency() -> None:
    raw = "caller-supplied-private-token"
    hashed = hash_external_idempotency_key(raw)
    concurrency = generate_concurrency_key("FRED", "GDP")
    run_key = generate_run_key(
        schedule_id=7,
        trigger_type=ProviderSyncTriggerType.manual,
        scheduled_for=datetime(2026, 7, 25, tzinfo=UTC),
        request_fingerprint="a" * 64,
        request_idempotency_hash=hashed,
    )
    sync_key = generate_sync_idempotency_key(run_key)
    assert raw not in hashed + concurrency + run_key + sync_key
    assert len(hashed) == len(concurrency) == len(run_key) == 64
    assert sync_key.startswith("scheduler:")
    assert sync_key == generate_sync_idempotency_key(run_key)


def test_scheduler_constraints_and_partial_running_index(scheduler_engine: Engine) -> None:
    with Session(scheduler_engine, expire_on_commit=False) as session:
        schedule = _schedule()
        session.add(schedule)
        session.commit()

        duplicate = _schedule(provider="fred", provider_series_id="GDP")
        session.add(duplicate)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        first = _run(schedule, suffix="one", status=ProviderSyncRunStatus.running)
        second = _run(schedule, suffix="two", status=ProviderSyncRunStatus.running)
        session.add(first)
        session.commit()
        session.add(second)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        assert (
            session.scalar(select(ProviderSyncRun).where(ProviderSyncRun.id == first.id)) is first
        )


def test_manual_idempotency_hash_is_persisted_without_raw_key(
    scheduler_engine: Engine,
) -> None:
    raw = "never-store-this-value"
    with Session(scheduler_engine, expire_on_commit=False) as session:
        schedule = _schedule()
        session.add(schedule)
        session.commit()
        run = _run(schedule, suffix=raw, trigger=ProviderSyncTriggerType.manual)
        session.add(run)
        session.commit()
        assert run.request_idempotency_hash == hash_external_idempotency_key(f"request-{raw}")
        assert raw not in run.request_idempotency_hash
        assert raw not in run.sync_idempotency_key
        assert raw not in run.run_key


def test_completed_runs_are_immutable_and_schedule_delete_is_restricted(
    scheduler_engine: Engine,
) -> None:
    with Session(scheduler_engine, expire_on_commit=False) as session:
        schedule = _schedule()
        session.add(schedule)
        session.commit()
        run = _run(schedule, suffix="failed", status=ProviderSyncRunStatus.failed)
        session.add(run)
        session.commit()

        run.error_message = "Attempted overwrite"
        with pytest.raises(ValueError, match="immutable"):
            session.commit()
        session.rollback()

        with pytest.raises(ValueError, match="immutable"):
            session.delete(run)
            session.commit()
        session.rollback()

        with pytest.raises(IntegrityError):
            session.execute(
                delete(ProviderSyncSchedule).where(ProviderSyncSchedule.id == schedule.id)
            )
            session.commit()
        session.rollback()


def test_scheduler_schema_and_partial_index_compile_for_postgresql() -> None:
    dialect = postgresql.dialect()  # type: ignore[no-untyped-call]
    schedule_ddl = str(
        CreateTable(cast(Table, ProviderSyncSchedule.__table__)).compile(dialect=dialect)
    )
    run_ddl = str(CreateTable(cast(Table, ProviderSyncRun.__table__)).compile(dialect=dialect))
    assert "CREATE TYPE" not in schedule_ddl + run_ddl
    assert "uq_provider_sync_schedule_provider_series" in schedule_ddl
    assert "ck_provider_sync_run_terminal_result" in run_ddl
    run_table = cast(Table, ProviderSyncRun.__table__)
    partial = next(
        index
        for index in run_table.indexes
        if index.name == "uq_provider_sync_run_running_concurrency"
    )
    partial_ddl = str(CreateIndex(partial).compile(dialect=dialect))
    assert "UNIQUE" in partial_ddl
    assert "WHERE status = 'running'" in partial_ddl


def test_migrated_schema_contains_scheduler_constraints(scheduler_engine: Engine) -> None:
    schema = inspect(scheduler_engine)
    assert {"provider_sync_schedules", "provider_sync_runs"} <= set(schema.get_table_names())
    schedule_uniques = {
        item["name"] for item in schema.get_unique_constraints("provider_sync_schedules")
    }
    assert "uq_provider_sync_schedule_provider_series" in schedule_uniques
    run_indexes = {item["name"]: item for item in schema.get_indexes("provider_sync_runs")}
    assert bool(run_indexes["uq_provider_sync_run_running_concurrency"]["unique"])
    foreign_keys = {item["name"]: item for item in schema.get_foreign_keys("provider_sync_runs")}
    assert foreign_keys["fk_provider_sync_run_schedule"]["options"]["ondelete"] == "RESTRICT"
    assert foreign_keys["fk_provider_sync_run_import_batch"]["options"]["ondelete"] == "RESTRICT"
