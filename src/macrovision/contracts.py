from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from typing import Annotated, Any

from fastapi import Query
from pydantic import AfterValidator, BaseModel, Field, PlainSerializer

RATIO_QUANTUM = Decimal("0.000001")
PageLimit = Annotated[int, Query(ge=1, le=200)]
PageOffset = Annotated[int, Query(ge=0)]


class ErrorResponse(BaseModel):
    code: str
    message: str
    details: list[dict[str, Any]] | dict[str, Any] | None = None
    detail: Any | None = None


def utc_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamp must include a UTC offset")
    return value.astimezone(UTC)


def exact_ratio(value: Decimal) -> Decimal:
    if not value.is_finite():
        raise ValueError("Ratio must be finite")
    try:
        rounded = value.quantize(RATIO_QUANTUM, rounding=ROUND_HALF_EVEN)
    except InvalidOperation as exc:
        raise ValueError("Ratio cannot be represented at six-decimal precision") from exc
    if rounded < 0 or rounded > 1:
        raise ValueError("Ratio must be between 0 and 1 inclusive")
    return rounded


Ratio = Annotated[
    Decimal,
    Field(ge=Decimal("0"), le=Decimal("1")),
    AfterValidator(exact_ratio),
    PlainSerializer(lambda value: format(value, ".6f"), return_type=str, when_used="json"),
]
