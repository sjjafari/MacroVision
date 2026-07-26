import os
from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from macrovision.config import Settings
from macrovision.database import create_database_engine
from macrovision.provider_contracts import ExternalDataProvider
from macrovision.provider_registry import ProviderRegistry
from macrovision.scheduler_models import ProviderSyncRun
from macrovision.scheduler_schemas import ProviderSyncRunNowRequest, ProviderSyncScheduleCreate
from macrovision.scheduler_services import (
    claim_pending_runs,
    create_schedule,
    enqueue_run_now,
)

POSTGRES_TEST_URL = os.getenv("MACROVISION_POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(
    POSTGRES_TEST_URL is None,
    reason="A dedicated PostgreSQL scheduler test database is not configured",
)


def _database_url() -> str:
    if POSTGRES_TEST_URL is None:
        raise RuntimeError("PostgreSQL scheduler test URL is unavailable")
    return POSTGRES_TEST_URL


def _unsupported_provider(_: Settings) -> ExternalDataProvider:
    raise AssertionError("Provider construction is not needed for scheduler persistence tests")


@pytest.fixture
def postgres_scheduler() -> Generator[tuple[Engine, sessionmaker[Session]], None, None]:
    engine = create_database_engine(_database_url())
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with engine.begin() as connection:
        connection.execute(
            text("TRUNCATE provider_sync_runs, provider_sync_schedules RESTART IDENTITY")
        )
    try:
        yield engine, factory
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("TRUNCATE provider_sync_runs, provider_sync_schedules RESTART IDENTITY")
            )
        engine.dispose()


def _registry() -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register("stub", _unsupported_provider)
    return registry


def _schedule(
    factory: sessionmaker[Session],
    series_id: str,
    *,
    now: datetime,
) -> int:
    with factory() as session:
        schedule = create_schedule(
            session,
            ProviderSyncScheduleCreate(
                provider="stub",
                provider_series_id=series_id,
                internal_series_code=f"STUB.{series_id}",
                request_config={"geography": "US"},
                cadence_type="fixed_interval",
                interval_minutes=60,
                enabled=False,
            ),
            registry=_registry(),
            now=now,
        )
        return schedule.id


def _run(
    factory: sessionmaker[Session],
    schedule_id: int,
    key: str,
    *,
    now: datetime,
) -> int:
    with factory() as session:
        run = enqueue_run_now(
            session,
            schedule_id,
            ProviderSyncRunNowRequest(idempotency_key=key),
            maximum_attempts=2,
            now=now,
        )
        return run.id


def test_postgresql_skip_locked_claims_an_unlocked_series(
    postgres_scheduler: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = postgres_scheduler
    now = datetime(2026, 7, 26, 12, tzinfo=UTC)
    first_schedule = _schedule(factory, "LOCKED", now=now)
    second_schedule = _schedule(factory, "AVAILABLE", now=now)
    first_run = _run(factory, first_schedule, "locked-run", now=now)
    second_run = _run(factory, second_schedule, "available-run", now=now)

    with factory() as lock_session:
        locked = lock_session.scalar(
            select(ProviderSyncRun).where(ProviderSyncRun.id == first_run).with_for_update()
        )
        assert locked is not None

        with factory() as claiming_session:
            claimed = claim_pending_runs(
                claiming_session,
                worker_id="postgres-worker-two",
                now=now,
                lease_seconds=300,
                limit=2,
            )
            assert [run.id for run in claimed] == [second_run]
        lock_session.rollback()

    with factory() as claiming_session:
        claimed = claim_pending_runs(
            claiming_session,
            worker_id="postgres-worker-one",
            now=now,
            lease_seconds=300,
            limit=2,
        )
        assert [run.id for run in claimed] == [first_run]


def test_postgresql_partial_index_prevents_same_series_overlap(
    postgres_scheduler: tuple[Engine, sessionmaker[Session]],
) -> None:
    engine, factory = postgres_scheduler
    now = datetime(2026, 7, 26, 12, tzinfo=UTC)
    schedule_id = _schedule(factory, "GDP", now=now)
    first_run = _run(factory, schedule_id, "first-gdp-run", now=now)
    second_run = _run(factory, schedule_id, "second-gdp-run", now=now)

    with factory() as session:
        first = claim_pending_runs(
            session,
            worker_id="postgres-first-worker",
            now=now,
            lease_seconds=300,
            limit=2,
        )
        assert [run.id for run in first] == [first_run]
    with factory() as session:
        assert (
            claim_pending_runs(
                session,
                worker_id="postgres-second-worker",
                now=now,
                lease_seconds=300,
                limit=2,
            )
            == []
        )
        pending = session.get(ProviderSyncRun, second_run)
        assert pending is not None
        assert pending.status == "pending"

    with engine.connect() as connection:
        index_definition = connection.scalar(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE schemaname = current_schema() "
                "AND indexname = 'uq_provider_sync_run_running_concurrency'"
            )
        )
    assert index_definition is not None
    assert "UNIQUE INDEX" in index_definition
    assert "WHERE" in index_definition
    assert "status" in index_definition
    assert "running" in index_definition
