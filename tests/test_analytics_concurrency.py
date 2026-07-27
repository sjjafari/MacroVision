import os
import threading
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

import macrovision.analytics_services as analytics_services
import macrovision.database as database
from macrovision.analytics_models import (
    AnalyticsRun,
    DerivedObservation,
    DerivedObservationLineage,
    DerivedSeriesDefinition,
)
from macrovision.analytics_schemas import TransformationType
from macrovision.analytics_services import (
    AnalyticsExecutionError,
    AnalyticsExecutionRequest,
    execute_analytics_run,
)
from macrovision.database import Base, create_database_engine
from macrovision.macro_data_models import DataObservation, DataRevision, ObservationStatus
from tests.test_analytics_services import (
    FEB,
    JAN,
    _definition,
    _observation,
    _request,
    _series,
)

POSTGRES_TEST_URL = os.getenv("MACROVISION_POSTGRES_TEST_URL")


def test_sqlite_precise_clock_preserves_same_second_eligibility(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = datetime(2026, 7, 1, 12, 0, 0, 900000, tzinfo=UTC)
    monkeypatch.setattr(
        database,
        "_sqlite_utc_now",
        lambda: snapshot.strftime("%Y-%m-%d %H:%M:%S.%f"),
    )
    engine = create_database_engine(f"sqlite:///{tmp_path / 'precise-clock.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session: Session = factory()
    series = _series(session, "S.PRECISE")
    jan = DataObservation(
        series=series,
        observed_at=JAN,
        publication_timestamp=JAN,
        ingestion_timestamp=snapshot.replace(microsecond=100000),
        value=Decimal("10"),
        status=ObservationStatus.present,
        provider_metadata={},
    )
    feb = DataObservation(
        series=series,
        observed_at=FEB,
        publication_timestamp=FEB,
        ingestion_timestamp=snapshot.replace(microsecond=100000),
        value=Decimal("20"),
        status=ObservationStatus.present,
        provider_metadata={},
    )
    session.add_all(
        [
            jan,
            feb,
            DataRevision(
                observation=feb,
                sequence=1,
                previous_value=Decimal("20"),
                revised_value=Decimal("25"),
                previous_status=ObservationStatus.present,
                revised_status=ObservationStatus.present,
                publication_timestamp=FEB,
                revision_timestamp=snapshot.replace(microsecond=200000),
                provider_metadata={},
                reason="same-second eligible",
            ),
            DataRevision(
                observation=feb,
                sequence=2,
                previous_value=Decimal("25"),
                revised_value=Decimal("30"),
                previous_status=ObservationStatus.present,
                revised_status=ObservationStatus.present,
                publication_timestamp=FEB,
                revision_timestamp=snapshot.replace(microsecond=950000),
                provider_metadata={},
                reason="after cutoff",
            ),
        ]
    )
    session.commit()
    definition = _definition(session, TransformationType.difference, [series])
    explicit = snapshot.replace(microsecond=500000)
    run = execute_analytics_run(
        session,
        _request(definition, start=FEB, end=FEB, as_of=explicit),
    )
    output = session.scalar(select(DerivedObservation).where(DerivedObservation.run_id == run.id))
    assert output is not None
    assert output.value == Decimal("15.00000000")
    assert run.calculation_cutoff == explicit
    assert run.calculation_cutoff.microsecond == 500000
    session.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


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


@pytest.mark.parametrize("journal_mode", ["DELETE", "WAL"])
def test_sqlite_snapshot_blocks_revision_writer_and_remains_stable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    journal_mode: str,
) -> None:
    engine = create_database_engine(
        f"sqlite:///{tmp_path / f'analytics-writer-{journal_mode}.db'}?timeout=0.05"
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    seed: Session = factory()
    seed.connection().exec_driver_sql(f"PRAGMA journal_mode={journal_mode}")
    series = _series(seed, f"S.WRITER.{journal_mode}")
    _observation(seed, series, JAN, "10")
    current = _observation(seed, series, FEB, "20")
    seed.commit()
    definition = _definition(seed, TransformationType.difference, [series])
    request = _request(definition, start=FEB, end=FEB, as_of=None)
    current_id = current.id
    seed.close()

    acquired = threading.Event()
    release = threading.Event()
    original_resolver = analytics_services._resolve_snapshot

    def blocking_resolver(*args: object, **kwargs: object) -> object:
        acquired.set()
        assert release.wait(timeout=10)
        return original_resolver(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(analytics_services, "_resolve_snapshot", blocking_resolver)
    result: dict[str, object] = {}

    def execute() -> None:
        session: Session = factory()
        try:
            result["run"] = execute_analytics_run(session, request)
        except BaseException as exc:  # pragma: no cover
            result["error"] = exc
        finally:
            session.close()

    worker = threading.Thread(target=execute)
    worker.start()
    assert acquired.wait(timeout=10)
    writer: Session = factory()
    revision = DataRevision(
        observation_id=current_id,
        sequence=1,
        previous_value=Decimal("20"),
        revised_value=Decimal("25"),
        previous_status=ObservationStatus.present,
        revised_status=ObservationStatus.present,
        publication_timestamp=FEB,
        revision_timestamp=datetime.now(UTC),
        provider_metadata={},
        reason="blocked correction",
    )
    writer.add(revision)
    with pytest.raises(OperationalError):
        writer.commit()
    writer.rollback()
    assert writer.scalar(select(func.count(DataRevision.id))) == 0
    writer.close()

    release.set()
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
    assert check.scalar(select(func.count(AnalyticsRun.id))) == 1
    check.close()

    monkeypatch.setattr(analytics_services, "_resolve_snapshot", original_resolver)
    writer = factory()
    writer.add(
        DataRevision(
            observation_id=current_id,
            sequence=1,
            previous_value=Decimal("20"),
            revised_value=Decimal("25"),
            previous_status=ObservationStatus.present,
            revised_status=ObservationStatus.present,
            publication_timestamp=FEB,
            revision_timestamp=datetime.now(UTC),
            provider_metadata={},
            reason="committed correction",
        )
    )
    writer.commit()
    writer.close()
    later: Session = factory()
    second = execute_analytics_run(later, request)
    second_output = later.scalar(
        select(DerivedObservation).where(DerivedObservation.run_id == second.id)
    )
    assert second_output is not None
    assert second_output.value == Decimal("15.00000000")
    assert second.id != first.id
    later.close()
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


@pytest.mark.skipif(
    POSTGRES_TEST_URL is None,
    reason="A dedicated PostgreSQL analytics test database is not configured",
)
def test_postgresql_concurrent_execution_returns_single_winner(
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
    series = _series(seed, "S.PG.REUSABLE.RACE")
    _observation(seed, series, JAN, "10")
    _observation(seed, series, FEB, "20")
    seed.commit()
    definition = _definition(seed, TransformationType.difference, [series])
    request = _request(definition, start=FEB, end=FEB, as_of=None)
    seed.close()

    barrier = threading.Barrier(2)
    original_persist = analytics_services._persist_outputs

    def synchronized_persist(*args: object, **kwargs: object) -> object:
        barrier.wait(timeout=10)
        return original_persist(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(analytics_services, "_persist_outputs", synchronized_persist)
    results: list[AnalyticsRun] = []
    errors: list[BaseException] = []

    def execute() -> None:
        session: Session = factory()
        try:
            results.append(execute_analytics_run(session, request))
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)
        finally:
            session.close()

    workers = [threading.Thread(target=execute) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=20)
    assert all(not worker.is_alive() for worker in workers)
    assert not errors
    assert len(results) == 2
    assert results[0].id == results[1].id

    check: Session = factory()
    winner = check.get(AnalyticsRun, results[0].id)
    assert winner is not None
    assert winner.status == "succeeded"
    assert check.scalar(select(func.count(AnalyticsRun.id))) == 1
    assert check.scalar(select(func.count(DerivedObservation.id))) == 1
    assert check.scalar(select(func.count(DerivedObservationLineage.id))) == 2
    assert winner.outputs_present == 1
    assert winner.outputs_missing == 0
    assert winner.lineage_links == 2
    check.close()
    engine.dispose()


@pytest.mark.skipif(
    POSTGRES_TEST_URL is None,
    reason="A dedicated PostgreSQL analytics test database is not configured",
)
def test_postgresql_same_request_active_index_race_returns_winner() -> None:
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
    series = _series(seed, "S.PG.ACTIVE.RACE")
    _observation(seed, series, JAN, "10")
    _observation(seed, series, FEB, "20")
    seed.commit()
    definition = _definition(seed, TransformationType.difference, [series])
    request = _request(
        definition,
        start=FEB,
        end=FEB,
        as_of=datetime(2026, 5, 1, tzinfo=UTC),
    )
    seed.close()
    start = threading.Barrier(2)
    results: list[AnalyticsRun] = []
    errors: list[BaseException] = []

    def execute() -> None:
        session: Session = factory()
        try:
            start.wait(timeout=10)
            results.append(execute_analytics_run(session, request))
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)
        finally:
            session.close()

    workers = [threading.Thread(target=execute) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=20)
    assert all(not worker.is_alive() for worker in workers)
    assert not errors
    assert len(results) == 2
    assert results[0].id == results[1].id
    with factory() as check:
        assert check.scalar(select(func.count(AnalyticsRun.id))) == 1
        assert check.scalar(select(func.count(DerivedObservation.id))) == 1
        assert check.scalar(select(func.count(DerivedObservationLineage.id))) == 2
    engine.dispose()
