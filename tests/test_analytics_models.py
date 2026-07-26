from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from macrovision.analytics_models import (
    AnalyticsRun,
    DerivedObservation,
    DerivedObservationLineage,
    DerivedSeriesDefinition,
    DerivedSeriesDefinitionVersion,
    DerivedSeriesInput,
)
from macrovision.analytics_schemas import DerivedSeriesDefinitionCreate
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

NOW = datetime(2026, 7, 26, tzinfo=UTC)
FP_A = "a" * 64
FP_B = "b" * 64
FP_C = "c" * 64


def seed_graph(
    session: Session,
) -> tuple[
    DerivedSeriesDefinition,
    DerivedSeriesDefinitionVersion,
    DataSeries,
]:
    source = DataSource(code="TEST", name="Test", description="")
    series = DataSeries(
        source=source,
        code="TEST.CPI",
        name="CPI",
        description="",
        category=SeriesCategory.inflation,
        geography="US",
        frequency=DataFrequency.monthly,
        unit="index",
        currency=None,
        seasonal_adjustment=SeasonalAdjustment.adjusted,
        publication_lag_days=0,
        is_active=True,
        series_metadata={},
        lock_version=1,
    )
    definition = DerivedSeriesDefinition(
        code="CPI.YOY",
        title="CPI YoY",
        description=None,
        enabled=True,
        lock_version=1,
    )
    version = DerivedSeriesDefinitionVersion(
        definition=definition,
        version=1,
        transformation_type="year_over_year_percent_change",
        parameters={"transformation_type": "year_over_year_percent_change"},
        parameters_fingerprint=FP_A,
        output_unit="percent",
        output_frequency="monthly",
        output_geography="US",
        output_currency=None,
        output_seasonal_adjustment="adjusted",
        engine_contract_version="1",
    )
    session.add_all([source, series, definition, version])
    session.commit()
    return definition, version, series


def make_run(
    version: DerivedSeriesDefinitionVersion,
    *,
    status: str = "pending",
    request: str = FP_A,
    reusable: str | None = None,
) -> AnalyticsRun:
    terminal = status in {"succeeded", "failed"}
    return AnalyticsRun(
        definition_version=version,
        status=status,
        requested_start_at=NOW,
        requested_end_at=NOW,
        calculation_cutoff=NOW,
        engine_version="1",
        request_fingerprint=request,
        snapshot_fingerprint=FP_B if terminal else None,
        reusable_fingerprint=reusable,
        inputs_examined=0,
        outputs_present=0,
        outputs_missing=0,
        lineage_links=0,
        started_at=NOW if terminal else None,
        completed_at=NOW if terminal else None,
        error_code="failed" if status == "failed" else None,
        error_message="Safe" if status == "failed" else None,
    )


def test_schema_normalization_and_database_code_uniqueness(db_session: Session) -> None:
    payload = DerivedSeriesDefinitionCreate.model_validate(
        {
            "code": "cpi.yoy",
            "title": "CPI",
            "inputs": [{"position": 0, "alias": "value", "source_series_id": 1}],
            "parameters": {"transformation_type": "difference"},
        }
    )
    assert payload.code == "CPI.YOY"
    db_session.add(
        DerivedSeriesDefinition(code=payload.code, title="One", enabled=True, lock_version=1)
    )
    db_session.commit()
    db_session.add(
        DerivedSeriesDefinition(code="CPI.YOY", title="Two", enabled=True, lock_version=1)
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


@pytest.mark.parametrize("code", ["lower", "1START", "BAD SPACE", "É"])
def test_database_code_check_rejects_noncanonical_values(db_session: Session, code: str) -> None:
    db_session.add(
        DerivedSeriesDefinition(code=code, title="Invalid", enabled=True, lock_version=1)
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_definition_constraints_and_expected_indexes(db_session: Session) -> None:
    db_session.add(DerivedSeriesDefinition(code="VALID", title="", enabled=True, lock_version=0))
    with pytest.raises(IntegrityError):
        db_session.commit()
    schema = inspect(db_session.get_bind())
    indexes = {item["name"] for item in schema.get_indexes("derived_series_definitions")}
    assert "ix_derived_definition_enabled_code" in indexes


def test_version_and_input_uniqueness_and_restrict(db_session: Session) -> None:
    definition, version, series = seed_graph(db_session)
    db_session.add(
        DerivedSeriesInput(
            definition_version=version,
            position=0,
            alias="value",
            source_series=series,
            source_code_snapshot=series.code,
            source_unit_snapshot=series.unit,
            source_frequency_snapshot=series.frequency.value,
            source_geography_snapshot=series.geography,
            source_currency_snapshot=None,
            source_seasonal_adjustment_snapshot=series.seasonal_adjustment.value,
        )
    )
    db_session.commit()
    duplicate = DerivedSeriesDefinitionVersion(
        definition=definition,
        version=1,
        transformation_type="difference",
        parameters={},
        parameters_fingerprint=FP_B,
        output_unit="index",
        output_frequency="monthly",
        output_geography="US",
        output_seasonal_adjustment="adjusted",
        engine_contract_version="1",
    )
    db_session.add(duplicate)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
    with pytest.raises(IntegrityError):
        db_session.execute(delete(DataSeries).where(DataSeries.id == series.id))
        db_session.commit()


def test_version_and_input_are_immutable(db_session: Session) -> None:
    _, version, series = seed_graph(db_session)
    item = DerivedSeriesInput(
        definition_version=version,
        position=0,
        alias="value",
        source_series=series,
        source_code_snapshot=series.code,
        source_unit_snapshot=series.unit,
        source_frequency_snapshot="monthly",
        source_geography_snapshot="US",
        source_seasonal_adjustment_snapshot="adjusted",
    )
    db_session.add(item)
    db_session.commit()
    version.change_note = "overwrite"
    with pytest.raises(ValueError, match="immutable"):
        db_session.commit()
    db_session.rollback()
    db_session.delete(item)
    with pytest.raises(ValueError, match="immutable"):
        db_session.commit()


def test_fingerprint_checks_and_active_partial_uniqueness(db_session: Session) -> None:
    _, version, _ = seed_graph(db_session)
    db_session.add(make_run(version, request=FP_A))
    db_session.commit()
    db_session.add(make_run(version, status="running", request=FP_A))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
    db_session.add(make_run(version, request="G" * 64))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_failed_runs_do_not_reserve_reusable_identity(db_session: Session) -> None:
    _, version, _ = seed_graph(db_session)
    first = make_run(version, status="failed", request=FP_A)
    second = make_run(version, status="failed", request=FP_A)
    db_session.add_all([first, second])
    db_session.commit()
    assert first.reusable_fingerprint is None
    assert second.reusable_fingerprint is None


def test_succeeded_reusable_identity_is_unique(db_session: Session) -> None:
    _, version, _ = seed_graph(db_session)
    db_session.add(make_run(version, status="succeeded", request=FP_A, reusable=FP_C))
    db_session.commit()
    db_session.add(make_run(version, status="succeeded", request=FP_B, reusable=FP_C))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_run_range_counters_and_reusable_status_checks(db_session: Session) -> None:
    _, version, _ = seed_graph(db_session)
    run = make_run(version, status="pending", reusable=FP_C)
    run.requested_start_at = NOW.replace(year=2027)
    run.inputs_examined = -1
    db_session.add(run)
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_terminal_run_immutability_but_pending_transition_is_allowed(
    db_session: Session,
) -> None:
    _, version, _ = seed_graph(db_session)
    pending = make_run(version)
    terminal = make_run(version, status="failed", request=FP_B)
    db_session.add_all([pending, terminal])
    db_session.commit()
    pending.status = "running"
    pending.started_at = NOW
    db_session.commit()
    terminal.error_message = "Overwrite"
    with pytest.raises(ValueError, match="Terminal"):
        db_session.commit()
    db_session.rollback()
    db_session.delete(terminal)
    with pytest.raises(ValueError, match="Terminal"):
        db_session.commit()


def test_observation_shapes_and_immutability(db_session: Session) -> None:
    _, version, _ = seed_graph(db_session)
    run = make_run(version)
    present = DerivedObservation(
        run=run,
        definition_version=version,
        observed_at=NOW,
        value=Decimal("1.25000000"),
        status="present",
    )
    missing = DerivedObservation(
        run=run,
        definition_version=version,
        observed_at=NOW.replace(month=6),
        value=None,
        status="missing",
        missing_reason="source_missing",
    )
    db_session.add_all([run, present, missing])
    db_session.commit()
    assert present.value == Decimal("1.25000000")
    present.value = Decimal("2")
    with pytest.raises(ValueError, match="immutable"):
        db_session.commit()
    db_session.rollback()
    db_session.add(
        DerivedObservation(
            run=run,
            definition_version=version,
            observed_at=NOW.replace(month=5),
            status="missing",
            missing_reason="not_approved",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


def _source_versions(
    db_session: Session, series: DataSeries
) -> tuple[DataObservation, DataRevision]:
    observation = DataObservation(
        series=series,
        observed_at=NOW,
        publication_timestamp=NOW,
        ingestion_timestamp=NOW,
        value=Decimal("1"),
        status=ObservationStatus.present,
        provider_metadata={},
    )
    revision = DataRevision(
        observation=observation,
        sequence=1,
        previous_value=Decimal("1"),
        revised_value=Decimal("2"),
        previous_status=ObservationStatus.present,
        revised_status=ObservationStatus.present,
        publication_timestamp=NOW,
        revision_timestamp=NOW,
        provider_metadata={},
        reason="Revision",
    )
    db_session.add_all([observation, revision])
    db_session.commit()
    return observation, revision


def test_lineage_original_revision_shapes_and_non_null_uniqueness(
    db_session: Session,
) -> None:
    _, version, series = seed_graph(db_session)
    source, revision = _source_versions(db_session, series)
    run = make_run(version)
    derived = DerivedObservation(
        run=run,
        definition_version=version,
        observed_at=NOW,
        value=Decimal("2"),
        status="present",
    )
    db_session.add_all([run, derived])
    db_session.flush()
    original = DerivedObservationLineage(
        derived_observation=derived,
        input_position=0,
        source_observation=source,
        source_version_kind="original",
        source_version_id=source.id,
        lineage_position=0,
        source_knowledge_timestamp=NOW,
    )
    revised = DerivedObservationLineage(
        derived_observation=derived,
        input_position=0,
        source_observation=source,
        source_revision=revision,
        source_version_kind="revision",
        source_version_id=revision.id,
        lineage_position=1,
        source_knowledge_timestamp=NOW,
    )
    db_session.add_all([original, revised])
    db_session.commit()
    assert original.source_revision_id is None
    assert revised.source_revision_id == revision.id
    db_session.add(
        DerivedObservationLineage(
            derived_observation=derived,
            input_position=0,
            source_observation=source,
            source_version_kind="original",
            source_version_id=source.id,
            lineage_position=0,
            source_knowledge_timestamp=NOW,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_invalid_lineage_shape_and_lineage_immutability(db_session: Session) -> None:
    _, version, series = seed_graph(db_session)
    source, revision = _source_versions(db_session, series)
    run = make_run(version)
    derived = DerivedObservation(
        run=run,
        definition_version=version,
        observed_at=NOW,
        value=Decimal("2"),
        status="present",
    )
    valid = DerivedObservationLineage(
        derived_observation=derived,
        input_position=0,
        source_observation=source,
        source_revision=revision,
        source_version_kind="revision",
        source_version_id=revision.id,
        lineage_position=0,
        source_knowledge_timestamp=NOW,
    )
    db_session.add_all([run, derived, valid])
    db_session.commit()
    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                "INSERT INTO derived_observation_lineage "
                "(derived_observation_id,input_position,source_observation_id,"
                "source_revision_id,source_version_kind,source_version_id,"
                "lineage_position,source_knowledge_timestamp) "
                "VALUES (:derived,0,:observation,:revision,'original',:observation,1,:time)"
            ),
            {
                "derived": derived.id,
                "observation": source.id,
                "revision": revision.id,
                "time": NOW,
            },
        )
        db_session.commit()
    db_session.rollback()
    valid.lineage_position = 1
    with pytest.raises(ValueError, match="immutable"):
        db_session.commit()


def test_all_analytics_foreign_keys_are_restrict(db_session: Session) -> None:
    schema = inspect(db_session.get_bind())
    for table in (
        "derived_series_definition_versions",
        "derived_series_inputs",
        "analytics_runs",
        "derived_observations",
        "derived_observation_lineage",
    ):
        for foreign_key in schema.get_foreign_keys(table):
            assert foreign_key["options"].get("ondelete") == "RESTRICT"


def test_no_current_or_derived_dependency_columns(db_session: Session) -> None:
    schema = inspect(db_session.get_bind())
    definition_columns = {
        column["name"] for column in schema.get_columns("derived_series_definitions")
    }
    input_columns = {column["name"] for column in schema.get_columns("derived_series_inputs")}
    assert "current_version_id" not in definition_columns
    assert "source_definition_version_id" not in input_columns
    assert db_session.scalar(text("SELECT COUNT(*) FROM derived_series_definitions")) == 0


def test_private_fingerprints_are_not_in_default_repr(db_session: Session) -> None:
    _, version, _ = seed_graph(db_session)
    run = make_run(version, request=FP_A)
    representation = repr(run)
    assert FP_A not in representation
    assert "request_fingerprint" not in representation
