"""Create initial MacroVision schema."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260723_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "investor_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("base_currency", sa.String(3), nullable=False),
        sa.Column("investment_horizon_years", sa.Integer(), nullable=False),
        sa.Column("liquidity_need", sa.Float(), nullable=False),
        sa.Column("objectives", sa.Text(), nullable=False),
        sa.Column("constraints", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("investment_horizon_years > 0", name="ck_profile_horizon_positive"),
        sa.CheckConstraint(
            "liquidity_need >= 0 AND liquidity_need <= 1", name="ck_profile_liquidity_range"
        ),
    )
    op.create_index("ix_investor_profiles_name", "investor_profiles", ["name"])
    op.create_table(
        "risk_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "investor_id",
            sa.Integer(),
            sa.ForeignKey("investor_profiles.id", ondelete="CASCADE"),
            unique=True,
            nullable=False,
        ),
        sa.Column(
            "tolerance",
            sa.Enum("conservative", "moderate", "growth", "aggressive", name="risktolerance"),
            nullable=False,
        ),
        sa.Column("max_drawdown", sa.Float(), nullable=False),
        sa.Column("loss_capacity", sa.Float(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "max_drawdown >= 0 AND max_drawdown <= 1", name="ck_risk_drawdown_range"
        ),
        sa.CheckConstraint(
            "loss_capacity >= 0 AND loss_capacity <= 1", name="ck_risk_capacity_range"
        ),
    )
    op.create_table(
        "risk_budgets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "risk_profile_id",
            sa.Integer(),
            sa.ForeignKey("risk_profiles.id", ondelete="CASCADE"),
            unique=True,
            nullable=False,
        ),
        sa.Column("total_risk_budget", sa.Float(), nullable=False),
        sa.Column("per_decision_limit", sa.Float(), nullable=False),
        sa.Column("minimum_cash_allocation", sa.Float(), nullable=False),
        sa.CheckConstraint(
            "total_risk_budget >= 0 AND total_risk_budget <= 1", name="ck_budget_total_range"
        ),
        sa.CheckConstraint(
            "per_decision_limit >= 0 AND per_decision_limit <= total_risk_budget",
            name="ck_budget_decision_limit",
        ),
        sa.CheckConstraint(
            "minimum_cash_allocation >= 0 AND minimum_cash_allocation <= 1",
            name="ck_budget_cash_range",
        ),
    )
    op.create_table(
        "research_journals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "investor_id",
            sa.Integer(),
            sa.ForeignKey("investor_profiles.id"),
            nullable=False,
        ),
        sa.Column("asset", sa.String(120), nullable=False),
        sa.Column("hypothesis", sa.Text(), nullable=False),
        sa.Column("evidence_for", sa.Text(), nullable=False),
        sa.Column("evidence_against", sa.Text(), nullable=False),
        sa.Column("critic_review", sa.Text(), nullable=False),
        sa.Column("probability", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("invalidation_conditions", sa.Text(), nullable=False),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column("lessons", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("draft", "active", "invalidated", "closed", name="journalstatus"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "probability >= 0 AND probability <= 1", name="ck_journal_probability_range"
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_journal_confidence_range"
        ),
    )
    op.create_index("ix_research_journals_asset", "research_journals", ["asset"])


def downgrade() -> None:
    op.drop_index("ix_research_journals_asset", table_name="research_journals")
    op.drop_table("research_journals")
    op.drop_table("risk_budgets")
    op.drop_table("risk_profiles")
    op.drop_index("ix_investor_profiles_name", table_name="investor_profiles")
    op.drop_table("investor_profiles")
