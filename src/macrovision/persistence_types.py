from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

from sqlalchemy import BigInteger
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator


class ScaledDecimal(TypeDecorator[Decimal]):
    """Persist Decimal values as exact scaled 64-bit integers."""

    impl = BigInteger
    cache_ok = True

    def __init__(self, scale: int) -> None:
        super().__init__()
        self.scale = scale
        self.multiplier = Decimal(10) ** scale
        self.quantum = Decimal(1).scaleb(-scale)

    def process_bind_param(self, value: Any, dialect: Dialect) -> int | None:
        del dialect
        if value is None:
            return None
        if not isinstance(value, Decimal):
            raise TypeError("Scaled database values must be Decimal instances")
        decimal_value = value.quantize(self.quantum, rounding=ROUND_HALF_EVEN)
        return int(decimal_value * self.multiplier)

    def process_result_value(self, value: Any, dialect: Dialect) -> Decimal | None:
        del dialect
        if value is None:
            return None
        return (Decimal(value) / self.multiplier).quantize(self.quantum, rounding=ROUND_HALF_EVEN)
