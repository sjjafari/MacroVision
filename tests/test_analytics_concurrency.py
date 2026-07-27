import os
import threading
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

import macrovision.analytics_services as analytics_services
from macrovision.analytics_models import (
    AnalyticsRun,
    DerivedObservation,
    DerivedSeriesDefinition,
)
from macrovision.analytics_schemas import TransformationType
from macrovision.analytics_services import (
    AnalyticsExecutionError,
    AnalyticsExecutionRequest,
    execute_analytics_run,
)
from macrovision.database import Base, create_database_engine
from macrovision.macro_data_models import DataRevision, ObservationStatus
from tests.test_analytics_services import (
    FEB,
    JAN,
    _definition,
    _observation,
    _request,
    _series,
)

POSTGRES_TEST_URL = os.getenv("MACROVISION_POSTGRES_TEST_URL")


@pytest.mark.parametrize("journal_mode", ["DELETE", "WAL"])
def test_sqlite_begin_immediate_lock_failure_leaves_no_partial_graph(
    tmp_path: Path, journal_mode: str
) -> None:
    engine = create_database_engine(
        f"sqlite:///{tmp_path / f'analytics-{journal_mode}.db'}?timeout=0.05"
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    seed: Session = factory()
    series = _series(seed, f"S.{journal_mode}")
    _observation(seed, series, JAN, "1")
    _observation(seed, series, FEB, "2")
    seed.commit()
    definition = _definition(seed, TransformationType.difference, [series])
    definition_id = definition.id
    seed.close()

    holder: Session = factory()
    contender: Session = factory()
    try:
        holder.connection().exec_driver_sql(f"PRAGMA journal_mode={journal_mode}")
        holder.connection().exec_driver_sql("BEGIN IMMEDIATE")
        with pytest.raises(AnalyticsExecutionError):
            execute_analytics_run(
                contender,
                _request(definition, start=FEB, end=FEB),
            )
        holder.rollback()
        assert contender.scalar(select(func.count(AnalyticsRun.id))) == 0
        assert contender.scalar(select(func.count(DerivedObservation.id))) == 0
        contender.rollback()
        loaded = contender.get(DerivedSeriesDefinition, definition_id)
        assert loaded is not None
        contender.rollback()
        run = execute_analytics_run(
            contender,
            AnalyticsExecutionRequest(
                definition_id=definition_id,
                requested_start_at=FEB,
                requested_end_at=FEB,
            ),
        )
        assert run.status == "succeeded"
    finally:
        holder.rollback()
        contender.close()
        holder.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.mark.skipif(
    POSTGRES_TEST_URL is None,
    reason="A dedicated PostgreSQL analytics test database is not configured",
)
def test_postgresql_repeatable_read_excludes_revision_committed_mid_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert POSTGRES_TEST_URL is not None
    engine = create_database_engine(POSTGRES_TEST_URL)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE derived_observation_lineage, derived_observations, analytics_runs, "
                "derived_series_inputs, derived_series_definition_versions, "
                "derived_series_definitions, data_revisions, data_observations, data_series, "
                "data_import_batches, data_sources RESTART IDENTITY CASCADE"
            )
        )
    seed: Session = factory()
    series = _series(seed, "S.PG.SNAPSHOT")
    _observation(seed, series, JAN, "10")
    current = _observation(seed, series, FEB, "20")
    seed.commit()
    definition = _definition(seed, TransformationType.difference, [series])
    request = _request(definition, start=FEB, end=FEB, as_of=None)
    current_id = current.id
    seed.close()

    acquired = threading.Event()
    revision_committed = threading.Event()
    original_resolver = analytics_services._resolve_snapshot

    def blocking_resolver(*args: object, **kwargs: object) -> object:
        acquired.set()
        assert revision_committed.wait(timeout=10)
        return original_resolver(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(analytics_services, "_resolve_snapshot", blocking_resolver)
    result: dict[str, object] = {}

    def execute() -> None:
        session: Session = factory()
        try:
            result["run"] = execute_analytics_run(session, request)
        except BaseException as exc:  # pragma: no cover - assertion reports thread failure
            result["error"] = exc
        finally:
            session.close()

    worker = threading.Thread(target=execute)
    worker.start()
    assert acquired.wait(timeout=10)
    writer: Session = factory()
    writer.add(
        DataRevision(
            observation_id=current_id,
            sequence=1,
            previous_value=Decimal("20"),
            revised_value=Decimal("25"),
            previous_status=ObservationStatus.present,
            revised_status=ObservationStatus.present,
            publication_timestamp=FEB,
            revision_timestamp=datetime(2026, 4, 2, tzinfo=UTC),
            provider_metadata={},
            reason="concurrent correction",
        )
    )
    writer.commit()
    writer.close()
    revision_committed.set()
    worker.join(timeout=15)
    assert not worker.is_alive()
    assert "error" not in result
    first = result["run"]
    assert isinstance(first, AnalyticsRun)
    check: Session = factory()
    first_output = check.scalar(
        select(DerivedObservation).where(DerivedObservation.run_id == first.id)
    )
    assert first_output is not None
    assert first_output.value == Decimal("10.00000000")
    check.close()

    monkeypatch.setattr(analytics_services, "_resolve_snapshot", original_resolver)
    later: Session = factory()
    second = execute_analytics_run(later, request)
    second_output = later.scalar(
        select(DerivedObservation).where(DerivedObservation.run_id == second.id)
    )
    assert second_output is not None
    assert second_output.value == Decimal("15.00000000")
    assert second.id != first.id
    later.close()
    engine.dispose()
