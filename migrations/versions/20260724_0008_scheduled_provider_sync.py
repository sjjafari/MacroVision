"""Add scheduled provider synchronization persistence foundation."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260724_0008"
down_revision: str | None = "20260724_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provider_sync_schedules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("provider_series_id", sa.String(length=120), nullable=False),
        sa.Column("internal_series_code", sa.String(length=120), nullable=True),
        sa.Column("request_config", sa.JSON(), nullable=False),
        sa.Column("request_config_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("cadence_type", sa.String(length=24), nullable=False),
        sa.Column("interval_minutes", sa.Integer(), nullable=True),
        sa.Column("daily_time_utc", sa.Time(timezone=False), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("last_scheduled_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.Column("lock_version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "LENGTH(provider) > 0 AND LENGTH(provider) <= 40 AND provider = LOWER(provider)",
            name="ck_provider_sync_schedule_provider",
        ),
        sa.CheckConstraint(
            "LENGTH(provider_series_id) > 0 AND LENGTH(provider_series_id) <= 120",
            name="ck_provider_sync_schedule_series",
        ),
        sa.CheckConstraint(
            "internal_series_code IS NULL OR "
            "(LENGTH(internal_series_code) > 0 AND LENGTH(internal_series_code) <= 120)",
            name="ck_provider_sync_schedule_internal_series",
        ),
        sa.CheckConstraint(
            "LENGTH(request_config_fingerprint) = 64",
            name="ck_provider_sync_schedule_fingerprint",
        ),
        sa.CheckConstraint(
            "LENGTH(CAST(request_config AS TEXT)) <= 4096",
            name="ck_provider_sync_schedule_config_size",
        ),
        sa.CheckConstraint(
            "cadence_type IN ('fixed_interval', 'daily_utc')",
            name="ck_provider_sync_schedule_cadence",
        ),
        sa.CheckConstraint(
            "(cadence_type = 'fixed_interval' "
            "AND interval_minutes BETWEEN 5 AND 525600 AND daily_time_utc IS NULL) OR "
            "(cadence_type = 'daily_utc' AND interval_minutes IS NULL "
            "AND daily_time_utc IS NOT NULL)",
            name="ck_provider_sync_schedule_cadence_shape",
        ),
        sa.CheckConstraint(
            "enabled = false OR next_run_at IS NOT NULL",
            name="ck_provider_sync_schedule_enabled_next",
        ),
        sa.CheckConstraint(
            "last_scheduled_at IS NULL OR next_run_at IS NULL OR last_scheduled_at < next_run_at",
            name="ck_provider_sync_schedule_progress",
        ),
        sa.CheckConstraint(
            "lock_version > 0",
            name="ck_provider_sync_schedule_lock_version",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "provider_series_id",
            name="uq_provider_sync_schedule_provider_series",
        ),
    )
    op.create_index(
        "ix_provider_sync_schedule_due",
        "provider_sync_schedules",
        ["enabled", "next_run_at", "id"],
    )
    op.create_index(
        "ix_provider_sync_schedule_provider_series",
        "provider_sync_schedules",
        ["provider", "provider_series_id"],
    )
    op.create_index(
        "ix_provider_sync_schedule_updated",
        "provider_sync_schedules",
        ["updated_at", "id"],
    )

    op.create_table(
        "provider_sync_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("schedule_id", sa.Integer(), nullable=False),
        sa.Column("run_key", sa.String(length=64), nullable=False),
        sa.Column("trigger_type", sa.String(length=16), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("provider_series_id", sa.String(length=120), nullable=False),
        sa.Column("concurrency_key", sa.String(length=64), nullable=False),
        sa.Column("request_snapshot", sa.JSON(), nullable=False),
        sa.Column("request_snapshot_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("maximum_attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_acquired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_generation", sa.Integer(), nullable=False),
        sa.Column("request_idempotency_hash", sa.String(length=64), nullable=True),
        sa.Column("sync_idempotency_key", sa.String(length=80), nullable=False),
        sa.Column("import_batch_id", sa.Integer(), nullable=True),
        sa.Column("observations_received", sa.Integer(), nullable=False),
        sa.Column("observations_accepted", sa.Integer(), nullable=False),
        sa.Column("observations_revised", sa.Integer(), nullable=False),
        sa.Column("observations_missing", sa.Integer(), nullable=False),
        sa.Column("observations_rejected", sa.Integer(), nullable=False),
        sa.Column("provider_replay", sa.Boolean(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.CheckConstraint("LENGTH(run_key) = 64", name="ck_provider_sync_run_key"),
        sa.CheckConstraint(
            "trigger_type IN ('scheduled', 'manual')",
            name="ck_provider_sync_run_trigger",
        ),
        sa.CheckConstraint(
            "(trigger_type = 'manual' AND request_idempotency_hash IS NOT NULL) OR "
            "(trigger_type = 'scheduled' AND request_idempotency_hash IS NULL)",
            name="ck_provider_sync_run_manual_hash",
        ),
        sa.CheckConstraint(
            "LENGTH(provider) > 0 AND LENGTH(provider) <= 40 AND provider = LOWER(provider)",
            name="ck_provider_sync_run_provider",
        ),
        sa.CheckConstraint(
            "LENGTH(provider_series_id) > 0 AND LENGTH(provider_series_id) <= 120",
            name="ck_provider_sync_run_series",
        ),
        sa.CheckConstraint(
            "LENGTH(concurrency_key) = 64",
            name="ck_provider_sync_run_concurrency_key",
        ),
        sa.CheckConstraint(
            "LENGTH(request_snapshot_fingerprint) = 64",
            name="ck_provider_sync_run_fingerprint",
        ),
        sa.CheckConstraint(
            "LENGTH(CAST(request_snapshot AS TEXT)) <= 4096",
            name="ck_provider_sync_run_snapshot_size",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed')",
            name="ck_provider_sync_run_status",
        ),
        sa.CheckConstraint(
            "attempt_number >= 0 AND maximum_attempts > 0 "
            "AND maximum_attempts <= 10 AND attempt_number <= maximum_attempts",
            name="ck_provider_sync_run_attempts",
        ),
        sa.CheckConstraint(
            "lease_generation >= 0",
            name="ck_provider_sync_run_lease_generation",
        ),
        sa.CheckConstraint(
            "observations_received >= 0 AND observations_accepted >= 0 "
            "AND observations_revised >= 0 AND observations_missing >= 0 "
            "AND observations_rejected >= 0",
            name="ck_provider_sync_run_counters",
        ),
        sa.CheckConstraint(
            "observations_accepted + observations_rejected <= observations_received "
            "AND observations_revised <= observations_accepted "
            "AND observations_missing <= observations_received",
            name="ck_provider_sync_run_counter_relationships",
        ),
        sa.CheckConstraint(
            "started_at IS NULL OR started_at >= created_at",
            name="ck_provider_sync_run_started_order",
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR (started_at IS NOT NULL AND completed_at >= started_at)",
            name="ck_provider_sync_run_completed_order",
        ),
        sa.CheckConstraint(
            "(status = 'pending' AND completed_at IS NULL "
            "AND lease_owner IS NULL AND lease_acquired_at IS NULL "
            "AND lease_expires_at IS NULL) OR "
            "(status = 'running' AND started_at IS NOT NULL AND completed_at IS NULL "
            "AND lease_owner IS NOT NULL AND lease_acquired_at IS NOT NULL "
            "AND lease_expires_at > lease_acquired_at) OR "
            "(status IN ('succeeded', 'failed') AND completed_at IS NOT NULL "
            "AND lease_owner IS NULL AND lease_acquired_at IS NULL AND lease_expires_at IS NULL)",
            name="ck_provider_sync_run_state_timestamps",
        ),
        sa.CheckConstraint(
            "(status = 'succeeded' AND import_batch_id IS NOT NULL "
            "AND error_code IS NULL AND error_message IS NULL) OR "
            "(status = 'failed' AND error_code IS NOT NULL AND error_message IS NOT NULL) OR "
            "(status IN ('pending', 'running') AND import_batch_id IS NULL "
            "AND error_code IS NULL AND error_message IS NULL)",
            name="ck_provider_sync_run_terminal_result",
        ),
        sa.CheckConstraint(
            "request_idempotency_hash IS NULL OR LENGTH(request_idempotency_hash) = 64",
            name="ck_provider_sync_run_idempotency_hash",
        ),
        sa.CheckConstraint(
            "LENGTH(sync_idempotency_key) BETWEEN 1 AND 80",
            name="ck_provider_sync_run_sync_key",
        ),
        sa.ForeignKeyConstraint(
            ["import_batch_id"],
            ["data_import_batches.id"],
            name="fk_provider_sync_run_import_batch",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["schedule_id"],
            ["provider_sync_schedules.id"],
            name="fk_provider_sync_run_schedule",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_key", name="uq_provider_sync_run_key"),
        sa.UniqueConstraint(
            "schedule_id",
            "request_idempotency_hash",
            name="uq_provider_sync_run_manual_idempotency",
        ),
        sa.UniqueConstraint(
            "sync_idempotency_key",
            name="uq_provider_sync_run_sync_key",
        ),
    )
    op.create_index(
        "ix_provider_sync_run_eligible",
        "provider_sync_runs",
        ["status", "next_attempt_at", "scheduled_for", "id"],
    )
    op.create_index(
        "ix_provider_sync_run_schedule_created",
        "provider_sync_runs",
        ["schedule_id", "created_at", "id"],
    )
    op.create_index(
        "ix_provider_sync_run_concurrency_status",
        "provider_sync_runs",
        ["concurrency_key", "status", "lease_expires_at"],
    )
    op.create_index(
        "ix_provider_sync_run_lease_owner",
        "provider_sync_runs",
        ["lease_owner", "status"],
    )
    op.create_index(
        "ix_provider_sync_run_import_batch",
        "provider_sync_runs",
        ["import_batch_id"],
    )
    op.create_index(
        "uq_provider_sync_run_running_concurrency",
        "provider_sync_runs",
        ["concurrency_key"],
        unique=True,
        sqlite_where=sa.text("status = 'running'"),
        postgresql_where=sa.text("status = 'running'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_provider_sync_run_running_concurrency",
        table_name="provider_sync_runs",
        sqlite_where=sa.text("status = 'running'"),
        postgresql_where=sa.text("status = 'running'"),
    )
    op.drop_index("ix_provider_sync_run_import_batch", table_name="provider_sync_runs")
    op.drop_index("ix_provider_sync_run_lease_owner", table_name="provider_sync_runs")
    op.drop_index("ix_provider_sync_run_concurrency_status", table_name="provider_sync_runs")
    op.drop_index("ix_provider_sync_run_schedule_created", table_name="provider_sync_runs")
    op.drop_index("ix_provider_sync_run_eligible", table_name="provider_sync_runs")
    op.drop_table("provider_sync_runs")

    op.drop_index("ix_provider_sync_schedule_updated", table_name="provider_sync_schedules")
    op.drop_index(
        "ix_provider_sync_schedule_provider_series",
        table_name="provider_sync_schedules",
    )
    op.drop_index("ix_provider_sync_schedule_due", table_name="provider_sync_schedules")
    op.drop_table("provider_sync_schedules")
