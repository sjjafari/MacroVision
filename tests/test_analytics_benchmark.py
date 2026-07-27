import json
import os
import sys
from typing import cast

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from macrovision import analytics_benchmark
from macrovision import analytics_services as analytics_execution
from macrovision.analytics_benchmark import run_benchmark
from macrovision.analytics_models import DerivedSeriesDefinition
from macrovision.database import create_database_engine
from macrovision.macro_data_models import DataSource


def test_sqlite_benchmark_is_deterministic_and_replays() -> None:
    summary = run_benchmark(sizes=(10,))
    assert summary["backend"] == "sqlite"
    cases = cast(list[dict[str, object]], summary["cases"])
    assert len(cases) == 2
    assert {item["transformation"] for item in cases} == {
        "difference",
        "moving_average",
    }
    assert all(item["outputs"] == 10 for item in cases)
    assert all(item["replayed_run_id_matches"] is True for item in cases)
    assert all(
        float(cast(float, item["replay_seconds"])) < float(cast(float, item["total_seconds"]))
        for item in cases
    )
    assert all(
        item["timing_method"]
        == (
            "estimated by subtracting an independent source-resolution "
            "measurement from total execution"
        )
        for item in cases
    )
    assert all("estimated_transformation_persistence_seconds" in item for item in cases)
    assert all("transformation_persistence_seconds" not in item for item in cases)


def test_postgresql_benchmark_requires_explicit_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MACROVISION_POSTGRES_BENCHMARK_URL", raising=False)
    with pytest.raises(RuntimeError, match="MACROVISION_POSTGRES_BENCHMARK_URL"):
        run_benchmark(sizes=(10,), postgres=True)


def test_shared_database_benchmark_failure_cleans_only_owned_rows(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unrelated = DataSource(code="UNRELATED", name="Unrelated", description="")
    db_session.add(unrelated)
    db_session.commit()
    database_url = str(cast(Engine, db_session.get_bind()).url)
    monkeypatch.setattr(analytics_benchmark, "_verify_postgresql_schema", lambda _engine: None)

    def fail_execution(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("synthetic benchmark failure")

    monkeypatch.setattr(
        analytics_execution,
        "execute_analytics_run",
        fail_execution,
    )
    with pytest.raises(RuntimeError, match="synthetic benchmark failure"):
        analytics_benchmark._run_case(
            database_url,
            10,
            "difference",
            initialize_schema=False,
        )
    db_session.expire_all()
    assert db_session.scalar(select(func.count(DataSource.id))) == 1
    assert (
        db_session.scalar(select(func.count(DataSource.id)).where(DataSource.code == "UNRELATED"))
        == 1
    )


def test_shared_benchmark_refuses_an_unmigrated_database(db_session: Session) -> None:
    engine = cast(Engine, db_session.get_bind())
    with pytest.raises(RuntimeError, match="not fully migrated"):
        analytics_benchmark._verify_postgresql_schema(engine)


@pytest.mark.parametrize("as_json", [True, False])
def test_benchmark_command_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    as_json: bool,
) -> None:
    arguments = ["analytics-benchmark", "--sizes", "2"]
    if as_json:
        arguments.append("--json")
    monkeypatch.setattr(sys, "argv", arguments)
    analytics_benchmark.main()
    result = json.loads(capsys.readouterr().out)
    assert result["backend"] == "sqlite"
    assert len(result["cases"]) == 2


POSTGRES_BENCHMARK_URL = os.getenv("MACROVISION_POSTGRES_TEST_URL")


@pytest.mark.skipif(
    POSTGRES_BENCHMARK_URL is None,
    reason="A dedicated PostgreSQL Analytics benchmark database is not configured",
)
def test_postgresql_benchmark_is_rerunnable_and_cleans_owned_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert POSTGRES_BENCHMARK_URL is not None
    monkeypatch.setenv("MACROVISION_POSTGRES_BENCHMARK_URL", POSTGRES_BENCHMARK_URL)
    first = run_benchmark(sizes=(10,), postgres=True)
    second = run_benchmark(sizes=(10,), postgres=True)
    assert first["backend"] == second["backend"] == "postgresql"
    assert len(cast(list[object], first["cases"])) == 2
    assert len(cast(list[object], second["cases"])) == 2

    engine = create_database_engine(POSTGRES_BENCHMARK_URL)
    with Session(engine) as session:
        assert (
            session.scalar(
                select(func.count(DerivedSeriesDefinition.id)).where(
                    DerivedSeriesDefinition.code.startswith("BENCH.", autoescape=True)
                )
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count(DataSource.id)).where(
                    DataSource.code.startswith("BENCH.", autoescape=True)
                )
            )
            == 0
        )
    engine.dispose()
