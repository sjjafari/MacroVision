"""Stabilize aggregate concurrency and audit safety."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260724_0005"
down_revision: str | None = "20260724_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("portfolios") as batch:
        batch.add_column(
            sa.Column(
                "lock_version",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("1"),
            )
        )
        batch.create_check_constraint("ck_portfolio_lock_version_positive", "lock_version > 0")

    with op.batch_alter_table("research_journals") as batch:
        batch.add_column(sa.Column("closed_at", sa.DateTime(), nullable=True))
        batch.add_column(
            sa.Column(
                "lock_version",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("1"),
            )
        )
        batch.create_check_constraint("ck_journal_lock_version_positive", "lock_version > 0")
    op.execute(
        sa.text(
            "UPDATE research_journals SET closed_at = updated_at "
            "WHERE status = 'closed' AND closed_at IS NULL"
        )
    )

    with op.batch_alter_table("data_import_batches") as batch:
        batch.add_column(sa.Column("failed_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("failure_summary", sa.String(length=500), nullable=True))
        batch.create_check_constraint(
            "ck_import_failure_details",
            "(status = 'failed' AND failed_at IS NOT NULL "
            "AND failure_summary IS NOT NULL) OR "
            "(status != 'failed' AND failed_at IS NULL "
            "AND failure_summary IS NULL)",
        )

    op.create_table(
        "data_import_errors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "import_batch_id",
            sa.Integer(),
            sa.ForeignKey("data_import_batches.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("row_index", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=False),
        sa.Column("message", sa.String(length=500), nullable=False),
        sa.Column("source_context", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("row_index >= 0", name="ck_import_error_row_index"),
    )
    op.create_index(
        "ix_import_error_batch_row",
        "data_import_errors",
        ["import_batch_id", "row_index"],
    )


def downgrade() -> None:
    op.drop_index("ix_import_error_batch_row", table_name="data_import_errors")
    op.drop_table("data_import_errors")

    with op.batch_alter_table("data_import_batches") as batch:
        batch.drop_constraint("ck_import_failure_details", type_="check")
        batch.drop_column("failure_summary")
        batch.drop_column("failed_at")

    with op.batch_alter_table("research_journals") as batch:
        batch.drop_constraint("ck_journal_lock_version_positive", type_="check")
        batch.drop_column("lock_version")
        batch.drop_column("closed_at")

    with op.batch_alter_table("portfolios") as batch:
        batch.drop_constraint("ck_portfolio_lock_version_positive", type_="check")
        batch.drop_column("lock_version")
