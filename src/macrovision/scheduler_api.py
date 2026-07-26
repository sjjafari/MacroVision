from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from macrovision import scheduler_schemas as schemas
from macrovision import scheduler_services as services
from macrovision.config import get_settings
from macrovision.contracts import ErrorResponse, PageLimit, PageOffset
from macrovision.database import get_db
from macrovision.provider_contracts import ProviderError
from macrovision.provider_registry import get_provider_registry

router = APIRouter(tags=["provider-scheduler"])
DbSession = Annotated[Session, Depends(get_db)]


def _http_error(exc: Exception) -> HTTPException:
    code = 404 if isinstance(exc, services.SchedulerNotFoundError) else 409
    return HTTPException(status_code=code, detail=str(exc))


@router.post(
    "/provider-sync-schedules",
    response_model=schemas.ProviderSyncScheduleRead,
    status_code=status.HTTP_201_CREATED,
    responses={
        409: {"model": ErrorResponse, "description": "Duplicate schedule"},
        422: {"model": ErrorResponse, "description": "Invalid provider or schedule"},
    },
)
def create_schedule(
    payload: schemas.ProviderSyncScheduleCreate,
    session: DbSession,
) -> schemas.ProviderSyncScheduleRead:
    try:
        schedule = services.create_schedule(
            session,
            payload,
            registry=get_provider_registry(),
            now=datetime.now(UTC),
        )
        return schemas.ProviderSyncScheduleRead.model_validate(schedule)
    except services.SchedulerConflictError as exc:
        raise _http_error(exc) from exc
    except ProviderError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/provider-sync-schedules",
    response_model=list[schemas.ProviderSyncScheduleRead],
)
def list_schedules(
    session: DbSession,
    limit: PageLimit = 100,
    offset: PageOffset = 0,
) -> list[schemas.ProviderSyncScheduleRead]:
    return [
        schemas.ProviderSyncScheduleRead.model_validate(item)
        for item in services.list_schedules(session, limit=limit, offset=offset)
    ]


@router.get(
    "/provider-sync-schedules/{schedule_id}",
    response_model=schemas.ProviderSyncScheduleRead,
)
def get_schedule(
    schedule_id: int,
    session: DbSession,
) -> schemas.ProviderSyncScheduleRead:
    try:
        return schemas.ProviderSyncScheduleRead.model_validate(
            services.get_schedule(session, schedule_id)
        )
    except services.SchedulerNotFoundError as exc:
        raise _http_error(exc) from exc


@router.patch(
    "/provider-sync-schedules/{schedule_id}",
    response_model=schemas.ProviderSyncScheduleRead,
)
def patch_schedule(
    schedule_id: int,
    payload: schemas.ProviderSyncSchedulePatch,
    session: DbSession,
) -> schemas.ProviderSyncScheduleRead:
    try:
        return schemas.ProviderSyncScheduleRead.model_validate(
            services.update_schedule(
                session,
                schedule_id,
                payload,
                now=datetime.now(UTC),
            )
        )
    except (services.SchedulerNotFoundError, services.SchedulerConflictError) as exc:
        raise _http_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _change_schedule_state(
    schedule_id: int,
    payload: schemas.ProviderSyncScheduleStateChange,
    session: Session,
    *,
    enabled: bool,
) -> schemas.ProviderSyncScheduleRead:
    try:
        return schemas.ProviderSyncScheduleRead.model_validate(
            services.set_schedule_enabled(
                session,
                schedule_id,
                expected_lock_version=payload.expected_lock_version,
                enabled=enabled,
                now=datetime.now(UTC),
            )
        )
    except (services.SchedulerNotFoundError, services.SchedulerConflictError) as exc:
        raise _http_error(exc) from exc


@router.post(
    "/provider-sync-schedules/{schedule_id}/enable",
    response_model=schemas.ProviderSyncScheduleRead,
)
def enable_schedule(
    schedule_id: int,
    payload: schemas.ProviderSyncScheduleStateChange,
    session: DbSession,
) -> schemas.ProviderSyncScheduleRead:
    return _change_schedule_state(schedule_id, payload, session, enabled=True)


@router.post(
    "/provider-sync-schedules/{schedule_id}/disable",
    response_model=schemas.ProviderSyncScheduleRead,
)
def disable_schedule(
    schedule_id: int,
    payload: schemas.ProviderSyncScheduleStateChange,
    session: DbSession,
) -> schemas.ProviderSyncScheduleRead:
    return _change_schedule_state(schedule_id, payload, session, enabled=False)


@router.post(
    "/provider-sync-schedules/{schedule_id}/runs",
    response_model=schemas.ProviderSyncRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def enqueue_run_now(
    schedule_id: int,
    payload: schemas.ProviderSyncRunNowRequest,
    session: DbSession,
) -> schemas.ProviderSyncRunRead:
    try:
        return schemas.ProviderSyncRunRead.model_validate(
            services.enqueue_run_now(
                session,
                schedule_id,
                payload,
                maximum_attempts=get_settings().scheduler_maximum_attempts,
                now=datetime.now(UTC),
            )
        )
    except (services.SchedulerNotFoundError, services.SchedulerConflictError) as exc:
        raise _http_error(exc) from exc


@router.get(
    "/provider-sync-runs",
    response_model=list[schemas.ProviderSyncRunRead],
)
def list_runs(
    session: DbSession,
    limit: PageLimit = 100,
    offset: PageOffset = 0,
    schedule_id: int | None = None,
    provider: str | None = None,
    provider_series_id: str | None = None,
    status_filter: Annotated[
        schemas.ProviderSyncRunStatus | None,
        Query(alias="status"),
    ] = None,
) -> list[schemas.ProviderSyncRunRead]:
    try:
        return [
            schemas.ProviderSyncRunRead.model_validate(item)
            for item in services.list_runs(
                session,
                limit=limit,
                offset=offset,
                schedule_id=schedule_id,
                provider=provider,
                provider_series_id=provider_series_id,
                status=status_filter,
            )
        ]
    except ProviderError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/provider-sync-runs/{run_id}",
    response_model=schemas.ProviderSyncRunRead,
)
def get_run(run_id: int, session: DbSession) -> schemas.ProviderSyncRunRead:
    try:
        return schemas.ProviderSyncRunRead.model_validate(services.get_run(session, run_id))
    except services.SchedulerNotFoundError as exc:
        raise _http_error(exc) from exc
