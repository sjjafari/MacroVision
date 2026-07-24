"""Add Portfolio Engine v0.2 tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM

revision: str = "20260723_0002"
down_revision: str | None = "20260723_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MONEY = sa.BigInteger()
QUANTITY = sa.BigInteger()


def _drop_owned_postgresql_enums(*names: str) -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for name in names:
        ENUM(name=name).drop(bind, checkfirst=True)


def upgrade() -> None:
    op.create_table(
        "portfolios",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "investor_id",
            sa.Integer(),
            sa.ForeignKey("investor_profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("base_currency", sa.String(3), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_portfolios_investor_id", "portfolios", ["investor_id"])
    op.create_index("ix_portfolios_name", "portfolios", ["name"])

    op.create_table(
        "portfolio_positions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "portfolio_id",
            sa.Integer(),
            sa.ForeignKey("portfolios.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("asset_name", sa.String(160), nullable=False),
        sa.Column("quantity", QUANTITY, nullable=False),
        sa.Column("average_cost", MONEY, nullable=False),
        sa.Column("current_price", MONEY, nullable=False),
        sa.Column("realized_pl", MONEY, nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_position_quantity_positive"),
        sa.CheckConstraint("average_cost >= 0", name="ck_position_average_cost_nonnegative"),
        sa.CheckConstraint("current_price >= 0", name="ck_position_price_nonnegative"),
        sa.UniqueConstraint("portfolio_id", "symbol", name="uq_position_portfolio_symbol"),
    )
    op.create_table(
        "cash_balances",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "portfolio_id",
            sa.Integer(),
            sa.ForeignKey("portfolios.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("balance", MONEY, nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("balance >= 0", name="ck_cash_balance_nonnegative"),
        sa.UniqueConstraint("portfolio_id", "currency", name="uq_cash_portfolio_currency"),
    )
    transaction_type = sa.Enum(
        "buy",
        "sell",
        "deposit",
        "withdrawal",
        "fee",
        "dividend",
        "interest",
        name="transactiontype",
    )
    op.create_table(
        "portfolio_transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "portfolio_id",
            sa.Integer(),
            sa.ForeignKey("portfolios.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("transaction_type", transaction_type, nullable=False),
        sa.Column("symbol", sa.String(32), nullable=True),
        sa.Column("asset_name", sa.String(160), nullable=True),
        sa.Column("quantity", QUANTITY, nullable=True),
        sa.Column("unit_price", MONEY, nullable=True),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("realized_pl", MONEY, nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_transaction_amount_positive"),
        sa.CheckConstraint(
            "quantity IS NULL OR quantity > 0", name="ck_transaction_quantity_positive"
        ),
        sa.CheckConstraint(
            "unit_price IS NULL OR unit_price >= 0", name="ck_transaction_price_nonnegative"
        ),
    )
    op.create_index(
        "ix_transaction_portfolio_occurred",
        "portfolio_transactions",
        ["portfolio_id", "occurred_at"],
    )
    op.create_index(
        "ix_transaction_portfolio_symbol",
        "portfolio_transactions",
        ["portfolio_id", "symbol"],
    )

    op.create_table(
        "portfolio_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "portfolio_id",
            sa.Integer(),
            sa.ForeignKey("portfolios.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("total_value", MONEY, nullable=False),
        sa.Column("position_value", MONEY, nullable=False),
        sa.Column("base_cash_balance", MONEY, nullable=False),
        sa.Column("total_cost_basis", MONEY, nullable=False),
        sa.Column("realized_pl", MONEY, nullable=False),
        sa.Column("unrealized_pl", MONEY, nullable=False),
        sa.Column("allocations_json", sa.Text(), nullable=False),
        sa.Column("cash_balances_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("total_value >= 0", name="ck_snapshot_total_nonnegative"),
        sa.CheckConstraint("position_value >= 0", name="ck_snapshot_positions_nonnegative"),
        sa.CheckConstraint("base_cash_balance >= 0", name="ck_snapshot_cash_nonnegative"),
        sa.CheckConstraint("total_cost_basis >= 0", name="ck_snapshot_cost_nonnegative"),
    )
    op.create_index(
        "ix_snapshot_portfolio_captured",
        "portfolio_snapshots",
        ["portfolio_id", "captured_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_snapshot_portfolio_captured", table_name="portfolio_snapshots")
    op.drop_table("portfolio_snapshots")
    op.drop_index("ix_transaction_portfolio_symbol", table_name="portfolio_transactions")
    op.drop_index("ix_transaction_portfolio_occurred", table_name="portfolio_transactions")
    op.drop_table("portfolio_transactions")
    op.drop_table("cash_balances")
    op.drop_table("portfolio_positions")
    op.drop_index("ix_portfolios_name", table_name="portfolios")
    op.drop_index("ix_portfolios_investor_id", table_name="portfolios")
    op.drop_table("portfolios")
    _drop_owned_postgresql_enums("transactiontype")
