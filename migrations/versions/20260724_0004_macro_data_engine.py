"""Add Macro Data Engine v0.4 tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260724_0004"
down_revision: str | None = "20260723_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VALUE = sa.BigInteger()


def upgrade() -> None:
    series_category = sa.Enum(
        "inflation",
        "employment",
        "growth",
        "interest_rate",
        "currency",
        "commodity",
        "equity_index",
        "volatility",
        "liquidity",
        "custom",
        name="seriescategory",
    )
    frequency = sa.Enum(
        "daily",
        "weekly",
        "monthly",
        "quarterly",
        "annual",
        "irregular",
        name="datafrequency",
    )
    seasonal_adjustment = sa.Enum(
        "adjusted",
        "not_adjusted",
        "not_applicable",
        "unknown",
        name="seasonaladjustment",
    )
    observation_status = sa.Enum("present", "missing", name="observationstatus")
    import_status = sa.Enum(
        "processing",
        "completed",
        "completed_with_errors",
        "failed",
        name="importstatus",
    )
    quality_type = sa.Enum(
        "duplicate_observation",
        "impossible_timestamp",
        "frequency_violation",
        "invalid_numeric_range",
        "stale_series",
        "large_unexpected_change",
        name="qualityissuetype",
    )
    quality_status = sa.Enum("open", "acknowledged", "resolved", name="qualityissuestatus")

    op.create_table(
        "data_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(80), nullable=False, unique=True),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("reference_url", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_data_sources_name", "data_sources", ["name"])

    op.create_table(
        "data_series",
        sa.Column(
            "source_id",
            sa.Integer(),
            sa.ForeignKey("data_sources.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(120), nullable=False, unique=True),
        sa.Column("name", sa.String(240), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("category", series_category, nullable=False),
        sa.Column("geography", sa.String(120), nullable=False),
        sa.Column("frequency", frequency, nullable=False),
        sa.Column("unit", sa.String(80), nullable=False),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("seasonal_adjustment", seasonal_adjustment, nullable=False),
        sa.Column("publication_lag_days", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("series_metadata", sa.JSON(), nullable=False),
        sa.Column("minimum_value", VALUE, nullable=True),
        sa.Column("maximum_value", VALUE, nullable=True),
        sa.Column("max_change_percent", VALUE, nullable=True),
        sa.Column("stale_after_days", sa.Integer(), nullable=True),
        sa.Column("lock_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("publication_lag_days >= 0", name="ck_series_publication_lag"),
        sa.CheckConstraint(
            "stale_after_days IS NULL OR stale_after_days > 0",
            name="ck_series_stale",
        ),
        sa.CheckConstraint(
            "minimum_value IS NULL OR maximum_value IS NULL OR minimum_value <= maximum_value",
            name="ck_series_value_range",
        ),
        sa.CheckConstraint(
            "max_change_percent IS NULL OR max_change_percent >= 0",
            name="ck_series_change_nonnegative",
        ),
        sa.CheckConstraint("lock_version > 0", name="ck_series_lock_version"),
    )
    op.create_index("ix_data_series_source_id", "data_series", ["source_id"])
    op.create_index("ix_data_series_name", "data_series", ["name"])
    op.create_index("ix_data_series_category", "data_series", ["category"])
    op.create_index("ix_data_series_active_category", "data_series", ["is_active", "category"])

    op.create_table(
        "data_import_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "source_id",
            sa.Integer(),
            sa.ForeignKey("data_sources.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(160), nullable=False, unique=True),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("imported_at", sa.DateTime(), nullable=False),
        sa.Column("status", import_status, nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("accepted_rows", sa.Integer(), nullable=False),
        sa.Column("rejected_rows", sa.Integer(), nullable=False),
        sa.Column("partial_mode", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.CheckConstraint("row_count >= 0", name="ck_import_row_count"),
        sa.CheckConstraint("accepted_rows >= 0", name="ck_import_accepted"),
        sa.CheckConstraint("rejected_rows >= 0", name="ck_import_rejected"),
        sa.CheckConstraint(
            "accepted_rows + rejected_rows = row_count",
            name="ck_import_count_total",
        ),
    )
    op.create_index("ix_data_import_batches_source_id", "data_import_batches", ["source_id"])
    op.create_index(
        "ix_import_source_imported",
        "data_import_batches",
        ["source_id", "imported_at"],
    )

    op.create_table(
        "data_observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "series_id",
            sa.Integer(),
            sa.ForeignKey("data_series.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "import_batch_id",
            sa.Integer(),
            sa.ForeignKey("data_import_batches.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("publication_timestamp", sa.DateTime(), nullable=False),
        sa.Column("ingestion_timestamp", sa.DateTime(), nullable=False),
        sa.Column("value", VALUE, nullable=True),
        sa.Column("status", observation_status, nullable=False),
        sa.Column("source_reference", sa.String(500), nullable=True),
        sa.UniqueConstraint("series_id", "observed_at", name="uq_observation_series_timestamp"),
        sa.CheckConstraint(
            "(status = 'present' AND value IS NOT NULL) OR (status = 'missing' AND value IS NULL)",
            name="ck_observation_status_value",
        ),
        sa.CheckConstraint(
            "publication_timestamp >= observed_at",
            name="ck_observation_publication_time",
        ),
        sa.CheckConstraint(
            "ingestion_timestamp >= publication_timestamp",
            name="ck_observation_ingestion_time",
        ),
    )
    op.create_index(
        "ix_observation_series_observed",
        "data_observations",
        ["series_id", "observed_at"],
    )
    op.create_index(
        "ix_observation_series_ingested",
        "data_observations",
        ["series_id", "ingestion_timestamp"],
    )

    op.create_table(
        "data_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "observation_id",
            sa.Integer(),
            sa.ForeignKey("data_observations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "import_batch_id",
            sa.Integer(),
            sa.ForeignKey("data_import_batches.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("previous_value", VALUE, nullable=True),
        sa.Column("revised_value", VALUE, nullable=True),
        sa.Column("previous_status", observation_status, nullable=False),
        sa.Column("revised_status", observation_status, nullable=False),
        sa.Column("publication_timestamp", sa.DateTime(), nullable=False),
        sa.Column("revision_timestamp", sa.DateTime(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("source_reference", sa.String(500), nullable=True),
        sa.UniqueConstraint(
            "observation_id",
            "sequence",
            name="uq_revision_observation_sequence",
        ),
        sa.CheckConstraint("sequence > 0", name="ck_data_revision_sequence"),
        sa.CheckConstraint(
            "(previous_status = 'present' AND previous_value IS NOT NULL) OR "
            "(previous_status = 'missing' AND previous_value IS NULL)",
            name="ck_revision_previous_status_value",
        ),
        sa.CheckConstraint(
            "(revised_status = 'present' AND revised_value IS NOT NULL) OR "
            "(revised_status = 'missing' AND revised_value IS NULL)",
            name="ck_revision_revised_status_value",
        ),
    )
    op.create_index(
        "ix_revision_observation_time",
        "data_revisions",
        ["observation_id", "revision_timestamp"],
    )

    op.create_table(
        "data_quality_issues",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "series_id",
            sa.Integer(),
            sa.ForeignKey("data_series.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "observation_id",
            sa.Integer(),
            sa.ForeignKey("data_observations.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("issue_type", quality_type, nullable=False),
        sa.Column("status", quality_status, nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("detected_at", sa.DateTime(), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("resolution_notes", sa.Text(), nullable=False),
        sa.Column("lock_version", sa.Integer(), nullable=False),
        sa.CheckConstraint("lock_version > 0", name="ck_quality_lock_version"),
    )
    op.create_index(
        "ix_quality_status_detected",
        "data_quality_issues",
        ["status", "detected_at"],
    )
    op.create_index(
        "ix_quality_series_type",
        "data_quality_issues",
        ["series_id", "issue_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_quality_series_type", table_name="data_quality_issues")
    op.drop_index("ix_quality_status_detected", table_name="data_quality_issues")
    op.drop_table("data_quality_issues")
    op.drop_index("ix_revision_observation_time", table_name="data_revisions")
    op.drop_table("data_revisions")
    op.drop_index("ix_observation_series_ingested", table_name="data_observations")
    op.drop_index("ix_observation_series_observed", table_name="data_observations")
    op.drop_table("data_observations")
    op.drop_index("ix_import_source_imported", table_name="data_import_batches")
    op.drop_index("ix_data_import_batches_source_id", table_name="data_import_batches")
    op.drop_table("data_import_batches")
    op.drop_index("ix_data_series_active_category", table_name="data_series")
    op.drop_index("ix_data_series_category", table_name="data_series")
    op.drop_index("ix_data_series_name", table_name="data_series")
    op.drop_index("ix_data_series_source_id", table_name="data_series")
    op.drop_table("data_series")
    op.drop_index("ix_data_sources_name", table_name="data_sources")
    op.drop_table("data_sources")
