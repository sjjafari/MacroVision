from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from macrovision.database import Base
from macrovision.persistence_types import ScaledDecimal, UTCDateTime

MONEY_PRECISION = 28
MONEY_SCALE = 8
QUANTITY_SCALE = 10


MoneyValue = ScaledDecimal(MONEY_SCALE)
QuantityValue = ScaledDecimal(QUANTITY_SCALE)


class TransactionType(StrEnum):
    buy = "buy"
    sell = "sell"
    deposit = "deposit"
    withdrawal = "withdrawal"
    fee = "fee"
    dividend = "dividend"
    interest = "interest"


class Portfolio(Base):
    __tablename__ = "portfolios"

    id: Mapped[int] = mapped_column(primary_key=True)
    investor_id: Mapped[int | None] = mapped_column(
        ForeignKey("investor_profiles.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(120), index=True)
    base_currency: Mapped[str] = mapped_column(String(3))
    lock_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())

    positions: Mapped[list["PortfolioPosition"]] = relationship(
        back_populates="portfolio", cascade="all, delete-orphan"
    )
    cash_balances: Mapped[list["CashBalance"]] = relationship(
        back_populates="portfolio", cascade="all, delete-orphan"
    )
    transactions: Mapped[list["PortfolioTransaction"]] = relationship(
        back_populates="portfolio", cascade="save-update, merge", passive_deletes="all"
    )
    snapshots: Mapped[list["PortfolioSnapshot"]] = relationship(
        back_populates="portfolio", cascade="save-update, merge", passive_deletes="all"
    )
    __table_args__ = (
        CheckConstraint("lock_version > 0", name="ck_portfolio_lock_version_positive"),
    )
    __mapper_args__ = {  # noqa: RUF012
        "version_id_col": lock_version,
        "version_id_generator": False,
    }


class PortfolioPosition(Base):
    __tablename__ = "portfolio_positions"

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id", ondelete="CASCADE"))
    symbol: Mapped[str] = mapped_column(String(32))
    asset_name: Mapped[str] = mapped_column(String(160))
    quantity: Mapped[Decimal] = mapped_column(QuantityValue)
    average_cost: Mapped[Decimal] = mapped_column(MoneyValue)
    current_price: Mapped[Decimal] = mapped_column(MoneyValue)
    realized_pl: Mapped[Decimal] = mapped_column(MoneyValue, default=Decimal("0"))
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now()
    )

    portfolio: Mapped[Portfolio] = relationship(back_populates="positions")

    __table_args__ = (
        UniqueConstraint("portfolio_id", "symbol", name="uq_position_portfolio_symbol"),
        CheckConstraint("quantity > 0", name="ck_position_quantity_positive"),
        CheckConstraint("average_cost >= 0", name="ck_position_average_cost_nonnegative"),
        CheckConstraint("current_price >= 0", name="ck_position_price_nonnegative"),
    )


class CashBalance(Base):
    __tablename__ = "cash_balances"

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id", ondelete="CASCADE"))
    currency: Mapped[str] = mapped_column(String(3))
    balance: Mapped[Decimal] = mapped_column(MoneyValue, default=Decimal("0"))
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now()
    )

    portfolio: Mapped[Portfolio] = relationship(back_populates="cash_balances")

    __table_args__ = (
        UniqueConstraint("portfolio_id", "currency", name="uq_cash_portfolio_currency"),
        CheckConstraint("balance >= 0", name="ck_cash_balance_nonnegative"),
    )


class PortfolioTransaction(Base):
    __tablename__ = "portfolio_transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id", ondelete="RESTRICT"))
    transaction_type: Mapped[TransactionType] = mapped_column(Enum(TransactionType))
    symbol: Mapped[str | None] = mapped_column(String(32), nullable=True)
    asset_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    quantity: Mapped[Decimal | None] = mapped_column(QuantityValue, nullable=True)
    unit_price: Mapped[Decimal | None] = mapped_column(MoneyValue, nullable=True)
    amount: Mapped[Decimal] = mapped_column(MoneyValue)
    currency: Mapped[str] = mapped_column(String(3))
    realized_pl: Mapped[Decimal] = mapped_column(MoneyValue, default=Decimal("0"))
    note: Mapped[str] = mapped_column(Text, default="")
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())

    portfolio: Mapped[Portfolio] = relationship(back_populates="transactions")

    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_transaction_amount_positive"),
        CheckConstraint(
            "quantity IS NULL OR quantity > 0", name="ck_transaction_quantity_positive"
        ),
        CheckConstraint(
            "unit_price IS NULL OR unit_price >= 0", name="ck_transaction_price_nonnegative"
        ),
        Index("ix_transaction_portfolio_occurred", "portfolio_id", "occurred_at"),
        Index("ix_transaction_portfolio_symbol", "portfolio_id", "symbol"),
    )


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id", ondelete="RESTRICT"))
    captured_at: Mapped[datetime] = mapped_column(UTCDateTime())
    total_value: Mapped[Decimal] = mapped_column(MoneyValue)
    position_value: Mapped[Decimal] = mapped_column(MoneyValue)
    base_cash_balance: Mapped[Decimal] = mapped_column(MoneyValue)
    total_cost_basis: Mapped[Decimal] = mapped_column(MoneyValue)
    realized_pl: Mapped[Decimal] = mapped_column(MoneyValue)
    unrealized_pl: Mapped[Decimal] = mapped_column(MoneyValue)
    allocations_json: Mapped[str] = mapped_column(Text)
    cash_balances_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())

    portfolio: Mapped[Portfolio] = relationship(back_populates="snapshots")

    __table_args__ = (
        CheckConstraint("total_value >= 0", name="ck_snapshot_total_nonnegative"),
        CheckConstraint("position_value >= 0", name="ck_snapshot_positions_nonnegative"),
        CheckConstraint("base_cash_balance >= 0", name="ck_snapshot_cash_nonnegative"),
        CheckConstraint("total_cost_basis >= 0", name="ck_snapshot_cost_nonnegative"),
        Index("ix_snapshot_portfolio_captured", "portfolio_id", "captured_at"),
    )


def _prevent_audit_mutation(
    _mapper: object, _connection: object, _target: PortfolioTransaction | PortfolioSnapshot
) -> None:
    raise ValueError("Portfolio transactions and snapshots are immutable")


event.listen(PortfolioTransaction, "before_update", _prevent_audit_mutation)
event.listen(PortfolioTransaction, "before_delete", _prevent_audit_mutation)
event.listen(PortfolioSnapshot, "before_update", _prevent_audit_mutation)
event.listen(PortfolioSnapshot, "before_delete", _prevent_audit_mutation)
