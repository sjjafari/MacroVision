from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

import macrovision.analytics_services as services
from macrovision.analytics_models import AnalyticsRun, DerivedObservation
from macrovision.analytics_schemas import TransformationType
from macrovision.analytics_services import (
    AnalyticsConflictError,
    AnalyticsExecutionError,
    AnalyticsExecutionRequest,
    AnalyticsNotFoundError,
    AnalyticsResourceLimitError,
    AnalyticsSnapshotError,
    AnalyticsValidationError,
    _safe_error,
    execute_analytics_run,
)
from tests.test_analytics_services import (
    FEB,
    INGESTED,
    JAN,
    MAR,
    _definition,
    _observation,
    _request,
    _series,
)


def test_execution_request_is_strict_utc_and_inclusive() -> None:
    request = AnalyticsExecutionRequest(
        definition_id=1,
        requested_start_at=datetime(2026, 1, 1, 3, 30, tzinfo=UTC),
        requested_end_at=datetime(2026, 1, 1, 3, 30, tzinfo=UTC),
    )
    assert request.requested_start_at == request.requested_end_at
    with pytest.raises(ValidationError):
        AnalyticsExecutionRequest(
            definition_id=1,
            requested_start_at=datetime(2026, 1, 2),
            requested_end_at=datetime(2026, 1, 1),
        )
    with pytest.raises(ValidationError):
        AnalyticsExecutionRequest.model_validate(
            {
                "definition_id": 1,
                "requested_start_at": MAR,
                "requested_end_at": JAN,
                "caller_fingerprint": "unsafe",
            }
        )
    with pytest.raises(ValidationError):
        AnalyticsExecutionRequest(
            definition_id=1,
            requested_start_at=MAR,
            requested_end_at=JAN,
        )


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (AnalyticsSnapshotError("private"), "analytics_snapshot"),
        (AnalyticsConflictError("private"), "analytics_conflict"),
        (AnalyticsExecutionError("private"), "analytics_execution"),
        (OperationalError("statement", {}, Exception("private")), "database_conflict"),
        (RuntimeError("private"), "analytics_execution"),
    ],
)
def test_service_error_messages_are_bounded_and_sanitized(error: Exception, code: str) -> None:
    safe_code, message = _safe_error(error)
    assert safe_code == code
    assert "private" not in message


def test_missing_and_absent_inputs_have_distinct_results_and_lineage(
    db_session: Session,
) -> None:
    series = _series(db_session, "S.MISSING")
    _observation(db_session, series, JAN, "10")
    _observation(db_session, series, FEB, None)
    _observation(db_session, series, MAR, "30")
    db_session.commit()
    definition = _definition(db_session, TransformationType.difference, [series])
    run = execute_analytics_run(db_session, _request(definition))
    outputs = db_session.scalars(
        select(DerivedObservation)
        .where(DerivedObservation.run_id == run.id)
        .order_by(DerivedObservation.observed_at)
    ).all()
    assert [item.missing_reason for item in outputs] == [
        "source_missing",
        "source_missing",
    ]
    assert run.inputs_examined == 4
    assert run.lineage_links == 4

    second = _series(db_session, "S.ABSENT")
    _observation(db_session, second, JAN, "10")
    _observation(db_session, second, MAR, "30")
    db_session.commit()
    absent_definition = _definition(db_session, TransformationType.difference, [second])
    absent = execute_analytics_run(db_session, _request(absent_definition))
    absent_output = db_session.scalar(
        select(DerivedObservation).where(
            DerivedObservation.run_id == absent.id,
            DerivedObservation.observed_at == MAR,
        )
    )
    assert absent_output is not None
    assert absent_output.missing_reason == "timestamp_absent"
    assert absent.inputs_examined == 2
    assert absent.lineage_links == 1


def test_output_resource_limit_rolls_back_without_partial_graph(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    series = _series(db_session, "S.LIMIT")
    _observation(db_session, series, JAN, "1")
    _observation(db_session, series, FEB, "2")
    db_session.commit()
    definition = _definition(db_session, TransformationType.difference, [series])
    monkeypatch.setattr(services, "MAX_CANDIDATE_OUTPUTS", 1)
    with pytest.raises(AnalyticsResourceLimitError):
        execute_analytics_run(
            db_session,
            _request(definition, start=JAN, end=FEB, as_of=INGESTED),
        )
    failed = db_session.scalar(select(AnalyticsRun).where(AnalyticsRun.status == "failed"))
    assert failed is not None
    db_session.rollback()
    assert failed.error_code == "analytics_resource_limit"
    assert db_session.scalar(select(func.count(DerivedObservation.id))) == 0


def test_fingerprints_remain_private_in_repr_and_errors(db_session: Session) -> None:
    series = _series(db_session, "S.PRIVATE")
    _observation(db_session, series, JAN, "1")
    _observation(db_session, series, FEB, "2")
    db_session.commit()
    definition = _definition(db_session, TransformationType.difference, [series])
    run = execute_analytics_run(db_session, _request(definition, start=FEB, end=FEB))
    representation = repr(run)
    assert run.snapshot_fingerprint is not None
    assert run.reusable_fingerprint is not None
    assert run.request_fingerprint not in representation
    assert run.snapshot_fingerprint not in representation
    assert run.reusable_fingerprint not in representation
    with pytest.raises(AnalyticsConflictError):
        execute_analytics_run(
            db_session,
            _request(
                definition,
                start=FEB,
                end=FEB,
                retry=run.id,
            ),
        )


def test_active_exact_request_is_returned_without_duplicate_graph(
    db_session: Session,
) -> None:
    series = _series(db_session, "S.ACTIVE")
    _observation(db_session, series, JAN, "1")
    _observation(db_session, series, FEB, "2")
    db_session.commit()
    definition = _definition(db_session, TransformationType.difference, [series])
    request = _request(definition, start=FEB, end=FEB)
    completed = execute_analytics_run(db_session, request)
    active = AnalyticsRun(
        definition_version_id=completed.definition_version_id,
        status="pending",
        requested_start_at=completed.requested_start_at,
        requested_end_at=completed.requested_end_at,
        calculation_cutoff=completed.calculation_cutoff,
        engine_version=completed.engine_version,
        request_fingerprint=completed.request_fingerprint,
        inputs_examined=0,
        outputs_present=0,
        outputs_missing=0,
        lineage_links=0,
    )
    db_session.add(active)
    db_session.commit()
    replay = execute_analytics_run(db_session, request)
    assert replay.id == active.id
    assert db_session.scalar(select(func.count(DerivedObservation.id))) == 1


def test_requested_version_structural_tamper_and_fresh_session_are_enforced(
    db_session: Session,
) -> None:
    series = _series(db_session, "S.STRUCTURE")
    _observation(db_session, series, JAN, "1")
    _observation(db_session, series, FEB, "2")
    db_session.commit()
    definition = _definition(db_session, TransformationType.difference, [series])
    with pytest.raises(AnalyticsNotFoundError):
        execute_analytics_run(
            db_session,
            AnalyticsExecutionRequest(
                definition_id=definition.id,
                definition_version=2,
                requested_start_at=FEB,
                requested_end_at=FEB,
            ),
        )
    db_session.execute(select(func.count()).select_from(DerivedObservation))
    with pytest.raises(AnalyticsConflictError, match="fresh session"):
        execute_analytics_run(db_session, _request(definition, start=FEB, end=FEB))
    db_session.rollback()
    db_session.execute(
        text(
            "UPDATE derived_series_definition_versions "
            "SET parameters_fingerprint=:fingerprint WHERE definition_id=:definition"
        ),
        {"fingerprint": "f" * 64, "definition": definition.id},
    )
    db_session.commit()
    with pytest.raises(AnalyticsValidationError):
        execute_analytics_run(db_session, _request(definition, start=FEB, end=FEB))


def test_retry_target_validation_and_linkage(db_session: Session) -> None:
    series = _series(db_session, "S.RETRY")
    _observation(db_session, series, JAN, "0")
    _observation(db_session, series, FEB, "2")
    db_session.commit()
    definition = _definition(db_session, TransformationType.rebase_index, [series])
    request = _request(definition, start=FEB, end=FEB)
    with pytest.raises(AnalyticsExecutionError):
        execute_analytics_run(db_session, request)
    failed = db_session.scalar(select(AnalyticsRun).where(AnalyticsRun.status == "failed"))
    assert failed is not None
    failed_id = failed.id
    definition_id = definition.id
    retry_request = AnalyticsExecutionRequest(
        definition_id=definition_id,
        requested_start_at=FEB,
        requested_end_at=FEB,
        as_of=datetime(2026, 5, 1, tzinfo=UTC),
        retry_of_run_id=failed_id,
    )
    db_session.rollback()
    with pytest.raises(AnalyticsExecutionError):
        execute_analytics_run(db_session, retry_request)
    retry = db_session.scalars(
        select(AnalyticsRun).where(AnalyticsRun.retry_of_run_id == failed_id)
    ).one()
    assert retry.status == "failed"
    db_session.rollback()
    with pytest.raises(AnalyticsNotFoundError):
        execute_analytics_run(
            db_session,
            AnalyticsExecutionRequest(
                definition_id=definition_id,
                requested_start_at=FEB,
                requested_end_at=FEB,
                as_of=datetime(2026, 5, 1, tzinfo=UTC),
                retry_of_run_id=999_999,
            ),
        )
    with pytest.raises(AnalyticsValidationError):
        execute_analytics_run(
            db_session,
            AnalyticsExecutionRequest(
                definition_id=definition_id,
                requested_start_at=JAN,
                requested_end_at=FEB,
                as_of=datetime(2026, 5, 1, tzinfo=UTC),
                retry_of_run_id=failed_id,
            ),
        )
    db_session.execute(text("DELETE FROM analytics_runs WHERE retry_of_run_id IS NOT NULL"))
    db_session.execute(text("DELETE FROM analytics_runs"))
    db_session.commit()
