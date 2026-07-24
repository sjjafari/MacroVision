from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from macrovision.portfolio_models import TransactionType

Money = Decimal
MAX_MONEY = Decimal("92233720368.54775807")
MAX_QUANTITY = Decimal("922337203.6854775807")


class PortfolioCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    base_currency: str = Field(default="USD", pattern=r"^[A-Za-z]{3}$")
    investor_id: int | None = Field(default=None, gt=0)


class PositionPriceUpdate(BaseModel):
    current_price: Money = Field(gt=0, le=MAX_MONEY, decimal_places=8)


class TransactionCreate(BaseModel):
    transaction_type: TransactionType
    symbol: str | None = Field(default=None, min_length=1, max_length=32)
    asset_name: str | None = Field(default=None, min_length=1, max_length=160)
    quantity: Money | None = Field(default=None, gt=0, le=MAX_QUANTITY, decimal_places=10)
    unit_price: Money | None = Field(default=None, gt=0, le=MAX_MONEY, decimal_places=8)
    amount: Money | None = Field(default=None, gt=0, le=MAX_MONEY, decimal_places=8)
    currency: str = Field(default="USD", pattern=r"^[A-Za-z]{3}$")
    note: str = Field(default="", max_length=2000)
    occurred_at: datetime | None = None

    @model_validator(mode="after")
    def validate_transaction_fields(self) -> "TransactionCreate":
        if self.transaction_type in {TransactionType.buy, TransactionType.sell}:
            if self.symbol is None or self.quantity is None or self.unit_price is None:
                raise ValueError("buy and sell require symbol, quantity, and unit_price")
            if self.symbol.upper() == "CASH":
                raise ValueError("CASH is reserved for the portfolio cash allocation")
            if self.amount is not None:
                raise ValueError("amount is calculated for buy and sell transactions")
        elif self.amount is None:
            raise ValueError(f"{self.transaction_type.value} requires amount")
        elif self.quantity is not None or self.unit_price is not None:
            raise ValueError("cash transactions cannot include quantity or unit_price")
        return self


class PositionRead(BaseModel):
    id: int
    symbol: str
    asset_name: str
    quantity: Money
    average_cost: Money
    current_price: Money
    market_value: Money
    cost_basis: Money
    realized_pl: Money
    unrealized_pl: Money
    allocation_percentage: Money


class CashBalanceRead(BaseModel):
    currency: str
    balance: Money
    model_config = ConfigDict(from_attributes=True)


class PortfolioRead(BaseModel):
    id: int
    investor_id: int | None
    name: str
    base_currency: str
    lock_version: int
    created_at: datetime
    positions: list[PositionRead]
    cash_balances: list[CashBalanceRead]


class TransactionRead(BaseModel):
    id: int
    portfolio_id: int
    transaction_type: TransactionType
    symbol: str | None
    asset_name: str | None
    quantity: Money | None
    unit_price: Money | None
    amount: Money
    currency: str
    realized_pl: Money
    note: str
    occurred_at: datetime
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class PortfolioSummary(BaseModel):
    portfolio_id: int
    valuation_currency: str
    total_value: Money
    position_value: Money
    base_cash_balance: Money
    total_cost_basis: Money
    realized_pl: Money
    unrealized_pl: Money
    allocations: dict[str, Money]
    cash_balances: dict[str, Money]
    unconverted_cash_currencies: list[str]


class SnapshotRead(BaseModel):
    id: int
    portfolio_id: int
    captured_at: datetime
    total_value: Money
    position_value: Money
    base_cash_balance: Money
    total_cost_basis: Money
    realized_pl: Money
    unrealized_pl: Money
    allocations: dict[str, Money]
    cash_balances: dict[str, Money]
    created_at: datetime
