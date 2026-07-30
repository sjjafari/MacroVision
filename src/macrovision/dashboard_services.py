"""Batch-oriented, read-only dashboard projections."""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from macrovision import macro_data_services
from macrovision.analytics_models import (
    AnalyticsRun,
    DerivedObservation,
    DerivedSeriesDefinition,
    DerivedSeriesDefinitionVersion,
)
from macrovision.dashboard_catalog import (
    DASHBOARDS_BY_CODE,
    VALIDATED_DASHBOARD_CATALOG,
)
from macrovision.dashboard_schemas import (
    DashboardCode,
    DashboardComparison,
    DashboardComparisonState,
    DashboardComparisonType,
    DashboardDefinition,
    DashboardFreshness,
    DashboardFreshnessAgeBasis,
    DashboardFreshnessPolicy,
    DashboardFreshnessPolicyType,
    DashboardFreshnessStatus,
    DashboardGroupSummary,
    DashboardMetricDefinition,
    DashboardMetricKind,
    DashboardMetricState,
    DashboardMetricSummary,
    DashboardSourceAttribution,
    DashboardSummary,
    DerivedDashboardIdentity,
    RawDashboardIdentity,
)
from macrovision.macro_data_models import (
    DataFrequency,
    DataObservation,
    DataSeries,
    ObservationStatus,
)
from macrovision.macro_data_schemas import MAX_DATA_VALUE, MIN_DATA_VALUE

_QUANTUM = Decimal("0.00000001")


class DashboardNotFoundError(Exception):
    pass


@dataclass(frozen=True)
class _DerivedResult:
    definition: DerivedSeriesDefinition
    version: DerivedSeriesDefinitionVersion
    run: AnalyticsRun | None
    observation: DerivedObservation | None


def list_dashboards() -> tuple[DashboardDefinition, ...]:
    return VALIDATED_DASHBOARD_CATALOG


def get_dashboard(dashboard_code: str) -> DashboardDefinition:
    try:
        code = DashboardCode(dashboard_code)
    except ValueError as exc:
        raise DashboardNotFoundError("Dashboard was not found") from exc
    dashboard = DASHBOARDS_BY_CODE.get(code)
    if dashboard is None:
        raise DashboardNotFoundError("Dashboard was not found")
    return dashboard


def _raw_codes(dashboard: DashboardDefinition) -> set[str]:
    return {
        metric.raw_series_code
        for group in dashboard.groups
        for metric in group.metrics
        if metric.raw_series_code is not None
    }


def _derived_codes(dashboard: DashboardDefinition) -> set[str]:
    codes = {
        metric.derived_definition_code
        for group in dashboard.groups
        for metric in group.metrics
        if metric.derived_definition_code is not None
    }
    codes.update(
        metric.comparison.derived_definition_code
        for group in dashboard.groups
        for metric in group.metrics
        if metric.comparison.derived_definition_code is not None
    )
    return {code for code in codes if code is not None}


def _load_raw(
    session: Session, codes: set[str]
) -> tuple[dict[str, DataSeries], dict[int, list[DataObservation]]]:
    if not codes:
        return {}, {}
    series = list(
        session.scalars(
            select(DataSeries)
            .options(joinedload(DataSeries.source))
            .where(DataSeries.code.in_(codes))
            .order_by(DataSeries.code, DataSeries.id)
        ).unique()
    )
    by_code = {item.code: item for item in series}
    if not series:
        return by_code, {}
    series_ids = [item.id for item in series]
    ranked = (
        select(
            DataObservation.id.label("observation_id"),
            func.row_number()
            .over(
                partition_by=DataObservation.series_id,
                order_by=(
                    DataObservation.observed_at.desc(),
                    DataObservation.id.desc(),
                ),
            )
            .label("rank"),
        )
        .where(DataObservation.series_id.in_(series_ids))
        .subquery()
    )
    observations = list(
        session.scalars(
            select(DataObservation)
            .join(ranked, ranked.c.observation_id == DataObservation.id)
            .options(selectinload(DataObservation.revisions))
            .where(ranked.c.rank <= 2)
            .order_by(
                DataObservation.series_id,
                DataObservation.observed_at.desc(),
                DataObservation.id.desc(),
            )
        ).unique()
    )
    by_series: dict[int, list[DataObservation]] = {}
    for observation in observations:
        by_series.setdefault(observation.series_id, []).append(observation)
    return by_code, by_series


def _load_derived(session: Session, codes: set[str]) -> dict[str, _DerivedResult]:
    if not codes:
        return {}
    definitions = list(
        session.scalars(
            select(DerivedSeriesDefinition)
            .where(DerivedSeriesDefinition.code.in_(codes))
            .order_by(DerivedSeriesDefinition.code, DerivedSeriesDefinition.id)
        )
    )
    if not definitions:
        return {}
    definition_ids = [item.id for item in definitions]
    ranked_versions = (
        select(
            DerivedSeriesDefinitionVersion.id.label("version_id"),
            func.row_number()
            .over(
                partition_by=DerivedSeriesDefinitionVersion.definition_id,
                order_by=(
                    DerivedSeriesDefinitionVersion.version.desc(),
                    DerivedSeriesDefinitionVersion.id.desc(),
                ),
            )
            .label("rank"),
        )
        .where(DerivedSeriesDefinitionVersion.definition_id.in_(definition_ids))
        .subquery()
    )
    versions = list(
        session.scalars(
            select(DerivedSeriesDefinitionVersion)
            .join(
                ranked_versions,
                ranked_versions.c.version_id == DerivedSeriesDefinitionVersion.id,
            )
            .where(ranked_versions.c.rank == 1)
        )
    )
    versions_by_definition = {item.definition_id: item for item in versions}
    version_ids = [item.id for item in versions]
    runs: list[AnalyticsRun] = []
    if version_ids:
        ranked_runs = (
            select(
                AnalyticsRun.id.label("run_id"),
                func.row_number()
                .over(
                    partition_by=AnalyticsRun.definition_version_id,
                    order_by=(AnalyticsRun.completed_at.desc(), AnalyticsRun.id.desc()),
                )
                .label("rank"),
            )
            .where(
                AnalyticsRun.definition_version_id.in_(version_ids),
                AnalyticsRun.status == "succeeded",
            )
            .subquery()
        )
        runs = list(
            session.scalars(
                select(AnalyticsRun)
                .join(ranked_runs, ranked_runs.c.run_id == AnalyticsRun.id)
                .where(ranked_runs.c.rank == 1)
            )
        )
    runs_by_version = {item.definition_version_id: item for item in runs}
    run_ids = [item.id for item in runs]
    observations: list[DerivedObservation] = []
    if run_ids:
        ranked_observations = (
            select(
                DerivedObservation.id.label("observation_id"),
                func.row_number()
                .over(
                    partition_by=DerivedObservation.run_id,
                    order_by=(
                        DerivedObservation.observed_at.desc(),
                        DerivedObservation.id.desc(),
                    ),
                )
                .label("rank"),
            )
            .where(DerivedObservation.run_id.in_(run_ids))
            .subquery()
        )
        observations = list(
            session.scalars(
                select(DerivedObservation)
                .join(
                    ranked_observations,
                    ranked_observations.c.observation_id == DerivedObservation.id,
                )
                .where(ranked_observations.c.rank == 1)
            )
        )
    observations_by_run = {item.run_id: item for item in observations}
    resolved: dict[str, _DerivedResult] = {}
    for definition in definitions:
        version = versions_by_definition.get(definition.id)
        if version is None:
            continue
        run = runs_by_version.get(version.id)
        resolved[definition.code] = _DerivedResult(
            definition=definition,
            version=version,
            run=run,
            observation=observations_by_run.get(run.id) if run is not None else None,
        )
    return resolved


def _freshness(
    policy: DashboardFreshnessPolicy,
    series: DataSeries | None,
    observed_at: datetime | None,
    analytics_completed_at: datetime | None,
    generated_at: datetime,
) -> DashboardFreshness:
    if observed_at is None:
        return DashboardFreshness(
            policy=policy.type,
            status=DashboardFreshnessStatus.unavailable,
            stale_after_days=None,
            age_basis=policy.age_basis,
            evaluated_at=generated_at,
        )
    if policy.type == DashboardFreshnessPolicyType.not_configured:
        return DashboardFreshness(
            policy=policy.type,
            status=DashboardFreshnessStatus.not_configured,
            stale_after_days=None,
            age_basis=policy.age_basis,
            evaluated_at=generated_at,
        )
    if policy.type == DashboardFreshnessPolicyType.raw_series_stale_after_days:
        stale_after = series.stale_after_days if series is not None else None
        age_timestamp: datetime | None = observed_at
    else:
        stale_after = policy.stale_after_days
        age_timestamp = (
            observed_at
            if policy.age_basis == DashboardFreshnessAgeBasis.observed_at
            else analytics_completed_at
        )
    if stale_after is None or age_timestamp is None:
        status = DashboardFreshnessStatus.not_configured
    else:
        age_days = max((generated_at.date() - age_timestamp.date()).days, 0)
        status = (
            DashboardFreshnessStatus.stale
            if age_days > stale_after
            else (DashboardFreshnessStatus.current)
        )
    return DashboardFreshness(
        policy=policy.type,
        status=status,
        stale_after_days=stale_after,
        age_basis=policy.age_basis,
        evaluated_at=generated_at,
    )


def _empty_comparison(metric: DashboardMetricDefinition) -> DashboardComparison:
    return DashboardComparison(
        type=metric.comparison.type,
        basis_code=metric.comparison.basis_code,
        basis_label_fa=metric.comparison.basis_label_fa,
        anchor_policy=metric.comparison.anchor_policy,
        state=DashboardComparisonState.missing,
        state_reason="metric_unavailable",
    )


def _quantized(value: Decimal) -> Decimal:
    rounded = value.quantize(_QUANTUM, rounding=ROUND_HALF_EVEN)
    if rounded < MIN_DATA_VALUE or rounded > MAX_DATA_VALUE:
        raise InvalidOperation
    return rounded


def _previous_comparison(
    metric: DashboardMetricDefinition,
    current_value: Decimal,
    current_observed_at: datetime,
    previous: DataObservation | None,
) -> DashboardComparison:
    base = {
        "type": metric.comparison.type,
        "basis_code": metric.comparison.basis_code,
        "basis_label_fa": metric.comparison.basis_label_fa,
        "anchor_policy": metric.comparison.anchor_policy,
        "current_observed_at": current_observed_at,
    }
    if previous is None:
        return DashboardComparison(
            **base,
            state=DashboardComparisonState.incomparable,
            state_reason="previous_observation_missing",
        )
    previous_read = macro_data_services.observation_to_read(previous)
    if previous_read.status != ObservationStatus.present or previous_read.value is None:
        return DashboardComparison(
            **base,
            state=DashboardComparisonState.incomparable,
            state_reason="previous_observation_has_no_value",
            reference_observation_id=previous.id,
        )
    try:
        absolute = _quantized(current_value - previous_read.value)
    except (InvalidOperation, OverflowError):
        return DashboardComparison(
            **base,
            state=DashboardComparisonState.incomparable,
            state_reason="absolute_change_not_representable",
            reference_observation_id=previous.id,
            reference_observed_at=previous_read.observed_at,
            reference_value=previous_read.value,
        )
    percentage: Decimal | None = None
    state = DashboardComparisonState.available
    reason = None
    if previous_read.value == 0:
        state = DashboardComparisonState.incomparable
        reason = "percentage_reference_is_zero"
    else:
        try:
            percentage = _quantized((absolute / previous_read.value) * Decimal(100))
        except (InvalidOperation, OverflowError):
            state = DashboardComparisonState.incomparable
            reason = "percentage_change_not_representable"
    return DashboardComparison(
        **base,
        state=state,
        state_reason=reason,
        reference_observation_id=previous.id,
        reference_observed_at=previous_read.observed_at,
        reference_value=previous_read.value,
        absolute_change=absolute,
        percentage_change=percentage,
    )


def _derived_identity(code: str, result: _DerivedResult | None) -> DerivedDashboardIdentity:
    if result is None:
        return DerivedDashboardIdentity(
            definition_id=None,
            definition_code=code,
            definition_version=None,
            run_id=None,
            observation_id=None,
        )
    return DerivedDashboardIdentity(
        definition_id=result.definition.id,
        definition_code=code,
        definition_version=result.version.version,
        run_id=result.run.id if result.run is not None else None,
        observation_id=result.observation.id if result.observation is not None else None,
    )


def _existing_derived_comparison(
    metric: DashboardMetricDefinition,
    raw_frequency: DataFrequency,
    current_observed_at: datetime,
    derived: dict[str, _DerivedResult],
) -> DashboardComparison:
    code = metric.comparison.derived_definition_code
    assert code is not None
    result = derived.get(code)
    base = {
        "type": metric.comparison.type,
        "basis_code": metric.comparison.basis_code,
        "basis_label_fa": metric.comparison.basis_label_fa,
        "anchor_policy": metric.comparison.anchor_policy,
        "current_observed_at": current_observed_at,
        "derived_identity": _derived_identity(code, result),
    }
    if result is None or result.run is None or result.observation is None:
        return DashboardComparison(
            **base,
            state=DashboardComparisonState.missing,
            state_reason="derived_comparison_missing",
        )
    if DataFrequency(result.version.output_frequency) != raw_frequency:
        return DashboardComparison(
            **base,
            state=DashboardComparisonState.frequency_mismatch,
            state_reason="derived_comparison_frequency_mismatch",
        )
    if result.observation.observed_at.astimezone(UTC) != current_observed_at.astimezone(UTC):
        return DashboardComparison(
            **base,
            state=DashboardComparisonState.incomparable,
            state_reason="derived_comparison_anchor_mismatch",
            derived_observed_at=result.observation.observed_at.astimezone(UTC),
            derived_calculation_cutoff=result.run.calculation_cutoff,
            derived_completed_at=result.run.completed_at,
        )
    if result.observation.status != "present" or result.observation.value is None:
        return DashboardComparison(
            **base,
            state=DashboardComparisonState.missing,
            state_reason=result.observation.missing_reason or "derived_comparison_missing",
        )
    return DashboardComparison(
        **base,
        state=DashboardComparisonState.available,
        state_reason=None,
        derived_value=result.observation.value,
        derived_observed_at=result.observation.observed_at.astimezone(UTC),
        derived_calculation_cutoff=result.run.calculation_cutoff,
        derived_completed_at=result.run.completed_at,
    )


def _raw_summary(
    metric: DashboardMetricDefinition,
    series_by_code: dict[str, DataSeries],
    observations_by_series: dict[int, list[DataObservation]],
    derived: dict[str, _DerivedResult],
    generated_at: datetime,
) -> DashboardMetricSummary:
    code = metric.raw_series_code
    assert code is not None
    series = series_by_code.get(code)
    observations = observations_by_series.get(series.id, []) if series is not None else []
    current = observations[0] if observations else None
    current_read = macro_data_services.observation_to_read(current) if current is not None else None
    raw_identity = RawDashboardIdentity(
        series_id=series.id if series is not None else None,
        series_code=code,
        observation_id=current.id if current is not None else None,
    )
    if series is None or current_read is None:
        return DashboardMetricSummary(
            metric_key=metric.metric_key,
            kind=metric.kind,
            label_fa=metric.label_fa,
            subtitle_fa=metric.subtitle_fa,
            state=DashboardMetricState.missing,
            state_reason="configured_series_missing" if series is None else "observation_missing",
            value=None,
            unit=series.unit if series is not None else None,
            localized_unit_label=metric.localized_unit_label,
            frequency=series.frequency if series is not None else None,
            geography=series.geography if series is not None else None,
            currency=series.currency if series is not None else None,
            observed_at=None,
            source_publication_timestamp=None,
            knowledge_cutoff=None,
            calculation_cutoff=None,
            analytics_completed_at=None,
            source=None,
            comparison=_empty_comparison(metric),
            freshness=_freshness(
                metric.freshness_policy,
                series,
                None,
                None,
                generated_at,
            ),
            raw_identity=raw_identity,
            derived_identity=None,
        )
    source = DashboardSourceAttribution(
        source_id=series.source.id,
        source_code=series.source.code,
        source_name=series.source.name,
        reference_url=series.source.reference_url,
        source_reference=current_read.source_reference,
    )
    point_available = (
        current_read.status == ObservationStatus.present and current_read.value is not None
    )
    if not point_available:
        comparison = _empty_comparison(metric)
    elif metric.comparison.type == DashboardComparisonType.previous_observation:
        assert current_read.value is not None
        comparison = _previous_comparison(
            metric,
            current_read.value,
            current_read.observed_at,
            observations[1] if len(observations) > 1 else None,
        )
    elif metric.comparison.type == DashboardComparisonType.existing_derived_metric:
        comparison = _existing_derived_comparison(
            metric,
            series.frequency,
            current_read.observed_at,
            derived,
        )
    else:
        comparison = DashboardComparison(
            type=metric.comparison.type,
            basis_code=metric.comparison.basis_code,
            basis_label_fa=metric.comparison.basis_label_fa,
            anchor_policy=metric.comparison.anchor_policy,
            state=DashboardComparisonState.available,
            state_reason=None,
            current_observed_at=current_read.observed_at,
        )
    freshness = _freshness(
        metric.freshness_policy,
        series,
        current_read.observed_at if point_available else None,
        None,
        generated_at,
    )
    if not point_available:
        state = DashboardMetricState.missing
        reason = "current_observation_missing"
    elif freshness.status == DashboardFreshnessStatus.stale:
        state = DashboardMetricState.stale
        reason = "series_stale"
    else:
        state = DashboardMetricState.available
        reason = None
    return DashboardMetricSummary(
        metric_key=metric.metric_key,
        kind=metric.kind,
        label_fa=metric.label_fa,
        subtitle_fa=metric.subtitle_fa,
        state=state,
        state_reason=reason,
        value=current_read.value,
        unit=series.unit,
        localized_unit_label=metric.localized_unit_label,
        frequency=series.frequency,
        geography=series.geography,
        currency=series.currency,
        observed_at=current_read.observed_at,
        source_publication_timestamp=current_read.publication_timestamp,
        knowledge_cutoff=current_read.ingestion_timestamp,
        calculation_cutoff=None,
        analytics_completed_at=None,
        source=source,
        comparison=comparison,
        freshness=freshness,
        raw_identity=raw_identity,
        derived_identity=None,
    )


def _derived_summary(
    metric: DashboardMetricDefinition,
    derived: dict[str, _DerivedResult],
    generated_at: datetime,
) -> DashboardMetricSummary:
    code = metric.derived_definition_code
    assert code is not None
    result = derived.get(code)
    identity = _derived_identity(code, result)
    run = result.run if result is not None else None
    observation = result.observation if result is not None else None
    available = (
        result is not None
        and run is not None
        and observation is not None
        and observation.status == "present"
        and observation.value is not None
    )
    freshness = _freshness(
        metric.freshness_policy,
        None,
        observation.observed_at if available and observation is not None else None,
        run.completed_at if run is not None else None,
        generated_at,
    )
    metric_state = (
        DashboardMetricState.missing
        if not available
        else (
            DashboardMetricState.stale
            if freshness.status == DashboardFreshnessStatus.stale
            else DashboardMetricState.available
        )
    )
    return DashboardMetricSummary(
        metric_key=metric.metric_key,
        kind=metric.kind,
        label_fa=metric.label_fa,
        subtitle_fa=metric.subtitle_fa,
        state=metric_state,
        state_reason=(
            "persisted_derived_result_missing"
            if not available
            else ("derived_result_stale" if metric_state == DashboardMetricState.stale else None)
        ),
        value=observation.value if available and observation is not None else None,
        unit=result.version.output_unit if result is not None else None,
        localized_unit_label=metric.localized_unit_label,
        frequency=(DataFrequency(result.version.output_frequency) if result is not None else None),
        geography=result.version.output_geography if result is not None else None,
        currency=result.version.output_currency if result is not None else None,
        observed_at=(observation.observed_at.astimezone(UTC) if observation is not None else None),
        source_publication_timestamp=None,
        knowledge_cutoff=run.calculation_cutoff if run is not None else None,
        calculation_cutoff=run.calculation_cutoff if run is not None else None,
        analytics_completed_at=run.completed_at if run is not None else None,
        source=None,
        comparison=DashboardComparison(
            type=metric.comparison.type,
            basis_code=metric.comparison.basis_code,
            basis_label_fa=metric.comparison.basis_label_fa,
            anchor_policy=metric.comparison.anchor_policy,
            state=(
                DashboardComparisonState.available
                if available
                else DashboardComparisonState.missing
            ),
            state_reason=None if available else "persisted_derived_result_missing",
            current_observed_at=observation.observed_at if observation is not None else None,
        ),
        freshness=freshness,
        raw_identity=None,
        derived_identity=identity,
    )


def dashboard_summary(
    session: Session, dashboard_code: str, *, now: datetime | None = None
) -> DashboardSummary:
    dashboard = get_dashboard(dashboard_code)
    generated_at = now or datetime.now(UTC)
    series_by_code, observations_by_series = _load_raw(session, _raw_codes(dashboard))
    derived = _load_derived(session, _derived_codes(dashboard))
    groups: list[DashboardGroupSummary] = []
    for group in dashboard.groups:
        metrics = [
            (
                _raw_summary(
                    metric,
                    series_by_code,
                    observations_by_series,
                    derived,
                    generated_at,
                )
                if metric.kind == DashboardMetricKind.raw
                else _derived_summary(metric, derived, generated_at)
            )
            for metric in group.metrics
        ]
        groups.append(
            DashboardGroupSummary(
                group_code=group.group_code,
                title_fa=group.title_fa,
                metrics=metrics,
            )
        )
    cutoffs = [
        metric.knowledge_cutoff
        for group in groups
        for metric in group.metrics
        if metric.knowledge_cutoff is not None
    ]
    return DashboardSummary(
        dashboard_code=dashboard.dashboard_code,
        generated_at=generated_at,
        latest_knowledge_cutoff=max(cutoffs) if cutoffs else None,
        stale_metric_count=sum(
            metric.freshness.status == DashboardFreshnessStatus.stale
            for group in groups
            for metric in group.metrics
        ),
        groups=groups,
    )
