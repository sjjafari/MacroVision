"""Deterministic, vintage-aware execution for persisted Macro Analytics."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator
from sqlalchemy import Select, func, select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session, joinedload

from macrovision.analytics_models import (
    AnalyticsRun,
    DerivedObservation,
    DerivedObservationLineage,
    DerivedSeriesDefinition,
    DerivedSeriesDefinitionVersion,
    DerivedSeriesInput,
)
from macrovision.analytics_schemas import InputMetadata, OutputMetadata, TransformationParameters
from macrovision.analytics_transformations import (
    AnalyticsContractError,
    InputState,
    PointValue,
    canonical_json,
    canonical_parameters,
    evaluate_transformation,
    get_transformation_spec,
    parameters_fingerprint,
    required_timestamps,
)
from macrovision.contracts import utc_timestamp
from macrovision.macro_data_models import (
    DataFrequency,
    DataObservation,
    DataRevision,
    ObservationStatus,
    SeasonalAdjustment,
)
from macrovision.persistence_types import UTCDateTime

ANALYTICS_ENGINE_VERSION: Final = "0.7-phase-2b.1"
MAX_INPUTS: Final = 2
MAX_CANDIDATE_OUTPUTS: Final = 10_000
MAX_SOURCE_REQUIREMENTS: Final = 25_000
MAX_LINEAGE_LINKS: Final = 100_000
QUERY_BATCH_SIZE: Final = 400


class AnalyticsServiceError(RuntimeError):
    """A bounded, public-safe analytics service error."""

    code = "analytics_error"


class AnalyticsNotFoundError(AnalyticsServiceError):
    code = "analytics_not_found"


class AnalyticsConflictError(AnalyticsServiceError):
    code = "analytics_conflict"


class AnalyticsValidationError(AnalyticsServiceError):
    code = "analytics_validation"


class AnalyticsResourceLimitError(AnalyticsServiceError):
    code = "analytics_resource_limit"


class AnalyticsSnapshotError(AnalyticsServiceError):
    code = "analytics_snapshot"


class AnalyticsExecutionError(AnalyticsServiceError):
    code = "analytics_execution"


class AnalyticsExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    definition_id: int = Field(gt=0)
    definition_version: int | None = Field(default=None, gt=0)
    requested_start_at: datetime
    requested_end_at: datetime
    as_of: datetime | None = None
    retry_of_run_id: int | None = Field(default=None, gt=0)

    @field_validator("requested_start_at", "requested_end_at", "as_of")
    @classmethod
    def normalize_timestamp(cls, value: datetime | None) -> datetime | None:
        return utc_timestamp(value) if value is not None else None

    @model_validator(mode="after")
    def validate_range(self) -> AnalyticsExecutionRequest:
        if self.requested_start_at > self.requested_end_at:
            raise ValueError("requested_start_at must not exceed requested_end_at")
        return self


@dataclass(frozen=True)
class ResolvedSourcePoint:
    input_position: int
    lineage_position: int
    required_at: datetime
    point: PointValue
    observation_id: int | None
    revision_id: int | None
    source_version_kind: str | None
    source_version_id: int | None
    knowledge_timestamp: datetime | None

    def fingerprint_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "input_position": self.input_position,
            "lineage_position": self.lineage_position,
            "required_at": self.required_at,
            "state": self.point.state.value,
        }
        if self.observation_id is None:
            payload["absent"] = True
            return payload
        payload.update(
            {
                "observation_id": self.observation_id,
                "revision_id": self.revision_id,
                "source_version_kind": self.source_version_kind,
                "source_version_id": self.source_version_id,
                "knowledge_timestamp": self.knowledge_timestamp,
                "value": self.point.value,
            }
        )
        return payload


@dataclass(frozen=True)
class ResolvedOutputPoint:
    observed_at: datetime
    inputs: tuple[tuple[ResolvedSourcePoint, ...], ...]


@dataclass(frozen=True)
class PreparedDefinition:
    definition: DerivedSeriesDefinition
    version: DerivedSeriesDefinitionVersion
    inputs: tuple[DerivedSeriesInput, ...]
    parameters: TransformationParameters
    frequency: DataFrequency


@dataclass(frozen=True)
class AnalyticsExecutionOutcome:
    run: AnalyticsRun
    disposition: str


_PARAMETERS_ADAPTER: TypeAdapter[TransformationParameters] = TypeAdapter(TransformationParameters)


def _safe_error(exc: BaseException) -> tuple[str, str]:
    if isinstance(exc, AnalyticsResourceLimitError):
        return exc.code, "Analytics execution exceeded a configured resource limit"
    if isinstance(exc, AnalyticsSnapshotError):
        return exc.code, "The source snapshot could not be resolved safely"
    if isinstance(exc, AnalyticsValidationError | AnalyticsContractError):
        return "analytics_contract", "The analytics definition or request is invalid"
    if isinstance(exc, AnalyticsConflictError):
        return exc.code, "The analytics request conflicts with another operation"
    if isinstance(exc, DBAPIError):
        return "database_conflict", "The analytics transaction could not be completed"
    return AnalyticsExecutionError.code, "Analytics execution failed"


def _digest(payload: object) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _database_timestamp(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _begin_snapshot(session: Session) -> str:
    if session.in_transaction():
        raise AnalyticsConflictError("Analytics execution requires a fresh session")
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
    elif dialect == "sqlite":
        session.connection().exec_driver_sql("BEGIN IMMEDIATE")
    else:
        raise AnalyticsSnapshotError("Unsupported analytics database")
    return dialect


def _snapshot_clock(dialect: str) -> Any:
    if dialect == "postgresql":
        return func.statement_timestamp(type_=UTCDateTime())
    if dialect == "sqlite":
        return func.macrovision_utc_now(type_=UTCDateTime())
    raise AnalyticsSnapshotError("Unsupported analytics database")


def _definition_statement(
    request: AnalyticsExecutionRequest, dialect: str
) -> Select[tuple[Any, ...]]:
    statement = (
        select(
            DerivedSeriesDefinition,
            DerivedSeriesDefinitionVersion,
            _snapshot_clock(dialect),
        )
        .join(
            DerivedSeriesDefinitionVersion,
            DerivedSeriesDefinitionVersion.definition_id == DerivedSeriesDefinition.id,
        )
        .where(DerivedSeriesDefinition.id == request.definition_id)
        .order_by(
            DerivedSeriesDefinitionVersion.version.desc(),
            DerivedSeriesDefinitionVersion.id.desc(),
        )
        .limit(1)
    )
    if request.definition_version is not None:
        statement = statement.where(
            DerivedSeriesDefinitionVersion.version == request.definition_version
        )
    return statement


def _load_definition(
    session: Session, request: AnalyticsExecutionRequest, dialect: str
) -> tuple[PreparedDefinition, datetime]:
    row = session.execute(_definition_statement(request, dialect)).one_or_none()
    if row is None:
        if session.get(DerivedSeriesDefinition, request.definition_id) is None:
            raise AnalyticsNotFoundError("Analytics definition was not found")
        raise AnalyticsNotFoundError("Requested analytics definition version was not found")
    definition, version, database_now = row
    if not definition.enabled:
        raise AnalyticsValidationError("Analytics definition is disabled")
    inputs = tuple(
        session.scalars(
            select(DerivedSeriesInput)
            .where(DerivedSeriesInput.definition_version_id == version.id)
            .order_by(DerivedSeriesInput.position, DerivedSeriesInput.id)
        )
    )
    if not inputs or len(inputs) > MAX_INPUTS:
        raise AnalyticsValidationError("Analytics input count is invalid")
    if tuple(item.position for item in inputs) != tuple(range(len(inputs))):
        raise AnalyticsValidationError("Analytics input positions are invalid")
    try:
        parameters = _PARAMETERS_ADAPTER.validate_python(version.parameters)
        spec = get_transformation_spec(parameters.transformation_type)
        if tuple(item.alias for item in inputs) != spec.ordered_aliases:
            raise AnalyticsContractError("Analytics input aliases are invalid")
        if parameters_fingerprint(parameters) != version.parameters_fingerprint:
            raise AnalyticsContractError("Analytics parameters are inconsistent")
        metadata = [
            InputMetadata(
                unit=item.source_unit_snapshot,
                frequency=DataFrequency(item.source_frequency_snapshot),
                geography=item.source_geography_snapshot,
                currency=item.source_currency_snapshot,
                seasonal_adjustment=SeasonalAdjustment(item.source_seasonal_adjustment_snapshot),
            )
            for item in inputs
        ]
        output = spec.validate_metadata(metadata)
    except (ValueError, AnalyticsContractError) as exc:
        raise AnalyticsValidationError("Analytics definition is structurally invalid") from exc
    stored_output = OutputMetadata(
        unit=version.output_unit,
        frequency=DataFrequency(version.output_frequency),
        geography=version.output_geography,
        currency=version.output_currency,
        seasonal_adjustment=SeasonalAdjustment(version.output_seasonal_adjustment),
    )
    if output != stored_output:
        raise AnalyticsValidationError("Analytics output metadata is inconsistent")
    return (
        PreparedDefinition(definition, version, inputs, parameters, output.frequency),
        _database_timestamp(database_now),
    )


def _validate_retry(
    session: Session,
    request: AnalyticsExecutionRequest,
    prepared: PreparedDefinition,
) -> AnalyticsRun | None:
    if request.retry_of_run_id is None:
        return None
    retry = session.get(AnalyticsRun, request.retry_of_run_id)
    if retry is None:
        raise AnalyticsNotFoundError("Retry target was not found")
    if retry.status != "failed":
        raise AnalyticsConflictError("Only failed analytics runs can be retried")
    if (
        retry.definition_version_id != prepared.version.id
        or retry.requested_start_at != request.requested_start_at
        or retry.requested_end_at != request.requested_end_at
    ):
        raise AnalyticsValidationError("Retry target is incompatible with this request")
    return retry


def _request_payload(
    prepared: PreparedDefinition,
    request: AnalyticsExecutionRequest,
    cutoff: datetime,
) -> dict[str, object]:
    return {
        "definition_version_id": prepared.version.id,
        "definition_version": prepared.version.version,
        "requested_start_at": request.requested_start_at,
        "requested_end_at": request.requested_end_at,
        "calculation_cutoff": cutoff,
        "engine_contract_version": prepared.version.engine_contract_version,
        "engine_version": ANALYTICS_ENGINE_VERSION,
    }


def _candidate_timestamps(
    session: Session,
    prepared: PreparedDefinition,
    request: AnalyticsExecutionRequest,
    cutoff: datetime,
) -> tuple[datetime, ...]:
    rows = tuple(
        session.execute(
            select(DataObservation.observed_at, DataObservation.id)
            .where(
                DataObservation.series_id == prepared.inputs[0].source_series_id,
                DataObservation.ingestion_timestamp <= cutoff,
                DataObservation.observed_at >= request.requested_start_at,
                DataObservation.observed_at <= request.requested_end_at,
            )
            .order_by(DataObservation.observed_at, DataObservation.id)
            .limit(MAX_CANDIDATE_OUTPUTS + 1)
        )
    )
    if len(rows) > MAX_CANDIDATE_OUTPUTS:
        raise AnalyticsResourceLimitError("Too many candidate outputs")
    return tuple(_database_timestamp(item.observed_at) for item in rows)


def _chunks(items: list[Any], size: int = QUERY_BATCH_SIZE) -> list[list[Any]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def _latest_eligible_revisions(
    session: Session, observation_ids: list[int], cutoff: datetime
) -> tuple[DataRevision, ...]:
    selected: list[DataRevision] = []
    for batch in _chunks(observation_ids):
        ranked = (
            select(
                DataRevision.id.label("revision_id"),
                func.row_number()
                .over(
                    partition_by=DataRevision.observation_id,
                    order_by=(DataRevision.sequence.desc(), DataRevision.id.desc()),
                )
                .label("revision_rank"),
            )
            .where(
                DataRevision.observation_id.in_(batch),
                DataRevision.revision_timestamp <= cutoff,
            )
            .subquery()
        )
        selected.extend(
            session.scalars(
                select(DataRevision)
                .join(ranked, ranked.c.revision_id == DataRevision.id)
                .where(ranked.c.revision_rank == 1)
                .order_by(DataRevision.observation_id, DataRevision.id)
            )
        )
    return tuple(selected)


def _resolve_snapshot(
    session: Session,
    prepared: PreparedDefinition,
    candidates: tuple[datetime, ...],
    cutoff: datetime,
) -> tuple[ResolvedOutputPoint, ...]:
    spec = get_transformation_spec(prepared.parameters.transformation_type)
    requirements: list[tuple[int, int, datetime, datetime]] = []
    timestamps_by_series: dict[int, set[datetime]] = defaultdict(set)
    for output_at in candidates:
        required = required_timestamps(spec, output_at, prepared.frequency, prepared.parameters)
        if required is None:
            continue
        for item in prepared.inputs:
            for role, required_at in enumerate(required):
                requirements.append((item.position, role, output_at, required_at))
                timestamps_by_series[item.source_series_id].add(required_at)
                if len(requirements) > MAX_SOURCE_REQUIREMENTS:
                    raise AnalyticsResourceLimitError("Too many source requirements")

    observations: dict[tuple[int, datetime], DataObservation] = {}
    for series_id, timestamps in timestamps_by_series.items():
        ordered = sorted(timestamps)
        for batch in _chunks(ordered):
            for observation in session.scalars(
                select(DataObservation)
                .where(
                    DataObservation.series_id == series_id,
                    DataObservation.observed_at.in_(batch),
                    DataObservation.ingestion_timestamp <= cutoff,
                )
                .order_by(DataObservation.observed_at, DataObservation.id)
            ):
                observations[(series_id, _database_timestamp(observation.observed_at))] = (
                    observation
                )

    revisions: dict[int, DataRevision] = {}
    observation_ids = sorted(item.id for item in observations.values())
    for revision in _latest_eligible_revisions(session, observation_ids, cutoff):
        revisions[revision.observation_id] = revision

    resolved: list[ResolvedOutputPoint] = []
    for output_at in candidates:
        required = required_timestamps(spec, output_at, prepared.frequency, prepared.parameters)
        input_windows: list[tuple[ResolvedSourcePoint, ...]] = []
        for item in prepared.inputs:
            window: list[ResolvedSourcePoint] = []
            if required is not None:
                for role, required_at in enumerate(required):
                    selected_observation = observations.get((item.source_series_id, required_at))
                    if selected_observation is None:
                        window.append(
                            ResolvedSourcePoint(
                                item.position,
                                role,
                                required_at,
                                PointValue(InputState.absent),
                                None,
                                None,
                                None,
                                None,
                                None,
                            )
                        )
                        continue
                    selected_revision = revisions.get(selected_observation.id)
                    status = (
                        selected_revision.revised_status
                        if selected_revision
                        else selected_observation.status
                    )
                    value = (
                        selected_revision.revised_value
                        if selected_revision
                        else selected_observation.value
                    )
                    point = (
                        PointValue(InputState.present, value)
                        if status is ObservationStatus.present
                        else PointValue(InputState.missing)
                    )
                    window.append(
                        ResolvedSourcePoint(
                            item.position,
                            role,
                            required_at,
                            point,
                            selected_observation.id,
                            selected_revision.id if selected_revision else None,
                            "revision" if selected_revision else "original",
                            selected_revision.id if selected_revision else selected_observation.id,
                            _database_timestamp(
                                selected_revision.revision_timestamp
                                if selected_revision
                                else selected_observation.ingestion_timestamp
                            ),
                        )
                    )
            input_windows.append(tuple(window))
        resolved.append(ResolvedOutputPoint(output_at, tuple(input_windows)))
    return tuple(resolved)


def _snapshot_payload(
    prepared: PreparedDefinition,
    request: AnalyticsExecutionRequest,
    cutoff: datetime,
    points: tuple[ResolvedOutputPoint, ...],
    *,
    include_cutoff: bool,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "definition_id": prepared.definition.id,
        "definition_version_id": prepared.version.id,
        "definition_version": prepared.version.version,
        "parameters_fingerprint": prepared.version.parameters_fingerprint,
        "parameters": canonical_parameters(prepared.parameters),
        "inputs": [
            {
                "position": item.position,
                "alias": item.alias,
                "source_series_id": item.source_series_id,
                "source_code": item.source_code_snapshot,
                "source_unit": item.source_unit_snapshot,
                "source_frequency": item.source_frequency_snapshot,
                "source_geography": item.source_geography_snapshot,
                "source_currency": item.source_currency_snapshot,
                "source_seasonal_adjustment": item.source_seasonal_adjustment_snapshot,
            }
            for item in prepared.inputs
        ],
        "requested_start_at": request.requested_start_at,
        "requested_end_at": request.requested_end_at,
        "engine_version": ANALYTICS_ENGINE_VERSION,
        "outputs": [
            {
                "observed_at": point.observed_at,
                "sources": [
                    source.fingerprint_payload() for window in point.inputs for source in window
                ],
            }
            for point in points
        ],
    }
    if include_cutoff:
        payload["calculation_cutoff"] = cutoff
    return payload


def _persist_outputs(
    session: Session,
    run: AnalyticsRun,
    prepared: PreparedDefinition,
    points: tuple[ResolvedOutputPoint, ...],
) -> tuple[int, int, int]:
    present = missing = lineage_count = 0
    for resolved in points:
        result = evaluate_transformation(
            prepared.parameters,
            tuple(tuple(source.point for source in window) for window in resolved.inputs),
        )
        output = DerivedObservation(
            run=run,
            definition_version=prepared.version,
            observed_at=resolved.observed_at,
            value=result.value,
            status="present" if result.is_present else "missing",
            missing_reason=result.missing_reason.value if result.missing_reason else None,
        )
        session.add(output)
        session.flush()
        present += int(result.is_present)
        missing += int(not result.is_present)
        for window in resolved.inputs:
            for source in window:
                if source.observation_id is None:
                    continue
                session.add(
                    DerivedObservationLineage(
                        derived_observation=output,
                        input_position=source.input_position,
                        source_observation_id=source.observation_id,
                        source_revision_id=source.revision_id,
                        source_version_kind=source.source_version_kind,
                        source_version_id=source.source_version_id,
                        lineage_position=source.lineage_position,
                        source_knowledge_timestamp=source.knowledge_timestamp,
                    )
                )
                lineage_count += 1
                if lineage_count > MAX_LINEAGE_LINKS:
                    raise AnalyticsResourceLimitError("Too many lineage links")
    return present, missing, lineage_count


def _persist_failed_run(
    session: Session,
    *,
    prepared: PreparedDefinition,
    request: AnalyticsExecutionRequest,
    cutoff: datetime,
    request_fingerprint: str,
    started_at: datetime,
    snapshot_fingerprint: str | None,
    exc: BaseException,
) -> None:
    code, message = _safe_error(exc)
    failed = AnalyticsRun(
        definition_version_id=prepared.version.id,
        status="failed",
        requested_start_at=request.requested_start_at,
        requested_end_at=request.requested_end_at,
        calculation_cutoff=cutoff,
        engine_version=ANALYTICS_ENGINE_VERSION,
        request_fingerprint=request_fingerprint,
        snapshot_fingerprint=snapshot_fingerprint,
        reusable_fingerprint=None,
        inputs_examined=0,
        outputs_present=0,
        outputs_missing=0,
        lineage_links=0,
        started_at=started_at,
        completed_at=max(datetime.now(UTC), started_at),
        error_code=code[:64],
        error_message=message[:500],
        retry_of_run_id=request.retry_of_run_id,
    )
    session.add(failed)
    session.commit()


def execute_analytics_run_outcome(
    session: Session,
    request: AnalyticsExecutionRequest,
) -> AnalyticsExecutionOutcome:
    """Resolve one database snapshot, execute, and atomically persist its output graph."""

    prepared: PreparedDefinition | None = None
    cutoff: datetime | None = None
    request_fingerprint: str | None = None
    snapshot_fingerprint: str | None = None
    started_at: datetime | None = None
    try:
        dialect = _begin_snapshot(session)
        prepared, database_now = _load_definition(session, request, dialect)
        cutoff = request.as_of or database_now
        if cutoff > database_now:
            raise AnalyticsValidationError("as_of cannot be in the future")
        _validate_retry(session, request, prepared)
        request_fingerprint = _digest(_request_payload(prepared, request, cutoff))
        active = session.scalar(
            select(AnalyticsRun)
            .where(
                AnalyticsRun.request_fingerprint == request_fingerprint,
                AnalyticsRun.status.in_(("pending", "running")),
            )
            .order_by(AnalyticsRun.id)
        )
        if active is not None:
            session.rollback()
            return AnalyticsExecutionOutcome(active, "active_existing")
        started_at = datetime.now(UTC)
        run = AnalyticsRun(
            definition_version=prepared.version,
            status="pending",
            requested_start_at=request.requested_start_at,
            requested_end_at=request.requested_end_at,
            calculation_cutoff=cutoff,
            engine_version=ANALYTICS_ENGINE_VERSION,
            request_fingerprint=request_fingerprint,
            inputs_examined=0,
            outputs_present=0,
            outputs_missing=0,
            lineage_links=0,
            retry_of_run_id=request.retry_of_run_id,
        )
        session.add(run)
        session.flush()
        run.status = "running"
        run.started_at = started_at
        session.flush()
        candidates = _candidate_timestamps(session, prepared, request, cutoff)
        resolved = _resolve_snapshot(session, prepared, candidates, cutoff)
        inputs_examined = sum(len(window) for point in resolved for window in point.inputs)
        snapshot_fingerprint = _digest(
            _snapshot_payload(prepared, request, cutoff, resolved, include_cutoff=True)
        )
        reusable_fingerprint = _digest(
            _snapshot_payload(prepared, request, cutoff, resolved, include_cutoff=False)
        )
        reusable = session.scalar(
            select(AnalyticsRun)
            .options(joinedload(AnalyticsRun.observations))
            .where(
                AnalyticsRun.reusable_fingerprint == reusable_fingerprint,
                AnalyticsRun.status == "succeeded",
            )
            .order_by(AnalyticsRun.id)
        )
        if reusable is not None:
            reusable_id = reusable.id
            session.rollback()
            winner = session.get(AnalyticsRun, reusable_id)
            assert winner is not None
            return AnalyticsExecutionOutcome(winner, "completed_existing")
        present, missing, lineage_count = _persist_outputs(session, run, prepared, resolved)
        completed_at = max(datetime.now(UTC), started_at)
        run.inputs_examined = inputs_examined
        run.outputs_present = present
        run.outputs_missing = missing
        run.lineage_links = lineage_count
        run.snapshot_fingerprint = snapshot_fingerprint
        run.reusable_fingerprint = reusable_fingerprint
        run.status = "succeeded"
        run.completed_at = completed_at
        run.error_code = None
        run.error_message = None
        session.commit()
        return AnalyticsExecutionOutcome(run, "created")
    except (KeyboardInterrupt, SystemExit, GeneratorExit):
        session.rollback()
        raise
    except IntegrityError as exc:
        session.rollback()
        if request_fingerprint is not None:
            active = session.scalar(
                select(AnalyticsRun)
                .where(
                    AnalyticsRun.request_fingerprint == request_fingerprint,
                    AnalyticsRun.status.in_(("pending", "running")),
                )
                .order_by(AnalyticsRun.id)
            )
            if active is not None:
                return AnalyticsExecutionOutcome(active, "active_existing")
        if prepared is not None and cutoff is not None and "resolved" in locals():
            semantic = _digest(
                _snapshot_payload(
                    prepared,
                    request,
                    cutoff,
                    resolved,
                    include_cutoff=False,
                )
            )
            winner = session.scalar(
                select(AnalyticsRun).where(
                    AnalyticsRun.reusable_fingerprint == semantic,
                    AnalyticsRun.status == "succeeded",
                )
            )
            if winner is not None:
                return AnalyticsExecutionOutcome(winner, "completed_existing")
        raise AnalyticsConflictError("Concurrent analytics execution conflict") from exc
    except Exception as exc:
        session.rollback()
        if (
            prepared is not None
            and cutoff is not None
            and request_fingerprint is not None
            and started_at is not None
        ):
            _persist_failed_run(
                session,
                prepared=prepared,
                request=request,
                cutoff=cutoff,
                request_fingerprint=request_fingerprint,
                started_at=started_at,
                snapshot_fingerprint=snapshot_fingerprint,
                exc=exc,
            )
        if isinstance(exc, AnalyticsServiceError):
            raise
        raise AnalyticsExecutionError("Analytics execution failed") from exc


def execute_analytics_run(
    session: Session,
    request: AnalyticsExecutionRequest,
) -> AnalyticsRun:
    """Preserve the Phase 2B internal API while exposing safe HTTP disposition data."""

    return execute_analytics_run_outcome(session, request).run
