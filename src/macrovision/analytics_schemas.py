import re
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    field_validator,
    model_validator,
)

from macrovision.contracts import utc_timestamp
from macrovision.macro_data_models import DataFrequency, SeasonalAdjustment

DERIVED_CODE_PATTERN = r"^[A-Z][A-Z0-9_.-]{0,119}$"
DECIMAL_QUANTUM = Decimal("0.00000001")


class TransformationType(StrEnum):
    difference = "difference"
    percent_change = "percent_change"
    year_over_year_percent_change = "year_over_year_percent_change"
    ratio = "ratio"
    spread = "spread"
    moving_average = "moving_average"
    rolling_standard_deviation = "rolling_standard_deviation"
    rolling_z_score = "rolling_z_score"
    rebase_index = "rebase_index"


def canonical_code(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Derived-series code must be a string")
    try:
        value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("Derived-series code must contain ASCII characters only") from exc
    normalized = value.upper()
    if re.fullmatch(DERIVED_CODE_PATTERN, normalized) is None:
        raise ValueError("Derived-series code has an invalid format")
    return normalized


def _reject_float(value: object) -> object:
    if isinstance(value, float):
        raise ValueError("Floating-point values are not accepted")
    return value


def _finite_decimal(value: Decimal) -> Decimal:
    if not value.is_finite():
        raise ValueError("Decimal value must be finite")
    return value


CanonicalDecimal = Annotated[
    Decimal,
    BeforeValidator(_reject_float),
    AfterValidator(_finite_decimal),
    PlainSerializer(lambda value: format(value, "f"), return_type=str, when_used="json"),
]


class StrictAnalyticsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoParameters(StrictAnalyticsModel):
    transformation_type: Literal[
        TransformationType.difference,
        TransformationType.percent_change,
        TransformationType.year_over_year_percent_change,
        TransformationType.ratio,
        TransformationType.spread,
    ]


class MovingAverageParameters(StrictAnalyticsModel):
    transformation_type: Literal[TransformationType.moving_average]
    window: int = Field(ge=2, le=1000)


class RollingStandardDeviationParameters(StrictAnalyticsModel):
    transformation_type: Literal[TransformationType.rolling_standard_deviation]
    window: int = Field(ge=2, le=1000)


class RollingZScoreParameters(StrictAnalyticsModel):
    transformation_type: Literal[TransformationType.rolling_z_score]
    window: int = Field(ge=2, le=1000)


class RebaseIndexParameters(StrictAnalyticsModel):
    transformation_type: Literal[TransformationType.rebase_index]
    base_timestamp: datetime
    base_value: CanonicalDecimal = Decimal("100.00000000")

    @field_validator("base_timestamp")
    @classmethod
    def normalize_base_timestamp(cls, value: datetime) -> datetime:
        return utc_timestamp(value)

    @field_validator("base_value")
    @classmethod
    def positive_base_value(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("base_value must be positive")
        return value


TransformationParameters = Annotated[
    NoParameters
    | MovingAverageParameters
    | RollingStandardDeviationParameters
    | RollingZScoreParameters
    | RebaseIndexParameters,
    Field(discriminator="transformation_type"),
]


class DerivedSeriesInputContract(StrictAnalyticsModel):
    position: int = Field(ge=0)
    alias: str = Field(min_length=1, max_length=40, pattern=r"^[a-z][a-z0-9_]{0,39}$")
    source_series_id: int = Field(gt=0)


class DerivedSeriesDefinitionCreate(StrictAnalyticsModel):
    code: str = Field(min_length=1, max_length=120, pattern=DERIVED_CODE_PATTERN)
    title: str = Field(min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=2000)
    enabled: bool = True
    inputs: list[DerivedSeriesInputContract] = Field(min_length=1, max_length=2)
    parameters: TransformationParameters
    change_note: str | None = Field(default=None, max_length=1000)

    @field_validator("code", mode="before")
    @classmethod
    def normalize_code(cls, value: object) -> object:
        return canonical_code(value) if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_registry_contract(self) -> "DerivedSeriesDefinitionCreate":
        from macrovision.analytics_transformations import validate_ordered_inputs

        validate_ordered_inputs(
            self.parameters.transformation_type,
            tuple(item.alias for item in self.inputs),
        )
        if tuple(item.position for item in self.inputs) != tuple(range(len(self.inputs))):
            raise ValueError("Input positions must be contiguous and ordered from zero")
        return self


class InputMetadata(StrictAnalyticsModel):
    unit: str = Field(min_length=1, max_length=80)
    frequency: DataFrequency
    geography: str = Field(min_length=1, max_length=120)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    seasonal_adjustment: SeasonalAdjustment


class OutputMetadata(StrictAnalyticsModel):
    unit: str
    frequency: DataFrequency
    geography: str
    currency: str | None
    seasonal_adjustment: SeasonalAdjustment
