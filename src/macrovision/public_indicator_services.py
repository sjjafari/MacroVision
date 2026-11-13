"""Public-safe indicator projections gated by explicit publication eligibility."""

from datetime import datetime

from sqlalchemy.orm import Session

from macrovision import indicator_services
from macrovision.indicator_schemas import IndicatorSnapshot, RelatedDerivedRead
from macrovision.macro_data_models import DataFrequency, SeriesCategory
from macrovision.public_indicator_schemas import (
    PublicIndicatorCatalogItem,
    PublicIndicatorCatalogPage,
    PublicIndicatorCurationRead,
    PublicIndicatorDetail,
)
from macrovision.publication_catalog import is_public_indicator


class PublicIndicatorNotFoundError(Exception):
    pass


def _eligible(series_code: str) -> None:
    if not is_public_indicator(series_code):
        raise PublicIndicatorNotFoundError("Public indicator was not found")


def public_catalog(
    session: Session,
    *,
    limit: int,
    offset: int,
    search: str | None = None,
    category: SeriesCategory | None = None,
    geography: str | None = None,
    frequency: DataFrequency | None = None,
    source_id: int | None = None,
    operational_is_active: bool | None = None,
) -> PublicIndicatorCatalogPage:
    private = indicator_services.list_indicator_catalog(
        session,
        limit=1000,
        offset=0,
        search=search,
        category=category,
        geography=geography,
        frequency=frequency,
        source_id=source_id,
        operational_is_active=operational_is_active,
    )
    eligible = [item for item in private.items if is_public_indicator(item.series_code)]
    items = [
        PublicIndicatorCatalogItem(**item.model_dump(), private_preview=False, public_eligibility=True)
        for item in eligible[offset : offset + limit]
    ]
    return PublicIndicatorCatalogPage(limit=limit, offset=offset, total=len(eligible), items=items)


def public_detail(session: Session, series_id: int) -> PublicIndicatorDetail:
    try:
        private = indicator_services.indicator_detail(session, series_id)
    except indicator_services.IndicatorNotFoundError as exc:
        raise PublicIndicatorNotFoundError("Public indicator was not found") from exc
    _eligible(private.canonical.series_code)
    return PublicIndicatorDetail(
        curation=PublicIndicatorCurationRead(
            catalog_order=private.curation.catalog_order,
            editorial_updated_at=private.curation.editorial_updated_at,
        ),
        presentation=private.presentation,
        canonical=private.canonical,
        source=private.source,
    )


def public_snapshot(
    session: Session, series_id: int, *, as_of: datetime | None
) -> IndicatorSnapshot:
    public_detail(session, series_id)
    try:
        return indicator_services.indicator_snapshot(session, series_id, as_of=as_of)
    except indicator_services.IndicatorNotFoundError as exc:
        raise PublicIndicatorNotFoundError("Public indicator was not found") from exc


def public_related(session: Session, series_id: int) -> RelatedDerivedRead:
    public_detail(session, series_id)
    try:
        return indicator_services.related_derived(session, series_id)
    except indicator_services.IndicatorNotFoundError as exc:
        raise PublicIndicatorNotFoundError("Public indicator was not found") from exc
