import os
from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from macrovision.database import create_database_engine
from macrovision.indicator_services import (
    indicator_snapshot,
    list_indicator_catalog,
    related_derived,
)
from tests.test_indicator_catalog import (
    _seed_derived,
    _seed_series,
    _seed_snapshot_history,
)

POSTGRES_TEST_URL = os.getenv("MACROVISION_POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(
    POSTGRES_TEST_URL is None,
    reason="A dedicated PostgreSQL indicator catalog test database is not configured",
)


def test_postgresql_catalog_snapshot_revision_and_related_derived_match_sqlite() -> None:
    assert POSTGRES_TEST_URL is not None
    engine = create_database_engine(POSTGRES_TEST_URL)
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, autoflush=False, expire_on_commit=False)
    try:
        series = _seed_series(session)
        _seed_snapshot_history(session, series)
        _seed_derived(session, series)
        page = list_indicator_catalog(
            session,
            limit=100,
            offset=0,
            search="consumer",
            category=series.category,
            geography="us",
            frequency=series.frequency,
            source_id=series.source_id,
            operational_is_active=True,
        )
        assert page.total == 1
        current = indicator_snapshot(session, series.id)
        historical = indicator_snapshot(
            session,
            series.id,
            as_of=datetime(2026, 1, 11, tzinfo=UTC),
        )
        assert str(current.value) == "1234567890.12345678"
        assert str(historical.value) == "1234567889.12345678"
        related = related_derived(session, series.id)
        assert related.items[0].state == "available"
        assert str(related.items[0].value) == "3.25000000"
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


def test_postgresql_empty_related_inputs_are_rejected_like_sqlite() -> None:
    assert POSTGRES_TEST_URL is not None
    engine = create_database_engine(POSTGRES_TEST_URL)
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, autoflush=False, expire_on_commit=False)
    try:
        series = _seed_series(session)
        _seed_derived(session, series, input_series=())
        item = related_derived(session, series.id).items[0]
        assert item.state == "persisted_result_missing"
        assert item.missing_reason == "definition_source_mismatch"
        assert item.value is None
        assert item.observed_at is None
        assert item.run_id is None
        assert item.observation_id is None
        assert item.calculation_cutoff is None
        assert item.completed_at is None
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


@pytest.mark.parametrize(
    ("identity_case", "expected_state"),
    [
        ("different_id_matching_code", "persisted_result_missing"),
        ("matching_id_different_code", "persisted_result_missing"),
        ("matching_id_matching_code", "available"),
    ],
)
def test_postgresql_related_identity_requires_matching_id_and_snapshot(
    identity_case: str, expected_state: str
) -> None:
    assert POSTGRES_TEST_URL is not None
    engine = create_database_engine(POSTGRES_TEST_URL)
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, autoflush=False, expire_on_commit=False)
    try:
        reviewed = _seed_series(session)
        unrelated = _seed_series(
            session,
            code="FRED.UNRATE",
            name="Unemployment Rate",
        )
        source_series = unrelated if identity_case == "different_id_matching_code" else reviewed
        code_snapshot = (
            unrelated.code if identity_case == "matching_id_different_code" else reviewed.code
        )
        _seed_derived(
            session,
            reviewed,
            input_series=(source_series,),
            input_code_snapshots=(code_snapshot,),
        )
        item = related_derived(session, reviewed.id).items[0]
        assert item.state == expected_state
        if expected_state == "available":
            assert str(item.value) == "3.25000000"
            assert item.run_id is not None
            assert item.observation_id is not None
        else:
            assert item.missing_reason == "definition_source_mismatch"
            assert item.value is None
            assert item.observed_at is None
            assert item.run_id is None
            assert item.observation_id is None
            assert item.calculation_cutoff is None
            assert item.completed_at is None
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()
