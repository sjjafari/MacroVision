"""Add Decision Engine v0.3 tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM

revision: str = "20260723_0003"
down_revision: str | None = "20260723_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCORE_MAX = 1_000_000


def _drop_owned_postgresql_enums(*names: str) -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for name in names:
        ENUM(name=name).drop(bind, checkfirst=True)


def _score_constraints(prefix: str) -> tuple[sa.CheckConstraint, sa.CheckConstraint]:
    return (
        sa.CheckConstraint(
            f"reliability_score >= 0 AND reliability_score <= {SCORE_MAX}",
            name=f"ck_{prefix}_reliability_range",
        ),
        sa.CheckConstraint(
            f"relevance_score >= 0 AND relevance_score <= {SCORE_MAX}",
            name=f"ck_{prefix}_relevance_range",
        ),
    )


def upgrade() -> None:
    decision_status = sa.Enum(
        "draft",
        "under_review",
        "active",
        "invalidated",
        "closed",
        name="decisionstatus",
    )
    source_type = sa.Enum(
        "research_paper",
        "financial_statement",
        "market_data",
        "news",
        "expert_opinion",
        "internal_analysis",
        "other",
        name="evidencesourcetype",
    )
    revision_event = sa.Enum(
        "created",
        "review_started",
        "revised",
        "activated",
        "invalidated",
        "closed",
        name="revisionevent",
    )

    op.create_table(
        "decision_cases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("context", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("probability", sa.BigInteger(), nullable=False),
        sa.Column("confidence", sa.BigInteger(), nullable=False),
        sa.Column("status", decision_status, nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("lock_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            f"probability >= 0 AND probability <= {SCORE_MAX}",
            name="ck_decision_probability_range",
        ),
        sa.CheckConstraint(
            f"confidence >= 0 AND confidence <= {SCORE_MAX}",
            name="ck_decision_confidence_range",
        ),
        sa.CheckConstraint("current_version > 0", name="ck_decision_version_positive"),
        sa.CheckConstraint("lock_version > 0", name="ck_decision_lock_version_positive"),
    )
    op.create_index("ix_decision_cases_title", "decision_cases", ["title"])
    op.create_index("ix_decision_status_updated", "decision_cases", ["status", "updated_at"])

    op.create_table(
        "decision_hypotheses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "decision_id",
            sa.Integer(),
            sa.ForeignKey("decision_cases.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_hypothesis_decision_created",
        "decision_hypotheses",
        ["decision_id", "created_at"],
    )

    op.create_table(
        "supporting_evidence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "decision_id",
            sa.Integer(),
            sa.ForeignKey("decision_cases.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_title", sa.String(240), nullable=False),
        sa.Column("source_type", source_type, nullable=False),
        sa.Column("publication_date", sa.Date(), nullable=True),
        sa.Column("reference", sa.String(500), nullable=True),
        sa.Column("reliability_score", sa.BigInteger(), nullable=False),
        sa.Column("relevance_score", sa.BigInteger(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        *_score_constraints("support"),
    )
    op.create_index(
        "ix_support_decision_created",
        "supporting_evidence",
        ["decision_id", "created_at"],
    )

    op.create_table(
        "opposing_evidence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "decision_id",
            sa.Integer(),
            sa.ForeignKey("decision_cases.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_title", sa.String(240), nullable=False),
        sa.Column("source_type", source_type, nullable=False),
        sa.Column("publication_date", sa.Date(), nullable=True),
        sa.Column("reference", sa.String(500), nullable=True),
        sa.Column("reliability_score", sa.BigInteger(), nullable=False),
        sa.Column("relevance_score", sa.BigInteger(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        *_score_constraints("oppose"),
    )
    op.create_index(
        "ix_oppose_decision_created",
        "opposing_evidence",
        ["decision_id", "created_at"],
    )

    op.create_table(
        "critic_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "decision_id",
            sa.Integer(),
            sa.ForeignKey("decision_cases.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("reviewer", sa.String(160), nullable=False),
        sa.Column("analysis", sa.Text(), nullable=False),
        sa.Column("key_risks", sa.Text(), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_critic_decision_created",
        "critic_reviews",
        ["decision_id", "created_at"],
    )

    op.create_table(
        "invalidation_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "decision_id",
            sa.Integer(),
            sa.ForeignKey("decision_cases.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("condition", sa.Text(), nullable=False),
        sa.Column("observation_source", sa.String(300), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_rule_decision_created",
        "invalidation_rules",
        ["decision_id", "created_at"],
    )

    op.create_table(
        "decision_outcomes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "decision_id",
            sa.Integer(),
            sa.ForeignKey("decision_cases.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("lessons_learned", sa.Text(), nullable=False),
        sa.Column("accuracy_assessment", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            f"accuracy_assessment >= 0 AND accuracy_assessment <= {SCORE_MAX}",
            name="ck_outcome_accuracy_range",
        ),
    )

    op.create_table(
        "decision_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "decision_id",
            sa.Integer(),
            sa.ForeignKey("decision_cases.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("event", revision_event, nullable=False),
        sa.Column("status", decision_status, nullable=False),
        sa.Column("probability", sa.BigInteger(), nullable=False),
        sa.Column("confidence", sa.BigInteger(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("change_summary", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("decision_id", "version", name="uq_revision_decision_version"),
        sa.CheckConstraint("version > 0", name="ck_revision_version_positive"),
        sa.CheckConstraint(
            f"probability >= 0 AND probability <= {SCORE_MAX}",
            name="ck_revision_probability_range",
        ),
        sa.CheckConstraint(
            f"confidence >= 0 AND confidence <= {SCORE_MAX}",
            name="ck_revision_confidence_range",
        ),
    )


def downgrade() -> None:
    op.drop_table("decision_revisions")
    op.drop_table("decision_outcomes")
    op.drop_index("ix_rule_decision_created", table_name="invalidation_rules")
    op.drop_table("invalidation_rules")
    op.drop_index("ix_critic_decision_created", table_name="critic_reviews")
    op.drop_table("critic_reviews")
    op.drop_index("ix_oppose_decision_created", table_name="opposing_evidence")
    op.drop_table("opposing_evidence")
    op.drop_index("ix_support_decision_created", table_name="supporting_evidence")
    op.drop_table("supporting_evidence")
    op.drop_index("ix_hypothesis_decision_created", table_name="decision_hypotheses")
    op.drop_table("decision_hypotheses")
    op.drop_index("ix_decision_status_updated", table_name="decision_cases")
    op.drop_index("ix_decision_cases_title", table_name="decision_cases")
    op.drop_table("decision_cases")
    _drop_owned_postgresql_enums(
        "revisionevent",
        "evidencesourcetype",
        "decisionstatus",
    )
