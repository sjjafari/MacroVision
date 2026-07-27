"""Strict public contracts for the Macro Analytics API."""

from datetime import datetime
from enum import StrEnum

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from macrovision.analytics_schemas import (
    TransformationParameters,
    TransformationType,
    canonical_code,
)
from macrovision.contracts import utc_timestamp
from macrovision.macro_data_models import DataFrequency, SeasonalAdjustment
from macrovision.macro_data_schemas import DataDecimal


class PublicAnalyticsModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class AnalyticsRunStatus(StrEnum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class AnalyticsExecutionDisposition(StrEnum):
    created = "created"
    active_existing = "active_existing"
    completed_existing = "completed_existing"


class DerivedSeriesInputCreate(PublicAnalyticsModel):
    alias: str = Field(min_length=1, max_length=40, pattern=r"^[a-z][a-z0-9_]{0,39}$")
    source_series_id: int = Field(gt=0)


class DerivedSeriesVersionCreateBase(PublicAnalyticsModel):
    parameters: TransformationParameters
    inputs: list[DerivedSeriesInputCreate] = Field(min_length=1, max_length=2)
    change_note: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_ordered_inputs(self) -> "DerivedSeriesVersionCreateBase":
        from macrovision.analytics_transformations import validate_ordered_inputs

        validate_ordered_inputs(
            self.parameters.transformation_type,
            tuple(item.alias for item in self.inputs),
        )
        return self


class DerivedSeriesVersionCreate(DerivedSeriesVersionCreateBase):
    expected_lock_version: int = Field(gt=0)


class DerivedSeriesCreate(PublicAnalyticsModel):
    code: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=2000)
    enabled: bool = True
    initial_version: DerivedSeriesVersionCreateBase

    @field_validator("code", mode="before")
    @classmethod
    def normalize_code(cls, value: object) -> object:
        return canonical_code(value) if isinstance(value, str) else value


class DerivedSeriesPatch(PublicAnalyticsModel):
    expected_lock_version: int = Field(gt=0)
    title: str | None = Field(default=None, min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=2000)


class DerivedSeriesStateChange(PublicAnalyticsModel):
    expected_lock_version: int = Field(gt=0)


class DerivedSeriesInputRead(PublicAnalyticsModel):
    position: int
    alias: str
    source_series_id: int
    source_code: str
    source_unit: str
    source_frequency: DataFrequency
    source_geography: str
    source_currency: str | None
    source_seasonal_adjustment: SeasonalAdjustment
    created_at: datetime


class DerivedSeriesVersionSummary(PublicAnalyticsModel):
    id: int
    version: int
    transformation_type: TransformationType
    created_at: datetime
    change_note: str | None


class DerivedSeriesVersionRead(DerivedSeriesVersionSummary):
    parameters: TransformationParameters
    inputs: list[DerivedSeriesInputRead]
    output_unit: str
    output_frequency: DataFrequency
    output_geography: str
    output_currency: str | None
    output_seasonal_adjustment: SeasonalAdjustment
    engine_contract_version: str


class DerivedSeriesRead(PublicAnalyticsModel):
    id: int
    code: str
    title: str
    description: str | None
    enabled: bool
    lock_version: int
    current_version: DerivedSeriesVersionSummary
    created_at: datetime
    updated_at: datetime


class DerivedSeriesPage(PublicAnalyticsModel):
    items: list[DerivedSeriesRead]
    limit: int
    offset: int


class DerivedSeriesVersionPage(PublicAnalyticsModel):
    items: list[DerivedSeriesVersionSummary]
    limit: int
    offset: int


class AnalyticsExecutionCreate(PublicAnalyticsModel):
    definition_version: int | None = Field(default=None, gt=0)
    requested_start_at: datetime
    requested_end_at: datetime
    as_of: datetime | None = None
    retry_of_run_id: int | None = Field(default=None, gt=0)

    @field_validator("requested_start_at", "requested_end_at", "as_of")
    @classmethod
    def normalize_timestamp(cls, value: datetime | None) -> datetime | None:
        return utc_timestamp(value) if value is not None else None

    @model_validator(mode="after")
    def validate_range(self) -> "AnalyticsExecutionCreate":
        if self.requested_start_at > self.requested_end_at:
            raise ValueError("requested_start_at must not exceed requested_end_at")
        return self


class AnalyticsRunSummary(PublicAnalyticsModel):
    id: int
    definition_id: int
    definition_version_id: int
    definition_version: int
    status: AnalyticsRunStatus
    requested_start_at: datetime
    requested_end_at: datetime
    calculation_cutoff: datetime
    engine_version: str
    inputs_examined: int
    outputs_present: int
    outputs_missing: int
    lineage_links: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    error_code: str | None
    error_message: str | None
    retry_of_run_id: int | None


class AnalyticsRunRead(AnalyticsRunSummary):
    pass


class AnalyticsExecutionRead(PublicAnalyticsModel):
    disposition: AnalyticsExecutionDisposition
    run: AnalyticsRunRead


class AnalyticsRunPage(PublicAnalyticsModel):
    items: list[AnalyticsRunSummary]
    limit: int
    offset: int


class DerivedObservationRead(PublicAnalyticsModel):
    id: int
    run_id: int
    definition_version_id: int
    observed_at: datetime
    value: DataDecimal | None
    status: str
    missing_reason: str | None
    created_at: datetime


class DerivedObservationPage(PublicAnalyticsModel):
    run_id: int
    definition_id: int
    definition_version: int
    items: list[DerivedObservationRead]
    limit: int
    offset: int


class LatestDerivedObservationRead(PublicAnalyticsModel):
    run_id: int
    definition_id: int
    definition_version: int
    observation: DerivedObservationRead


class DerivedObservationLineageRead(PublicAnalyticsModel):
    id: int
    input_position: int
    input_alias: str
    lineage_position: int
    source_observation_id: int
    source_revision_id: int | None
    source_version_kind: str
    source_version_id: int
    source_knowledge_timestamp: datetime


class DerivedObservationLineagePage(PublicAnalyticsModel):
    run_id: int
    observation_id: int
    items: list[DerivedObservationLineageRead]
    limit: int
    offset: int
