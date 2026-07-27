import os
import threading

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from macrovision import analytics_api_schemas as schemas
from macrovision import analytics_management_services as management
from macrovision.analytics_models import (
    DerivedSeriesDefinition,
    DerivedSeriesDefinitionVersion,
    DerivedSeriesInput,
)
from macrovision.database import create_database_engine
from macrovision.macro_data_models import (
    DataFrequency,
    DataSeries,
    DataSource,
    SeasonalAdjustment,
    SeriesCategory,
)

POSTGRES_TEST_URL = os.getenv("MACROVISION_POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(
    POSTGRES_TEST_URL is None,
    reason="A dedicated PostgreSQL Analytics API test database is not configured",
)


def _payload(
    source_id: int, *, expected_lock_version: int | None = None
) -> schemas.DerivedSeriesVersionCreateBase | schemas.DerivedSeriesVersionCreate:
    value: dict[str, object] = {
        "parameters": {"transformation_type": "difference"},
        "inputs": [{"alias": "value", "source_series_id": source_id}],
        "change_note": "Concurrent public version",
    }
    if expected_lock_version is None:
        return schemas.DerivedSeriesVersionCreateBase.model_validate(value)
    value["expected_lock_version"] = expected_lock_version
    return schemas.DerivedSeriesVersionCreate.model_validate(value)


def _seed(session: Session) -> tuple[int, int]:
    source = DataSource(code="ANALYTICS_API_PG", name="Test", description="")
    series = DataSeries(
        source=source,
        code="ANALYTICS.API.PG",
        name="Test",
        description="",
        category=SeriesCategory.custom,
        geography="US",
        frequency=DataFrequency.monthly,
        unit="index",
        seasonal_adjustment=SeasonalAdjustment.adjusted,
        publication_lag_days=0,
        is_active=True,
        series_metadata={},
        lock_version=1,
    )
    session.add(series)
    session.commit()
    initial = _payload(series.id)
    assert isinstance(initial, schemas.DerivedSeriesVersionCreateBase)
    definition = management.create_definition(
        session,
        schemas.DerivedSeriesCreate(
            code="ANALYTICS.API.PG.DEFINITION",
            title="Concurrent definition",
            initial_version=initial,
        ),
    )
    session.rollback()
    return series.id, definition.id


def test_postgresql_definition_and_version_races_have_one_winner() -> None:
    assert POSTGRES_TEST_URL is not None
    engine = create_database_engine(POSTGRES_TEST_URL)
    with engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE derived_observation_lineage, derived_observations, analytics_runs, "
                "derived_series_inputs, derived_series_definition_versions, "
                "derived_series_definitions, data_revisions, data_observations, data_series, "
                "data_import_batches, data_sources RESTART IDENTITY CASCADE"
            )
        )
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    seed = factory()
    source_id, definition_id = _seed(seed)
    seed.close()

    version_barrier = threading.Barrier(2)
    version_results: list[int] = []
    version_conflicts: list[str] = []

    def create_version() -> None:
        session: Session = factory()
        try:
            version_barrier.wait(timeout=10)
            version_payload = _payload(source_id, expected_lock_version=1)
            assert isinstance(version_payload, schemas.DerivedSeriesVersionCreate)
            result = management.create_version(
                session,
                definition_id,
                version_payload,
            )
            version_results.append(result.version)
        except management.AnalyticsConflictError as exc:
            version_conflicts.append(str(exc))
        finally:
            session.close()

    threads = [threading.Thread(target=create_version) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    assert all(not thread.is_alive() for thread in threads)
    assert version_results == [2]
    assert len(version_conflicts) == 1

    patch_barrier = threading.Barrier(2)
    patch_results: list[int] = []
    patch_conflicts: list[str] = []

    def patch_definition() -> None:
        session: Session = factory()
        try:
            patch_barrier.wait(timeout=10)
            result = management.patch_definition(
                session,
                definition_id,
                schemas.DerivedSeriesPatch(
                    expected_lock_version=2,
                    title="Winning concurrent title",
                ),
            )
            patch_results.append(result.lock_version)
        except management.AnalyticsConflictError as exc:
            patch_conflicts.append(str(exc))
        finally:
            session.close()

    threads = [threading.Thread(target=patch_definition) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    assert all(not thread.is_alive() for thread in threads)
    assert patch_results == [3]
    assert len(patch_conflicts) == 1

    state_barrier = threading.Barrier(2)
    state_results: list[int] = []
    state_conflicts: list[str] = []

    def set_state(enabled: bool) -> None:
        session: Session = factory()
        try:
            state_barrier.wait(timeout=10)
            result = management.set_definition_enabled(
                session,
                definition_id,
                schemas.DerivedSeriesStateChange(expected_lock_version=3),
                enabled=enabled,
            )
            state_results.append(result.lock_version)
        except management.AnalyticsConflictError as exc:
            state_conflicts.append(str(exc))
        finally:
            session.close()

    threads = [
        threading.Thread(target=set_state, args=(True,)),
        threading.Thread(target=set_state, args=(False,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    assert all(not thread.is_alive() for thread in threads)
    assert state_results == [4]
    assert len(state_conflicts) == 1

    check: Session = factory()
    definition = check.get(DerivedSeriesDefinition, definition_id)
    assert definition is not None
    assert definition.lock_version == 4
    assert (
        check.scalar(
            select(func.count(DerivedSeriesDefinitionVersion.id)).where(
                DerivedSeriesDefinitionVersion.definition_id == definition_id
            )
        )
        == 2
    )
    assert (
        check.scalar(
            select(func.count(DerivedSeriesInput.id))
            .join(DerivedSeriesDefinitionVersion)
            .where(DerivedSeriesDefinitionVersion.definition_id == definition_id)
        )
        == 2
    )
    check.close()
    engine.dispose()
