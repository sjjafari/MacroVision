from collections.abc import Generator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from macrovision.config import Settings, get_settings
from macrovision.database import create_database_engine, get_db
from macrovision.macro_data_models import DataImportBatch, DataObservation, DataRevision
from macrovision.main import app
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
from macrovision.provider_registry import ProviderRegistry
from macrovision.provider_services import synchronize_provider_series
from macrovision.scheduler_models import ProviderSyncRun, ProviderSyncSchedule
from macrovision.scheduler_schemas import (
    ProviderSyncRunNowRequest,
    ProviderSyncRunStatus,
    ProviderSyncScheduleCreate,
    ProviderSyncSchedulePatch,
    ProviderSyncTriggerType,
    ScheduleCadence,
)
from macrovision.scheduler_services import (
    SchedulerConflictError,
    calculate_latest_due_occurrence,
    calculate_next_future_occurrence,
    claim_pending_runs,
    classify_failure,
    complete_run_failure,
    create_schedule,
    enqueue_run_now,
    execute_claimed_run,
    generate_concurrency_key,
    generate_run_key,
    generate_sync_idempotency_key,
    get_run,
    hash_external_idempotency_key,
    materialize_due_schedules,
    recover_expired_runs,
    renew_lease,
    schedule_run_retry,
    set_schedule_enabled,
    update_schedule,
)
from macrovision.scheduler_worker import (
    LeaseHeartbeat,
    execute_with_heartbeat,
    run_cycle,
    verify_database,
)
from macrovision.scheduler_worker import main as worker_main


class StubScheduledProvider:
    identity = ProviderIdentity(
        code="STUB",
        name="Scheduled Stub",
        reference_url="https://provider.test/",
    )

    def get_series_metadata(
        self,
        series_id: str,
        query: SeriesMetadataQuery | None = None,
    ) -> ProviderSeriesMetadata:
        del query
        return ProviderSeriesMetadata(
            provider_series_id=series_id,
            title=f"Series {series_id}",
            description="Offline scheduled provider fixture",
            frequency=ProviderFrequency.monthly,
            unit="Index",
            seasonal_adjustment=ProviderSeasonalAdjustment.adjusted,
            observation_start=date(2026, 1, 1),
            observation_end=date(2026, 1, 1),
            realtime_start=date(2026, 2, 1),
            realtime_end=date(2026, 2, 1),
        )

    def get_observations(
        self,
        series_id: str,
        query: ObservationQuery,
    ) -> list[ProviderObservation]:
        del query
        return [
            ProviderObservation(
                observed_on=date(2026, 1, 1),
                value=Decimal("123.45670000"),
                is_missing=False,
                publication_timestamp=None,
                vintage_start=date(2026, 2, 1),
                vintage_end=date(2026, 2, 1),
                source_reference=f"https://provider.test/series/{series_id}",
            )
        ]

    def check_health(self) -> ProviderHealth:
        return ProviderHealth(available=True, checked_at=datetime(2026, 1, 1, tzinfo=UTC))

    def close(self) -> None:
        return None


@pytest.fixture
def scheduler_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[tuple[Engine, sessionmaker[Session]], None, None]:
    database_url = f"sqlite:///{tmp_path / 'phase2.db'}"
    monkeypatch.setenv("MACROVISION_DATABASE_URL", database_url)
    get_settings.cache_clear()
    command.upgrade(Config("alembic.ini"), "head")
    engine = create_database_engine(database_url)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        yield engine, factory
    finally:
        engine.dispose()
        get_settings.cache_clear()


def _registry() -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register("stub", lambda _: StubScheduledProvider())
    return registry


def _create_payload(
    series_id: str = "GDP",
    *,
    enabled: bool = True,
) -> ProviderSyncScheduleCreate:
    return ProviderSyncScheduleCreate(
        provider="stub",
        provider_series_id=series_id,
        internal_series_code=f"STUB.{series_id}",
        request_config={"category": "growth", "geography": "US"},
        cadence_type="fixed_interval",
        interval_minutes=5,
        enabled=enabled,
    )


def _create_schedule(
    factory: sessionmaker[Session],
    *,
    now: datetime,
    series_id: str = "GDP",
    enabled: bool = True,
) -> ProviderSyncSchedule:
    with factory() as session:
        return create_schedule(
            session,
            _create_payload(series_id, enabled=enabled),
            registry=_registry(),
            now=now,
        )


def _enqueue(
    factory: sessionmaker[Session],
    schedule_id: int,
    *,
    key: str,
    now: datetime,
) -> ProviderSyncRun:
    with factory() as session:
        return enqueue_run_now(
            session,
            schedule_id,
            ProviderSyncRunNowRequest(idempotency_key=key),
            maximum_attempts=2,
            now=now,
        )


def test_scheduler_api_crud_run_now_filters_and_safe_openapi(
    scheduler_runtime: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = scheduler_runtime

    def override_get_db() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            payload = {
                "provider": "fred",
                "provider_series_id": "GDP",
                "internal_series_code": "FRED.GDP",
                "request_config": {"category": "growth", "geography": "US"},
                "cadence_type": "fixed_interval",
                "interval_minutes": 60,
                "enabled": True,
            }
            created = client.post("/api/v1/provider-sync-schedules", json=payload)
            assert created.status_code == 201, created.text
            schedule = created.json()
            assert schedule["provider"] == "fred"
            assert schedule["lock_version"] == 1
            schedule_id = schedule["id"]

            duplicate = client.post("/api/v1/provider-sync-schedules", json=payload)
            assert duplicate.status_code == 409
            unknown = client.post(
                "/api/v1/provider-sync-schedules",
                json={**payload, "provider": "unknown", "provider_series_id": "OTHER"},
            )
            assert unknown.status_code == 422
            assert client.get("/api/v1/provider-sync-schedules").json()[0]["id"] == schedule_id

            patched = client.patch(
                f"/api/v1/provider-sync-schedules/{schedule_id}",
                json={
                    "expected_lock_version": 1,
                    "request_config": {"category": "growth", "geography": "USA"},
                    "interval_minutes": 120,
                },
            )
            assert patched.status_code == 200, patched.text
            assert patched.json()["lock_version"] == 2
            assert patched.json()["interval_minutes"] == 120
            stale = client.patch(
                f"/api/v1/provider-sync-schedules/{schedule_id}",
                json={"expected_lock_version": 1, "interval_minutes": 180},
            )
            assert stale.status_code == 409

            disabled = client.post(
                f"/api/v1/provider-sync-schedules/{schedule_id}/disable",
                json={"expected_lock_version": 2},
            )
            assert disabled.status_code == 200
            assert disabled.json()["enabled"] is False
            assert disabled.json()["next_run_at"] is None

            first = client.post(
                f"/api/v1/provider-sync-schedules/{schedule_id}/runs",
                json={"idempotency_key": "api-manual-key"},
            )
            second = client.post(
                f"/api/v1/provider-sync-schedules/{schedule_id}/runs",
                json={"idempotency_key": "api-manual-key"},
            )
            assert first.status_code == second.status_code == 202
            assert first.json()["id"] == second.json()["id"]
            serialized = first.text.lower()
            assert "idempotency" not in serialized
            assert "lease_owner" not in serialized
            assert "sync_idempotency" not in serialized

            filtered = client.get("/api/v1/provider-sync-runs?status=pending")
            assert filtered.status_code == 200
            assert [item["id"] for item in filtered.json()] == [first.json()["id"]]
            assert client.get("/api/v1/provider-sync-runs?limit=201").status_code == 422
            assert client.get("/api/v1/provider-sync-runs/999999").status_code == 404
            assert client.get("/api/v1/provider-sync-schedules/999999").status_code == 404

            document = client.get("/openapi.json").json()
            expected_paths = {
                "/api/v1/provider-sync-schedules",
                "/api/v1/provider-sync-schedules/{schedule_id}",
                "/api/v1/provider-sync-schedules/{schedule_id}/enable",
                "/api/v1/provider-sync-schedules/{schedule_id}/disable",
                "/api/v1/provider-sync-schedules/{schedule_id}/runs",
                "/api/v1/provider-sync-runs",
                "/api/v1/provider-sync-runs/{run_id}",
                "/api/v1/providers/fred/series/{fred_series_id}/sync",
            }
            assert expected_paths <= set(document["paths"])
            scheduler_document = str(
                {key: value for key, value in document["paths"].items() if "provider-sync" in key}
            ).lower()
            for secret_field in (
                "fred_api_key",
                "authorization",
                "request_idempotency_hash",
                "sync_idempotency_key",
                "lease_owner",
            ):
                assert secret_field not in scheduler_document
    finally:
        app.dependency_overrides.clear()


def test_run_now_changed_snapshot_conflicts_and_raw_key_is_absent(
    scheduler_runtime: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = scheduler_runtime
    now = datetime(2026, 7, 26, 12, tzinfo=UTC)
    schedule = _create_schedule(factory, now=now)
    first = _enqueue(factory, schedule.id, key="raw-external-value", now=now)
    with factory() as session:
        updated = update_schedule(
            session,
            schedule.id,
            ProviderSyncSchedulePatch(
                expected_lock_version=1,
                request_config={"category": "growth", "geography": "GLOBAL"},
            ),
            now=now + timedelta(minutes=1),
        )
        assert updated.lock_version == 2
    with factory() as session, pytest.raises(SchedulerConflictError):
        enqueue_run_now(
            session,
            schedule.id,
            ProviderSyncRunNowRequest(idempotency_key="raw-external-value"),
            maximum_attempts=2,
            now=now + timedelta(minutes=2),
        )
    with factory() as session:
        persisted = get_run(session, first.id)
        assert "raw-external-value" not in (
            cast(str, persisted.request_idempotency_hash)
            + persisted.run_key
            + persisted.sync_idempotency_key
        )
        assert persisted.request_snapshot["geography"] == "US"


def test_due_materialization_coalesces_and_is_idempotent(
    scheduler_runtime: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = scheduler_runtime
    start = datetime(2026, 7, 26, 10, tzinfo=UTC)
    schedule = _create_schedule(factory, now=start)
    outage_end = start + timedelta(minutes=32)
    with factory() as session:
        first = materialize_due_schedules(
            session,
            now=outage_end,
            limit=10,
            maximum_attempts=2,
        )
    assert len(first) == 1
    assert first[0].scheduled_for == start + timedelta(minutes=30)
    with factory() as session:
        repeated = materialize_due_schedules(
            session,
            now=outage_end,
            limit=10,
            maximum_attempts=2,
        )
        persisted_schedule = session.get(ProviderSyncSchedule, schedule.id)
        assert persisted_schedule is not None
        assert persisted_schedule.next_run_at == start + timedelta(minutes=35)
        assert persisted_schedule.last_scheduled_at == start + timedelta(minutes=30)
        assert persisted_schedule.lock_version == 2
    assert repeated == []


def test_disable_does_not_cancel_existing_run(
    scheduler_runtime: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = scheduler_runtime
    now = datetime(2026, 7, 26, 10, tzinfo=UTC)
    schedule = _create_schedule(factory, now=now)
    run = _enqueue(factory, schedule.id, key="keep-pending", now=now)
    with factory() as session:
        disabled = set_schedule_enabled(
            session,
            schedule.id,
            expected_lock_version=1,
            enabled=False,
            now=now + timedelta(minutes=1),
        )
        assert disabled.next_run_at is None
        assert get_run(session, run.id).status == ProviderSyncRunStatus.pending.value


def test_sqlite_claim_contention_and_provider_series_exclusion(
    scheduler_runtime: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = scheduler_runtime
    now = datetime(2026, 7, 26, 10, tzinfo=UTC)
    first_schedule = _create_schedule(factory, now=now, series_id="GDP")
    second_schedule = _create_schedule(factory, now=now, series_id="CPI")
    first = _enqueue(factory, first_schedule.id, key="first", now=now)
    same_series = _enqueue(factory, first_schedule.id, key="same-series", now=now)
    other_series = _enqueue(factory, second_schedule.id, key="other-series", now=now)

    with factory() as session:
        claimed_first = claim_pending_runs(
            session,
            worker_id="worker-one",
            now=now,
            lease_seconds=300,
            limit=10,
        )
    assert [run.id for run in claimed_first] == [first.id]
    with factory() as session:
        claimed_second = claim_pending_runs(
            session,
            worker_id="worker-two",
            now=now,
            lease_seconds=300,
            limit=10,
        )
    assert [run.id for run in claimed_second] == [other_series.id]
    with factory() as session:
        assert get_run(session, same_series.id).status == ProviderSyncRunStatus.pending.value
        no_duplicate = claim_pending_runs(
            session,
            worker_id="worker-three",
            now=now,
            lease_seconds=300,
            limit=10,
        )
        assert no_duplicate == []


def test_lease_fencing_recovery_and_exhaustion(
    scheduler_runtime: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = scheduler_runtime
    now = datetime(2026, 7, 26, 10, tzinfo=UTC)
    schedule = _create_schedule(factory, now=now)
    pending = _enqueue(factory, schedule.id, key="lease-test", now=now)
    with factory() as session:
        claimed = claim_pending_runs(
            session,
            worker_id="original",
            now=now,
            lease_seconds=60,
            limit=1,
        )[0]
        assert claimed.id == pending.id
        assert not renew_lease(
            session,
            claimed.id,
            worker_id="original",
            lease_generation=claimed.lease_generation + 1,
            now=now + timedelta(seconds=10),
            lease_seconds=60,
        )

    expired_at = now + timedelta(seconds=61)
    with factory() as session:
        assert (
            recover_expired_runs(
                session,
                now=expired_at,
                limit=10,
                base_seconds=30,
                maximum_seconds=300,
            )
            == 1
        )
        recovered = get_run(session, claimed.id)
        assert recovered.status == ProviderSyncRunStatus.pending.value
        assert recovered.started_at == now
        assert recovered.next_attempt_at is not None
        retry_at = recovered.next_attempt_at
        assert not complete_run_failure(
            session,
            recovered.id,
            worker_id="original",
            lease_generation=claimed.lease_generation,
            now=expired_at,
            error_code="stale",
            error_message="Must not write",
        )

    with factory() as session:
        reclaimed = claim_pending_runs(
            session,
            worker_id="replacement",
            now=retry_at,
            lease_seconds=60,
            limit=1,
        )[0]
        assert reclaimed.lease_generation == claimed.lease_generation + 1
    with factory() as session:
        assert (
            recover_expired_runs(
                session,
                now=retry_at + timedelta(seconds=61),
                limit=10,
                base_seconds=30,
                maximum_seconds=300,
            )
            == 1
        )
        failed = get_run(session, reclaimed.id)
        assert failed.status == ProviderSyncRunStatus.failed.value
        assert failed.error_code == "lease_expired"


def test_failure_classification_is_bounded_and_deliberate() -> None:
    retryable = classify_failure(
        ProviderError(ProviderErrorCode.timeout, "unsafe detail", status_code=504)
    )
    assert retryable.retryable
    assert retryable.error_message == "External provider timed out"
    authentication = classify_failure(
        ProviderError(
            ProviderErrorCode.authentication_failed,
            "credential-containing detail",
            status_code=502,
        )
    )
    assert not authentication.retryable
    assert "credential-containing" not in authentication.error_message
    assert classify_failure(RuntimeError("private internals")).error_message == (
        "Scheduled synchronization failed safely"
    )


def test_crash_after_import_replays_batch_without_duplicates(
    scheduler_runtime: tuple[Engine, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, factory = scheduler_runtime
    now = datetime(2026, 7, 26, 10, tzinfo=UTC)
    schedule = _create_schedule(factory, now=now, enabled=False)
    pending = _enqueue(factory, schedule.id, key="crash-window", now=now)
    with factory() as session:
        claimed = claim_pending_runs(
            session,
            worker_id="crashing-worker",
            now=now,
            lease_seconds=60,
            limit=1,
        )[0]
    from macrovision import scheduler_services

    original_complete = scheduler_services.complete_run_success
    original_sync = synchronize_provider_series

    def assert_transaction_boundary(session: Session, *args: Any, **kwargs: Any) -> Any:
        assert not session.in_transaction()
        return original_sync(session, *args, **kwargs)

    monkeypatch.setattr(
        scheduler_services,
        "synchronize_provider_series",
        assert_transaction_boundary,
    )
    monkeypatch.setattr(scheduler_services, "complete_run_success", lambda *a, **k: False)
    assert not execute_claimed_run(
        factory,
        claimed.id,
        worker_id="crashing-worker",
        lease_generation=claimed.lease_generation,
        registry=_registry(),
        settings=Settings(_env_file=None),
        now=now,
    )
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(DataImportBatch)) == 1
        assert session.scalar(select(func.count()).select_from(DataObservation)) == 1
        assert get_run(session, pending.id).status == ProviderSyncRunStatus.running.value

    recovered_at = now + timedelta(seconds=61)
    with factory() as session:
        recover_expired_runs(
            session,
            now=recovered_at,
            limit=10,
            base_seconds=30,
            maximum_seconds=300,
        )
        recovered = get_run(session, pending.id)
        assert recovered.next_attempt_at is not None
        retry_at = recovered.next_attempt_at
    with factory() as session:
        reclaimed = claim_pending_runs(
            session,
            worker_id="replacement-worker",
            now=retry_at,
            lease_seconds=300,
            limit=1,
        )[0]
    monkeypatch.setattr(scheduler_services, "complete_run_success", original_complete)
    assert execute_claimed_run(
        factory,
        reclaimed.id,
        worker_id="replacement-worker",
        lease_generation=reclaimed.lease_generation,
        registry=_registry(),
        settings=Settings(_env_file=None),
        now=retry_at,
    )
    with factory() as session:
        finished = get_run(session, pending.id)
        assert finished.status == ProviderSyncRunStatus.succeeded.value
        assert finished.provider_replay is True
        assert session.scalar(select(func.count()).select_from(DataImportBatch)) == 1
        assert session.scalar(select(func.count()).select_from(DataObservation)) == 1
        assert session.scalar(select(func.count()).select_from(DataRevision)) == 0


def test_worker_cycle_and_cli_are_injectable_and_do_not_sleep(
    scheduler_runtime: tuple[Engine, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, factory = scheduler_runtime
    settings = Settings(_env_file=None)
    verify_database(factory)
    assert (
        run_cycle(
            session_factory=factory,
            registry=_registry(),
            settings=settings,
            worker_id="test-worker",
            now_factory=lambda: datetime(2026, 7, 26, tzinfo=UTC),
        )
        == 0
    )
    monkeypatch.setattr("macrovision.scheduler_worker.verify_database", lambda _: None)
    monkeypatch.setattr("macrovision.scheduler_worker.run_cycle", lambda **_: 0)
    assert worker_main(["--once", "--worker-id", "cli-test"]) == 0
    assert worker_main(["--once", "--claim-limit", "11"]) == 2


def test_execution_failure_retries_then_fails_with_sanitized_error(
    scheduler_runtime: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = scheduler_runtime
    now = datetime(2026, 7, 26, 10, tzinfo=UTC)
    schedule = _create_schedule(factory, now=now, enabled=False)
    pending = _enqueue(factory, schedule.id, key="failure-path", now=now)

    def failing_factory(_: Settings) -> StubScheduledProvider:
        raise ProviderError(
            ProviderErrorCode.timeout,
            "upstream detail must not persist",
            status_code=504,
        )

    retry_registry = ProviderRegistry()
    retry_registry.register("stub", failing_factory)
    with factory() as session:
        first_claim = claim_pending_runs(
            session,
            worker_id="retry-worker",
            now=now,
            lease_seconds=300,
            limit=1,
        )[0]
    assert execute_claimed_run(
        factory,
        first_claim.id,
        worker_id="retry-worker",
        lease_generation=first_claim.lease_generation,
        registry=retry_registry,
        settings=Settings(_env_file=None),
        now=now,
    )
    with factory() as session:
        retry = get_run(session, pending.id)
        assert retry.status == ProviderSyncRunStatus.pending.value
        assert retry.next_attempt_at is not None
        assert retry.error_message is None
        retry_at = retry.next_attempt_at
        assert not schedule_run_retry(
            session,
            999999,
            worker_id="nobody",
            lease_generation=1,
            now=retry_at,
            base_seconds=30,
            maximum_seconds=300,
        )

    def terminal_factory(_: Settings) -> StubScheduledProvider:
        raise ProviderError(
            ProviderErrorCode.authentication_failed,
            "secret upstream diagnostic",
            status_code=502,
        )

    terminal_registry = ProviderRegistry()
    terminal_registry.register("stub", terminal_factory)
    with factory() as session:
        second_claim = claim_pending_runs(
            session,
            worker_id="terminal-worker",
            now=retry_at,
            lease_seconds=300,
            limit=1,
        )[0]
    assert execute_claimed_run(
        factory,
        second_claim.id,
        worker_id="terminal-worker",
        lease_generation=second_claim.lease_generation,
        registry=terminal_registry,
        settings=Settings(_env_file=None),
        now=retry_at,
    )
    with factory() as session:
        failed = get_run(session, pending.id)
        assert failed.status == ProviderSyncRunStatus.failed.value
        assert failed.error_code == ProviderErrorCode.authentication_failed.value
        assert failed.error_message == "Provider authentication failed"
        assert "secret" not in failed.error_message


def test_worker_failure_exit_and_heartbeat_paths(
    scheduler_runtime: tuple[Engine, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, factory = scheduler_runtime
    now = datetime(2026, 7, 26, 10, tzinfo=UTC)
    schedule = _create_schedule(factory, now=now, enabled=False)
    _enqueue(factory, schedule.id, key="worker-failure", now=now)
    settings = Settings(_env_file=None)

    def fail_claimed(
        session_factory: sessionmaker[Session],
        run: ProviderSyncRun,
        **_: Any,
    ) -> bool:
        with session_factory() as session:
            return complete_run_failure(
                session,
                run.id,
                worker_id="cycle-worker",
                lease_generation=run.lease_generation,
                now=now,
                error_code="controlled",
                error_message="Controlled worker failure",
            )

    assert (
        run_cycle(
            session_factory=factory,
            registry=_registry(),
            settings=settings,
            worker_id="cycle-worker",
            now_factory=lambda: now,
            execute=fail_claimed,
        )
        == 1
    )

    monkeypatch.setattr(
        "macrovision.scheduler_worker.verify_database",
        lambda _: (_ for _ in ()).throw(RuntimeError("wrong revision")),
    )
    assert worker_main(["--once"]) == 3
    monkeypatch.setattr("macrovision.scheduler_worker.verify_database", lambda _: None)
    monkeypatch.setattr(
        "macrovision.scheduler_worker.run_cycle",
        lambda **_: (_ for _ in ()).throw(RuntimeError("safe failure")),
    )
    assert worker_main(["--once"]) == 4
    assert worker_main(["--once", "--poll-seconds", "0"]) == 2
    assert worker_main(["--once", "--worker-id", "x" * 129]) == 2

    class ImmediateThread:
        def __init__(self, *, target: Any, name: str, daemon: bool) -> None:
            del name, daemon
            self.target = target

        def start(self) -> None:
            self.target()

        def join(self, timeout: int) -> None:
            assert timeout == 2

    class OneHeartbeat:
        calls = 0

        def wait(self, _: int) -> bool:
            self.calls += 1
            return self.calls > 1

        def set(self) -> None:
            return None

    monkeypatch.setattr("macrovision.scheduler_worker.Thread", ImmediateThread)
    monkeypatch.setattr("macrovision.scheduler_worker.renew_lease", lambda *a, **k: False)
    heartbeat = LeaseHeartbeat(
        factory,
        run_id=1,
        worker_id="heartbeat-worker",
        lease_generation=1,
        lease_seconds=60,
        heartbeat_seconds=1,
        now_factory=lambda: now,
    )
    heartbeat._stop = cast(Any, OneHeartbeat())
    with heartbeat:
        pass
    assert heartbeat.lease_lost


def test_execute_with_heartbeat_passes_fencing_identity(
    scheduler_runtime: tuple[Engine, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, factory = scheduler_runtime
    now = datetime(2026, 7, 26, 10, tzinfo=UTC)
    schedule = _create_schedule(factory, now=now, enabled=False)
    pending = _enqueue(factory, schedule.id, key="heartbeat-execute", now=now)
    with factory() as session:
        claimed = claim_pending_runs(
            session,
            worker_id="heartbeat-execute-worker",
            now=now,
            lease_seconds=300,
            limit=1,
        )[0]

    entered: list[int] = []

    class FakeHeartbeat:
        def __init__(self, _: Any, **kwargs: Any) -> None:
            entered.append(cast(int, kwargs["lease_generation"]))

        def __enter__(self) -> "FakeHeartbeat":
            return self

        def __exit__(self, *_: object) -> None:
            return None

    monkeypatch.setattr(
        "macrovision.scheduler_worker.execute_claimed_run",
        lambda *a, **k: k["lease_generation"] == claimed.lease_generation,
    )
    assert execute_with_heartbeat(
        factory,
        claimed,
        worker_id="heartbeat-execute-worker",
        registry=_registry(),
        settings=Settings(_env_file=None),
        now_factory=lambda: now,
        heartbeat_factory=cast(Any, FakeHeartbeat),
    )
    assert entered == [claimed.lease_generation]
    assert pending.id == claimed.id


def test_scheduler_key_and_daily_cadence_boundaries() -> None:
    now = datetime(2026, 7, 26, 10, tzinfo=UTC)
    daily = ScheduleCadence(cadence_type="daily_utc", daily_time_utc="09:30")
    assert calculate_next_future_occurrence(daily, previous=now, now=now) == datetime(
        2026, 7, 27, 9, 30, tzinfo=UTC
    )
    assert calculate_latest_due_occurrence(
        daily,
        next_run_at=datetime(2026, 7, 26, 9, 30, tzinfo=UTC),
        now=now,
    ) == datetime(2026, 7, 26, 9, 30, tzinfo=UTC)
    assert (
        calculate_latest_due_occurrence(
            daily,
            next_run_at=datetime(2026, 7, 27, 9, 30, tzinfo=UTC),
            now=now,
        )
        is None
    )
    with pytest.raises(ValueError):
        generate_concurrency_key("stub", "")
    with pytest.raises(ValueError):
        hash_external_idempotency_key("")
    with pytest.raises(ValueError):
        generate_run_key(
            schedule_id=0,
            trigger_type=ProviderSyncTriggerType.manual,
            scheduled_for=now,
            request_fingerprint="a" * 64,
        )
    with pytest.raises(ValueError):
        generate_sync_idempotency_key("not-a-sha256")
