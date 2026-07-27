"""Management and read services for the public Macro Analytics API."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import Select, and_, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from macrovision import analytics_api_schemas as schemas
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
    OutputMetadata,
    TransformationParameters,
)
from macrovision.analytics_transformations import (
    AnalyticsContractError,
    get_transformation_spec,
    parameters_fingerprint,
)
from macrovision.contracts import utc_timestamp
from macrovision.macro_data_models import DataSeries

ENGINE_CONTRACT_VERSION: Final = "phase-2b"
_PARAMETERS: TypeAdapter[TransformationParameters] = TypeAdapter(TransformationParameters)


class AnalyticsManagementError(RuntimeError):
    """Base class for bounded public management errors."""


class AnalyticsNotFoundError(AnalyticsManagementError):
    pass


class AnalyticsConflictError(AnalyticsManagementError):
    pass


class AnalyticsValidationError(AnalyticsManagementError):
    pass


@dataclass(frozen=True)
class VersionComponents:
    parameters: TransformationParameters
    sources: tuple[DataSeries, ...]
    output: OutputMetadata


def _commit(session: Session, message: str) -> None:
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise AnalyticsConflictError(message) from exc


def _version_summary(
    version: DerivedSeriesDefinitionVersion,
) -> schemas.DerivedSeriesVersionSummary:
    return schemas.DerivedSeriesVersionSummary(
        id=version.id,
        version=version.version,
        transformation_type=version.transformation_type,
        created_at=version.created_at,
        change_note=version.change_note,
    )


def _parse_parameters(value: object) -> TransformationParameters:
    try:
        return _PARAMETERS.validate_python(value)
    except ValidationError as exc:
        raise AnalyticsValidationError("Analytics transformation parameters are invalid") from exc


def _input_read(item: DerivedSeriesInput) -> schemas.DerivedSeriesInputRead:
    return schemas.DerivedSeriesInputRead(
        position=item.position,
        alias=item.alias,
        source_series_id=item.source_series_id,
        source_code=item.source_code_snapshot,
        source_unit=item.source_unit_snapshot,
        source_frequency=item.source_frequency_snapshot,
        source_geography=item.source_geography_snapshot,
        source_currency=item.source_currency_snapshot,
        source_seasonal_adjustment=item.source_seasonal_adjustment_snapshot,
        created_at=item.created_at,
    )


def version_to_read(
    version: DerivedSeriesDefinitionVersion,
) -> schemas.DerivedSeriesVersionRead:
    parameters = _parse_parameters(version.parameters)
    return schemas.DerivedSeriesVersionRead(
        **_version_summary(version).model_dump(),
        parameters=parameters,
        inputs=[_input_read(item) for item in version.inputs],
        output_unit=version.output_unit,
        output_frequency=version.output_frequency,
        output_geography=version.output_geography,
        output_currency=version.output_currency,
        output_seasonal_adjustment=version.output_seasonal_adjustment,
        engine_contract_version=version.engine_contract_version,
    )


def definition_to_read(
    definition: DerivedSeriesDefinition,
    current_version: DerivedSeriesDefinitionVersion,
) -> schemas.DerivedSeriesRead:
    return schemas.DerivedSeriesRead(
        id=definition.id,
        code=definition.code,
        title=definition.title,
        description=definition.description,
        enabled=definition.enabled,
        lock_version=definition.lock_version,
        current_version=_version_summary(current_version),
        created_at=definition.created_at,
        updated_at=definition.updated_at,
    )


def _prepare_version(
    session: Session,
    payload: schemas.DerivedSeriesVersionCreateBase | schemas.DerivedSeriesVersionCreate,
) -> VersionComponents:
    source_ids = [item.source_series_id for item in payload.inputs]
    if len(set(source_ids)) != len(source_ids):
        raise AnalyticsValidationError("Analytics source inputs must be distinct")
    sources_by_id = {
        item.id: item
        for item in session.scalars(select(DataSeries).where(DataSeries.id.in_(source_ids)))
    }
    if len(sources_by_id) != len(source_ids):
        raise AnalyticsNotFoundError("Analytics source data series was not found")
    sources = tuple(sources_by_id[source_id] for source_id in source_ids)
    if any(not source.is_active for source in sources):
        raise AnalyticsValidationError("New analytics versions require active source series")
    try:
        spec = get_transformation_spec(payload.parameters.transformation_type)
        output = spec.validate_metadata(
            [
                InputMetadata(
                    unit=source.unit,
                    frequency=source.frequency,
                    geography=source.geography,
                    currency=source.currency,
                    seasonal_adjustment=source.seasonal_adjustment,
                )
                for source in sources
            ]
        )
    except (ValueError, AnalyticsContractError) as exc:
        raise AnalyticsValidationError("Analytics input metadata is incompatible") from exc
    return VersionComponents(payload.parameters, sources, output)


def _new_version(
    definition: DerivedSeriesDefinition,
    *,
    version_number: int,
    payload: schemas.DerivedSeriesVersionCreateBase | schemas.DerivedSeriesVersionCreate,
    components: VersionComponents,
) -> DerivedSeriesDefinitionVersion:
    version = DerivedSeriesDefinitionVersion(
        definition=definition,
        version=version_number,
        transformation_type=components.parameters.transformation_type.value,
        parameters=components.parameters.model_dump(mode="json"),
        parameters_fingerprint=parameters_fingerprint(components.parameters),
        output_unit=components.output.unit,
        output_frequency=components.output.frequency.value,
        output_geography=components.output.geography,
        output_currency=components.output.currency,
        output_seasonal_adjustment=components.output.seasonal_adjustment.value,
        engine_contract_version=ENGINE_CONTRACT_VERSION,
        change_note=payload.change_note,
    )
    for position, (source_input, source) in enumerate(
        zip(payload.inputs, components.sources, strict=True)
    ):
        version.inputs.append(
            DerivedSeriesInput(
                position=position,
                alias=source_input.alias,
                source_series=source,
                source_code_snapshot=source.code,
                source_unit_snapshot=source.unit,
                source_frequency_snapshot=source.frequency.value,
                source_geography_snapshot=source.geography,
                source_currency_snapshot=source.currency,
                source_seasonal_adjustment_snapshot=source.seasonal_adjustment.value,
            )
        )
    return version


def create_definition(
    session: Session, payload: schemas.DerivedSeriesCreate
) -> schemas.DerivedSeriesRead:
    components = _prepare_version(session, payload.initial_version)
    definition = DerivedSeriesDefinition(
        code=payload.code,
        title=payload.title,
        description=payload.description,
        enabled=payload.enabled,
        lock_version=1,
    )
    version = _new_version(
        definition,
        version_number=1,
        payload=payload.initial_version,
        components=components,
    )
    session.add(definition)
    _commit(session, "A derived-series definition with this code already exists")
    session.refresh(definition)
    session.refresh(version)
    return definition_to_read(definition, version)


def _current_version_statement(
    definition_id: int,
) -> Select[tuple[DerivedSeriesDefinitionVersion]]:
    return (
        select(DerivedSeriesDefinitionVersion)
        .where(DerivedSeriesDefinitionVersion.definition_id == definition_id)
        .order_by(
            DerivedSeriesDefinitionVersion.version.desc(),
            DerivedSeriesDefinitionVersion.id.desc(),
        )
        .limit(1)
    )


def get_definition(
    session: Session, definition_id: int
) -> tuple[DerivedSeriesDefinition, DerivedSeriesDefinitionVersion]:
    definition = session.get(DerivedSeriesDefinition, definition_id)
    if definition is None:
        raise AnalyticsNotFoundError("Derived-series definition was not found")
    version = session.scalar(_current_version_statement(definition_id))
    if version is None:
        raise AnalyticsNotFoundError("Derived-series definition has no version")
    return definition, version


def get_definition_read(session: Session, definition_id: int) -> schemas.DerivedSeriesRead:
    definition, version = get_definition(session, definition_id)
    return definition_to_read(definition, version)


def list_definitions(
    session: Session,
    *,
    enabled: bool | None,
    code: str | None,
    code_prefix: str | None,
    limit: int,
    offset: int,
) -> schemas.DerivedSeriesPage:
    maximum_version = (
        select(
            DerivedSeriesDefinitionVersion.definition_id.label("definition_id"),
            func.max(DerivedSeriesDefinitionVersion.version).label("version"),
        )
        .group_by(DerivedSeriesDefinitionVersion.definition_id)
        .subquery()
    )
    statement = (
        select(DerivedSeriesDefinition, DerivedSeriesDefinitionVersion)
        .join(
            maximum_version,
            maximum_version.c.definition_id == DerivedSeriesDefinition.id,
        )
        .join(
            DerivedSeriesDefinitionVersion,
            and_(
                DerivedSeriesDefinitionVersion.definition_id == maximum_version.c.definition_id,
                DerivedSeriesDefinitionVersion.version == maximum_version.c.version,
            ),
        )
    )
    if enabled is not None:
        statement = statement.where(DerivedSeriesDefinition.enabled == enabled)
    if code is not None:
        statement = statement.where(DerivedSeriesDefinition.code == code)
    if code_prefix is not None:
        statement = statement.where(DerivedSeriesDefinition.code.startswith(code_prefix))
    rows = session.execute(
        statement.order_by(DerivedSeriesDefinition.code, DerivedSeriesDefinition.id)
        .limit(limit)
        .offset(offset)
    )
    return schemas.DerivedSeriesPage(
        items=[definition_to_read(definition, version) for definition, version in rows],
        limit=limit,
        offset=offset,
    )


def _conditional_definition_update(
    session: Session,
    definition_id: int,
    *,
    expected_lock_version: int,
    values: dict[str, object],
) -> tuple[DerivedSeriesDefinition, DerivedSeriesDefinitionVersion]:
    result = session.execute(
        update(DerivedSeriesDefinition)
        .where(
            DerivedSeriesDefinition.id == definition_id,
            DerivedSeriesDefinition.lock_version == expected_lock_version,
        )
        .values(
            **values,
            lock_version=DerivedSeriesDefinition.lock_version + 1,
            updated_at=func.now(),
        )
        .returning(DerivedSeriesDefinition.id)
    )
    if result.scalar_one_or_none() is None:
        session.rollback()
        if session.get(DerivedSeriesDefinition, definition_id) is None:
            raise AnalyticsNotFoundError("Derived-series definition was not found")
        raise AnalyticsConflictError("Derived-series definition was changed; reload and retry")
    _commit(session, "Derived-series definition update conflicted with another request")
    return get_definition(session, definition_id)


def patch_definition(
    session: Session, definition_id: int, payload: schemas.DerivedSeriesPatch
) -> schemas.DerivedSeriesRead:
    values = payload.model_dump(exclude={"expected_lock_version"}, exclude_unset=True)
    definition, version = _conditional_definition_update(
        session,
        definition_id,
        expected_lock_version=payload.expected_lock_version,
        values=values,
    )
    return definition_to_read(definition, version)


def set_definition_enabled(
    session: Session,
    definition_id: int,
    payload: schemas.DerivedSeriesStateChange,
    *,
    enabled: bool,
) -> schemas.DerivedSeriesRead:
    definition, version = _conditional_definition_update(
        session,
        definition_id,
        expected_lock_version=payload.expected_lock_version,
        values={"enabled": enabled},
    )
    return definition_to_read(definition, version)


def list_versions(
    session: Session, definition_id: int, *, limit: int, offset: int
) -> schemas.DerivedSeriesVersionPage:
    if session.get(DerivedSeriesDefinition, definition_id) is None:
        raise AnalyticsNotFoundError("Derived-series definition was not found")
    versions = list(
        session.scalars(
            select(DerivedSeriesDefinitionVersion)
            .where(DerivedSeriesDefinitionVersion.definition_id == definition_id)
            .order_by(
                DerivedSeriesDefinitionVersion.version.desc(),
                DerivedSeriesDefinitionVersion.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
    )
    return schemas.DerivedSeriesVersionPage(
        items=[_version_summary(version) for version in versions],
        limit=limit,
        offset=offset,
    )


def get_version(
    session: Session, definition_id: int, version_number: int
) -> DerivedSeriesDefinitionVersion:
    version = session.scalar(
        select(DerivedSeriesDefinitionVersion)
        .options(selectinload(DerivedSeriesDefinitionVersion.inputs))
        .where(
            DerivedSeriesDefinitionVersion.definition_id == definition_id,
            DerivedSeriesDefinitionVersion.version == version_number,
        )
    )
    if version is None:
        if session.get(DerivedSeriesDefinition, definition_id) is None:
            raise AnalyticsNotFoundError("Derived-series definition was not found")
        raise AnalyticsNotFoundError("Derived-series definition version was not found")
    return version


def create_version(
    session: Session,
    definition_id: int,
    payload: schemas.DerivedSeriesVersionCreate,
) -> schemas.DerivedSeriesVersionRead:
    components = _prepare_version(session, payload)
    result = session.execute(
        update(DerivedSeriesDefinition)
        .where(
            DerivedSeriesDefinition.id == definition_id,
            DerivedSeriesDefinition.lock_version == payload.expected_lock_version,
        )
        .values(
            lock_version=DerivedSeriesDefinition.lock_version + 1,
            updated_at=func.now(),
        )
        .returning(DerivedSeriesDefinition.id)
    )
    if result.scalar_one_or_none() is None:
        session.rollback()
        if session.get(DerivedSeriesDefinition, definition_id) is None:
            raise AnalyticsNotFoundError("Derived-series definition was not found")
        raise AnalyticsConflictError("Derived-series definition was changed; reload and retry")
    definition = session.get(DerivedSeriesDefinition, definition_id)
    assert definition is not None
    next_version = (
        session.scalar(
            select(func.max(DerivedSeriesDefinitionVersion.version)).where(
                DerivedSeriesDefinitionVersion.definition_id == definition_id
            )
        )
        or 0
    ) + 1
    version = _new_version(
        definition,
        version_number=next_version,
        payload=payload,
        components=components,
    )
    session.add(version)
    _commit(session, "Derived-series version creation conflicted with another request")
    return version_to_read(get_version(session, definition_id, next_version))


def run_to_read(
    run: AnalyticsRun,
    *,
    definition_id: int | None = None,
    version_number: int | None = None,
) -> schemas.AnalyticsRunRead:
    version = run.definition_version
    return schemas.AnalyticsRunRead(
        id=run.id,
        definition_id=definition_id if definition_id is not None else version.definition_id,
        definition_version_id=run.definition_version_id,
        definition_version=version_number if version_number is not None else version.version,
        status=run.status,
        requested_start_at=run.requested_start_at,
        requested_end_at=run.requested_end_at,
        calculation_cutoff=run.calculation_cutoff,
        engine_version=run.engine_version,
        inputs_examined=run.inputs_examined,
        outputs_present=run.outputs_present,
        outputs_missing=run.outputs_missing,
        lineage_links=run.lineage_links,
        created_at=run.created_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
        error_code=run.error_code,
        error_message=run.error_message,
        retry_of_run_id=run.retry_of_run_id,
    )


def _run_statement() -> Select[tuple[AnalyticsRun]]:
    return select(AnalyticsRun).options(selectinload(AnalyticsRun.definition_version))


def get_run(session: Session, run_id: int) -> AnalyticsRun:
    run = session.scalar(_run_statement().where(AnalyticsRun.id == run_id))
    if run is None:
        raise AnalyticsNotFoundError("Analytics run was not found")
    return run


def list_runs(
    session: Session,
    *,
    definition_id: int | None,
    definition_version: int | None,
    status: schemas.AnalyticsRunStatus | None,
    created_from: datetime | None,
    created_to: datetime | None,
    limit: int,
    offset: int,
) -> schemas.AnalyticsRunPage:
    statement = _run_statement().join(AnalyticsRun.definition_version)
    if definition_id is not None:
        statement = statement.where(DerivedSeriesDefinitionVersion.definition_id == definition_id)
    if definition_version is not None:
        statement = statement.where(DerivedSeriesDefinitionVersion.version == definition_version)
    if status is not None:
        statement = statement.where(AnalyticsRun.status == status.value)
    if created_from is not None:
        statement = statement.where(AnalyticsRun.created_at >= created_from)
    if created_to is not None:
        statement = statement.where(AnalyticsRun.created_at <= created_to)
    runs = session.scalars(
        statement.order_by(AnalyticsRun.created_at.desc(), AnalyticsRun.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return schemas.AnalyticsRunPage(
        items=[run_to_read(run) for run in runs],
        limit=limit,
        offset=offset,
    )


def observation_to_read(item: DerivedObservation) -> schemas.DerivedObservationRead:
    return schemas.DerivedObservationRead.model_validate(item)


def _observation_page(
    session: Session,
    run: AnalyticsRun,
    *,
    start: datetime | None,
    end: datetime | None,
    limit: int,
    offset: int,
) -> schemas.DerivedObservationPage:
    statement = select(DerivedObservation).where(DerivedObservation.run_id == run.id)
    if start is not None:
        statement = statement.where(DerivedObservation.observed_at >= start)
    if end is not None:
        statement = statement.where(DerivedObservation.observed_at <= end)
    items = session.scalars(
        statement.order_by(DerivedObservation.observed_at, DerivedObservation.id)
        .limit(limit)
        .offset(offset)
    )
    return schemas.DerivedObservationPage(
        run_id=run.id,
        definition_id=run.definition_version.definition_id,
        definition_version=run.definition_version.version,
        items=[observation_to_read(item) for item in items],
        limit=limit,
        offset=offset,
    )


def run_observations(
    session: Session,
    run_id: int,
    *,
    start: datetime | None,
    end: datetime | None,
    limit: int,
    offset: int,
) -> schemas.DerivedObservationPage:
    return _observation_page(
        session,
        get_run(session, run_id),
        start=start,
        end=end,
        limit=limit,
        offset=offset,
    )


def observation_lineage(
    session: Session,
    run_id: int,
    observation_id: int,
    *,
    limit: int,
    offset: int,
) -> schemas.DerivedObservationLineagePage:
    observation = session.scalar(
        select(DerivedObservation).where(
            DerivedObservation.id == observation_id,
            DerivedObservation.run_id == run_id,
        )
    )
    if observation is None:
        raise AnalyticsNotFoundError("Derived observation was not found for this run")
    rows = session.execute(
        select(DerivedObservationLineage, DerivedSeriesInput.alias)
        .join(
            DerivedSeriesInput,
            and_(
                DerivedSeriesInput.definition_version_id == observation.definition_version_id,
                DerivedSeriesInput.position == DerivedObservationLineage.input_position,
            ),
        )
        .where(DerivedObservationLineage.derived_observation_id == observation_id)
        .order_by(
            DerivedObservationLineage.input_position,
            DerivedObservationLineage.lineage_position,
            DerivedObservationLineage.id,
        )
        .limit(limit)
        .offset(offset)
    )
    return schemas.DerivedObservationLineagePage(
        run_id=run_id,
        observation_id=observation_id,
        items=[
            schemas.DerivedObservationLineageRead(
                id=lineage.id,
                input_position=lineage.input_position,
                input_alias=alias,
                lineage_position=lineage.lineage_position,
                source_observation_id=lineage.source_observation_id,
                source_revision_id=lineage.source_revision_id,
                source_version_kind=lineage.source_version_kind,
                source_version_id=lineage.source_version_id,
                source_knowledge_timestamp=lineage.source_knowledge_timestamp,
            )
            for lineage, alias in rows
        ],
        limit=limit,
        offset=offset,
    )


def _version_for_definition(
    session: Session,
    definition_id: int,
    *,
    version_number: int | None,
    as_of: datetime | None = None,
) -> DerivedSeriesDefinitionVersion:
    if session.get(DerivedSeriesDefinition, definition_id) is None:
        raise AnalyticsNotFoundError("Derived-series definition was not found")
    statement = select(DerivedSeriesDefinitionVersion).where(
        DerivedSeriesDefinitionVersion.definition_id == definition_id
    )
    if version_number is not None:
        statement = statement.where(DerivedSeriesDefinitionVersion.version == version_number)
    elif as_of is not None:
        statement = statement.where(DerivedSeriesDefinitionVersion.created_at <= as_of)
    version = session.scalar(
        statement.order_by(
            DerivedSeriesDefinitionVersion.version.desc(),
            DerivedSeriesDefinitionVersion.id.desc(),
        ).limit(1)
    )
    if version is None:
        raise AnalyticsNotFoundError("No eligible derived-series version was found")
    return version


def _latest_succeeded_run(
    session: Session,
    version: DerivedSeriesDefinitionVersion,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    as_of: datetime | None = None,
) -> AnalyticsRun:
    statement = _run_statement().where(
        AnalyticsRun.definition_version_id == version.id,
        AnalyticsRun.status == "succeeded",
    )
    if start is not None:
        statement = statement.where(AnalyticsRun.requested_start_at <= start)
    if end is not None:
        statement = statement.where(AnalyticsRun.requested_end_at >= end)
    if as_of is not None:
        statement = statement.where(AnalyticsRun.calculation_cutoff <= as_of)
        ordering: tuple[Any, ...] = (
            AnalyticsRun.calculation_cutoff.desc(),
            AnalyticsRun.completed_at.desc(),
            AnalyticsRun.id.desc(),
        )
    else:
        ordering = (AnalyticsRun.completed_at.desc(), AnalyticsRun.id.desc())
    run = session.scalar(statement.order_by(*ordering).limit(1))
    if run is None:
        raise AnalyticsNotFoundError("No eligible succeeded analytics run was found")
    return run


def latest_observation(
    session: Session, definition_id: int
) -> schemas.LatestDerivedObservationRead:
    version = _version_for_definition(session, definition_id, version_number=None)
    run = _latest_succeeded_run(session, version)
    observation = session.scalar(
        select(DerivedObservation)
        .where(DerivedObservation.run_id == run.id)
        .order_by(
            DerivedObservation.observed_at.desc(),
            DerivedObservation.id.desc(),
        )
        .limit(1)
    )
    if observation is None:
        raise AnalyticsNotFoundError("Latest analytics run has no observations")
    return schemas.LatestDerivedObservationRead(
        run_id=run.id,
        definition_id=definition_id,
        definition_version=version.version,
        observation=observation_to_read(observation),
    )


def ranged_observations(
    session: Session,
    definition_id: int,
    *,
    start: datetime | None,
    end: datetime | None,
    definition_version: int | None,
    run_id: int | None,
    limit: int,
    offset: int,
) -> schemas.DerivedObservationPage:
    if run_id is not None:
        run = get_run(session, run_id)
        if (
            run.status != "succeeded"
            or run.definition_version.definition_id != definition_id
            or (
                definition_version is not None
                and run.definition_version.version != definition_version
            )
        ):
            raise AnalyticsNotFoundError(
                "Requested run does not match the derived-series selection"
            )
        if (start is not None and run.requested_start_at > start) or (
            end is not None and run.requested_end_at < end
        ):
            raise AnalyticsNotFoundError("Requested run does not cover the requested range")
    else:
        version = _version_for_definition(session, definition_id, version_number=definition_version)
        run = _latest_succeeded_run(session, version, start=start, end=end)
    return _observation_page(session, run, start=start, end=end, limit=limit, offset=offset)


def observations_as_of(
    session: Session,
    definition_id: int,
    *,
    as_of: datetime,
    start: datetime | None,
    end: datetime | None,
    definition_version: int | None,
    limit: int,
    offset: int,
) -> schemas.DerivedObservationPage:
    normalized = utc_timestamp(as_of)
    version = _version_for_definition(
        session,
        definition_id,
        version_number=definition_version,
        as_of=normalized,
    )
    run = _latest_succeeded_run(
        session,
        version,
        start=start,
        end=end,
        as_of=normalized,
    )
    return _observation_page(session, run, start=start, end=end, limit=limit, offset=offset)
