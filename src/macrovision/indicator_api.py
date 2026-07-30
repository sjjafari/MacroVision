from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from macrovision.contracts import PageLimit, PageOffset
from macrovision.database import get_db
from macrovision.indicator_schemas import (
    IndicatorCatalogPage,
    IndicatorDetail,
    IndicatorSearch,
    IndicatorSnapshot,
    PositiveSourceId,
    RelatedDerivedRead,
)
from macrovision.indicator_services import (
    IndicatorNotFoundError,
    indicator_detail,
    indicator_snapshot,
    list_indicator_catalog,
    related_derived,
)
from macrovision.macro_data_models import DataFrequency, SeriesCategory

router = APIRouter(tags=["private indicator catalog"])
DbSession = Annotated[Session, Depends(get_db)]


def _not_found(exc: IndicatorNotFoundError) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc))


@router.get("/indicator-catalog", response_model=IndicatorCatalogPage)
def list_catalog(
    session: DbSession,
    limit: PageLimit = 100,
    offset: PageOffset = 0,
    search: IndicatorSearch | None = None,
    category: SeriesCategory | None = None,
    geography: Annotated[str | None, Query(min_length=1, max_length=120)] = None,
    frequency: DataFrequency | None = None,
    source_id: PositiveSourceId | None = None,
    operational_is_active: bool | None = None,
) -> IndicatorCatalogPage:
    return list_indicator_catalog(
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


@router.get("/indicator-catalog/{series_id}", response_model=IndicatorDetail)
def get_indicator(series_id: int, session: DbSession) -> IndicatorDetail:
    try:
        return indicator_detail(session, series_id)
    except IndicatorNotFoundError as exc:
        raise _not_found(exc) from exc


@router.get(
    "/indicator-catalog/{series_id}/snapshot",
    response_model=IndicatorSnapshot,
)
def get_indicator_snapshot(
    series_id: int,
    session: DbSession,
    as_of: datetime | None = None,
) -> IndicatorSnapshot:
    try:
        return indicator_snapshot(session, series_id, as_of=as_of)
    except IndicatorNotFoundError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/indicator-catalog/{series_id}/related-derived",
    response_model=RelatedDerivedRead,
)
def get_related_derived(series_id: int, session: DbSession) -> RelatedDerivedRead:
    try:
        return related_derived(session, series_id)
    except IndicatorNotFoundError as exc:
        raise _not_found(exc) from exc
