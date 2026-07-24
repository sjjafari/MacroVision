from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    field_validator,
    model_validator,
)

from macrovision.config import get_settings
from macrovision.contracts import utc_timestamp
from macrovision.macro_data_models import (
    DataFrequency,
    ImportStatus,
    ObservationStatus,
    QualityIssueStatus,
    QualityIssueType,
    SeasonalAdjustment,
    SeriesCategory,
)

MAX_DATA_VALUE = Decimal("92233720368.54775807")
MIN_DATA_VALUE = -MAX_DATA_VALUE

DataDecimal = Annotated[
    Decimal,
    Field(
        ge=MIN_DATA_VALUE,
        le=MAX_DATA_VALUE,
        decimal_places=8,
        allow_inf_nan=False,
    ),
    PlainSerializer(lambda value: format(value, ".8f"), return_type=str, when_used="json"),
]


def _aware_utc(value: datetime) -> datetime:
    return utc_timestamp(value)


class DataSourceCreate(BaseModel):
    code: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    name: str = Field(min_length=1, max_length=180)
    description: str = ""
    reference_url: str | None = Field(default=None, max_length=500)


class DataSourceRead(DataSourceCreate):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class DataSeriesCreate(BaseModel):
    source_id: int = Field(gt=0)
    code: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.-]+$")
    name: str = Field(min_length=1, max_length=240)
    description: str = ""
    category: SeriesCategory
    geography: str = Field(min_length=1, max_length=120)
    frequency: DataFrequency
    unit: str = Field(min_length=1, max_length=80)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    seasonal_adjustment: SeasonalAdjustment = SeasonalAdjustment.unknown
    publication_lag_days: int = Field(default=0, ge=0)
    is_active: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)
    minimum_value: DataDecimal | None = Field(default=None, decimal_places=8)
    maximum_value: DataDecimal | None = Field(default=None, decimal_places=8)
    max_change_percent: DataDecimal | None = Field(default=None, ge=0, decimal_places=8)
    stale_after_days: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_range(self) -> "DataSeriesCreate":
        if (
            self.minimum_value is not None
            and self.maximum_value is not None
            and self.minimum_value > self.maximum_value
        ):
            raise ValueError("minimum_value cannot exceed maximum_value")
        return self


class DataSeriesPatch(BaseModel):
    expected_lock_version: int = Field(gt=0)
    name: str | None = Field(default=None, min_length=1, max_length=240)
    description: str | None = None
    category: SeriesCategory | None = None
    geography: str | None = Field(default=None, min_length=1, max_length=120)
    frequency: DataFrequency | None = None
    unit: str | None = Field(default=None, min_length=1, max_length=80)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    seasonal_adjustment: SeasonalAdjustment | None = None
    publication_lag_days: int | None = Field(default=None, ge=0)
    is_active: bool | None = None
    metadata: dict[str, Any] | None = None
    minimum_value: DataDecimal | None = Field(default=None, decimal_places=8)
    maximum_value: DataDecimal | None = Field(default=None, decimal_places=8)
    max_change_percent: DataDecimal | None = Field(default=None, ge=0, decimal_places=8)
    stale_after_days: int | None = Field(default=None, gt=0)


class DataSeriesRead(BaseModel):
    id: int
    source_id: int
    code: str
    name: str
    description: str
    category: SeriesCategory
    geography: str
    frequency: DataFrequency
    unit: str
    currency: str | None
    seasonal_adjustment: SeasonalAdjustment
    publication_lag_days: int
    is_active: bool
    metadata: dict[str, Any]
    minimum_value: DataDecimal | None
    maximum_value: DataDecimal | None
    max_change_percent: DataDecimal | None
    stale_after_days: int | None
    lock_version: int
    created_at: datetime
    updated_at: datetime


class ObservationWrite(BaseModel):
    observed_at: datetime
    publication_timestamp: datetime
    value: DataDecimal | None = Field(default=None, decimal_places=8)
    status: ObservationStatus = ObservationStatus.present
    source_reference: str | None = Field(default=None, max_length=500)
    revision_reason: str | None = None

    @field_validator("observed_at", "publication_timestamp")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        return _aware_utc(value)

    @model_validator(mode="after")
    def validate_status_value(self) -> "ObservationWrite":
        if self.status == ObservationStatus.present and self.value is None:
            raise ValueError("present observations require a value")
        if self.status == ObservationStatus.missing and self.value is not None:
            raise ValueError("missing observations must use a null value")
        if self.publication_timestamp < self.observed_at:
            raise ValueError("publication_timestamp cannot precede observed_at")
        return self


class ObservationRead(BaseModel):
    id: int
    series_id: int
    observed_at: datetime
    publication_timestamp: datetime
    ingestion_timestamp: datetime
    value: DataDecimal | None
    status: ObservationStatus
    source_reference: str | None
    revision_count: int


class DataRevisionRead(BaseModel):
    id: int
    observation_id: int
    import_batch_id: int | None
    sequence: int
    previous_value: DataDecimal | None
    revised_value: DataDecimal | None
    previous_status: ObservationStatus
    revised_status: ObservationStatus
    publication_timestamp: datetime
    revision_timestamp: datetime
    reason: str
    source_reference: str | None
    model_config = ConfigDict(from_attributes=True)


class ImportRow(ObservationWrite):
    series_code: str = Field(min_length=1, max_length=120)


class DataImportCreate(BaseModel):
    source_id: int = Field(gt=0)
    idempotency_key: str = Field(min_length=1, max_length=160)
    partial_mode: bool = False
    notes: str = ""
    rows: list[ImportRow] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_import_limits(self) -> "DataImportCreate":
        settings = get_settings()
        if len(self.rows) > settings.max_import_rows:
            raise ValueError(f"Import cannot exceed {settings.max_import_rows} rows")
        if len(self.notes) > settings.max_import_notes_length:
            raise ValueError("Import notes exceed the configured maximum length")
        return self


class DataImportErrorRead(BaseModel):
    id: int
    import_batch_id: int
    row_index: int
    error_code: str
    message: str
    source_context: dict[str, Any]
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class DataImportRead(BaseModel):
    id: int
    source_id: int
    idempotency_key: str
    imported_at: datetime
    failed_at: datetime | None
    failure_summary: str | None
    status: ImportStatus
    row_count: int
    accepted_rows: int
    rejected_rows: int
    partial_mode: bool
    notes: str
    errors: list[DataImportErrorRead]
    model_config = ConfigDict(from_attributes=True)


class QualityIssueRead(BaseModel):
    id: int
    series_id: int
    observation_id: int | None
    issue_type: QualityIssueType
    status: QualityIssueStatus
    message: str
    details: dict[str, Any]
    detected_at: datetime
    acknowledged_at: datetime | None
    resolved_at: datetime | None
    resolution_notes: str
    lock_version: int


class QualityIssueAction(BaseModel):
    expected_lock_version: int = Field(gt=0)
    notes: str = Field(default="", max_length=1000)
    actor_reference: str | None = Field(default=None, max_length=200)


class QualityIssueEventRead(BaseModel):
    id: int
    issue_id: int
    previous_status: QualityIssueStatus
    new_status: QualityIssueStatus
    event_timestamp: datetime
    note: str
    actor_reference: str | None
    source_lock_version: int
    model_config = ConfigDict(from_attributes=True)


class StaleScanRead(BaseModel):
    inspected_count: int
    created_count: int
