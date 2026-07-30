"""Read-only projections for the reviewed private indicator catalog."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from macrovision import dashboard_services, macro_data_services
from macrovision.analytics_models import (
    DerivedSeriesDefinition,
    DerivedSeriesDefinitionVersion,
)
from macrovision.dashboard_schemas import (
    DashboardComparison,
    DashboardComparisonAnchorPolicy,
    DashboardComparisonState,
    DashboardComparisonType,
    DashboardFreshnessStatus,
)
from macrovision.indicator_catalog import (
    REVIEWED_INDICATOR_CATALOG,
    REVIEWED_INDICATORS_BY_CODE,
    IndicatorCatalogEntry,
    is_credential_free_http_url,
)
from macrovision.indicator_schemas import (
    IndicatorAvailability,
    IndicatorCanonicalRead,
    IndicatorCatalogItem,
    IndicatorCatalogPage,
    IndicatorCurationRead,
    IndicatorDetail,
    IndicatorMetricState,
    IndicatorObservationIdentity,
    IndicatorPresentationRead,
    IndicatorSnapshot,
    IndicatorSnapshotMode,
    IndicatorSourceRead,
    IndicatorSourceSummary,
    RelatedDerivedItem,
    RelatedDerivedRead,
    RelatedDerivedState,
)
from macrovision.macro_data_models import (
    DataFrequency,
    DataSeries,
    ObservationStatus,
    SeriesCategory,
)
from macrovision.macro_data_schemas import _aware_utc


class IndicatorNotFoundError(Exception):
    pass


def _safe_reference_url(value: str | None) -> str | None:
    if value is None:
        return None
    if not is_credential_free_http_url(value):
        return None
    return value


def _source_summary(series: DataSeries) -> IndicatorSourceSummary:
    return IndicatorSourceSummary(
        source_id=series.source.id,
        source_code=series.source.code,
        source_name=series.source.name,
        reference_url=_safe_reference_url(series.source.reference_url),
    )


def _load_reviewed_series(session: Session) -> dict[str, DataSeries]:
    codes = [entry.series_code for entry in REVIEWED_INDICATOR_CATALOG]
    series = session.scalars(
        select(DataSeries)
        .options(joinedload(DataSeries.source))
        .where(DataSeries.code.in_(codes))
        .order_by(DataSeries.code, DataSeries.id)
    ).unique()
    return {item.code: item for item in series}


def _catalog_item(
    entry: IndicatorCatalogEntry,
    series: DataSeries | None,
) -> IndicatorCatalogItem:
    return IndicatorCatalogItem(
        catalog_order=entry.catalog_order,
        curation_status=entry.curation_status,
        availability=(
            IndicatorAvailability.available
            if series is not None
            else IndicatorAvailability.configured_series_missing
        ),
        series_id=series.id if series is not None else None,
        series_code=entry.series_code,
        display_name_fa=entry.display_name_fa,
        original_name=series.name if series is not None else None,
        description_fa=entry.description_fa,
        localized_unit_label=entry.localized_unit_label,
        category=series.category if series is not None else None,
        geography=series.geography if series is not None else None,
        frequency=series.frequency if series is not None else None,
        unit=series.unit if series is not None else None,
        seasonal_adjustment_status=entry.seasonal_adjustment_status,
        operational_is_active=series.is_active if series is not None else None,
        source=_source_summary(series) if series is not None else None,
        editorial_updated_at=entry.editorial_updated_at,
    )


def list_indicator_catalog(
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
) -> IndicatorCatalogPage:
    series_by_code = _load_reviewed_series(session)
    normalized_search = search.casefold() if search is not None else None
    filtered: list[IndicatorCatalogItem] = []
    for entry in REVIEWED_INDICATOR_CATALOG:
        series = series_by_code.get(entry.series_code)
        if normalized_search is not None:
            searchable = (
                entry.display_name_fa,
                entry.description_fa,
                entry.series_code,
                series.name if series is not None else "",
            )
            if not any(normalized_search in value.casefold() for value in searchable):
                continue
        if category is not None and (series is None or series.category != category):
            continue
        if geography is not None and (
            series is None or series.geography.casefold() != geography.casefold()
        ):
            continue
        if frequency is not None and (series is None or series.frequency != frequency):
            continue
        if source_id is not None and (series is None or series.source_id != source_id):
            continue
        if operational_is_active is not None and (
            series is None or series.is_active is not operational_is_active
        ):
            continue
        filtered.append(_catalog_item(entry, series))
    return IndicatorCatalogPage(
        limit=limit,
        offset=offset,
        total=len(filtered),
        items=filtered[offset : offset + limit],
    )


def _reviewed_series(
    session: Session,
    series_id: int,
) -> tuple[IndicatorCatalogEntry, DataSeries]:
    series = session.scalar(
        select(DataSeries).options(joinedload(DataSeries.source)).where(DataSeries.id == series_id)
    )
    if series is None:
        raise IndicatorNotFoundError("Indicator was not found")
    entry = REVIEWED_INDICATORS_BY_CODE.get(series.code)
    if entry is None:
        raise IndicatorNotFoundError("Indicator was not found")
    return entry, series


def indicator_detail(session: Session, series_id: int) -> IndicatorDetail:
    entry, series = _reviewed_series(session, series_id)
    return IndicatorDetail(
        curation=IndicatorCurationRead(
            curation_status=entry.curation_status,
            catalog_order=entry.catalog_order,
            editorial_updated_at=entry.editorial_updated_at,
        ),
        presentation=IndicatorPresentationRead(
            display_name_fa=entry.display_name_fa,
            original_name=series.name,
            description_fa=entry.description_fa,
            methodology_summary_fa=entry.methodology_summary_fa,
            localized_unit_label=entry.localized_unit_label or series.unit,
            source_attribution_fa=entry.source_attribution_fa,
            seasonal_adjustment_status=entry.seasonal_adjustment_status,
            source_methodology_url=entry.source_methodology_url,
        ),
        canonical=IndicatorCanonicalRead(
            series_id=series.id,
            series_code=series.code,
            name=series.name,
            description=series.description,
            category=series.category,
            geography=series.geography,
            frequency=series.frequency,
            unit=series.unit,
            currency=series.currency,
            is_active=series.is_active,
            stale_after_days=series.stale_after_days,
            created_at=series.created_at,
            updated_at=series.updated_at,
        ),
        source=IndicatorSourceRead(
            **_source_summary(series).model_dump(),
            description=series.source.description,
        ),
    )


def _missing_comparison() -> DashboardComparison:
    return DashboardComparison(
        type=DashboardComparisonType.previous_observation,
        basis_code="previous_observation",
        basis_label_fa="در مقایسه با مشاهدهٔ قبلی",
        anchor_policy=DashboardComparisonAnchorPolicy.previous_observation,
        state=DashboardComparisonState.missing,
        state_reason="metric_unavailable",
    )


def indicator_snapshot(
    session: Session,
    series_id: int,
    *,
    as_of: datetime | None = None,
    generated_at: datetime | None = None,
) -> IndicatorSnapshot:
    entry, series = _reviewed_series(session, series_id)
    current_time = (generated_at or datetime.now(UTC)).astimezone(UTC)
    normalized_as_of = _aware_utc(as_of) if as_of is not None else None
    evaluated_at = normalized_as_of or current_time
    observations = macro_data_services.latest_effective_observations(
        session,
        series_id,
        as_of=normalized_as_of,
        limit=2,
    )
    current = observations[0] if observations else None
    previous = observations[1] if len(observations) > 1 else None
    point_available = (
        current is not None
        and current.status == ObservationStatus.present
        and current.value is not None
    )
    freshness = dashboard_services.raw_series_freshness(
        series,
        current.observed_at if point_available and current is not None else None,
        evaluated_at=evaluated_at,
    )
    state_reason: str | None
    if not point_available:
        state = IndicatorMetricState.missing
        state_reason = "observation_missing" if current is None else "current_observation_missing"
        comparison = _missing_comparison()
    else:
        assert current is not None and current.value is not None
        state = (
            IndicatorMetricState.stale
            if freshness.status == DashboardFreshnessStatus.stale
            else IndicatorMetricState.available
        )
        state_reason = "series_stale" if state == IndicatorMetricState.stale else None
        comparison = dashboard_services.previous_observation_comparison(
            current.value,
            current.observed_at,
            previous,
            basis_label_fa="در مقایسه با مشاهدهٔ قبلی",
        )
    return IndicatorSnapshot(
        mode=(
            IndicatorSnapshotMode.historical_as_of
            if normalized_as_of is not None
            else IndicatorSnapshotMode.current
        ),
        requested_as_of=normalized_as_of,
        generated_at=current_time,
        state=state,
        state_reason=state_reason,
        value=current.value if point_available and current is not None else None,
        observation_identity=(
            IndicatorObservationIdentity(
                series_id=series.id,
                observation_id=current.id,
                revision_count=current.revision_count,
            )
            if current is not None
            else None
        ),
        observed_at=current.observed_at if current is not None else None,
        source_publication_timestamp=(
            current.publication_timestamp if current is not None else None
        ),
        knowledge_cutoff=current.ingestion_timestamp if current is not None else None,
        unit=series.unit,
        localized_unit_label=entry.localized_unit_label or series.unit,
        frequency=series.frequency,
        geography=series.geography,
        source=_source_summary(series),
        source_attribution_fa=entry.source_attribution_fa,
        freshness=freshness,
        comparison=comparison,
    )


def related_derived(session: Session, series_id: int) -> RelatedDerivedRead:
    entry, series = _reviewed_series(session, series_id)
    specifications = tuple(sorted(entry.related_derived, key=lambda item: item.relation_order))
    codes = {item.definition_code for item in specifications}
    definitions = list(
        session.scalars(
            select(DerivedSeriesDefinition)
            .options(
                selectinload(DerivedSeriesDefinition.versions).selectinload(
                    DerivedSeriesDefinitionVersion.inputs
                )
            )
            .where(DerivedSeriesDefinition.code.in_(codes))
            .order_by(DerivedSeriesDefinition.code, DerivedSeriesDefinition.id)
        ).unique()
    )
    definitions_by_code = {item.code: item for item in definitions}
    persisted = dashboard_services.load_latest_persisted_derived_results(session, codes)
    items: list[RelatedDerivedItem] = []
    for specification in specifications:
        definition = definitions_by_code.get(specification.definition_code)
        result = persisted.get(specification.definition_code)
        if definition is None:
            state = RelatedDerivedState.definition_missing
            reason = "definition_missing"
        elif not definition.enabled:
            state = RelatedDerivedState.definition_disabled
            reason = "definition_disabled"
        elif result is None or result.run is None or result.observation is None:
            state = RelatedDerivedState.persisted_result_missing
            reason = "persisted_result_missing"
        elif result.version.inputs and not any(
            item.source_code_snapshot == series.code for item in result.version.inputs
        ):
            state = RelatedDerivedState.persisted_result_missing
            reason = "definition_source_mismatch"
        elif result.observation.status != "present" or result.observation.value is None:
            state = RelatedDerivedState.persisted_result_missing
            reason = result.observation.missing_reason or "persisted_result_missing"
        else:
            state = RelatedDerivedState.available
            reason = None
        items.append(
            RelatedDerivedItem(
                relation_code=specification.relation_code,
                relation_label_fa=specification.relation_label_fa,
                description_fa=specification.description_fa,
                state=state,
                definition_id=definition.id if definition is not None else None,
                definition_code=specification.definition_code,
                definition_version=result.version.version if result is not None else None,
                enabled=definition.enabled if definition is not None else None,
                value=(
                    result.observation.value
                    if state == RelatedDerivedState.available
                    and result is not None
                    and result.observation is not None
                    else None
                ),
                observed_at=(
                    result.observation.observed_at
                    if result is not None and result.observation is not None
                    else None
                ),
                run_id=result.run.id if result is not None and result.run is not None else None,
                observation_id=(
                    result.observation.id
                    if result is not None and result.observation is not None
                    else None
                ),
                calculation_cutoff=(
                    result.run.calculation_cutoff
                    if result is not None and result.run is not None
                    else None
                ),
                completed_at=(
                    result.run.completed_at
                    if result is not None and result.run is not None
                    else None
                ),
                missing_reason=reason,
            )
        )
    return RelatedDerivedRead(series_id=series.id, series_code=series.code, items=items)
