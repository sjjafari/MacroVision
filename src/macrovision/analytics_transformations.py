import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    localcontext,
)
from enum import StrEnum
from typing import TypeAlias

from pydantic import BaseModel

from macrovision.analytics_schemas import (
    InputMetadata,
    MovingAverageParameters,
    NoParameters,
    OutputMetadata,
    RebaseIndexParameters,
    RollingStandardDeviationParameters,
    RollingZScoreParameters,
    TransformationParameters,
    TransformationType,
    canonical_code,
)
from macrovision.macro_data_models import DataFrequency

OUTPUT_QUANTUM = Decimal("0.00000001")
MAX_OUTPUT = Decimal("92233720368.54775807")
MIN_OUTPUT = Decimal("-92233720368.54775808")
ANALYTICS_CONTEXT = Context(
    prec=38,
    rounding=ROUND_HALF_EVEN,
    traps=[InvalidOperation, DivisionByZero, Overflow],
)


class AnalyticsContractError(ValueError):
    """A structural analytics contract is invalid."""


class InputState(StrEnum):
    present = "present"
    missing = "missing"
    absent = "absent"


class MissingReason(StrEnum):
    source_missing = "source_missing"
    timestamp_absent = "timestamp_absent"
    insufficient_history = "insufficient_history"
    division_by_zero = "division_by_zero"
    non_finite_result = "non_finite_result"
    numeric_overflow = "numeric_overflow"


@dataclass(frozen=True)
class PointValue:
    state: InputState
    value: Decimal | None = None

    def __post_init__(self) -> None:
        if self.state is InputState.present:
            if not isinstance(self.value, Decimal) or not self.value.is_finite():
                raise AnalyticsContractError("Present points require a finite Decimal")
        elif self.value is not None:
            raise AnalyticsContractError("Missing and absent points cannot carry values")


@dataclass(frozen=True)
class TransformationResult:
    value: Decimal | None
    missing_reason: MissingReason | None

    @property
    def is_present(self) -> bool:
        return self.missing_reason is None


InputWindows: TypeAlias = tuple[tuple[PointValue, ...], ...]
ParameterContract: TypeAlias = type[BaseModel]
Evaluator: TypeAlias = Callable[[InputWindows, TransformationParameters], TransformationResult]


@dataclass(frozen=True)
class TransformationSpec:
    transformation_type: TransformationType
    arity: int
    ordered_aliases: tuple[str, ...]
    parameter_contract: ParameterContract
    required_history: Callable[[TransformationParameters], int]
    validate_metadata: Callable[[Sequence[InputMetadata]], OutputMetadata]
    evaluate: Evaluator


def canonical_decimal(value: Decimal) -> str:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise AnalyticsContractError("Canonical values must be finite Decimal instances")
    return format(value, "f")


def _json_ready(value: object) -> object:
    if isinstance(value, float):
        raise AnalyticsContractError("Floats cannot be canonicalized")
    if isinstance(value, Decimal):
        return canonical_decimal(value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise AnalyticsContractError("Canonical timestamps must be timezone-aware")
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    raise AnalyticsContractError("Unsupported canonical parameter type")


def canonical_json(value: object) -> str:
    return json.dumps(
        _json_ready(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def canonical_parameters(parameters: TransformationParameters) -> str:
    return canonical_json(parameters.model_dump(mode="python"))


def parameters_fingerprint(parameters: TransformationParameters) -> str:
    return hashlib.sha256(canonical_parameters(parameters).encode("utf-8")).hexdigest()


def normalize_derived_code(value: str) -> str:
    return canonical_code(value)


def _shift_months(value: datetime, months: int) -> datetime | None:
    total = value.year * 12 + value.month - 1 + months
    year, month_zero = divmod(total, 12)
    month = month_zero + 1
    try:
        return value.replace(year=year, month=month)
    except ValueError:
        return None


def previous_period_anchor(value: datetime, frequency: DataFrequency) -> datetime | None:
    if frequency is DataFrequency.daily:
        return value - timedelta(days=1)
    if frequency is DataFrequency.weekly:
        return value - timedelta(days=7)
    if frequency is DataFrequency.monthly:
        return _shift_months(value, -1)
    if frequency is DataFrequency.quarterly:
        return _shift_months(value, -3)
    if frequency is DataFrequency.annual:
        return _shift_months(value, -12)
    raise AnalyticsContractError("Irregular frequency is not supported")


def year_over_year_anchor(value: datetime, frequency: DataFrequency) -> datetime | None:
    if frequency is DataFrequency.weekly:
        return value - timedelta(weeks=52)
    if frequency is DataFrequency.daily:
        try:
            return value.replace(year=value.year - 1)
        except ValueError:
            return None
    if frequency is DataFrequency.monthly:
        return _shift_months(value, -12)
    if frequency is DataFrequency.quarterly:
        return _shift_months(value, -12)
    if frequency is DataFrequency.annual:
        return _shift_months(value, -12)
    raise AnalyticsContractError("Irregular frequency is not supported")


def _missing(points: Sequence[PointValue], expected: int) -> MissingReason | None:
    if len(points) < expected:
        return MissingReason.insufficient_history
    if any(point.state is InputState.absent for point in points):
        return MissingReason.timestamp_absent
    if any(point.state is InputState.missing for point in points):
        return MissingReason.source_missing
    return None


def _present(value: Decimal) -> TransformationResult:
    try:
        with localcontext(ANALYTICS_CONTEXT):
            quantized = value.quantize(OUTPUT_QUANTUM, rounding=ROUND_HALF_EVEN)
    except (InvalidOperation, Overflow):
        return TransformationResult(None, MissingReason.non_finite_result)
    if not quantized.is_finite():
        return TransformationResult(None, MissingReason.non_finite_result)
    if quantized < MIN_OUTPUT or quantized > MAX_OUTPUT:
        return TransformationResult(None, MissingReason.numeric_overflow)
    return TransformationResult(quantized, None)


def _values(points: Sequence[PointValue]) -> list[Decimal]:
    return [point.value for point in points if point.value is not None]


def _difference(inputs: InputWindows, _: TransformationParameters) -> TransformationResult:
    reason = _missing(inputs[0], 2)
    if reason:
        return TransformationResult(None, reason)
    values = _values(inputs[0])
    with localcontext(ANALYTICS_CONTEXT):
        return _present(values[-1] - values[-2])


def _percent_change(inputs: InputWindows, _: TransformationParameters) -> TransformationResult:
    reason = _missing(inputs[0], 2)
    if reason:
        return TransformationResult(None, reason)
    previous, current = _values(inputs[0])[-2:]
    if previous == 0:
        return TransformationResult(None, MissingReason.division_by_zero)
    with localcontext(ANALYTICS_CONTEXT):
        return _present(((current / previous) - Decimal(1)) * Decimal(100))


def _ratio(inputs: InputWindows, _: TransformationParameters) -> TransformationResult:
    for points in inputs:
        reason = _missing(points, 1)
        if reason:
            return TransformationResult(None, reason)
    numerator, denominator = (_values(points)[-1] for points in inputs)
    if denominator == 0:
        return TransformationResult(None, MissingReason.division_by_zero)
    with localcontext(ANALYTICS_CONTEXT):
        return _present(numerator / denominator)


def _spread(inputs: InputWindows, _: TransformationParameters) -> TransformationResult:
    for points in inputs:
        reason = _missing(points, 1)
        if reason:
            return TransformationResult(None, reason)
    minuend, subtrahend = (_values(points)[-1] for points in inputs)
    with localcontext(ANALYTICS_CONTEXT):
        return _present(minuend - subtrahend)


def _window(parameters: TransformationParameters) -> int:
    if isinstance(
        parameters,
        (
            MovingAverageParameters,
            RollingStandardDeviationParameters,
            RollingZScoreParameters,
        ),
    ):
        return parameters.window
    return 2


def _mean(values: Sequence[Decimal]) -> Decimal:
    with localcontext(ANALYTICS_CONTEXT):
        return sum(values, Decimal(0)) / Decimal(len(values))


def _population_stddev(values: Sequence[Decimal]) -> Decimal:
    with localcontext(ANALYTICS_CONTEXT):
        mean = _mean(values)
        variance = sum(((value - mean) ** 2 for value in values), Decimal(0)) / Decimal(len(values))
        return variance.sqrt()


def _moving_average(
    inputs: InputWindows, parameters: TransformationParameters
) -> TransformationResult:
    window = _window(parameters)
    reason = _missing(inputs[0], window)
    if reason:
        return TransformationResult(None, reason)
    return _present(_mean(_values(inputs[0])[-window:]))


def _rolling_stddev(
    inputs: InputWindows, parameters: TransformationParameters
) -> TransformationResult:
    window = _window(parameters)
    reason = _missing(inputs[0], window)
    if reason:
        return TransformationResult(None, reason)
    return _present(_population_stddev(_values(inputs[0])[-window:]))


def _rolling_z_score(
    inputs: InputWindows, parameters: TransformationParameters
) -> TransformationResult:
    window = _window(parameters)
    reason = _missing(inputs[0], window)
    if reason:
        return TransformationResult(None, reason)
    values = _values(inputs[0])[-window:]
    deviation = _population_stddev(values)
    if deviation == 0:
        return TransformationResult(None, MissingReason.division_by_zero)
    with localcontext(ANALYTICS_CONTEXT):
        return _present((values[-1] - _mean(values)) / deviation)


def _rebase(inputs: InputWindows, parameters: TransformationParameters) -> TransformationResult:
    if not isinstance(parameters, RebaseIndexParameters):
        raise AnalyticsContractError("rebase_index requires rebase parameters")
    if len(inputs[0]) < 2:
        raise AnalyticsContractError("The exact rebase base point is required")
    base, current = inputs[0][0], inputs[0][-1]
    if base.state is not InputState.present:
        raise AnalyticsContractError("The exact rebase base point must be present")
    if base.value == 0:
        raise AnalyticsContractError("The exact rebase base point cannot be zero")
    reason = _missing((current,), 1)
    if reason:
        return TransformationResult(None, reason)
    assert base.value is not None and current.value is not None
    with localcontext(ANALYTICS_CONTEXT):
        return _present(current.value / base.value * parameters.base_value)


def _single_metadata(
    metadata: Sequence[InputMetadata], unit: str | None = None, clear_currency: bool = False
) -> OutputMetadata:
    if len(metadata) != 1:
        raise AnalyticsContractError("Transformation requires exactly one input")
    item = metadata[0]
    if item.frequency is DataFrequency.irregular:
        raise AnalyticsContractError("Irregular frequency is not supported")
    return OutputMetadata(
        unit=unit or item.unit,
        frequency=item.frequency,
        geography=item.geography,
        currency=None if clear_currency else item.currency,
        seasonal_adjustment=item.seasonal_adjustment,
    )


def _multi_metadata(
    metadata: Sequence[InputMetadata], *, unit: str, preserve_currency: bool
) -> OutputMetadata:
    if len(metadata) != 2:
        raise AnalyticsContractError("Transformation requires exactly two inputs")
    first, second = metadata
    if first.frequency is DataFrequency.irregular:
        raise AnalyticsContractError("Irregular frequency is not supported")
    if (
        first.frequency != second.frequency
        or first.geography != second.geography
        or first.seasonal_adjustment != second.seasonal_adjustment
    ):
        raise AnalyticsContractError("Input frequency, geography, and seasonality must match")
    if first.unit != second.unit or first.currency != second.currency:
        raise AnalyticsContractError("Input unit and currency must match")
    return OutputMetadata(
        unit=first.unit if unit == "preserve" else unit,
        frequency=first.frequency,
        geography=first.geography,
        currency=first.currency if preserve_currency else None,
        seasonal_adjustment=first.seasonal_adjustment,
    )


def _history_none(_: TransformationParameters) -> int:
    return 0


def _history_one(_: TransformationParameters) -> int:
    return 1


def _history_window(parameters: TransformationParameters) -> int:
    return _window(parameters) - 1


def _unary_preserve(metadata: Sequence[InputMetadata]) -> OutputMetadata:
    return _single_metadata(metadata)


def _percent_metadata(metadata: Sequence[InputMetadata]) -> OutputMetadata:
    return _single_metadata(metadata, "percent", True)


REGISTRY: dict[TransformationType, TransformationSpec] = {
    TransformationType.difference: TransformationSpec(
        TransformationType.difference,
        1,
        ("value",),
        NoParameters,
        _history_one,
        _unary_preserve,
        _difference,
    ),
    TransformationType.percent_change: TransformationSpec(
        TransformationType.percent_change,
        1,
        ("value",),
        NoParameters,
        _history_one,
        _percent_metadata,
        _percent_change,
    ),
    TransformationType.year_over_year_percent_change: TransformationSpec(
        TransformationType.year_over_year_percent_change,
        1,
        ("value",),
        NoParameters,
        _history_one,
        _percent_metadata,
        _percent_change,
    ),
    TransformationType.ratio: TransformationSpec(
        TransformationType.ratio,
        2,
        ("numerator", "denominator"),
        NoParameters,
        _history_none,
        lambda items: _multi_metadata(items, unit="ratio", preserve_currency=False),
        _ratio,
    ),
    TransformationType.spread: TransformationSpec(
        TransformationType.spread,
        2,
        ("minuend", "subtrahend"),
        NoParameters,
        _history_none,
        lambda items: _multi_metadata(items, unit="preserve", preserve_currency=True),
        _spread,
    ),
    TransformationType.moving_average: TransformationSpec(
        TransformationType.moving_average,
        1,
        ("value",),
        MovingAverageParameters,
        _history_window,
        _unary_preserve,
        _moving_average,
    ),
    TransformationType.rolling_standard_deviation: TransformationSpec(
        TransformationType.rolling_standard_deviation,
        1,
        ("value",),
        RollingStandardDeviationParameters,
        _history_window,
        _unary_preserve,
        _rolling_stddev,
    ),
    TransformationType.rolling_z_score: TransformationSpec(
        TransformationType.rolling_z_score,
        1,
        ("value",),
        RollingZScoreParameters,
        _history_window,
        lambda items: _single_metadata(items, "z_score", True),
        _rolling_z_score,
    ),
    TransformationType.rebase_index: TransformationSpec(
        TransformationType.rebase_index,
        1,
        ("value",),
        RebaseIndexParameters,
        _history_none,
        lambda items: _single_metadata(items, "index", True),
        _rebase,
    ),
}


def get_transformation_spec(
    transformation_type: TransformationType | str,
) -> TransformationSpec:
    try:
        return REGISTRY[TransformationType(transformation_type)]
    except (ValueError, KeyError) as exc:
        raise AnalyticsContractError("Unknown analytics transformation") from exc


def validate_ordered_inputs(
    transformation_type: TransformationType | str, aliases: tuple[str, ...]
) -> None:
    spec = get_transformation_spec(transformation_type)
    if aliases != spec.ordered_aliases:
        raise AnalyticsContractError(
            f"{spec.transformation_type.value} requires ordered aliases "
            f"{', '.join(spec.ordered_aliases)}"
        )


def evaluate_transformation(
    parameters: TransformationParameters,
    inputs: InputWindows,
) -> TransformationResult:
    spec = get_transformation_spec(parameters.transformation_type)
    if len(inputs) != spec.arity:
        raise AnalyticsContractError("Transformation input arity is invalid")
    if not isinstance(parameters, spec.parameter_contract):
        raise AnalyticsContractError("Transformation parameter contract is invalid")
    return spec.evaluate(inputs, parameters)
