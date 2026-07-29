from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from macrovision import macro_data_models as models
from macrovision import macro_data_schemas as schemas
from macrovision import macro_data_services as services
from macrovision.contracts import PageLimit, PageOffset
from macrovision.database import get_db

router = APIRouter(tags=["macro-data"])
DbSession = Annotated[Session, Depends(get_db)]


def _http_error(exc: Exception) -> HTTPException:
    code = 404 if isinstance(exc, services.DataNotFoundError) else 409
    return HTTPException(status_code=code, detail=str(exc))


@router.post(
    "/data-sources",
    response_model=schemas.DataSourceRead,
    status_code=status.HTTP_201_CREATED,
)
def create_source(payload: schemas.DataSourceCreate, session: DbSession) -> schemas.DataSourceRead:
    try:
        return schemas.DataSourceRead.model_validate(services.create_source(session, payload))
    except services.DataConflictError as exc:
        raise _http_error(exc) from exc


@router.get("/data-sources", response_model=list[schemas.DataSourceRead])
def list_sources(
    session: DbSession, limit: PageLimit = 100, offset: PageOffset = 0
) -> list[schemas.DataSourceRead]:
    return [
        schemas.DataSourceRead.model_validate(item)
        for item in services.list_sources(session, limit=limit, offset=offset)
    ]


@router.get("/data-sources/{source_id}", response_model=schemas.DataSourceRead)
def get_source(source_id: int, session: DbSession) -> schemas.DataSourceRead:
    try:
        return schemas.DataSourceRead.model_validate(services.get_source(session, source_id))
    except services.DataNotFoundError as exc:
        raise _http_error(exc) from exc


@router.post(
    "/data-series",
    response_model=schemas.DataSeriesRead,
    status_code=status.HTTP_201_CREATED,
)
def create_series(payload: schemas.DataSeriesCreate, session: DbSession) -> schemas.DataSeriesRead:
    try:
        return services.series_to_read(services.create_series(session, payload))
    except (services.DataNotFoundError, services.DataConflictError) as exc:
        raise _http_error(exc) from exc


@router.get("/data-series", response_model=list[schemas.DataSeriesRead])
def list_series(
    session: DbSession,
    limit: PageLimit = 100,
    offset: PageOffset = 0,
    search: Annotated[str | None, Query(min_length=1, max_length=120)] = None,
    code: Annotated[
        str | None,
        Query(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.-]+$"),
    ] = None,
    category: models.SeriesCategory | None = None,
    geography: Annotated[str | None, Query(min_length=1, max_length=120)] = None,
    frequency: models.DataFrequency | None = None,
    source_id: Annotated[int | None, Query(gt=0)] = None,
    is_active: bool | None = None,
) -> list[schemas.DataSeriesRead]:
    if search is not None and not search.strip():
        raise HTTPException(status_code=422, detail="search must contain non-whitespace text")
    return [
        services.series_to_read(item)
        for item in services.list_series(
            session,
            limit=limit,
            offset=offset,
            search=search,
            code=code,
            category=category,
            geography=geography,
            frequency=frequency,
            source_id=source_id,
            is_active=is_active,
        )
    ]


@router.get("/data-series/{series_id}", response_model=schemas.DataSeriesRead)
def get_series(series_id: int, session: DbSession) -> schemas.DataSeriesRead:
    try:
        return services.series_to_read(services.get_series(session, series_id))
    except services.DataNotFoundError as exc:
        raise _http_error(exc) from exc


@router.patch("/data-series/{series_id}", response_model=schemas.DataSeriesRead)
def patch_series(
    series_id: int, payload: schemas.DataSeriesPatch, session: DbSession
) -> schemas.DataSeriesRead:
    try:
        return services.series_to_read(services.patch_series(session, series_id, payload))
    except (services.DataNotFoundError, services.DataConflictError) as exc:
        raise _http_error(exc) from exc


@router.post(
    "/data-series/{series_id}/observations",
    response_model=schemas.ObservationRead,
    status_code=status.HTTP_201_CREATED,
)
def add_observation(
    series_id: int, payload: schemas.ObservationWrite, session: DbSession
) -> schemas.ObservationRead:
    try:
        return services.observation_to_read(services.add_observation(session, series_id, payload))
    except (services.DataNotFoundError, services.DataConflictError) as exc:
        raise _http_error(exc) from exc


@router.get(
    "/data-series/{series_id}/observations",
    response_model=list[schemas.ObservationRead],
)
def list_observations(
    series_id: int,
    session: DbSession,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: PageLimit = 100,
    offset: PageOffset = 0,
) -> list[schemas.ObservationRead]:
    try:
        normalized_start, normalized_end = _normalized_range(start, end)
        return [
            services.observation_to_read(item)
            for item in services.list_observations(
                session,
                series_id,
                start=normalized_start,
                end=normalized_end,
                limit=limit,
                offset=offset,
            )
        ]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except services.DataNotFoundError as exc:
        raise _http_error(exc) from exc


@router.get("/data-series/{series_id}/latest", response_model=schemas.ObservationRead)
def latest_observation(series_id: int, session: DbSession) -> schemas.ObservationRead:
    try:
        return services.observation_to_read(services.latest_observation(session, series_id))
    except services.DataNotFoundError as exc:
        raise _http_error(exc) from exc


@router.get(
    "/data-series/{series_id}/observations/as-of",
    response_model=list[schemas.ObservationRead],
)
def observations_as_of(
    series_id: int,
    as_of: datetime,
    session: DbSession,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: PageLimit = 100,
    offset: PageOffset = 0,
) -> list[schemas.ObservationRead]:
    try:
        normalized = schemas._aware_utc(as_of)
        normalized_start, normalized_end = _normalized_range(start, end)
        return [
            services.observation_to_read(item, as_of=normalized)
            for item in services.observations_as_of(
                session,
                series_id,
                as_of=normalized,
                start=normalized_start,
                end=normalized_end,
                limit=limit,
                offset=offset,
            )
        ]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except services.DataNotFoundError as exc:
        raise _http_error(exc) from exc


def _normalized_range(
    start: datetime | None, end: datetime | None
) -> tuple[datetime | None, datetime | None]:
    normalized_start = schemas._aware_utc(start) if start is not None else None
    normalized_end = schemas._aware_utc(end) if end is not None else None
    if (
        normalized_start is not None
        and normalized_end is not None
        and normalized_start > normalized_end
    ):
        raise ValueError("start must not exceed end")
    return normalized_start, normalized_end


@router.get(
    "/data-series/{series_id}/observations/{observation_id}/revisions",
    response_model=list[schemas.DataRevisionRead],
)
def list_revisions(
    series_id: int,
    observation_id: int,
    session: DbSession,
    limit: PageLimit = 100,
    offset: PageOffset = 0,
) -> list[schemas.DataRevisionRead]:
    try:
        return [
            schemas.DataRevisionRead.model_validate(item)
            for item in services.list_revisions(
                session,
                series_id,
                observation_id,
                limit=limit,
                offset=offset,
            )
        ]
    except services.DataNotFoundError as exc:
        raise _http_error(exc) from exc


@router.post(
    "/data-imports",
    response_model=schemas.DataImportRead,
    status_code=status.HTTP_201_CREATED,
)
def create_import(payload: schemas.DataImportCreate, session: DbSession) -> schemas.DataImportRead:
    try:
        return schemas.DataImportRead.model_validate(services.create_import(session, payload))
    except (services.DataNotFoundError, services.DataConflictError) as exc:
        raise _http_error(exc) from exc


@router.get("/data-imports", response_model=list[schemas.DataImportRead])
def list_imports(
    session: DbSession, limit: PageLimit = 100, offset: PageOffset = 0
) -> list[schemas.DataImportRead]:
    return [
        schemas.DataImportRead.model_validate(item)
        for item in services.list_imports(session, limit=limit, offset=offset)
    ]


@router.get("/data-imports/{import_id}", response_model=schemas.DataImportRead)
def get_import(import_id: int, session: DbSession) -> schemas.DataImportRead:
    try:
        return schemas.DataImportRead.model_validate(services.get_import(session, import_id))
    except services.DataNotFoundError as exc:
        raise _http_error(exc) from exc


@router.get("/data-quality/issues", response_model=list[schemas.QualityIssueRead])
def list_quality_issues(
    session: DbSession, limit: PageLimit = 100, offset: PageOffset = 0
) -> list[schemas.QualityIssueRead]:
    return [
        services.quality_issue_to_read(item)
        for item in services.list_quality_issues(session, limit=limit, offset=offset)
    ]


@router.get("/data-quality/issues/{issue_id}", response_model=schemas.QualityIssueRead)
def get_quality_issue(issue_id: int, session: DbSession) -> schemas.QualityIssueRead:
    try:
        return services.quality_issue_to_read(services.get_quality_issue(session, issue_id))
    except services.DataNotFoundError as exc:
        raise _http_error(exc) from exc


@router.get(
    "/data-quality/issues/{issue_id}/history",
    response_model=list[schemas.QualityIssueEventRead],
)
def list_quality_issue_history(
    issue_id: int,
    session: DbSession,
    limit: PageLimit = 100,
    offset: PageOffset = 0,
) -> list[schemas.QualityIssueEventRead]:
    try:
        return [
            schemas.QualityIssueEventRead.model_validate(event)
            for event in services.list_quality_issue_events(
                session, issue_id, limit=limit, offset=offset
            )
        ]
    except services.DataNotFoundError as exc:
        raise _http_error(exc) from exc


@router.post("/data-quality/scans/stale", response_model=schemas.StaleScanRead)
def scan_stale_quality_issues(session: DbSession) -> schemas.StaleScanRead:
    return services.scan_stale_series(session)


def _change_issue_status(
    issue_id: int,
    payload: schemas.QualityIssueAction,
    session: Session,
    target: models.QualityIssueStatus,
) -> schemas.QualityIssueRead:
    try:
        return services.quality_issue_to_read(
            services.update_quality_issue(session, issue_id, payload, target=target)
        )
    except (services.DataNotFoundError, services.DataConflictError) as exc:
        raise _http_error(exc) from exc


@router.post(
    "/data-quality/issues/{issue_id}/acknowledge",
    response_model=schemas.QualityIssueRead,
)
def acknowledge_quality_issue(
    issue_id: int, payload: schemas.QualityIssueAction, session: DbSession
) -> schemas.QualityIssueRead:
    return _change_issue_status(
        issue_id,
        payload,
        session,
        models.QualityIssueStatus.acknowledged,
    )


@router.post(
    "/data-quality/issues/{issue_id}/resolve",
    response_model=schemas.QualityIssueRead,
)
def resolve_quality_issue(
    issue_id: int, payload: schemas.QualityIssueAction, session: DbSession
) -> schemas.QualityIssueRead:
    return _change_issue_status(issue_id, payload, session, models.QualityIssueStatus.resolved)
