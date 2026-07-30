import os
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from macrovision import dashboard_services, macro_data_services
from macrovision.database import create_database_engine
from macrovision.macro_data_models import SeriesCategory
from macrovision.macro_data_schemas import MAX_DATA_VALUE, MIN_DATA_VALUE
from tests.test_dashboards import _seed_cpi

POSTGRES_TEST_URL = os.getenv("MACROVISION_POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(
    POSTGRES_TEST_URL is None,
    reason="A dedicated PostgreSQL dashboard test database is not configured",
)


@pytest.mark.parametrize(
    ("previous_value", "current_value", "expected_reason"),
    [
        ("1234567880.12345678", "1234567890.12345678", None),
        (str(MIN_DATA_VALUE), str(MAX_DATA_VALUE), "absolute_change_not_representable"),
        ("0.00000001", str(MAX_DATA_VALUE), "percentage_change_not_representable"),
    ],
)
def test_postgresql_filters_and_dashboard_batch_summary_match_sqlite_semantics(
    previous_value: str,
    current_value: str,
    expected_reason: str | None,
) -> None:
    assert POSTGRES_TEST_URL is not None
    engine = create_database_engine(POSTGRES_TEST_URL)
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, autoflush=False, expire_on_commit=False)
    try:
        series = _seed_cpi(
            session,
            previous_value=previous_value,
            current_value=current_value,
            with_derived=False,
        )
        filtered = macro_data_services.list_series(
            session,
            search="consumer",
            code="FRED.CPIAUCSL",
            category=SeriesCategory.inflation,
            geography="US",
            frequency=series.frequency,
            source_id=series.source_id,
            is_active=True,
            limit=10,
            offset=0,
        )
        assert [item.id for item in filtered] == [series.id]
        summary = dashboard_services.dashboard_summary(session, "macro")
        cpi = next(
            metric
            for group in summary.groups
            for metric in group.metrics
            if metric.metric_key == "cpi_level"
        )
        assert cpi.value == Decimal(current_value)
        assert cpi.comparison.reference_value == Decimal(previous_value)
        assert cpi.comparison.state_reason == expected_reason
        if expected_reason == "absolute_change_not_representable":
            assert cpi.comparison.absolute_change is None
            assert cpi.comparison.percentage_change is None
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()
