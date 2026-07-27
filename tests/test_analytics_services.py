from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from macrovision.analytics_models import (
    AnalyticsRun,
    DerivedObservation,
    DerivedObservationLineage,
    DerivedSeriesDefinition,
    DerivedSeriesDefinitionVersion,
    DerivedSeriesInput,
)
from macrovision.analytics_schemas import (
    InputMetadata,
    MovingAverageParameters,
    NoParameters,
    RebaseIndexParameters,
    RollingStandardDeviationParameters,
    RollingZScoreParameters,
    TransformationParameters,
    TransformationType,
)
from macrovision.analytics_services import (
    ANALYTICS_ENGINE_VERSION,
    AnalyticsExecutionRequest,
    AnalyticsNotFoundError,
    AnalyticsValidationError,
    _begin_snapshot,
    _candidate_timestamps,
    _definition_statement,
    _digest,
    _latest_eligible_revisions,
    _load_definition,
    _resolve_snapshot,
    _snapshot_payload,
    execute_analytics_run,
)
from macrovision.analytics_transformations import (
    get_transformation_spec,
    parameters_fingerprint,
)
from macrovision.macro_data_models import (
    DataFrequency,
    DataObservation,
    DataRevision,
    DataSeries,
    DataSource,
    ObservationStatus,
    SeasonalAdjustment,
    SeriesCategory,
)

JAN = datetime(2026, 1, 1, tzinfo=UTC)
FEB = datetime(2026, 2, 1, tzinfo=UTC)
MAR = datetime(2026, 3, 1, tzinfo=UTC)
INGESTED = datetime(2026, 4, 1, tzinfo=UTC)


def test_snapshot_clock_is_dialect_specific() -> None:
    from sqlalchemy.dialects import postgresql, sqlite

    request = AnalyticsExecutionRequest(
        definition_id=1,
        requested_start_at=JAN,
        requested_end_at=JAN,
    )
    postgres_sql = str(
        _definition_statement(request, "postgresql").compile(
            dialect=postgresql.dialect()  # type: ignore[no-untyped-call]
        )
    )
    sqlite_sql = str(_definition_statement(request, "sqlite").compile(dialect=sqlite.dialect()))
    assert "statement_timestamp()" in postgres_sql
    assert "CURRENT_TIMESTAMP" not in postgres_sql
    assert "macrovision_utc_now()" in sqlite_sql


def test_private_fingerprint_payloads_separate_cutoff_and_semantics(
    db_session: Session,
) -> None:
    series = _series(db_session, "S.FINGERPRINT.SEMANTICS")
    _observation(db_session, series, JAN, "10")
    _observation(db_session, series, FEB, "20")
    db_session.commit()
    definition = _definition(db_session, TransformationType.difference, [series])
    request = _request(definition, start=FEB, end=FEB, as_of=INGESTED)
    dialect = _begin_snapshot(db_session)
    prepared, _ = _load_definition(db_session, request, dialect)
    candidates = _candidate_timestamps(db_session, prepared, request, INGESTED)
    points = _resolve_snapshot(db_session, prepared, candidates, INGESTED)
    db_session.rollback()

    later_cutoff = datetime(2026, 4, 2, tzinfo=UTC)
    exact_at_first = _digest(
        _snapshot_payload(prepared, request, INGESTED, points, include_cutoff=True)
    )
    exact_at_second = _digest(
        _snapshot_payload(prepared, request, later_cutoff, points, include_cutoff=True)
    )
    reusable_at_first = _digest(
        _snapshot_payload(prepared, request, INGESTED, points, include_cutoff=False)
    )
    reusable_at_second = _digest(
        _snapshot_payload(prepared, request, later_cutoff, points, include_cutoff=False)
    )
    assert exact_at_first != exact_at_second
    assert reusable_at_first == reusable_at_second

    base = cast(
        dict[str, Any],
        _snapshot_payload(prepared, request, INGESTED, points, include_cutoff=False),
    )
    variants: list[dict[str, Any]] = []
    revision = deepcopy(base)
    revision_source = revision["outputs"][0]["sources"][0]
    revision_source.update(
        {
            "revision_id": 999,
            "source_version_kind": "revision",
            "source_version_id": 999,
            "value": Decimal("11"),
        }
    )
    variants.append(revision)
    absent = deepcopy(base)
    absent["outputs"][0]["sources"][0] = {
        "input_position": 0,
        "lineage_position": 0,
        "required_at": JAN,
        "state": "absent",
        "absent": True,
    }
    variants.append(absent)
    for key, value in (
        ("requested_end_at", MAR),
        ("definition_version", 2),
        ("parameters", {"transformation_type": "difference", "changed": True}),
        ("engine_version", "different-engine"),
    ):
        changed = deepcopy(base)
        changed[key] = value
        variants.append(changed)
    base_digest = _digest(base)
    assert all(_digest(variant) != base_digest for variant in variants)


def _series(session: Session, code: str) -> DataSeries:
    source = session.scalar(select(DataSource).where(DataSource.code == "ANALYTICS"))
    if source is None:
        source = DataSource(code="ANALYTICS", name="Analytics fixtures", description="")
        session.add(source)
        session.flush()
    series = DataSeries(
        source=source,
        code=code,
        name=code,
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
    session.flush()
    return series


def _observation(
    session: Session,
    series: DataSeries,
    observed_at: datetime,
    value: str | None,
) -> DataObservation:
    observation = DataObservation(
        series=series,
        observed_at=observed_at,
        publication_timestamp=observed_at,
        ingestion_timestamp=INGESTED,
        value=Decimal(value) if value is not None else None,
        status=ObservationStatus.present if value is not None else ObservationStatus.missing,
        provider_metadata={},
    )
    session.add(observation)
    session.flush()
    return observation


def _parameters(kind: TransformationType) -> TransformationParameters:
    if kind is TransformationType.moving_average:
        return MovingAverageParameters(transformation_type=kind, window=3)
    if kind is TransformationType.rolling_standard_deviation:
        return RollingStandardDeviationParameters(transformation_type=kind, window=2)
    if kind is TransformationType.rolling_z_score:
        return RollingZScoreParameters(transformation_type=kind, window=2)
    if kind is TransformationType.rebase_index:
        return RebaseIndexParameters(transformation_type=kind, base_timestamp=JAN)
    return NoParameters(transformation_type=kind)


def _definition(
    session: Session,
    kind: TransformationType,
    series: list[DataSeries],
    *,
    enabled: bool = True,
) -> DerivedSeriesDefinition:
    parameters = _parameters(kind)
    spec = get_transformation_spec(kind)
    input_metadata = [
        InputMetadata(
            unit="index",
            frequency=DataFrequency.monthly,
            geography="US",
            currency=None,
            seasonal_adjustment=SeasonalAdjustment.adjusted,
        )
        for _ in series
    ]
    output = spec.validate_metadata(input_metadata)
    definition = DerivedSeriesDefinition(
        code=f"TEST.{kind.value.upper()}.{series[0].id}",
        title=kind.value,
        enabled=enabled,
        lock_version=1,
    )
    version = DerivedSeriesDefinitionVersion(
        definition=definition,
        version=1,
        transformation_type=kind.value,
        parameters=parameters.model_dump(mode="json"),
        parameters_fingerprint=parameters_fingerprint(parameters),
        output_unit=output.unit,
        output_frequency=output.frequency.value,
        output_geography=output.geography,
        output_currency=output.currency,
        output_seasonal_adjustment=output.seasonal_adjustment.value,
        engine_contract_version="phase-2b",
    )
    session.add_all([definition, version])
    session.flush()
    for position, (alias, source) in enumerate(zip(spec.ordered_aliases, series, strict=True)):
        session.add(
            DerivedSeriesInput(
                definition_version=version,
                position=position,
                alias=alias,
                source_series=source,
                source_code_snapshot=source.code,
                source_unit_snapshot="index",
                source_frequency_snapshot="monthly",
                source_geography_snapshot="US",
                source_currency_snapshot=None,
                source_seasonal_adjustment_snapshot="adjusted",
            )
        )
    session.commit()
    return definition


def _request(
    definition: DerivedSeriesDefinition,
    *,
    start: datetime = FEB,
    end: datetime = MAR,
    as_of: datetime | None = datetime(2026, 5, 1, tzinfo=UTC),
    retry: int | None = None,
) -> AnalyticsExecutionRequest:
    return AnalyticsExecutionRequest(
        definition_id=definition.id,
        requested_start_at=start,
        requested_end_at=end,
        as_of=as_of,
        retry_of_run_id=retry,
    )


@pytest.mark.parametrize(
    ("kind", "left", "right", "expected"),
    [
        (TransformationType.difference, ("10", "15", "25"), None, "10.00000000"),
        (TransformationType.percent_change, ("10", "15", "30"), None, "100.00000000"),
        (
            TransformationType.year_over_year_percent_change,
            ("10", "15", "30"),
            None,
            None,
        ),
        (TransformationType.ratio, ("10", "15", "30"), ("2", "3", "5"), "6.00000000"),
        (TransformationType.spread, ("10", "15", "30"), ("2", "3", "5"), "25.00000000"),
        (TransformationType.moving_average, ("10", "20", "30"), None, "20.00000000"),
        (
            TransformationType.rolling_standard_deviation,
            ("10", "20", "30"),
            None,
            "5.00000000",
        ),
        (TransformationType.rolling_z_score, ("10", "20", "30"), None, "1.00000000"),
        (TransformationType.rebase_index, ("10", "20", "30"), None, "300.00000000"),
    ],
)
def test_all_transformations_execute_over_persisted_sources(
    db_session: Session,
    kind: TransformationType,
    left: tuple[str, str, str],
    right: tuple[str, str, str] | None,
    expected: str | None,
) -> None:
    first = _series(db_session, f"S.{kind.value}.1")
    for timestamp, value in zip((JAN, FEB, MAR), left, strict=True):
        _observation(db_session, first, timestamp, value)
    series = [first]
    if right:
        second = _series(db_session, f"S.{kind.value}.2")
        for timestamp, value in zip((JAN, FEB, MAR), right, strict=True):
            _observation(db_session, second, timestamp, value)
        series.append(second)
    db_session.commit()
    definition = _definition(db_session, kind, series)

    run = execute_analytics_run(db_session, _request(definition))
    outputs = db_session.scalars(
        select(DerivedObservation)
        .where(DerivedObservation.run_id == run.id)
        .order_by(DerivedObservation.observed_at)
    ).all()

    assert run.status == "succeeded"
    assert run.engine_version == ANALYTICS_ENGINE_VERSION
    assert len(outputs) == 2
    if expected is None:
        assert outputs[-1].status == "missing"
        assert outputs[-1].missing_reason in {"timestamp_absent", "insufficient_history"}
    else:
        assert outputs[-1].value == Decimal(expected)
    assert run.outputs_present + run.outputs_missing == len(outputs)
    assert run.lineage_links == db_session.scalar(
        select(func.count(DerivedObservationLineage.id))
        .join(DerivedObservation)
        .where(DerivedObservation.run_id == run.id)
    )


def test_as_of_selects_exact_revision_and_reuses_semantic_snapshot(
    db_session: Session,
) -> None:
    series = _series(db_session, "S.REVISION")
    _observation(db_session, series, JAN, "10")
    current = _observation(db_session, series, FEB, "20")
    revision = DataRevision(
        observation=current,
        sequence=1,
        previous_value=Decimal("20"),
        revised_value=Decimal("25"),
        previous_status=ObservationStatus.present,
        revised_status=ObservationStatus.present,
        publication_timestamp=FEB,
        revision_timestamp=datetime(2026, 6, 1, tzinfo=UTC),
        provider_metadata={},
        reason="corrected",
    )
    db_session.add(revision)
    db_session.commit()
    definition = _definition(db_session, TransformationType.difference, [series])

    before = execute_analytics_run(
        db_session,
        _request(definition, start=FEB, end=FEB, as_of=datetime(2026, 5, 1, tzinfo=UTC)),
    )
    after = execute_analytics_run(
        db_session,
        _request(definition, start=FEB, end=FEB, as_of=datetime(2026, 7, 1, tzinfo=UTC)),
    )
    replay = execute_analytics_run(
        db_session,
        _request(definition, start=FEB, end=FEB, as_of=datetime(2026, 7, 2, tzinfo=UTC)),
    )
    before_output = db_session.scalar(
        select(DerivedObservation).where(DerivedObservation.run_id == before.id)
    )
    after_output = db_session.scalar(
        select(DerivedObservation).where(DerivedObservation.run_id == after.id)
    )
    after_lineage = db_session.scalars(
        select(DerivedObservationLineage)
        .join(DerivedObservation)
        .where(DerivedObservation.run_id == after.id)
        .order_by(DerivedObservationLineage.lineage_position)
    ).all()

    assert before_output is not None and before_output.value == Decimal("10.00000000")
    assert after_output is not None and after_output.value == Decimal("15.00000000")
    assert [item.source_version_kind for item in after_lineage] == ["original", "revision"]
    assert after_lineage[-1].source_revision_id == revision.id
    assert replay.id == after.id
    assert before.snapshot_fingerprint != after.snapshot_fingerprint
    assert before.reusable_fingerprint != after.reusable_fingerprint


def test_zero_output_range_succeeds_without_graph(db_session: Session) -> None:
    series = _series(db_session, "S.EMPTY")
    _observation(db_session, series, JAN, "10")
    db_session.commit()
    definition = _definition(db_session, TransformationType.difference, [series])
    run = execute_analytics_run(
        db_session,
        _request(
            definition,
            start=datetime(2027, 1, 1, tzinfo=UTC),
            end=datetime(2027, 2, 1, tzinfo=UTC),
        ),
    )
    assert (run.outputs_present, run.outputs_missing, run.lineage_links) == (0, 0, 0)
    assert run.inputs_examined == 0


def test_missing_disabled_and_future_requests_are_controlled(db_session: Session) -> None:
    with pytest.raises(AnalyticsNotFoundError):
        execute_analytics_run(
            db_session,
            AnalyticsExecutionRequest(
                definition_id=999,
                requested_start_at=JAN,
                requested_end_at=FEB,
            ),
        )
    series = _series(db_session, "S.DISABLED")
    db_session.commit()
    disabled = _definition(db_session, TransformationType.difference, [series], enabled=False)
    with pytest.raises(AnalyticsValidationError):
        execute_analytics_run(db_session, _request(disabled))
    disabled.enabled = True
    db_session.commit()
    with pytest.raises(AnalyticsValidationError):
        execute_analytics_run(
            db_session,
            _request(disabled, as_of=datetime(2100, 1, 1, tzinfo=UTC)),
        )


def test_failed_structural_rebase_is_audited_without_partial_graph(
    db_session: Session,
) -> None:
    series = _series(db_session, "S.REBASE.FAIL")
    _observation(db_session, series, JAN, "0")
    _observation(db_session, series, FEB, "20")
    db_session.commit()
    definition = _definition(db_session, TransformationType.rebase_index, [series])
    with pytest.raises(Exception, match="Analytics execution failed"):
        execute_analytics_run(
            db_session,
            _request(definition, start=FEB, end=FEB),
        )
    failed = db_session.scalar(
        select(AnalyticsRun).where(AnalyticsRun.definition_version_id == definition.versions[0].id)
    )
    assert failed is not None
    assert failed.status == "failed"
    assert failed.reusable_fingerprint is None
    assert failed.error_message == "The analytics definition or request is invalid"
    assert (
        db_session.scalar(
            select(func.count(DerivedObservation.id)).where(DerivedObservation.run_id == failed.id)
        )
        == 0
    )


def test_latest_revision_query_returns_one_eligible_row_per_observation(
    db_session: Session,
) -> None:
    series = _series(db_session, "S.REVISION.WINDOW")
    first = _observation(db_session, series, JAN, "1")
    second = _observation(db_session, series, FEB, "2")
    db_session.commit()
    base_time = datetime(2026, 4, 2, tzinfo=UTC)
    for sequence in range(1, 101):
        db_session.add(
            DataRevision(
                observation_id=first.id,
                sequence=sequence,
                previous_value=Decimal(sequence - 1),
                revised_value=Decimal(sequence),
                previous_status=ObservationStatus.present,
                revised_status=ObservationStatus.present,
                publication_timestamp=base_time,
                revision_timestamp=base_time.replace(microsecond=sequence),
                provider_metadata={},
                reason="bounded history",
            )
        )
    db_session.add_all(
        [
            DataRevision(
                observation_id=second.id,
                sequence=1,
                previous_value=Decimal("2"),
                revised_value=Decimal("3"),
                previous_status=ObservationStatus.present,
                revised_status=ObservationStatus.present,
                publication_timestamp=base_time,
                revision_timestamp=base_time,
                provider_metadata={},
                reason="eligible",
            ),
            DataRevision(
                observation_id=second.id,
                sequence=2,
                previous_value=Decimal("3"),
                revised_value=Decimal("4"),
                previous_status=ObservationStatus.present,
                revised_status=ObservationStatus.present,
                publication_timestamp=base_time,
                revision_timestamp=datetime(2026, 6, 1, tzinfo=UTC),
                provider_metadata={},
                reason="future",
            ),
        ]
    )
    db_session.commit()

    selected = _latest_eligible_revisions(
        db_session, [first.id, second.id], datetime(2026, 5, 1, tzinfo=UTC)
    )

    assert len(selected) == 2
    assert [(item.observation_id, item.sequence) for item in selected] == [
        (first.id, 100),
        (second.id, 1),
    ]
