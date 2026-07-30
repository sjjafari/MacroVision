from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

from macrovision.dashboard_schemas import DashboardComparison, DashboardFreshness
from macrovision.macro_data_models import DataFrequency, SeriesCategory
from macrovision.macro_data_schemas import DataDecimal


class IndicatorModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IndicatorCurationStatus(StrEnum):
    reviewed_private = "reviewed_private"
    withheld = "withheld"


class IndicatorAvailability(StrEnum):
    available = "available"
    configured_series_missing = "configured_series_missing"


class IndicatorSeasonalAdjustmentStatus(StrEnum):
    seasonally_adjusted = "seasonally_adjusted"
    not_seasonally_adjusted = "not_seasonally_adjusted"
    not_applicable = "not_applicable"
    unknown = "unknown"


class IndicatorSnapshotMode(StrEnum):
    current = "current"
    historical_as_of = "historical_as_of"


class IndicatorMetricState(StrEnum):
    available = "available"
    stale = "stale"
    missing = "missing"


class RelatedDerivedState(StrEnum):
    available = "available"
    definition_missing = "definition_missing"
    persisted_result_missing = "persisted_result_missing"
    definition_disabled = "definition_disabled"


class IndicatorRelationCode(StrEnum):
    year_over_year = "year_over_year"
    month_over_month = "month_over_month"
    change = "change"
    spread = "spread"


class IndicatorSourceSummary(IndicatorModel):
    source_id: int
    source_code: str
    source_name: str
    reference_url: str | None


class IndicatorCatalogItem(IndicatorModel):
    catalog_order: int
    curation_status: IndicatorCurationStatus
    availability: IndicatorAvailability
    series_id: int | None
    series_code: str
    display_name_fa: str
    original_name: str | None
    description_fa: str
    localized_unit_label: str | None
    category: SeriesCategory | None
    geography: str | None
    frequency: DataFrequency | None
    unit: str | None
    seasonal_adjustment_status: IndicatorSeasonalAdjustmentStatus
    operational_is_active: bool | None
    source: IndicatorSourceSummary | None
    editorial_updated_at: datetime


class IndicatorCatalogPage(IndicatorModel):
    limit: int
    offset: int
    total: int
    items: list[IndicatorCatalogItem]


class IndicatorCurationRead(IndicatorModel):
    curation_status: IndicatorCurationStatus
    catalog_order: int
    editorial_updated_at: datetime
    private_preview: bool = True
    public_eligibility: bool = False


class IndicatorPresentationRead(IndicatorModel):
    display_name_fa: str
    original_name: str
    description_fa: str
    methodology_summary_fa: str
    localized_unit_label: str
    source_attribution_fa: str
    seasonal_adjustment_status: IndicatorSeasonalAdjustmentStatus
    source_methodology_url: str | None


class IndicatorCanonicalRead(IndicatorModel):
    series_id: int
    series_code: str
    name: str
    description: str
    category: SeriesCategory
    geography: str
    frequency: DataFrequency
    unit: str
    currency: str | None
    is_active: bool
    stale_after_days: int | None
    created_at: datetime
    updated_at: datetime


class IndicatorSourceRead(IndicatorSourceSummary):
    description: str


class IndicatorDetail(IndicatorModel):
    curation: IndicatorCurationRead
    presentation: IndicatorPresentationRead
    canonical: IndicatorCanonicalRead
    source: IndicatorSourceRead


class IndicatorObservationIdentity(IndicatorModel):
    series_id: int
    observation_id: int
    revision_count: int


class IndicatorSnapshot(IndicatorModel):
    mode: IndicatorSnapshotMode
    requested_as_of: datetime | None
    generated_at: datetime
    state: IndicatorMetricState
    state_reason: str | None
    value: DataDecimal | None
    observation_identity: IndicatorObservationIdentity | None
    observed_at: datetime | None
    source_publication_timestamp: datetime | None
    knowledge_cutoff: datetime | None
    unit: str
    localized_unit_label: str
    frequency: DataFrequency
    geography: str
    source: IndicatorSourceSummary
    source_attribution_fa: str
    freshness: DashboardFreshness
    comparison: DashboardComparison


class RelatedDerivedItem(IndicatorModel):
    relation_code: IndicatorRelationCode
    relation_label_fa: str
    description_fa: str
    state: RelatedDerivedState
    definition_id: int | None
    definition_code: str
    definition_version: int | None
    enabled: bool | None
    value: DataDecimal | None
    observed_at: datetime | None
    run_id: int | None
    observation_id: int | None
    calculation_cutoff: datetime | None
    completed_at: datetime | None
    missing_reason: str | None


class RelatedDerivedRead(IndicatorModel):
    series_id: int
    series_code: str
    items: list[RelatedDerivedItem]


IndicatorSearch = Annotated[str, Field(min_length=1, max_length=120)]
PositiveSourceId = Annotated[int, Field(gt=0)]

# OpenAPI must retain exact data values as strings at the transport boundary.
ExactIndicatorDecimal = Annotated[
    DataDecimal,
    PlainSerializer(lambda value: format(value, ".8f"), return_type=str, when_used="json"),
]
