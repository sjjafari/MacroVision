"""Public management, execution, and read API for Macro Analytics."""

from collections.abc import Generator
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from macrovision import analytics_api_schemas as schemas
from macrovision import analytics_management_services as management
from macrovision import analytics_services as execution
from macrovision.analytics_schemas import canonical_code
from macrovision.contracts import ErrorResponse, PageLimit, PageOffset, utc_timestamp
from macrovision.database import SessionLocal, get_db

router = APIRouter(tags=["macro-analytics"])
DbSession = Annotated[Session, Depends(get_db)]


def get_analytics_execution_db() -> Generator[Session, None, None]:
    """Yield a fresh session that has performed no SQL before Phase 2B execution."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


ExecutionSession = Annotated[Session, Depends(get_analytics_execution_db)]


def _management_error(exc: Exception) -> HTTPException:
    if isinstance(exc, management.AnalyticsNotFoundError):
        code = 404
    elif isinstance(exc, management.AnalyticsConflictError):
        code = 409
    else:
        code = 422
    return HTTPException(status_code=code, detail=str(exc))


def _execution_error(exc: Exception) -> HTTPException:
    if isinstance(exc, execution.AnalyticsNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, execution.AnalyticsConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(
        exc,
        (
            execution.AnalyticsValidationError,
            execution.AnalyticsResourceLimitError,
            execution.AnalyticsSnapshotError,
        ),
    ):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=500, detail="Analytics execution failed")


def _optional_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    try:
        return utc_timestamp(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _validate_range(start: datetime | None, end: datetime | None) -> None:
    if start is not None and end is not None and start > end:
        raise HTTPException(status_code=422, detail="start cannot exceed end")


@router.post(
    "/derived-series",
    response_model=schemas.DerivedSeriesRead,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def create_definition(
    payload: schemas.DerivedSeriesCreate, session: DbSession
) -> schemas.DerivedSeriesRead:
    try:
        return management.create_definition(session, payload)
    except management.AnalyticsManagementError as exc:
        raise _management_error(exc) from exc


@router.get("/derived-series", response_model=schemas.DerivedSeriesPage)
def list_definitions(
    session: DbSession,
    limit: PageLimit = 100,
    offset: PageOffset = 0,
    enabled: bool | None = None,
    code: Annotated[str | None, Query(min_length=1, max_length=120)] = None,
    code_prefix: Annotated[str | None, Query(min_length=1, max_length=120)] = None,
) -> schemas.DerivedSeriesPage:
    try:
        exact = canonical_code(code) if code is not None else None
        prefix = canonical_code(code_prefix) if code_prefix is not None else None
        return management.list_definitions(
            session,
            enabled=enabled,
            code=exact,
            code_prefix=prefix,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/derived-series/{definition_id}", response_model=schemas.DerivedSeriesRead)
def get_definition(definition_id: int, session: DbSession) -> schemas.DerivedSeriesRead:
    try:
        return management.get_definition_read(session, definition_id)
    except management.AnalyticsManagementError as exc:
        raise _management_error(exc) from exc


@router.patch("/derived-series/{definition_id}", response_model=schemas.DerivedSeriesRead)
def patch_definition(
    definition_id: int,
    payload: schemas.DerivedSeriesPatch,
    session: DbSession,
) -> schemas.DerivedSeriesRead:
    try:
        return management.patch_definition(session, definition_id, payload)
    except management.AnalyticsManagementError as exc:
        raise _management_error(exc) from exc


def _set_definition_state(
    definition_id: int,
    payload: schemas.DerivedSeriesStateChange,
    session: Session,
    *,
    enabled: bool,
) -> schemas.DerivedSeriesRead:
    try:
        return management.set_definition_enabled(session, definition_id, payload, enabled=enabled)
    except management.AnalyticsManagementError as exc:
        raise _management_error(exc) from exc


@router.post(
    "/derived-series/{definition_id}/enable",
    response_model=schemas.DerivedSeriesRead,
)
def enable_definition(
    definition_id: int,
    payload: schemas.DerivedSeriesStateChange,
    session: DbSession,
) -> schemas.DerivedSeriesRead:
    return _set_definition_state(definition_id, payload, session, enabled=True)


@router.post(
    "/derived-series/{definition_id}/disable",
    response_model=schemas.DerivedSeriesRead,
)
def disable_definition(
    definition_id: int,
    payload: schemas.DerivedSeriesStateChange,
    session: DbSession,
) -> schemas.DerivedSeriesRead:
    return _set_definition_state(definition_id, payload, session, enabled=False)


@router.get(
    "/derived-series/{definition_id}/versions",
    response_model=schemas.DerivedSeriesVersionPage,
)
def list_versions(
    definition_id: int,
    session: DbSession,
    limit: PageLimit = 100,
    offset: PageOffset = 0,
) -> schemas.DerivedSeriesVersionPage:
    try:
        return management.list_versions(session, definition_id, limit=limit, offset=offset)
    except management.AnalyticsManagementError as exc:
        raise _management_error(exc) from exc


@router.get(
    "/derived-series/{definition_id}/versions/{version_number}",
    response_model=schemas.DerivedSeriesVersionRead,
)
def get_version(
    definition_id: int, version_number: int, session: DbSession
) -> schemas.DerivedSeriesVersionRead:
    try:
        return management.version_to_read(
            management.get_version(session, definition_id, version_number)
        )
    except management.AnalyticsManagementError as exc:
        raise _management_error(exc) from exc


@router.post(
    "/derived-series/{definition_id}/versions",
    response_model=schemas.DerivedSeriesVersionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_version(
    definition_id: int,
    payload: schemas.DerivedSeriesVersionCreate,
    session: DbSession,
) -> schemas.DerivedSeriesVersionRead:
    try:
        return management.create_version(session, definition_id, payload)
    except management.AnalyticsManagementError as exc:
        raise _management_error(exc) from exc


@router.post(
    "/derived-series/{definition_id}/runs",
    response_model=schemas.AnalyticsExecutionRead,
    status_code=status.HTTP_201_CREATED,
    responses={
        200: {"model": schemas.AnalyticsExecutionRead, "description": "Reusable completed run"},
        202: {"model": schemas.AnalyticsExecutionRead, "description": "Existing active run"},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse, "description": "Safe internal execution failure"},
    },
)
def execute_definition(
    definition_id: int,
    payload: schemas.AnalyticsExecutionCreate,
    response: Response,
    session: ExecutionSession,
) -> schemas.AnalyticsExecutionRead:
    request = execution.AnalyticsExecutionRequest(
        definition_id=definition_id,
        definition_version=payload.definition_version,
        requested_start_at=payload.requested_start_at,
        requested_end_at=payload.requested_end_at,
        as_of=payload.as_of,
        retry_of_run_id=payload.retry_of_run_id,
    )
    try:
        outcome = execution.execute_analytics_run_outcome(session, request)
        if outcome.disposition == "active_existing":
            response.status_code = status.HTTP_202_ACCEPTED
        elif outcome.disposition == "completed_existing":
            response.status_code = status.HTTP_200_OK
        else:
            response.status_code = status.HTTP_201_CREATED
        return schemas.AnalyticsExecutionRead(
            disposition=outcome.disposition,
            run=management.run_to_read(outcome.run),
        )
    except execution.AnalyticsServiceError as exc:
        raise _execution_error(exc) from exc


@router.get("/analytics-runs", response_model=schemas.AnalyticsRunPage)
def list_runs(
    session: DbSession,
    limit: PageLimit = 100,
    offset: PageOffset = 0,
    definition_id: Annotated[int | None, Query(gt=0)] = None,
    definition_version: Annotated[int | None, Query(gt=0)] = None,
    status_filter: Annotated[schemas.AnalyticsRunStatus | None, Query(alias="status")] = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> schemas.AnalyticsRunPage:
    normalized_from = _optional_utc(created_from)
    normalized_to = _optional_utc(created_to)
    _validate_range(normalized_from, normalized_to)
    return management.list_runs(
        session,
        definition_id=definition_id,
        definition_version=definition_version,
        status=status_filter,
        created_from=normalized_from,
        created_to=normalized_to,
        limit=limit,
        offset=offset,
    )


@router.get("/analytics-runs/{run_id}", response_model=schemas.AnalyticsRunRead)
def get_run(run_id: int, session: DbSession) -> schemas.AnalyticsRunRead:
    try:
        return management.run_to_read(management.get_run(session, run_id))
    except management.AnalyticsManagementError as exc:
        raise _management_error(exc) from exc


@router.get(
    "/analytics-runs/{run_id}/observations",
    response_model=schemas.DerivedObservationPage,
)
def get_run_observations(
    run_id: int,
    session: DbSession,
    limit: PageLimit = 100,
    offset: PageOffset = 0,
    start: datetime | None = None,
    end: datetime | None = None,
) -> schemas.DerivedObservationPage:
    normalized_start = _optional_utc(start)
    normalized_end = _optional_utc(end)
    _validate_range(normalized_start, normalized_end)
    try:
        return management.run_observations(
            session,
            run_id,
            start=normalized_start,
            end=normalized_end,
            limit=limit,
            offset=offset,
        )
    except management.AnalyticsManagementError as exc:
        raise _management_error(exc) from exc


@router.get(
    "/analytics-runs/{run_id}/observations/{observation_id}/lineage",
    response_model=schemas.DerivedObservationLineagePage,
)
def get_observation_lineage(
    run_id: int,
    observation_id: int,
    session: DbSession,
    limit: PageLimit = 100,
    offset: PageOffset = 0,
) -> schemas.DerivedObservationLineagePage:
    try:
        return management.observation_lineage(
            session,
            run_id,
            observation_id,
            limit=limit,
            offset=offset,
        )
    except management.AnalyticsManagementError as exc:
        raise _management_error(exc) from exc


@router.get(
    "/derived-series/{definition_id}/observations/latest",
    response_model=schemas.LatestDerivedObservationRead,
)
def get_latest_observation(
    definition_id: int, session: DbSession
) -> schemas.LatestDerivedObservationRead:
    try:
        return management.latest_observation(session, definition_id)
    except management.AnalyticsManagementError as exc:
        raise _management_error(exc) from exc


@router.get(
    "/derived-series/{definition_id}/observations",
    response_model=schemas.DerivedObservationPage,
)
def get_ranged_observations(
    definition_id: int,
    session: DbSession,
    limit: PageLimit = 100,
    offset: PageOffset = 0,
    start: datetime | None = None,
    end: datetime | None = None,
    definition_version: Annotated[int | None, Query(gt=0)] = None,
    run_id: Annotated[int | None, Query(gt=0)] = None,
) -> schemas.DerivedObservationPage:
    normalized_start = _optional_utc(start)
    normalized_end = _optional_utc(end)
    _validate_range(normalized_start, normalized_end)
    try:
        return management.ranged_observations(
            session,
            definition_id,
            start=normalized_start,
            end=normalized_end,
            definition_version=definition_version,
            run_id=run_id,
            limit=limit,
            offset=offset,
        )
    except management.AnalyticsManagementError as exc:
        raise _management_error(exc) from exc


@router.get(
    "/derived-series/{definition_id}/observations/as-of",
    response_model=schemas.DerivedObservationPage,
)
def get_observations_as_of(
    definition_id: int,
    as_of: datetime,
    session: DbSession,
    limit: PageLimit = 100,
    offset: PageOffset = 0,
    start: datetime | None = None,
    end: datetime | None = None,
    definition_version: Annotated[int | None, Query(gt=0)] = None,
) -> schemas.DerivedObservationPage:
    normalized_as_of = _optional_utc(as_of)
    assert normalized_as_of is not None
    normalized_start = _optional_utc(start)
    normalized_end = _optional_utc(end)
    _validate_range(normalized_start, normalized_end)
    try:
        return management.observations_as_of(
            session,
            definition_id,
            as_of=normalized_as_of,
            start=normalized_start,
            end=normalized_end,
            definition_version=definition_version,
            limit=limit,
            offset=offset,
        )
    except management.AnalyticsManagementError as exc:
        raise _management_error(exc) from exc
