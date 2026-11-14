from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from macrovision.contracts import PageLimit, PageOffset
from macrovision.database import get_db
from macrovision.indicator_schemas import (
    IndicatorReaderFilter,
    IndicatorSearch,
    IndicatorSnapshot,
    PositiveSourceId,
    RelatedDerivedRead,
)
from macrovision.macro_data_models import DataFrequency, SeriesCategory
from macrovision.public_indicator_schemas import PublicIndicatorCatalogPage, PublicIndicatorDetail
from macrovision.public_indicator_services import (
    PublicIndicatorNotFoundError,
    public_catalog,
    public_detail,
    public_related,
    public_snapshot,
)

router = APIRouter(tags=["public indicator catalog"])
DbSession = Annotated[Session, Depends(get_db)]


def _not_found(exc: PublicIndicatorNotFoundError) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc))


@router.get("/public/indicator-catalog", response_model=PublicIndicatorCatalogPage)
def list_public_catalog(
    session: DbSession,
    limit: PageLimit = 100,
    offset: PageOffset = 0,
    search: IndicatorSearch | None = None,
    category: SeriesCategory | None = None,
    geography: IndicatorReaderFilter | None = None,
    frequency: DataFrequency | None = None,
    source_id: PositiveSourceId | None = None,
    operational_is_active: bool | None = None,
) -> PublicIndicatorCatalogPage:
    return public_catalog(
        session,
        limit=limit,
        offset=offset,
        search=search,
        category=category,
        geography=geography,
        frequency=frequency,
        source_id=source_id,
        operational_is_active=operational_is_active,
    )


@router.get("/public/indicator-catalog/{series_id}", response_model=PublicIndicatorDetail)
def get_public_indicator(series_id: int, session: DbSession) -> PublicIndicatorDetail:
    try:
        return public_detail(session, series_id)
    except PublicIndicatorNotFoundError as exc:
        raise _not_found(exc) from exc


@router.get("/public/indicator-catalog/{series_id}/snapshot", response_model=IndicatorSnapshot)
def get_public_snapshot(
    series_id: int, session: DbSession, as_of: datetime | None = None
) -> IndicatorSnapshot:
    try:
        return public_snapshot(session, series_id, as_of=as_of)
    except PublicIndicatorNotFoundError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/public/indicator-catalog/{series_id}/related-derived",
    response_model=RelatedDerivedRead,
)
def get_public_related(series_id: int, session: DbSession) -> RelatedDerivedRead:
    try:
        return public_related(session, series_id)
    except PublicIndicatorNotFoundError as exc:
        raise _not_found(exc) from exc
