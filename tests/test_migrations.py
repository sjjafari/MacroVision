from collections.abc import Iterator
from pathlib import Path
from typing import cast

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, Table, inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from macrovision import portfolio_schemas, portfolio_services
from macrovision.config import get_settings
from macrovision.database import create_database_engine
from macrovision.macro_data_models import DataObservation, DataSeries


@pytest.fixture
def migrated_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    database_url = f"sqlite:///{tmp_path / 'migrated.db'}"
    monkeypatch.setenv("MACROVISION_DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    engine = create_database_engine(database_url)
    try:
        yield engine
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_alembic_schema_has_stabilization_constraints(migrated_engine: Engine) -> None:
    schema = inspect(migrated_engine)
    assert "lock_version" in {column["name"] for column in schema.get_columns("portfolios")}
    assert {"closed_at", "lock_version"} <= {
        column["name"] for column in schema.get_columns("research_journals")
    }
    assert {"failed_at", "failure_summary"} <= {
        column["name"] for column in schema.get_columns("data_import_batches")
    }
    assert "data_import_errors" in schema.get_table_names()
    assert "data_quality_issue_events" in schema.get_table_names()
    assert {"provider_sync_schedules", "provider_sync_runs"} <= set(schema.get_table_names())
    assert {"provider_vintage_start", "provider_vintage_end", "provider_metadata"} <= {
        column["name"] for column in schema.get_columns("data_observations")
    }
    series_uniques = {item["name"] for item in schema.get_unique_constraints("data_series")}
    assert "uq_data_series_source_provider_id" in series_uniques
    series_checks = {item["name"] for item in schema.get_check_constraints("data_series")}
    assert "ck_series_provider_id_nonempty" in series_checks
    assert next(
        column
        for column in schema.get_columns("data_observations")
        if column["name"] == "publication_timestamp"
    )["nullable"]
    assert "provider_metadata" in {
        column["name"] for column in schema.get_columns("data_import_batches")
    }
    import_unique_columns = {
        column
        for item in schema.get_unique_constraints("data_import_batches")
        for column in item["column_names"]
    }
    assert "idempotency_key" in import_unique_columns
    checks = {
        constraint["name"]
        for table in ("portfolios", "research_journals", "data_import_batches")
        for constraint in schema.get_check_constraints(table)
    }
    assert {
        "ck_portfolio_lock_version_positive",
        "ck_journal_lock_version_positive",
        "ck_import_failure_details",
    } <= checks
    foreign_key = schema.get_foreign_keys("data_import_errors")[0]
    assert foreign_key["options"]["ondelete"] == "RESTRICT"
    indexes = {index["name"] for index in schema.get_indexes("data_import_errors")}
    assert "ix_import_error_batch_row" in indexes
    quality_event_fk = schema.get_foreign_keys("data_quality_issue_events")[0]
    assert quality_event_fk["options"]["ondelete"] == "RESTRICT"
    quality_indexes = {index["name"] for index in schema.get_indexes("data_quality_issue_events")}
    assert "ix_quality_event_issue_time" in quality_indexes
    issue_indexes = {index["name"]: index for index in schema.get_indexes("data_quality_issues")}
    assert bool(issue_indexes["uq_open_stale_issue_per_series"]["unique"])


def test_legacy_rows_survive_upgrade_to_stabilization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = f"sqlite:///{tmp_path / 'legacy.db'}"
    monkeypatch.setenv("MACROVISION_DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = Config("alembic.ini")
    command.upgrade(config, "20260724_0004")
    engine = create_database_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO investor_profiles "
                "(id,name,base_currency,investment_horizon_years,liquidity_need,"
                "objectives,constraints) VALUES "
                "(1,'Legacy','USD',10,0.1234565,'Preserve capital','None')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO research_journals "
                "(id,investor_id,asset,hypothesis,evidence_for,evidence_against,"
                "critic_review,probability,confidence,invalidation_conditions,decision,"
                "outcome,lessons,status) VALUES "
                "(1,1,'Cash','H','For','Against','Critic',0.6000005,0.5000015,'Rule','Hold',"
                "'Safe','Documented','closed')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO portfolios (id,investor_id,name,base_currency) "
                "VALUES (1,1,'Legacy portfolio','USD')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO decision_cases "
                "(id,title,question,context,rationale,probability,confidence,status,"
                "current_version,lock_version) VALUES "
                "(1,'Legacy decision','Q','C','R',600000,500000,'draft',1,1)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO data_sources (id,code,name,description) "
                "VALUES (1,'LEGACY','Legacy source','v0.4 record')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO data_import_batches "
                "(id,source_id,idempotency_key,request_fingerprint,imported_at,status,"
                "row_count,accepted_rows,rejected_rows,partial_mode,notes) VALUES "
                "(1,1,'legacy-key','fingerprint','2026-07-24','completed',0,0,0,0,'')"
            )
        )
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT lock_version FROM portfolios WHERE id=1")) == 1
        assert connection.scalar(
            text("SELECT closed_at IS NOT NULL FROM research_journals WHERE id=1")
        )
        assert (
            connection.scalar(text("SELECT liquidity_need FROM investor_profiles WHERE id=1"))
            == 123456
        )
        assert (
            connection.scalar(text("SELECT probability FROM research_journals WHERE id=1"))
            == 600000
        )
        assert (
            connection.scalar(text("SELECT confidence FROM research_journals WHERE id=1")) == 500002
        )
        assert connection.scalar(text("SELECT COUNT(*) FROM decision_cases")) == 1
        assert connection.scalar(text("SELECT COUNT(*) FROM data_import_batches")) == 1
    command.downgrade(config, "20260724_0005")
    with engine.connect() as connection:
        downgraded = connection.scalar(
            text("SELECT liquidity_need FROM investor_profiles WHERE id=1")
        )
        assert downgraded == pytest.approx(0.123456)
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT liquidity_need FROM investor_profiles WHERE id=1"))
            == 123456
        )
    engine.dispose()
    get_settings.cache_clear()


def test_migration_backed_portfolio_service_and_constraints(migrated_engine: Engine) -> None:
    with Session(migrated_engine, expire_on_commit=False) as session:
        portfolio = portfolio_services.create_portfolio(
            session,
            portfolio_schemas.PortfolioCreate(name="Migrated smoke"),
        )
        portfolio_services.record_transaction(
            session,
            portfolio.id,
            portfolio_schemas.TransactionCreate(
                transaction_type="deposit",
                amount="100",
            ),
        )
        assert portfolio_services.get_portfolio(session, portfolio.id).lock_version == 2
        with pytest.raises(IntegrityError):
            session.execute(
                text("UPDATE portfolios SET lock_version=0 WHERE id=:id"),
                {"id": portfolio.id},
            )
        session.rollback()


def test_provider_schema_compiles_for_postgresql_with_expected_constraints() -> None:
    dialect = postgresql.dialect()  # type: ignore[no-untyped-call]
    series_ddl = str(CreateTable(cast(Table, DataSeries.__table__)).compile(dialect=dialect))
    observation_ddl = str(
        CreateTable(cast(Table, DataObservation.__table__)).compile(dialect=dialect)
    )
    assert "uq_data_series_source_provider_id" in series_ddl
    assert "ck_series_provider_id_nonempty" in series_ddl
    publication_fragment = observation_ddl.split("publication_timestamp", 1)[1].split(",", 1)[0]
    assert "NOT NULL" not in publication_fragment
    migration_source = Path("migrations/versions/20260724_0007_fred_provider.py").read_text(
        encoding="utf-8"
    )
    assert 'down_revision: str | None = "20260724_0006"' in migration_source
    assert "uq_data_series_source_provider_id" in migration_source
    assert "ck_series_provider_id_nonempty" in migration_source


def test_scheduler_migration_downgrade_and_reupgrade_with_seeded_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = f"sqlite:///{tmp_path / 'scheduler-cycle.db'}"
    monkeypatch.setenv("MACROVISION_DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    engine = create_database_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO provider_sync_schedules "
                "(id,provider,provider_series_id,request_config,request_config_fingerprint,"
                "cadence_type,interval_minutes,next_run_at,enabled,lock_version) VALUES "
                "(1,'fred','GDP','{}',:fingerprint,'fixed_interval',60,"
                "'2026-07-25 13:00:00',1,1)"
            ),
            {"fingerprint": "a" * 64},
        )
        connection.execute(
            text(
                "INSERT INTO provider_sync_runs "
                "(id,schedule_id,run_key,trigger_type,provider,provider_series_id,"
                "concurrency_key,request_snapshot,request_snapshot_fingerprint,status,"
                "scheduled_for,started_at,completed_at,attempt_number,maximum_attempts,"
                "lease_generation,sync_idempotency_key,observations_received,"
                "observations_accepted,observations_revised,observations_missing,"
                "observations_rejected,error_code,error_message) VALUES "
                "(1,1,:run_key,'scheduled','fred','GDP',:concurrency_key,'{}',"
                ":fingerprint,'failed','2026-07-25 12:00:00','2026-07-25 12:00:00',"
                "'2026-07-25 12:01:00',1,2,1,:sync_key,0,0,0,0,0,"
                "'safe_failure','Sanitized failure')"
            ),
            {
                "run_key": "b" * 64,
                "concurrency_key": "c" * 64,
                "fingerprint": "a" * 64,
                "sync_key": f"scheduler:{'d' * 64}",
            },
        )
        connection.execute(
            text(
                "INSERT INTO data_sources (id,code,name,description) "
                "VALUES (1,'SAFE','Unaffected source','Must survive scheduler downgrade')"
            )
        )
    engine.dispose()

    command.downgrade(config, "20260724_0007")
    engine = create_database_engine(database_url)
    with engine.connect() as connection:
        assert "provider_sync_schedules" not in inspect(connection).get_table_names()
        assert connection.scalar(text("SELECT COUNT(*) FROM data_sources")) == 1
    engine.dispose()

    command.upgrade(config, "head")
    engine = create_database_engine(database_url)
    with engine.connect() as connection:
        assert {"provider_sync_schedules", "provider_sync_runs"} <= set(
            inspect(connection).get_table_names()
        )
        assert connection.scalar(text("SELECT COUNT(*) FROM data_sources")) == 1
    engine.dispose()
    get_settings.cache_clear()


def test_provider_provenance_downgrade_and_reupgrade_preserves_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = f"sqlite:///{tmp_path / 'provider-cycle.db'}"
    monkeypatch.setenv("MACROVISION_DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    engine = create_database_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO data_sources (id,code,name,description) "
                "VALUES (1,'FRED','Federal Reserve Economic Data','Provider')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO data_series "
                "(id,source_id,code,provider_series_id,name,description,category,"
                "geography,frequency,unit,seasonal_adjustment,publication_lag_days,"
                "is_active,series_metadata,lock_version) VALUES "
                "(1,1,'FRED.GDP','GDP','GDP','GDP','growth','US','quarterly','USD',"
                "'adjusted',0,1,'{}',1)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO data_observations "
                "(id,series_id,observed_at,publication_timestamp,ingestion_timestamp,"
                "provider_vintage_start,provider_vintage_end,provider_metadata,value,status) "
                "VALUES (1,1,'2025-01-01',NULL,'2025-02-01','2025-02-01',"
                "'2025-02-01','{}',10000000000,'present')"
            )
        )
    engine.dispose()
    command.downgrade(config, "20260724_0006")
    engine = create_database_engine(database_url)
    with engine.connect() as connection:
        assert connection.scalar(
            text("SELECT publication_timestamp IS NOT NULL FROM data_observations WHERE id=1")
        )
        assert "provider_series_id" not in {
            column["name"] for column in inspect(connection).get_columns("data_series")
        }
    engine.dispose()
    command.upgrade(config, "head")
    engine = create_database_engine(database_url)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT COUNT(*) FROM data_observations")) == 1
        assert "provider_series_id" in {
            column["name"] for column in inspect(connection).get_columns("data_series")
        }
    engine.dispose()
    get_settings.cache_clear()


@pytest.mark.parametrize(
    "legacy_revision",
    [
        "20260723_0001",
        "20260723_0002",
        "20260723_0003",
        "20260724_0004",
        "20260724_0005",
        "20260724_0006",
        "20260724_0007",
    ],
)
def test_each_legacy_schema_upgrades_to_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    legacy_revision: str,
) -> None:
    database_url = f"sqlite:///{tmp_path / f'{legacy_revision}.db'}"
    monkeypatch.setenv("MACROVISION_DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = Config("alembic.ini")
    command.upgrade(config, legacy_revision)
    command.upgrade(config, "head")
    engine = create_database_engine(database_url)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "20260724_0008"
        )
    engine.dispose()
    get_settings.cache_clear()
