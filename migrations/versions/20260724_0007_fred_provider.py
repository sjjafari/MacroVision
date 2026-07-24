"""Add provider provenance for external data synchronization."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260724_0007"
down_revision: str | None = "20260724_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("data_series") as batch:
        batch.add_column(sa.Column("provider_series_id", sa.String(length=120), nullable=True))
        batch.create_unique_constraint(
            "uq_data_series_source_provider_id",
            ["source_id", "provider_series_id"],
        )
        batch.create_check_constraint(
            "ck_series_provider_id_nonempty",
            "provider_series_id IS NULL OR LENGTH(provider_series_id) > 0",
        )

    with op.batch_alter_table("data_import_batches") as batch:
        batch.add_column(
            sa.Column(
                "provider_metadata",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )

    with op.batch_alter_table("data_observations") as batch:
        batch.drop_constraint("ck_observation_publication_time", type_="check")
        batch.drop_constraint("ck_observation_ingestion_time", type_="check")
        batch.alter_column(
            "publication_timestamp",
            existing_type=sa.DateTime(timezone=True),
            nullable=True,
        )
        batch.add_column(sa.Column("provider_vintage_start", sa.Date(), nullable=True))
        batch.add_column(sa.Column("provider_vintage_end", sa.Date(), nullable=True))
        batch.add_column(
            sa.Column(
                "provider_metadata",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )
        batch.create_check_constraint(
            "ck_observation_publication_time",
            "publication_timestamp IS NULL OR publication_timestamp >= observed_at",
        )
        batch.create_check_constraint(
            "ck_observation_ingestion_time",
            "publication_timestamp IS NULL OR ingestion_timestamp >= publication_timestamp",
        )
        batch.create_check_constraint(
            "ck_observation_vintage_range",
            "provider_vintage_end IS NULL OR provider_vintage_start IS NULL OR "
            "provider_vintage_end >= provider_vintage_start",
        )

    with op.batch_alter_table("data_revisions") as batch:
        batch.alter_column(
            "publication_timestamp",
            existing_type=sa.DateTime(timezone=True),
            nullable=True,
        )
        batch.add_column(sa.Column("provider_vintage_start", sa.Date(), nullable=True))
        batch.add_column(sa.Column("provider_vintage_end", sa.Date(), nullable=True))
        batch.add_column(
            sa.Column(
                "provider_metadata",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )
        batch.create_check_constraint(
            "ck_revision_vintage_range",
            "provider_vintage_end IS NULL OR provider_vintage_start IS NULL OR "
            "provider_vintage_end >= provider_vintage_start",
        )

    with op.batch_alter_table("data_import_batches") as batch:
        batch.alter_column("provider_metadata", server_default=None)
    with op.batch_alter_table("data_observations") as batch:
        batch.alter_column("provider_metadata", server_default=None)
    with op.batch_alter_table("data_revisions") as batch:
        batch.alter_column("provider_metadata", server_default=None)


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE data_observations SET publication_timestamp = ingestion_timestamp "
            "WHERE publication_timestamp IS NULL"
        )
    )
    op.execute(
        sa.text(
            "UPDATE data_revisions SET publication_timestamp = revision_timestamp "
            "WHERE publication_timestamp IS NULL"
        )
    )
    with op.batch_alter_table("data_revisions") as batch:
        batch.drop_constraint("ck_revision_vintage_range", type_="check")
        batch.drop_column("provider_metadata")
        batch.drop_column("provider_vintage_end")
        batch.drop_column("provider_vintage_start")
        batch.alter_column(
            "publication_timestamp",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
        )

    with op.batch_alter_table("data_observations") as batch:
        batch.drop_constraint("ck_observation_vintage_range", type_="check")
        batch.drop_constraint("ck_observation_ingestion_time", type_="check")
        batch.drop_constraint("ck_observation_publication_time", type_="check")
        batch.drop_column("provider_metadata")
        batch.drop_column("provider_vintage_end")
        batch.drop_column("provider_vintage_start")
        batch.alter_column(
            "publication_timestamp",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
        )
        batch.create_check_constraint(
            "ck_observation_publication_time",
            "publication_timestamp >= observed_at",
        )
        batch.create_check_constraint(
            "ck_observation_ingestion_time",
            "ingestion_timestamp >= publication_timestamp",
        )

    with op.batch_alter_table("data_import_batches") as batch:
        batch.drop_column("provider_metadata")

    with op.batch_alter_table("data_series") as batch:
        batch.drop_constraint("ck_series_provider_id_nonempty", type_="check")
        batch.drop_constraint("uq_data_series_source_provider_id", type_="unique")
        batch.drop_column("provider_series_id")
