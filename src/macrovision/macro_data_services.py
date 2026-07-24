import hashlib
import json
from contextlib import nullcontext
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from macrovision import macro_data_models as models
from macrovision import macro_data_schemas as schemas
from macrovision.config import get_settings
from macrovision.integrity import IntegrityConflictError, commit_or_conflict


class DataNotFoundError(Exception):
    pass


class DataConflictError(IntegrityConflictError):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def _commit(session: Session) -> None:
    try:
        commit_or_conflict(
            session,
            "Macro data update conflicted with existing or concurrent data",
        )
    except IntegrityConflictError as exc:
        raise DataConflictError(str(exc)) from exc


def _page(limit: int, offset: int) -> tuple[int, int]:
    if not 1 <= limit <= 200 or offset < 0:
        raise DataConflictError("Pagination requires limit 1..200 and offset >= 0")
    return limit, offset


def create_source(session: Session, payload: schemas.DataSourceCreate) -> models.DataSource:
    source = models.DataSource(**payload.model_dump())
    session.add(source)
    _commit(session)
    session.refresh(source)
    return source


def list_sources(session: Session, *, limit: int, offset: int) -> list[models.DataSource]:
    limit, offset = _page(limit, offset)
    return list(
        session.scalars(
            select(models.DataSource).order_by(models.DataSource.id).limit(limit).offset(offset)
        )
    )


def get_source(session: Session, source_id: int) -> models.DataSource:
    source = session.get(models.DataSource, source_id)
    if source is None:
        raise DataNotFoundError("Data source not found")
    return source


def create_series(session: Session, payload: schemas.DataSeriesCreate) -> models.DataSeries:
    get_source(session, payload.source_id)
    values = payload.model_dump(exclude={"metadata"})
    series = models.DataSeries(**values, series_metadata=payload.metadata)
    session.add(series)
    _commit(session)
    session.refresh(series)
    return series


def list_series(session: Session, *, limit: int, offset: int) -> list[models.DataSeries]:
    limit, offset = _page(limit, offset)
    return list(
        session.scalars(
            select(models.DataSeries).order_by(models.DataSeries.id).limit(limit).offset(offset)
        )
    )


def get_series(session: Session, series_id: int) -> models.DataSeries:
    series = session.get(models.DataSeries, series_id)
    if series is None:
        raise DataNotFoundError("Data series not found")
    return series


def patch_series(
    session: Session, series_id: int, payload: schemas.DataSeriesPatch
) -> models.DataSeries:
    series = get_series(session, series_id)
    if series.lock_version != payload.expected_lock_version:
        raise DataConflictError("Data series was changed; reload and retry")
    changes = payload.model_dump(exclude={"expected_lock_version"}, exclude_unset=True)
    if "metadata" in changes:
        changes["series_metadata"] = changes.pop("metadata")
    for field, value in changes.items():
        setattr(series, field, value)
    if (
        series.minimum_value is not None
        and series.maximum_value is not None
        and series.minimum_value > series.maximum_value
    ):
        raise DataConflictError("minimum_value cannot exceed maximum_value")
    series.lock_version += 1
    _commit(session)
    session.refresh(series)
    return series


def series_to_read(series: models.DataSeries) -> schemas.DataSeriesRead:
    return schemas.DataSeriesRead(
        id=series.id,
        source_id=series.source_id,
        code=series.code,
        name=series.name,
        description=series.description,
        category=series.category,
        geography=series.geography,
        frequency=series.frequency,
        unit=series.unit,
        currency=series.currency,
        seasonal_adjustment=series.seasonal_adjustment,
        publication_lag_days=series.publication_lag_days,
        is_active=series.is_active,
        metadata=series.series_metadata,
        minimum_value=series.minimum_value,
        maximum_value=series.maximum_value,
        max_change_percent=series.max_change_percent,
        stale_after_days=series.stale_after_days,
        lock_version=series.lock_version,
        created_at=series.created_at,
        updated_at=series.updated_at,
    )


def _observation_statement() -> Select[tuple[models.DataObservation]]:
    return select(models.DataObservation).options(selectinload(models.DataObservation.revisions))


def _effective_state(
    observation: models.DataObservation, as_of: datetime | None = None
) -> tuple[
    Decimal | None,
    models.ObservationStatus,
    datetime,
    datetime,
    str | None,
    int,
]:
    revisions = sorted(observation.revisions, key=lambda revision: revision.sequence)
    if as_of is not None:
        revisions = [revision for revision in revisions if revision.revision_timestamp <= as_of]
    if not revisions:
        return (
            observation.value,
            observation.status,
            observation.publication_timestamp,
            observation.ingestion_timestamp,
            observation.source_reference,
            0,
        )
    revision = revisions[-1]
    return (
        revision.revised_value,
        revision.revised_status,
        revision.publication_timestamp,
        revision.revision_timestamp,
        revision.source_reference,
        len(revisions),
    )


def observation_to_read(
    observation: models.DataObservation, *, as_of: datetime | None = None
) -> schemas.ObservationRead:
    value, status, publication, ingestion, reference, revision_count = _effective_state(
        observation, as_of
    )
    return schemas.ObservationRead(
        id=observation.id,
        series_id=observation.series_id,
        observed_at=observation.observed_at,
        publication_timestamp=publication,
        ingestion_timestamp=ingestion,
        value=value,
        status=status,
        source_reference=reference,
        revision_count=revision_count,
    )


def _add_issue(
    session: Session,
    *,
    series_id: int,
    issue_type: models.QualityIssueType,
    message: str,
    observation_id: int | None = None,
    details: dict[str, Any] | None = None,
) -> models.DataQualityIssue:
    issue = models.DataQualityIssue(
        series_id=series_id,
        observation_id=observation_id,
        issue_type=issue_type,
        status=models.QualityIssueStatus.open,
        message=message,
        details=details or {},
        detected_at=_now(),
        lock_version=1,
    )
    session.add(issue)
    return issue


def _frequency_violation(
    frequency: models.DataFrequency, previous: datetime, current: datetime
) -> bool:
    days = (current.date() - previous.date()).days
    bounds = {
        models.DataFrequency.daily: (1, 4),
        models.DataFrequency.weekly: (5, 10),
        models.DataFrequency.monthly: (20, 45),
        models.DataFrequency.quarterly: (70, 115),
        models.DataFrequency.annual: (330, 400),
    }
    expected = bounds.get(frequency)
    return expected is not None and not expected[0] <= days <= expected[1]


def _quality_checks(
    session: Session,
    series: models.DataSeries,
    observation: models.DataObservation,
    previous: models.DataObservation | None,
    effective_value: Decimal | None,
) -> None:
    if effective_value is not None and (
        (series.minimum_value is not None and effective_value < series.minimum_value)
        or (series.maximum_value is not None and effective_value > series.maximum_value)
    ):
        _add_issue(
            session,
            series_id=series.id,
            observation_id=observation.id,
            issue_type=models.QualityIssueType.invalid_numeric_range,
            message="Observation is outside configured numeric bounds",
            details={"value": str(effective_value)},
        )
    if previous is None:
        return
    if _frequency_violation(series.frequency, previous.observed_at, observation.observed_at):
        _add_issue(
            session,
            series_id=series.id,
            observation_id=observation.id,
            issue_type=models.QualityIssueType.frequency_violation,
            message="Observation spacing violates configured frequency",
        )
    previous_value = _effective_state(previous)[0]
    if (
        series.max_change_percent is not None
        and effective_value is not None
        and previous_value is not None
        and previous_value != Decimal(0)
    ):
        change = abs((effective_value - previous_value) / previous_value) * Decimal(100)
        if change > series.max_change_percent:
            _add_issue(
                session,
                series_id=series.id,
                observation_id=observation.id,
                issue_type=models.QualityIssueType.large_unexpected_change,
                message="Observation change exceeds configured threshold",
                details={"change_percent": str(change)},
            )


def _write_observation(
    session: Session,
    series: models.DataSeries,
    payload: schemas.ObservationWrite,
    *,
    import_batch_id: int | None = None,
    ingestion_timestamp: datetime | None = None,
) -> models.DataObservation:
    ingested_at = ingestion_timestamp or _now()
    if payload.publication_timestamp > ingested_at:
        raise DataConflictError("publication_timestamp cannot be in the future")
    existing = session.scalar(
        _observation_statement().where(
            models.DataObservation.series_id == series.id,
            models.DataObservation.observed_at == payload.observed_at,
        )
    )
    if existing is not None:
        if not payload.revision_reason:
            _add_issue(
                session,
                series_id=series.id,
                observation_id=existing.id,
                issue_type=models.QualityIssueType.duplicate_observation,
                message="Duplicate observation requires an explicit revision reason",
            )
            raise DataConflictError("Observation already exists; revision_reason is required")
        previous_value, previous_status, _, _, _, sequence = _effective_state(existing)
        revision = models.DataRevision(
            observation=existing,
            import_batch_id=import_batch_id,
            sequence=sequence + 1,
            previous_value=previous_value,
            revised_value=payload.value,
            previous_status=previous_status,
            revised_status=payload.status,
            publication_timestamp=payload.publication_timestamp,
            revision_timestamp=ingested_at,
            reason=payload.revision_reason,
            source_reference=payload.source_reference,
        )
        session.add(revision)
        return existing

    previous = session.scalar(
        _observation_statement()
        .where(
            models.DataObservation.series_id == series.id,
            models.DataObservation.observed_at < payload.observed_at,
        )
        .order_by(models.DataObservation.observed_at.desc())
        .limit(1)
    )
    observation = models.DataObservation(
        series=series,
        import_batch_id=import_batch_id,
        observed_at=payload.observed_at,
        publication_timestamp=payload.publication_timestamp,
        ingestion_timestamp=ingested_at,
        value=payload.value,
        status=payload.status,
        source_reference=payload.source_reference,
    )
    session.add(observation)
    session.flush()
    _quality_checks(session, series, observation, previous, payload.value)
    return observation


def add_observation(
    session: Session, series_id: int, payload: schemas.ObservationWrite
) -> models.DataObservation:
    series = get_series(session, series_id)
    if not series.is_active:
        raise DataConflictError("Inactive data series cannot accept observations")
    try:
        observation = _write_observation(session, series, payload)
        _commit(session)
    except DataConflictError as exc:
        pending_issues = [item for item in session.new if isinstance(item, models.DataQualityIssue)]
        if not pending_issues and "future" in str(exc):
            _add_issue(
                session,
                series_id=series.id,
                issue_type=models.QualityIssueType.impossible_timestamp,
                message=str(exc),
            )
            pending_issues = [item for item in session.new]
        if pending_issues:
            _commit(session)
        else:
            session.rollback()
        raise
    return (
        session.scalar(_observation_statement().where(models.DataObservation.id == observation.id))
        or observation
    )


def list_observations(
    session: Session, series_id: int, *, limit: int, offset: int
) -> list[models.DataObservation]:
    get_series(session, series_id)
    limit, offset = _page(limit, offset)
    return list(
        session.scalars(
            _observation_statement()
            .where(models.DataObservation.series_id == series_id)
            .order_by(
                models.DataObservation.observed_at,
                models.DataObservation.id,
            )
            .limit(limit)
            .offset(offset)
        ).unique()
    )


def latest_observation(session: Session, series_id: int) -> models.DataObservation:
    get_series(session, series_id)
    observation = session.scalar(
        _observation_statement()
        .where(models.DataObservation.series_id == series_id)
        .order_by(
            models.DataObservation.observed_at.desc(),
            models.DataObservation.id.desc(),
        )
        .limit(1)
    )
    if observation is None:
        raise DataNotFoundError("No observations found for data series")
    return observation


def observations_as_of(
    session: Session,
    series_id: int,
    *,
    as_of: datetime,
    limit: int,
    offset: int,
) -> list[models.DataObservation]:
    get_series(session, series_id)
    limit, offset = _page(limit, offset)
    return list(
        session.scalars(
            _observation_statement()
            .where(
                models.DataObservation.series_id == series_id,
                models.DataObservation.ingestion_timestamp <= as_of,
            )
            .order_by(
                models.DataObservation.observed_at,
                models.DataObservation.id,
            )
            .limit(limit)
            .offset(offset)
        ).unique()
    )


def list_revisions(
    session: Session, series_id: int, observation_id: int
) -> list[models.DataRevision]:
    get_series(session, series_id)
    observation = session.get(models.DataObservation, observation_id)
    if observation is None or observation.series_id != series_id:
        raise DataNotFoundError("Data observation not found")
    return list(
        session.scalars(
            select(models.DataRevision)
            .where(models.DataRevision.observation_id == observation_id)
            .order_by(models.DataRevision.sequence)
        )
    )


def create_import(session: Session, payload: schemas.DataImportCreate) -> models.DataImportBatch:
    fingerprint = hashlib.sha256(
        json.dumps(
            payload.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    existing = session.scalar(
        select(models.DataImportBatch)
        .options(selectinload(models.DataImportBatch.errors))
        .where(models.DataImportBatch.idempotency_key == payload.idempotency_key)
    )
    if existing is not None:
        if existing.request_fingerprint != fingerprint:
            raise DataConflictError(
                "Idempotency key was already used with a different import payload"
            )
        if existing.status == models.ImportStatus.failed:
            raise DataConflictError(
                f"Import batch {existing.id} previously failed; inspect its audit record"
            )
        return existing
    source = get_source(session, payload.source_id)
    imported_at = _now()
    accepted = 0
    rejected = 0
    batch = models.DataImportBatch(
        source=source,
        idempotency_key=payload.idempotency_key,
        request_fingerprint=fingerprint,
        imported_at=imported_at,
        status=models.ImportStatus.processing,
        row_count=len(payload.rows),
        accepted_rows=0,
        rejected_rows=len(payload.rows),
        partial_mode=payload.partial_mode,
        notes=payload.notes,
    )
    session.add(batch)
    _commit(session)
    batch_id = batch.id
    accepted = 0
    rejected = 0
    for row_index, row in enumerate(payload.rows):
        series: models.DataSeries | None = None
        try:
            row_transaction = session.begin_nested() if payload.partial_mode else nullcontext()
            with row_transaction:
                series = session.scalar(
                    select(models.DataSeries).where(models.DataSeries.code == row.series_code)
                )
                if series is None or series.source_id != payload.source_id:
                    raise DataConflictError(
                        f"Series {row.series_code} is unavailable for this source"
                    )
                _write_observation(
                    session,
                    series,
                    schemas.ObservationWrite.model_validate(row.model_dump()),
                    import_batch_id=batch_id,
                    ingestion_timestamp=imported_at,
                )
                session.flush()
            accepted += 1
        except (DataConflictError, IntegrityError) as exc:
            rejected += 1
            error_code, safe_message = _safe_import_error(exc)
            if not payload.partial_mode:
                session.rollback()
                failed_batch = get_import(session, batch_id)
                failed_batch.status = models.ImportStatus.failed
                failed_batch.accepted_rows = 0
                failed_batch.rejected_rows = failed_batch.row_count
                failed_batch.failed_at = _now()
                failed_batch.failure_summary = safe_message
                session.add(
                    _import_error(
                        failed_batch,
                        row_index,
                        row,
                        error_code,
                        safe_message,
                    )
                )
                _commit(session)
                raise DataConflictError(
                    f"Import batch {batch_id} failed atomically; no observations were accepted"
                ) from None
            session.add(
                _import_error(
                    batch,
                    row_index,
                    row,
                    error_code,
                    safe_message,
                )
            )
            if series is not None:
                issue_type = (
                    models.QualityIssueType.duplicate_observation
                    if "already exists" in str(exc)
                    else models.QualityIssueType.impossible_timestamp
                )
                _add_issue(
                    session,
                    series_id=series.id,
                    issue_type=issue_type,
                    message=f"Import row rejected: {safe_message}",
                )
    batch.accepted_rows = accepted
    batch.rejected_rows = rejected
    batch.status = (
        models.ImportStatus.completed
        if rejected == 0
        else models.ImportStatus.completed_with_errors
    )
    _commit(session)
    session.refresh(batch)
    return batch


def _safe_import_error(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, IntegrityError):
        return "integrity_conflict", "Row conflicts with existing persisted data"
    message = str(exc)
    if "unavailable for this source" in message:
        return "series_unavailable", "Series is unavailable for the selected source"
    if "already exists" in message:
        return "duplicate_observation", "Observation already exists without a revision reason"
    if "future" in message:
        return "impossible_timestamp", "Publication timestamp cannot be in the future"
    return "domain_conflict", "Row violates a macro data domain rule"


def _import_error(
    batch: models.DataImportBatch,
    row_index: int,
    row: schemas.ImportRow,
    error_code: str,
    message: str,
) -> models.DataImportError:
    maximum = min(get_settings().max_import_error_message_length, 500)
    return models.DataImportError(
        import_batch=batch,
        row_index=row_index,
        error_code=error_code,
        message=message[:maximum],
        source_context={
            "series_code": row.series_code,
            "observed_at": row.observed_at.isoformat(),
        },
    )


def list_imports(session: Session, *, limit: int, offset: int) -> list[models.DataImportBatch]:
    limit, offset = _page(limit, offset)
    return list(
        session.scalars(
            select(models.DataImportBatch)
            .options(selectinload(models.DataImportBatch.errors))
            .order_by(models.DataImportBatch.id)
            .limit(limit)
            .offset(offset)
        )
    )


def get_import(session: Session, import_id: int) -> models.DataImportBatch:
    batch = session.scalar(
        select(models.DataImportBatch)
        .options(selectinload(models.DataImportBatch.errors))
        .where(models.DataImportBatch.id == import_id)
    )
    if batch is None:
        raise DataNotFoundError("Data import batch not found")
    return batch


def _detect_stale_series(session: Session) -> None:
    now = _now()
    candidates = session.scalars(
        select(models.DataSeries).where(
            models.DataSeries.is_active.is_(True),
            models.DataSeries.stale_after_days.is_not(None),
        )
    )
    for series in candidates:
        latest = session.scalar(
            select(func.max(models.DataObservation.observed_at)).where(
                models.DataObservation.series_id == series.id
            )
        )
        stale = latest is None or (now.date() - latest.date()).days > (series.stale_after_days or 0)
        if stale:
            exists = session.scalar(
                select(models.DataQualityIssue.id).where(
                    models.DataQualityIssue.series_id == series.id,
                    models.DataQualityIssue.issue_type == models.QualityIssueType.stale_series,
                    models.DataQualityIssue.status != models.QualityIssueStatus.resolved,
                )
            )
            if exists is None:
                _add_issue(
                    session,
                    series_id=series.id,
                    issue_type=models.QualityIssueType.stale_series,
                    message="Series has exceeded its configured staleness threshold",
                )
    _commit(session)


def list_quality_issues(
    session: Session, *, limit: int, offset: int
) -> list[models.DataQualityIssue]:
    _detect_stale_series(session)
    limit, offset = _page(limit, offset)
    return list(
        session.scalars(
            select(models.DataQualityIssue)
            .order_by(models.DataQualityIssue.id)
            .limit(limit)
            .offset(offset)
        )
    )


def get_quality_issue(session: Session, issue_id: int) -> models.DataQualityIssue:
    issue = session.get(models.DataQualityIssue, issue_id)
    if issue is None:
        raise DataNotFoundError("Data quality issue not found")
    return issue


def update_quality_issue(
    session: Session,
    issue_id: int,
    payload: schemas.QualityIssueAction,
    *,
    target: models.QualityIssueStatus,
) -> models.DataQualityIssue:
    issue = get_quality_issue(session, issue_id)
    if issue.lock_version != payload.expected_lock_version:
        raise DataConflictError("Data quality issue was changed; reload and retry")
    now = _now()
    if target == models.QualityIssueStatus.acknowledged:
        if issue.status != models.QualityIssueStatus.open:
            raise DataConflictError("Only open issues can be acknowledged")
        issue.acknowledged_at = now
    else:
        if issue.status == models.QualityIssueStatus.resolved:
            raise DataConflictError("Data quality issue is already resolved")
        issue.resolved_at = now
        issue.resolution_notes = payload.notes
    issue.status = target
    issue.lock_version += 1
    _commit(session)
    session.refresh(issue)
    return issue


def quality_issue_to_read(
    issue: models.DataQualityIssue,
) -> schemas.QualityIssueRead:
    return schemas.QualityIssueRead(
        id=issue.id,
        series_id=issue.series_id,
        observation_id=issue.observation_id,
        issue_type=issue.issue_type,
        status=issue.status,
        message=issue.message,
        details=issue.details,
        detected_at=issue.detected_at,
        acknowledged_at=issue.acknowledged_at,
        resolved_at=issue.resolved_at,
        resolution_notes=issue.resolution_notes,
        lock_version=issue.lock_version,
    )
