"""Add Macro Analytics Phase 2A persistence."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260726_0009"
down_revision: str | None = "20260724_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_HEX_CHARS = "0123456789abcdef"


def _only_characters(column: str, characters: str) -> str:
    expression = column
    for character in characters:
        escaped = character.replace("'", "''")
        expression = f"REPLACE({expression}, '{escaped}', '')"
    return f"LENGTH({expression}) = 0"


def _fingerprint(column: str, *, nullable: bool) -> str:
    shape = (
        f"LENGTH({column}) = 64 AND {column} = LOWER({column}) "
        f"AND {_only_characters(column, _HEX_CHARS)}"
    )
    return f"{column} IS NULL OR ({shape})" if nullable else shape


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    code_check = (
        "LENGTH(code) BETWEEN 1 AND 120 AND code = UPPER(code) "
        "AND code GLOB '[A-Z]*' AND code NOT GLOB '*[^A-Z0-9_.-]*'"
        if dialect == "sqlite"
        else "code ~ '^[A-Z][A-Z0-9_.-]{0,119}$'"
    )
    op.create_table(
        "derived_series_definitions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=120), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("lock_version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(code_check, name="ck_derived_definition_code"),
        sa.CheckConstraint("LENGTH(title) BETWEEN 1 AND 240", name="ck_derived_definition_title"),
        sa.CheckConstraint(
            "description IS NULL OR LENGTH(description) <= 2000",
            name="ck_derived_definition_description",
        ),
        sa.CheckConstraint("lock_version > 0", name="ck_derived_definition_lock_version"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index(
        "ix_derived_definition_enabled_code",
        "derived_series_definitions",
        ["enabled", "code", "id"],
    )

    op.create_table(
        "derived_series_definition_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("definition_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("transformation_type", sa.String(length=48), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("parameters_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("output_unit", sa.String(length=80), nullable=False),
        sa.Column("output_frequency", sa.String(length=16), nullable=False),
        sa.Column("output_geography", sa.String(length=120), nullable=False),
        sa.Column("output_currency", sa.String(length=3), nullable=True),
        sa.Column("output_seasonal_adjustment", sa.String(length=24), nullable=False),
        sa.Column("engine_contract_version", sa.String(length=32), nullable=False),
        sa.Column("change_note", sa.String(length=1000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("version > 0", name="ck_derived_version_positive"),
        sa.CheckConstraint(
            "transformation_type IN "
            "('difference','percent_change','year_over_year_percent_change','ratio',"
            "'spread','moving_average','rolling_standard_deviation','rolling_z_score',"
            "'rebase_index')",
            name="ck_derived_version_transformation",
        ),
        sa.CheckConstraint(
            "LENGTH(CAST(parameters AS TEXT)) <= 4096",
            name="ck_derived_version_parameters_size",
        ),
        sa.CheckConstraint(
            _fingerprint("parameters_fingerprint", nullable=False),
            name="ck_derived_version_parameters_fingerprint",
        ),
        sa.CheckConstraint(
            "LENGTH(output_unit) BETWEEN 1 AND 80",
            name="ck_derived_version_output_unit",
        ),
        sa.CheckConstraint(
            "output_frequency IN ('daily','weekly','monthly','quarterly','annual')",
            name="ck_derived_version_frequency",
        ),
        sa.CheckConstraint(
            "LENGTH(output_geography) BETWEEN 1 AND 120",
            name="ck_derived_version_geography",
        ),
        sa.CheckConstraint(
            "output_currency IS NULL OR LENGTH(output_currency) = 3",
            name="ck_derived_version_currency",
        ),
        sa.CheckConstraint(
            "output_seasonal_adjustment IN ('adjusted','not_adjusted','not_applicable','unknown')",
            name="ck_derived_version_seasonal_adjustment",
        ),
        sa.CheckConstraint(
            "LENGTH(engine_contract_version) BETWEEN 1 AND 32",
            name="ck_derived_version_engine_contract",
        ),
        sa.CheckConstraint(
            "change_note IS NULL OR LENGTH(change_note) <= 1000",
            name="ck_derived_version_change_note",
        ),
        sa.ForeignKeyConstraint(
            ["definition_id"], ["derived_series_definitions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("definition_id", "version", name="uq_derived_version_number"),
    )
    op.create_index(
        "ix_derived_version_definition_version",
        "derived_series_definition_versions",
        ["definition_id", "version", "id"],
    )

    op.create_table(
        "derived_series_inputs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("definition_version_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("alias", sa.String(length=40), nullable=False),
        sa.Column("source_series_id", sa.Integer(), nullable=False),
        sa.Column("source_code_snapshot", sa.String(length=120), nullable=False),
        sa.Column("source_unit_snapshot", sa.String(length=80), nullable=False),
        sa.Column("source_frequency_snapshot", sa.String(length=16), nullable=False),
        sa.Column("source_geography_snapshot", sa.String(length=120), nullable=False),
        sa.Column("source_currency_snapshot", sa.String(length=3), nullable=True),
        sa.Column("source_seasonal_adjustment_snapshot", sa.String(length=24), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("position >= 0", name="ck_derived_input_position"),
        sa.CheckConstraint(
            "LENGTH(alias) BETWEEN 1 AND 40 AND alias = LOWER(alias)",
            name="ck_derived_input_alias",
        ),
        sa.CheckConstraint(
            "LENGTH(source_code_snapshot) BETWEEN 1 AND 120",
            name="ck_derived_input_source_code",
        ),
        sa.CheckConstraint(
            "LENGTH(source_unit_snapshot) BETWEEN 1 AND 80",
            name="ck_derived_input_source_unit",
        ),
        sa.CheckConstraint(
            "source_frequency_snapshot IN ('daily','weekly','monthly','quarterly','annual')",
            name="ck_derived_input_frequency",
        ),
        sa.CheckConstraint(
            "LENGTH(source_geography_snapshot) BETWEEN 1 AND 120",
            name="ck_derived_input_geography",
        ),
        sa.CheckConstraint(
            "source_currency_snapshot IS NULL OR LENGTH(source_currency_snapshot) = 3",
            name="ck_derived_input_currency",
        ),
        sa.CheckConstraint(
            "source_seasonal_adjustment_snapshot IN "
            "('adjusted','not_adjusted','not_applicable','unknown')",
            name="ck_derived_input_seasonal_adjustment",
        ),
        sa.ForeignKeyConstraint(
            ["definition_version_id"],
            ["derived_series_definition_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["source_series_id"], ["data_series.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("definition_version_id", "alias", name="uq_derived_input_alias"),
        sa.UniqueConstraint("definition_version_id", "position", name="uq_derived_input_position"),
    )
    op.create_index(
        "ix_derived_series_inputs_source_series_id",
        "derived_series_inputs",
        ["source_series_id"],
    )

    op.create_table(
        "analytics_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("definition_version_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("requested_start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("requested_end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("calculation_cutoff", sa.DateTime(timezone=True), nullable=False),
        sa.Column("engine_version", sa.String(length=32), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("snapshot_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("reusable_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("inputs_examined", sa.Integer(), nullable=False),
        sa.Column("outputs_present", sa.Integer(), nullable=False),
        sa.Column("outputs_missing", sa.Integer(), nullable=False),
        sa.Column("lineage_links", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("retry_of_run_id", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending','running','succeeded','failed')",
            name="ck_analytics_run_status",
        ),
        sa.CheckConstraint(
            "requested_start_at <= requested_end_at",
            name="ck_analytics_run_requested_range",
        ),
        sa.CheckConstraint(
            "inputs_examined >= 0 AND outputs_present >= 0 AND outputs_missing >= 0 "
            "AND lineage_links >= 0",
            name="ck_analytics_run_counters",
        ),
        sa.CheckConstraint(
            "LENGTH(engine_version) BETWEEN 1 AND 32",
            name="ck_analytics_run_engine_version",
        ),
        sa.CheckConstraint(
            _fingerprint("request_fingerprint", nullable=False),
            name="ck_analytics_run_request_fingerprint",
        ),
        sa.CheckConstraint(
            _fingerprint("snapshot_fingerprint", nullable=True),
            name="ck_analytics_run_snapshot_fingerprint",
        ),
        sa.CheckConstraint(
            _fingerprint("reusable_fingerprint", nullable=True),
            name="ck_analytics_run_reusable_fingerprint",
        ),
        sa.CheckConstraint(
            "reusable_fingerprint IS NULL OR status = 'succeeded'",
            name="ck_analytics_run_reusable_status",
        ),
        sa.CheckConstraint(
            "retry_of_run_id IS NULL OR retry_of_run_id != id",
            name="ck_analytics_run_retry_not_self",
        ),
        sa.CheckConstraint(
            "error_code IS NULL OR LENGTH(error_code) BETWEEN 1 AND 64",
            name="ck_analytics_run_error_code",
        ),
        sa.CheckConstraint(
            "error_message IS NULL OR LENGTH(error_message) <= 500",
            name="ck_analytics_run_error_message",
        ),
        sa.ForeignKeyConstraint(
            ["definition_version_id"],
            ["derived_series_definition_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["retry_of_run_id"], ["analytics_runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_analytics_run_definition_created",
        "analytics_runs",
        ["definition_version_id", "created_at", "id"],
    )
    op.create_index(
        "ix_analytics_run_status_created",
        "analytics_runs",
        ["status", "created_at", "id"],
    )
    op.create_index("ix_analytics_run_cutoff", "analytics_runs", ["calculation_cutoff", "id"])
    op.create_index(
        "uq_analytics_run_active_request",
        "analytics_runs",
        ["request_fingerprint"],
        unique=True,
        sqlite_where=sa.text("status IN ('pending','running')"),
        postgresql_where=sa.text("status IN ('pending','running')"),
    )
    op.create_index(
        "uq_analytics_run_reusable",
        "analytics_runs",
        ["reusable_fingerprint"],
        unique=True,
        sqlite_where=sa.text("reusable_fingerprint IS NOT NULL"),
        postgresql_where=sa.text("reusable_fingerprint IS NOT NULL"),
    )

    op.create_table(
        "derived_observations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("definition_version_id", sa.Integer(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("value", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("missing_reason", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(status = 'present' AND value IS NOT NULL AND missing_reason IS NULL) OR "
            "(status = 'missing' AND value IS NULL AND missing_reason IN "
            "('source_missing','timestamp_absent','insufficient_history',"
            "'division_by_zero','non_finite_result','numeric_overflow'))",
            name="ck_derived_observation_shape",
        ),
        sa.ForeignKeyConstraint(
            ["definition_version_id"],
            ["derived_series_definition_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["analytics_runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "observed_at", name="uq_derived_observation_run_time"),
    )
    op.create_index(
        "ix_derived_observation_definition_time",
        "derived_observations",
        ["definition_version_id", "observed_at", "id"],
    )
    op.create_index(
        "ix_derived_observation_run_time",
        "derived_observations",
        ["run_id", "observed_at", "id"],
    )

    op.create_table(
        "derived_observation_lineage",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("derived_observation_id", sa.Integer(), nullable=False),
        sa.Column("input_position", sa.Integer(), nullable=False),
        sa.Column("source_observation_id", sa.Integer(), nullable=False),
        sa.Column("source_revision_id", sa.Integer(), nullable=True),
        sa.Column("source_version_kind", sa.String(length=16), nullable=False),
        sa.Column("source_version_id", sa.Integer(), nullable=False),
        sa.Column("lineage_position", sa.Integer(), nullable=False),
        sa.Column("source_knowledge_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("input_position >= 0", name="ck_derived_lineage_input_position"),
        sa.CheckConstraint("lineage_position >= 0", name="ck_derived_lineage_position"),
        sa.CheckConstraint(
            "(source_revision_id IS NULL AND source_version_kind = 'original' "
            "AND source_version_id = source_observation_id) OR "
            "(source_revision_id IS NOT NULL AND source_version_kind = 'revision' "
            "AND source_version_id = source_revision_id)",
            name="ck_derived_lineage_source_shape",
        ),
        sa.ForeignKeyConstraint(
            ["derived_observation_id"],
            ["derived_observations.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_observation_id"],
            ["data_observations.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["source_revision_id"], ["data_revisions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "derived_observation_id",
            "input_position",
            "source_version_kind",
            "source_version_id",
            "lineage_position",
            name="uq_derived_lineage_version_position",
        ),
    )
    op.create_index(
        "ix_derived_lineage_source_observation",
        "derived_observation_lineage",
        ["source_observation_id"],
    )
    op.create_index(
        "ix_derived_lineage_source_revision",
        "derived_observation_lineage",
        ["source_revision_id"],
    )
    op.create_index(
        "ix_derived_lineage_point_position",
        "derived_observation_lineage",
        ["derived_observation_id", "input_position", "lineage_position", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_derived_lineage_point_position", table_name="derived_observation_lineage")
    op.drop_index("ix_derived_lineage_source_revision", table_name="derived_observation_lineage")
    op.drop_index("ix_derived_lineage_source_observation", table_name="derived_observation_lineage")
    op.drop_table("derived_observation_lineage")
    op.drop_index("ix_derived_observation_run_time", table_name="derived_observations")
    op.drop_index("ix_derived_observation_definition_time", table_name="derived_observations")
    op.drop_table("derived_observations")
    op.drop_index("uq_analytics_run_reusable", table_name="analytics_runs")
    op.drop_index("uq_analytics_run_active_request", table_name="analytics_runs")
    op.drop_index("ix_analytics_run_cutoff", table_name="analytics_runs")
    op.drop_index("ix_analytics_run_status_created", table_name="analytics_runs")
    op.drop_index("ix_analytics_run_definition_created", table_name="analytics_runs")
    op.drop_table("analytics_runs")
    op.drop_index("ix_derived_series_inputs_source_series_id", table_name="derived_series_inputs")
    op.drop_table("derived_series_inputs")
    op.drop_index(
        "ix_derived_version_definition_version",
        table_name="derived_series_definition_versions",
    )
    op.drop_table("derived_series_definition_versions")
    op.drop_index("ix_derived_definition_enabled_code", table_name="derived_series_definitions")
    op.drop_table("derived_series_definitions")
