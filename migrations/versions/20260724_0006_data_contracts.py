"""Standardize data contracts, UTC timestamps, ratios, and quality history."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM

revision: str = "20260724_0006"
down_revision: str | None = "20260724_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RATIO_COLUMNS = {
    "investor_profiles": ("liquidity_need",),
    "risk_profiles": ("max_drawdown", "loss_capacity"),
    "risk_budgets": (
        "total_risk_budget",
        "per_decision_limit",
        "minimum_cash_allocation",
    ),
    "research_journals": ("probability", "confidence"),
}
RATIO_CHECKS = {
    "investor_profiles": {
        "ck_profile_liquidity_range": "liquidity_need >= 0 AND liquidity_need <= {maximum}",
    },
    "risk_profiles": {
        "ck_risk_drawdown_range": "max_drawdown >= 0 AND max_drawdown <= {maximum}",
        "ck_risk_capacity_range": "loss_capacity >= 0 AND loss_capacity <= {maximum}",
    },
    "risk_budgets": {
        "ck_budget_total_range": "total_risk_budget >= 0 AND total_risk_budget <= {maximum}",
        "ck_budget_decision_limit": (
            "per_decision_limit >= 0 AND per_decision_limit <= total_risk_budget"
        ),
        "ck_budget_cash_range": (
            "minimum_cash_allocation >= 0 AND minimum_cash_allocation <= {maximum}"
        ),
    },
    "research_journals": {
        "ck_journal_probability_range": "probability >= 0 AND probability <= {maximum}",
        "ck_journal_confidence_range": "confidence >= 0 AND confidence <= {maximum}",
    },
}

TIMESTAMP_COLUMNS = {
    "investor_profiles": ("created_at",),
    "research_journals": ("closed_at", "created_at", "updated_at"),
    "portfolios": ("created_at",),
    "portfolio_positions": ("updated_at",),
    "cash_balances": ("updated_at",),
    "portfolio_transactions": ("occurred_at", "created_at"),
    "portfolio_snapshots": ("captured_at", "created_at"),
    "decision_cases": ("created_at", "updated_at"),
    "decision_hypotheses": ("created_at",),
    "supporting_evidence": ("created_at",),
    "opposing_evidence": ("created_at",),
    "critic_reviews": ("created_at",),
    "invalidation_rules": ("created_at",),
    "decision_outcomes": ("created_at",),
    "decision_revisions": ("created_at",),
    "data_sources": ("created_at",),
    "data_series": ("created_at", "updated_at"),
    "data_import_batches": ("imported_at", "failed_at"),
    "data_import_errors": ("created_at",),
    "data_observations": (
        "observed_at",
        "publication_timestamp",
        "ingestion_timestamp",
    ),
    "data_revisions": ("publication_timestamp", "revision_timestamp"),
    "data_quality_issues": ("detected_at", "acknowledged_at", "resolved_at"),
}


def _alter_timestamps(*, timezone: bool) -> None:
    for table, columns in TIMESTAMP_COLUMNS.items():
        with op.batch_alter_table(table) as batch:
            for column in columns:
                using = f"{column} AT TIME ZONE 'UTC'"
                batch.alter_column(
                    column,
                    type_=sa.DateTime(timezone=timezone),
                    existing_type=sa.DateTime(timezone=not timezone),
                    postgresql_using=using,
                )


def _half_even_scaled(column: str) -> str:
    scaled = f"({column} * 1000000)"
    lower = f"FLOOR({scaled})"
    return (
        "CASE "
        f"WHEN ({scaled} - {lower}) = 0.5 "
        f"AND (CAST({lower} AS BIGINT) % 2) = 0 "
        f"THEN {lower} ELSE FLOOR({scaled} + 0.5) END"
    )


def upgrade() -> None:
    for table, columns in RATIO_COLUMNS.items():
        with op.batch_alter_table(table) as batch:
            for constraint in RATIO_CHECKS[table]:
                batch.drop_constraint(constraint, type_="check")
        for column in columns:
            op.execute(sa.text(f"UPDATE {table} SET {column} = {_half_even_scaled(column)}"))
        with op.batch_alter_table(table) as batch:
            for column in columns:
                batch.alter_column(
                    column,
                    type_=sa.BigInteger(),
                    existing_type=sa.Float(),
                    postgresql_using=f"CAST({column} AS BIGINT)",
                )
            for name, expression in RATIO_CHECKS[table].items():
                batch.create_check_constraint(name, expression.format(maximum=1000000))

    _alter_timestamps(timezone=True)

    quality_status = ENUM(
        "open", "acknowledged", "resolved", name="qualityissuestatus", create_type=False
    )
    op.create_table(
        "data_quality_issue_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "issue_id",
            sa.Integer(),
            sa.ForeignKey("data_quality_issues.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("previous_status", quality_status, nullable=False),
        sa.Column("new_status", quality_status, nullable=False),
        sa.Column("event_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.String(length=1000), nullable=False),
        sa.Column("actor_reference", sa.String(length=200), nullable=True),
        sa.Column("source_lock_version", sa.Integer(), nullable=False),
        sa.CheckConstraint("source_lock_version > 0", name="ck_quality_event_lock_version"),
    )
    op.create_index(
        "ix_quality_event_issue_time",
        "data_quality_issue_events",
        ["issue_id", "event_timestamp", "id"],
    )
    op.create_index(
        "uq_open_stale_issue_per_series",
        "data_quality_issues",
        ["series_id"],
        unique=True,
        sqlite_where=sa.text("issue_type = 'stale_series' AND status != 'resolved'"),
        postgresql_where=sa.text("issue_type = 'stale_series' AND status != 'resolved'"),
    )


def downgrade() -> None:
    op.drop_index("uq_open_stale_issue_per_series", table_name="data_quality_issues")
    op.drop_index("ix_quality_event_issue_time", table_name="data_quality_issue_events")
    op.drop_table("data_quality_issue_events")
    _alter_timestamps(timezone=False)
    for table, columns in RATIO_COLUMNS.items():
        with op.batch_alter_table(table) as batch:
            for constraint in RATIO_CHECKS[table]:
                batch.drop_constraint(constraint, type_="check")
            for column in columns:
                batch.alter_column(
                    column,
                    type_=sa.Float(),
                    existing_type=sa.BigInteger(),
                    postgresql_using=f"{column}::double precision",
                )
        for column in columns:
            op.execute(sa.text(f"UPDATE {table} SET {column} = {column} / 1000000.0"))
        with op.batch_alter_table(table) as batch:
            for name, expression in RATIO_CHECKS[table].items():
                batch.create_check_constraint(name, expression.format(maximum=1))
