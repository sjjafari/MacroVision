"""Private, read-only dashboard contracts for the Web MVP."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from macrovision.macro_data_models import DataFrequency
from macrovision.macro_data_schemas import DataDecimal


class DashboardCode(StrEnum):
    home = "home"
    markets = "markets"
    macro = "macro"


class DashboardGroupCode(StrEnum):
    inflation = "inflation"
    interest_rates = "interest_rates"
    labor_market = "labor_market"
    economic_growth = "economic_growth"
    liquidity_money = "liquidity_money"
    yield_curve = "yield_curve"
    currencies = "currencies"
    commodities_energy = "commodities_energy"
    financial_conditions = "financial_conditions"
    geopolitical_risk = "geopolitical_risk"


class DashboardMetricKind(StrEnum):
    raw = "raw"
    derived = "derived"


class DashboardComparisonType(StrEnum):
    none = "none"
    previous_observation = "previous_observation"
    existing_derived_metric = "existing_derived_metric"


class DashboardMetricState(StrEnum):
    available = "available"
    missing = "missing"
    stale = "stale"
    incomparable = "incomparable"
    frequency_mismatch = "frequency_mismatch"


class DashboardFreshnessStatus(StrEnum):
    current = "current"
    stale = "stale"
    not_configured = "not_configured"
    unavailable = "unavailable"


class DashboardModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DashboardComparisonDefinition(DashboardModel):
    type: DashboardComparisonType
    basis_code: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    basis_label_fa: str = Field(min_length=1, max_length=160)
    derived_definition_code: str | None = Field(
        default=None,
        min_length=1,
        max_length=120,
        pattern=r"^[A-Z][A-Z0-9_.-]*$",
    )

    @model_validator(mode="after")
    def validate_derived_reference(self) -> "DashboardComparisonDefinition":
        requires_code = self.type == DashboardComparisonType.existing_derived_metric
        if requires_code != (self.derived_definition_code is not None):
            raise ValueError("existing_derived_metric alone requires derived_definition_code")
        return self


class DashboardFreshnessPolicy(DashboardModel):
    basis: str = Field(
        default="series_stale_after_days",
        pattern=r"^series_stale_after_days$",
    )


class DashboardMetricDefinition(DashboardModel):
    metric_key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    kind: DashboardMetricKind
    raw_series_code: str | None = Field(
        default=None,
        min_length=1,
        max_length=120,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )
    derived_definition_code: str | None = Field(
        default=None,
        min_length=1,
        max_length=120,
        pattern=r"^[A-Z][A-Z0-9_.-]*$",
    )
    label_fa: str = Field(min_length=1, max_length=160)
    subtitle_fa: str | None = Field(default=None, max_length=240)
    localized_unit_label: str | None = Field(default=None, max_length=80)
    comparison: DashboardComparisonDefinition
    freshness_policy: DashboardFreshnessPolicy = Field(default_factory=DashboardFreshnessPolicy)
    featured_chart: bool = False

    @model_validator(mode="after")
    def validate_identity(self) -> "DashboardMetricDefinition":
        raw = self.raw_series_code is not None
        derived = self.derived_definition_code is not None
        if self.kind == DashboardMetricKind.raw and (not raw or derived):
            raise ValueError("raw metrics require only raw_series_code")
        if self.kind == DashboardMetricKind.derived and (raw or not derived):
            raise ValueError("derived metrics require only derived_definition_code")
        if (
            self.kind == DashboardMetricKind.derived
            and self.comparison.type != DashboardComparisonType.none
        ):
            raise ValueError("derived dashboard metrics must use comparison type none")
        return self


class DashboardGroupDefinition(DashboardModel):
    group_code: DashboardGroupCode
    title_fa: str = Field(min_length=1, max_length=160)
    metrics: tuple[DashboardMetricDefinition, ...] = Field(min_length=1, max_length=12)


class DashboardDefinition(DashboardModel):
    dashboard_code: DashboardCode
    title_fa: str = Field(min_length=1, max_length=160)
    description_fa: str = Field(min_length=1, max_length=500)
    groups: tuple[DashboardGroupDefinition, ...] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def validate_unique_configuration(self) -> "DashboardDefinition":
        group_codes = [group.group_code for group in self.groups]
        if len(group_codes) != len(set(group_codes)):
            raise ValueError("dashboard group codes must be unique")
        metric_keys = [metric.metric_key for group in self.groups for metric in group.metrics]
        if len(metric_keys) != len(set(metric_keys)):
            raise ValueError("dashboard metric keys must be unique")
        featured_count = sum(
            metric.featured_chart for group in self.groups for metric in group.metrics
        )
        if featured_count > 1:
            raise ValueError("a dashboard may contain at most one featured chart")
        return self


class DashboardSourceAttribution(DashboardModel):
    source_id: int
    source_code: str
    source_name: str
    reference_url: str | None
    source_reference: str | None


class RawDashboardIdentity(DashboardModel):
    series_id: int | None
    series_code: str
    observation_id: int | None


class DerivedDashboardIdentity(DashboardModel):
    definition_id: int | None
    definition_code: str
    definition_version: int | None
    run_id: int | None
    observation_id: int | None


class DashboardFreshness(DashboardModel):
    status: DashboardFreshnessStatus
    stale_after_days: int | None
    age_basis: str
    evaluated_at: datetime


class DashboardComparison(DashboardModel):
    type: DashboardComparisonType
    basis_code: str
    basis_label_fa: str
    state: DashboardMetricState
    state_reason: str | None
    reference_observation_id: int | None = None
    reference_observed_at: datetime | None = None
    reference_value: DataDecimal | None = None
    derived_value: DataDecimal | None = None
    derived_observed_at: datetime | None = None
    derived_calculation_cutoff: datetime | None = None
    derived_completed_at: datetime | None = None
    absolute_change: DataDecimal | None = None
    percentage_change: DataDecimal | None = None
    derived_identity: DerivedDashboardIdentity | None = None


class DashboardMetricSummary(DashboardModel):
    metric_key: str
    kind: DashboardMetricKind
    label_fa: str
    subtitle_fa: str | None
    state: DashboardMetricState
    state_reason: str | None
    value: DataDecimal | None
    unit: str | None
    localized_unit_label: str | None
    frequency: DataFrequency | None
    geography: str | None
    currency: str | None
    observed_at: datetime | None
    source_publication_timestamp: datetime | None
    knowledge_cutoff: datetime | None
    calculation_cutoff: datetime | None
    analytics_completed_at: datetime | None
    source: DashboardSourceAttribution | None
    comparison: DashboardComparison
    freshness: DashboardFreshness
    raw_identity: RawDashboardIdentity | None
    derived_identity: DerivedDashboardIdentity | None


class DashboardGroupSummary(DashboardModel):
    group_code: DashboardGroupCode
    title_fa: str
    metrics: list[DashboardMetricSummary]


class DashboardSummary(DashboardModel):
    dashboard_code: DashboardCode
    generated_at: datetime
    latest_knowledge_cutoff: datetime | None
    stale_metric_count: int
    groups: list[DashboardGroupSummary]
