"""Deterministic, offline synchronous Macro Analytics benchmark."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from macrovision import analytics_api_schemas as api_schemas
from macrovision import analytics_management_services as management
from macrovision import analytics_services as execution
from macrovision.database import Base, create_database_engine
from macrovision.macro_data_models import (
    DataFrequency,
    DataObservation,
    DataSeries,
    DataSource,
    ObservationStatus,
    SeasonalAdjustment,
    SeriesCategory,
)


def _definition_payload(
    source_id: int, transformation: str, token: str
) -> api_schemas.DerivedSeriesCreate:
    parameters: dict[str, object] = {"transformation_type": transformation}
    if transformation == "moving_average":
        parameters["window"] = 2
    return api_schemas.DerivedSeriesCreate.model_validate(
        {
            "code": f"BENCH.{token}.{transformation.upper()}",
            "title": f"Benchmark {transformation}",
            "initial_version": {
                "parameters": parameters,
                "inputs": [{"alias": "value", "source_series_id": source_id}],
            },
        }
    )


def _seed(session: Session, count: int, token: str) -> tuple[int, datetime, datetime]:
    source = DataSource(code=f"BENCH.{token}", name="Offline benchmark", description="")
    series = DataSeries(
        source=source,
        code=f"BENCH.{token}.SOURCE",
        name="Synthetic source",
        description="Deterministic offline benchmark data",
        category=SeriesCategory.custom,
        geography="TEST",
        frequency=DataFrequency.daily,
        unit="index",
        seasonal_adjustment=SeasonalAdjustment.not_applicable,
        publication_lag_days=0,
        is_active=True,
        series_metadata={},
        lock_version=1,
    )
    session.add(series)
    session.flush()
    start = datetime(1990, 1, 1, tzinfo=UTC)
    ingestion = datetime(2020, 1, 1, tzinfo=UTC)
    session.add_all(
        [
            DataObservation(
                series_id=series.id,
                observed_at=start + timedelta(days=index),
                publication_timestamp=start + timedelta(days=index),
                ingestion_timestamp=ingestion,
                value=Decimal(index + 1),
                status=ObservationStatus.present,
                provider_metadata={},
            )
            for index in range(count + 1)
        ]
    )
    session.commit()
    return series.id, start + timedelta(days=1), start + timedelta(days=count)


def _measure_resolution(
    factory: sessionmaker[Session], request: execution.AnalyticsExecutionRequest
) -> float:
    session = factory()
    started = time.perf_counter()
    try:
        dialect = execution._begin_snapshot(session)
        prepared, _ = execution._load_definition(session, request, dialect)
        cutoff = request.as_of
        assert cutoff is not None
        candidates = execution._candidate_timestamps(session, prepared, request, cutoff)
        execution._resolve_snapshot(session, prepared, candidates, cutoff)
        return time.perf_counter() - started
    finally:
        session.rollback()
        session.close()


def _run_case(database_url: str, count: int, transformation: str) -> dict[str, object]:
    engine = create_database_engine(database_url)
    try:
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        setup = factory()
        token = f"N{count}.{transformation.upper()}"
        source_id, start, end = _seed(setup, count, token)
        definition = management.create_definition(
            setup, _definition_payload(source_id, transformation, token)
        )
        definition_id = definition.id
        setup.close()
        request = execution.AnalyticsExecutionRequest(
            definition_id=definition_id,
            requested_start_at=start,
            requested_end_at=end,
            as_of=datetime(2025, 1, 1, tzinfo=UTC),
        )
        resolution_seconds = _measure_resolution(factory, request)

        first_session = factory()
        started = time.perf_counter()
        first = execution.execute_analytics_run(first_session, request)
        total_seconds = time.perf_counter() - started
        first_session.close()

        replay_session = factory()
        replay_started = time.perf_counter()
        replay = execution.execute_analytics_run(replay_session, request)
        replay_seconds = time.perf_counter() - replay_started
        replay_session.close()
        return {
            "candidates": count,
            "transformation": transformation,
            "source_resolution_seconds": round(resolution_seconds, 6),
            "transformation_persistence_seconds": round(
                max(total_seconds - resolution_seconds, 0), 6
            ),
            "total_seconds": round(total_seconds, 6),
            "replay_seconds": round(replay_seconds, 6),
            "outputs": first.outputs_present + first.outputs_missing,
            "lineage": first.lineage_links,
            "replayed_run_id_matches": replay.id == first.id,
        }
    finally:
        engine.dispose()


def run_benchmark(
    *,
    sizes: tuple[int, ...] = (100, 1_000, 10_000),
    postgres: bool = False,
) -> dict[str, object]:
    cases: list[dict[str, object]] = []
    if postgres:
        database_url = os.getenv("MACROVISION_POSTGRES_BENCHMARK_URL")
        if not database_url:
            raise RuntimeError(
                "MACROVISION_POSTGRES_BENCHMARK_URL is required for PostgreSQL benchmarking"
            )
        backend = "postgresql"
        cases.extend(
            _run_case(database_url, count, transformation)
            for count in sizes
            for transformation in ("difference", "moving_average")
        )
    else:
        backend = "sqlite"
        with tempfile.TemporaryDirectory(prefix="macrovision-analytics-benchmark-") as directory:
            for count in sizes:
                for transformation in ("difference", "moving_average"):
                    database = Path(directory) / f"{count}-{transformation}.db"
                    cases.append(
                        _run_case(
                            f"sqlite:///{database.as_posix()}",
                            count,
                            transformation,
                        )
                    )
    return {"backend": backend, "cases": cases}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--postgres", action="store_true")
    parser.add_argument("--sizes", default="100,1000,10000")
    arguments = parser.parse_args()
    sizes = tuple(int(item) for item in arguments.sizes.split(","))
    summary = run_benchmark(sizes=sizes, postgres=arguments.postgres)
    if arguments.as_json:
        print(json.dumps(summary, sort_keys=True))
    else:
        print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
