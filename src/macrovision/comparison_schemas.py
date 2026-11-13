"""Read-only multi-series comparison contracts for Web MVP Phase 4."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from macrovision.macro_data_models import DataFrequency
from macrovision.macro_data_schemas import DataDecimal


class ComparisonKind(StrEnum):
    raw = "raw"
    derived = "derived"


class ComparisonPointStatus(StrEnum):
    present = "present"
    missing = "missing"


class ComparisonPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    observed_at: datetime
    value: DataDecimal | None
    status: ComparisonPointStatus
    missing_reason: str | None = None


class ComparisonSeries(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: ComparisonKind
    resource_id: int
    code: str
    title: str
    frequency: DataFrequency
    unit: str
    geography: str
    currency: str | None
    axis_id: str
    definition_version: int | None = None
    run_id: int | None = None
    points: list[ComparisonPoint]


class ComparisonWarningCode(StrEnum):
    frequency_mismatch = "frequency_mismatch"
    multiple_axes = "multiple_axes"


class ComparisonRead(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: str
    requested_as_of: datetime | None
    start: datetime
    end: datetime
    frequency_mismatch: bool
    axis_count: int
    warnings: list[ComparisonWarningCode]
    series: list[ComparisonSeries]
