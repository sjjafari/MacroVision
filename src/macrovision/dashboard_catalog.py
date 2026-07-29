"""Reviewed private dashboard curation.

This catalog is deliberately code-owned. It is not publication eligibility and
does not discover series from the database.
"""

from collections.abc import Iterable

from macrovision.dashboard_schemas import (
    DashboardCode,
    DashboardComparisonAnchorPolicy,
    DashboardComparisonDefinition,
    DashboardComparisonType,
    DashboardDefinition,
    DashboardFreshnessAgeBasis,
    DashboardFreshnessPolicy,
    DashboardFreshnessPolicyType,
    DashboardGroupCode,
    DashboardGroupDefinition,
    DashboardMetricDefinition,
    DashboardMetricKind,
    raw_freshness_policy,
)


def _comparison(
    comparison_type: DashboardComparisonType,
    basis_code: str,
    basis_label_fa: str,
    *,
    derived_definition_code: str | None = None,
) -> DashboardComparisonDefinition:
    anchor_policy = {
        DashboardComparisonType.none: DashboardComparisonAnchorPolicy.not_applicable,
        DashboardComparisonType.previous_observation: (
            DashboardComparisonAnchorPolicy.previous_observation
        ),
        DashboardComparisonType.existing_derived_metric: (
            DashboardComparisonAnchorPolicy.same_observed_at
        ),
    }[comparison_type]
    return DashboardComparisonDefinition(
        type=comparison_type,
        basis_code=basis_code,
        basis_label_fa=basis_label_fa,
        anchor_policy=anchor_policy,
        derived_definition_code=derived_definition_code,
    )


NO_COMPARISON = _comparison(
    DashboardComparisonType.none,
    "no_comparison",
    "بدون مقایسه",
)
PREVIOUS = _comparison(
    DashboardComparisonType.previous_observation,
    "previous_observation",
    "در مقایسه با مشاهدهٔ قبلی",
)


def _raw(
    metric_key: str,
    series_code: str,
    label_fa: str,
    *,
    subtitle_fa: str | None = None,
    localized_unit_label: str | None = None,
    comparison: DashboardComparisonDefinition = PREVIOUS,
    featured_chart: bool = False,
) -> DashboardMetricDefinition:
    return DashboardMetricDefinition(
        metric_key=metric_key,
        kind=DashboardMetricKind.raw,
        raw_series_code=series_code,
        label_fa=label_fa,
        subtitle_fa=subtitle_fa,
        localized_unit_label=localized_unit_label,
        comparison=comparison,
        freshness_policy=raw_freshness_policy(),
        featured_chart=featured_chart,
    )


def _derived(
    metric_key: str,
    definition_code: str,
    label_fa: str,
    *,
    subtitle_fa: str | None = None,
    localized_unit_label: str | None = None,
    featured_chart: bool = False,
) -> DashboardMetricDefinition:
    return DashboardMetricDefinition(
        metric_key=metric_key,
        kind=DashboardMetricKind.derived,
        derived_definition_code=definition_code,
        label_fa=label_fa,
        subtitle_fa=subtitle_fa,
        localized_unit_label=localized_unit_label,
        comparison=NO_COMPARISON,
        freshness_policy=DashboardFreshnessPolicy(
            type=DashboardFreshnessPolicyType.not_configured,
            age_basis=DashboardFreshnessAgeBasis.not_applicable,
        ),
        featured_chart=featured_chart,
    )


def _group(
    code: DashboardGroupCode,
    title_fa: str,
    *metrics: DashboardMetricDefinition,
) -> DashboardGroupDefinition:
    return DashboardGroupDefinition(group_code=code, title_fa=title_fa, metrics=metrics)


_CPI_DERIVED_COMPARISON = _comparison(
    DashboardComparisonType.existing_derived_metric,
    "year_over_year",
    "تغییر سالانهٔ محاسبه‌شده",
    derived_definition_code="ANALYTICS.CPI.YOY",
)


DASHBOARD_CATALOG = (
    DashboardDefinition(
        dashboard_code=DashboardCode.home,
        title_fa="نمای اصلی",
        description_fa="خلاصهٔ گزینش‌شده از وضعیت اقتصاد کلان و بازارها",
        groups=(
            _group(
                DashboardGroupCode.inflation,
                "تورم",
                _raw(
                    "headline_cpi",
                    "FRED.CPIAUCSL",
                    "شاخص قیمت مصرف‌کننده",
                    comparison=_CPI_DERIVED_COMPARISON,
                    featured_chart=True,
                ),
            ),
            _group(
                DashboardGroupCode.interest_rates,
                "نرخ‌های بهره",
                _raw("policy_rate", "FRED.FEDFUNDS", "نرخ وجوه فدرال"),
            ),
            _group(
                DashboardGroupCode.economic_growth,
                "رشد اقتصادی",
                _derived(
                    "real_gdp_yoy",
                    "ANALYTICS.GDP.YOY",
                    "رشد سالانهٔ تولید ناخالص داخلی واقعی",
                    localized_unit_label="درصد",
                ),
            ),
        ),
    ),
    DashboardDefinition(
        dashboard_code=DashboardCode.markets,
        title_fa="بازارها",
        description_fa="نمای گزینش‌شده از ارز، انرژی و شرایط مالی",
        groups=(
            _group(
                DashboardGroupCode.currencies,
                "ارزها",
                _raw("usd_eur", "FRED.DEXUSEU", "نرخ برابری یورو به دلار"),
            ),
            _group(
                DashboardGroupCode.commodities_energy,
                "کالا و انرژی",
                _raw("wti_oil", "FRED.DCOILWTICO", "نفت خام WTI"),
            ),
            _group(
                DashboardGroupCode.financial_conditions,
                "شرایط مالی",
                _raw("financial_conditions", "FRED.NFCI", "شاخص شرایط مالی"),
            ),
            _group(
                DashboardGroupCode.geopolitical_risk,
                "ریسک ژئوپلیتیک",
                _raw("global_policy_uncertainty", "FRED.GEPUCURRENT", "عدم‌قطعیت سیاستی جهان"),
            ),
        ),
    ),
    DashboardDefinition(
        dashboard_code=DashboardCode.macro,
        title_fa="اقتصاد کلان",
        description_fa="داشبورد گزینش‌شدهٔ تورم، رشد، نقدینگی و ریسک",
        groups=(
            _group(
                DashboardGroupCode.inflation,
                "تورم",
                _raw("cpi_level", "FRED.CPIAUCSL", "سطح شاخص قیمت مصرف‌کننده"),
                _derived(
                    "cpi_yoy",
                    "ANALYTICS.CPI.YOY",
                    "تورم سالانه",
                    localized_unit_label="درصد",
                    featured_chart=True,
                ),
            ),
            _group(
                DashboardGroupCode.interest_rates,
                "نرخ‌های بهره",
                _raw("federal_funds_rate", "FRED.FEDFUNDS", "نرخ وجوه فدرال"),
            ),
            _group(
                DashboardGroupCode.labor_market,
                "بازار کار",
                _raw("unemployment_rate", "FRED.UNRATE", "نرخ بیکاری"),
            ),
            _group(
                DashboardGroupCode.economic_growth,
                "رشد اقتصادی",
                _derived("gdp_yoy", "ANALYTICS.GDP.YOY", "رشد سالانهٔ تولید واقعی"),
            ),
            _group(
                DashboardGroupCode.liquidity_money,
                "نقدینگی و پول",
                _raw("money_supply_m2", "FRED.M2SL", "حجم پول M2"),
            ),
            _group(
                DashboardGroupCode.yield_curve,
                "منحنی بازده",
                _derived(
                    "yield_curve_10y2y",
                    "ANALYTICS.YIELD_CURVE.10Y2Y",
                    "شیب منحنی بازده ۱۰ساله به ۲ساله",
                ),
            ),
            _group(
                DashboardGroupCode.currencies,
                "ارزها",
                _raw("euro_usd", "FRED.DEXUSEU", "نرخ برابری یورو به دلار"),
            ),
            _group(
                DashboardGroupCode.commodities_energy,
                "کالا و انرژی",
                _raw("crude_oil_wti", "FRED.DCOILWTICO", "نفت خام WTI"),
            ),
            _group(
                DashboardGroupCode.financial_conditions,
                "شرایط مالی",
                _raw("nfci", "FRED.NFCI", "شاخص شرایط مالی"),
            ),
            _group(
                DashboardGroupCode.geopolitical_risk,
                "ریسک ژئوپلیتیک",
                _raw("geopolitical_uncertainty", "FRED.GEPUCURRENT", "عدم‌قطعیت سیاستی جهان"),
            ),
        ),
    ),
)


def validate_dashboard_catalog(
    definitions: Iterable[DashboardDefinition],
) -> tuple[DashboardDefinition, ...]:
    catalog = tuple(definitions)
    codes = [definition.dashboard_code for definition in catalog]
    if len(codes) != len(set(codes)):
        raise ValueError("dashboard codes must be unique")
    if set(codes) != set(DashboardCode):
        raise ValueError("private dashboard catalog must define home, markets, and macro")
    return catalog


VALIDATED_DASHBOARD_CATALOG = validate_dashboard_catalog(DASHBOARD_CATALOG)
DASHBOARDS_BY_CODE = {
    dashboard.dashboard_code: dashboard for dashboard in VALIDATED_DASHBOARD_CATALOG
}
