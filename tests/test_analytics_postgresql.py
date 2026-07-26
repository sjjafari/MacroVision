import os
from collections.abc import Generator

import pytest
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import IntegrityError

from macrovision.database import create_database_engine

POSTGRES_TEST_URL = os.getenv("MACROVISION_POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(
    POSTGRES_TEST_URL is None,
    reason="A dedicated PostgreSQL analytics test database is not configured",
)


def _database_url() -> str:
    if POSTGRES_TEST_URL is None:
        raise RuntimeError("PostgreSQL analytics test URL is unavailable")
    return POSTGRES_TEST_URL


@pytest.fixture
def postgres_analytics() -> Generator[Engine, None, None]:
    engine = create_database_engine(_database_url())
    with engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE derived_observation_lineage, derived_observations, analytics_runs, "
                "derived_series_inputs, derived_series_definition_versions, "
                "derived_series_definitions, data_revisions, data_observations, data_series, "
                "data_import_batches, data_sources RESTART IDENTITY CASCADE"
            )
        )
    try:
        yield engine
    finally:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "TRUNCATE derived_observation_lineage, derived_observations, analytics_runs, "
                    "derived_series_inputs, derived_series_definition_versions, "
                    "derived_series_definitions, data_revisions, data_observations, data_series, "
                    "data_import_batches, data_sources RESTART IDENTITY CASCADE"
                )
            )
        engine.dispose()


def _seed_analytics(connection: Connection) -> None:
    connection.execute(
        text(
            "INSERT INTO derived_series_definitions "
            "(id,code,title,enabled,lock_version) VALUES (1,'CPI.YOY','CPI',true,1)"
        )
    )
    connection.execute(
        text(
            "INSERT INTO derived_series_definition_versions "
            "(id,definition_id,version,transformation_type,parameters,"
            "parameters_fingerprint,output_unit,output_frequency,output_geography,"
            "output_seasonal_adjustment,engine_contract_version) VALUES "
            "(1,1,1,'difference','{}',:fingerprint,'index','monthly','US','adjusted','1')"
        ),
        {"fingerprint": "a" * 64},
    )


def test_postgresql_code_and_partial_fingerprint_indexes(
    postgres_analytics: Engine,
) -> None:
    with postgres_analytics.begin() as connection:
        _seed_analytics(connection)
        with connection.begin_nested(), pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO derived_series_definitions "
                    "(code,title,enabled,lock_version) VALUES ('cpi.yoy','lower',true,1)"
                )
            )
    with postgres_analytics.begin() as connection:
        _seed_analytics(connection)
        values = {
            "version": 1,
            "status": "pending",
            "time": "2026-01-01T00:00:00Z",
            "fingerprint": "b" * 64,
        }
        statement = text(
            "INSERT INTO analytics_runs "
            "(definition_version_id,status,requested_start_at,requested_end_at,"
            "calculation_cutoff,engine_version,request_fingerprint,inputs_examined,"
            "outputs_present,outputs_missing,lineage_links) VALUES "
            "(:version,:status,:time,:time,:time,'1',:fingerprint,0,0,0,0)"
        )
        connection.execute(statement, values)
        with connection.begin_nested(), pytest.raises(IntegrityError):
            connection.execute(statement, values)


def test_postgresql_lineage_shape_and_non_null_uniqueness(
    postgres_analytics: Engine,
) -> None:
    with postgres_analytics.begin() as connection:
        _seed_analytics(connection)
        connection.execute(
            text("INSERT INTO data_sources (id,code,name,description) VALUES (1,'TEST','Test','')")
        )
        connection.execute(
            text(
                "INSERT INTO data_series "
                "(id,source_id,code,name,description,category,geography,frequency,unit,"
                "seasonal_adjustment,publication_lag_days,is_active,series_metadata,"
                "lock_version) VALUES "
                "(1,1,'TEST.CPI','CPI','','inflation','US','monthly','index','adjusted',"
                "0,true,'{}',1)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO data_observations "
                "(id,series_id,observed_at,publication_timestamp,ingestion_timestamp,"
                "provider_metadata,value,status) VALUES "
                "(1,1,'2026-01-01','2026-01-01','2026-01-01','{}',100000000,'present')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO analytics_runs "
                "(id,definition_version_id,status,requested_start_at,requested_end_at,"
                "calculation_cutoff,engine_version,request_fingerprint,inputs_examined,"
                "outputs_present,outputs_missing,lineage_links) VALUES "
                "(1,1,'pending','2026-01-01','2026-01-01','2026-01-01','1',:fp,0,0,0,0)"
            ),
            {"fp": "c" * 64},
        )
        connection.execute(
            text(
                "INSERT INTO derived_observations "
                "(id,run_id,definition_version_id,observed_at,value,status) "
                "VALUES (1,1,1,'2026-01-01',100000000,'present')"
            )
        )
        lineage = text(
            "INSERT INTO derived_observation_lineage "
            "(derived_observation_id,input_position,source_observation_id,"
            "source_version_kind,source_version_id,lineage_position,"
            "source_knowledge_timestamp) VALUES "
            "(1,0,1,'original',1,0,'2026-01-01')"
        )
        connection.execute(lineage)
        with connection.begin_nested(), pytest.raises(IntegrityError):
            connection.execute(lineage)
        with connection.begin_nested(), pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO derived_observation_lineage "
                    "(derived_observation_id,input_position,source_observation_id,"
                    "source_revision_id,source_version_kind,source_version_id,"
                    "lineage_position,source_knowledge_timestamp) VALUES "
                    "(1,0,1,1,'original',1,1,'2026-01-01')"
                )
            )
