import os

import pytest
from sqlalchemy.orm import Session

from macrovision import dashboard_services, macro_data_services
from macrovision.database import create_database_engine
from macrovision.macro_data_models import SeriesCategory
from tests.test_dashboards import _seed_cpi

POSTGRES_TEST_URL = os.getenv("MACROVISION_POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(
    POSTGRES_TEST_URL is None,
    reason="A dedicated PostgreSQL dashboard test database is not configured",
)


def test_postgresql_filters_and_dashboard_batch_summary_match_sqlite_semantics() -> None:
    assert POSTGRES_TEST_URL is not None
    engine = create_database_engine(POSTGRES_TEST_URL)
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, autoflush=False, expire_on_commit=False)
    try:
        series = _seed_cpi(session)
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
        assert str(cpi.value) == "1234567890.12345678"
        assert str(cpi.comparison.reference_value) == "1234567880.12345678"
        assert str(cpi.comparison.absolute_change) == "10.00000000"
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()
