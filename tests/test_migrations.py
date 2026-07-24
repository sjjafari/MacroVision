from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from macrovision import portfolio_schemas, portfolio_services
from macrovision.config import get_settings
from macrovision.database import create_database_engine


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
                "(1,'Legacy','USD',10,0.2,'Preserve capital','None')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO research_journals "
                "(id,investor_id,asset,hypothesis,evidence_for,evidence_against,"
                "critic_review,probability,confidence,invalidation_conditions,decision,"
                "outcome,lessons,status) VALUES "
                "(1,1,'Cash','H','For','Against','Critic',0.6,0.5,'Rule','Hold',"
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
        assert connection.scalar(text("SELECT COUNT(*) FROM decision_cases")) == 1
        assert connection.scalar(text("SELECT COUNT(*) FROM data_import_batches")) == 1
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


@pytest.mark.parametrize(
    "legacy_revision",
    [
        "20260723_0001",
        "20260723_0002",
        "20260723_0003",
        "20260724_0004",
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
            "20260724_0005"
        )
    engine.dispose()
    get_settings.cache_clear()
