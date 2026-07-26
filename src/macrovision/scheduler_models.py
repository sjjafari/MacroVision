from datetime import datetime, time
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Time,
    UniqueConstraint,
    event,
    func,
    inspect,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, object_session, relationship
from sqlalchemy.orm.state import InstanceState

from macrovision.database import Base
from macrovision.macro_data_models import DataImportBatch
from macrovision.persistence_types import UTCDateTime
from macrovision.scheduler_schemas import (
    MAX_INTERVAL_MINUTES,
    MAX_REQUEST_CONFIG_BYTES,
    MIN_INTERVAL_MINUTES,
    ProviderSyncRunStatus,
)


class ProviderSyncSchedule(Base):
    __tablename__ = "provider_sync_schedules"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(40))
    provider_series_id: Mapped[str] = mapped_column(String(120))
    internal_series_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    request_config: Mapped[dict[str, Any]] = mapped_column(JSON)
    request_config_fingerprint: Mapped[str] = mapped_column(String(64))
    cadence_type: Mapped[str] = mapped_column(String(24))
    interval_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    daily_time_utc: Mapped[time | None] = mapped_column(Time(timezone=False), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_scheduled_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now()
    )
    lock_version: Mapped[int] = mapped_column(Integer, default=1)

    runs: Mapped[list["ProviderSyncRun"]] = relationship(
        back_populates="schedule",
        cascade="save-update, merge",
        passive_deletes="all",
    )

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "provider_series_id",
            name="uq_provider_sync_schedule_provider_series",
        ),
        CheckConstraint(
            "LENGTH(provider) > 0 AND LENGTH(provider) <= 40 AND provider = LOWER(provider)",
            name="ck_provider_sync_schedule_provider",
        ),
        CheckConstraint(
            "LENGTH(provider_series_id) > 0 AND LENGTH(provider_series_id) <= 120",
            name="ck_provider_sync_schedule_series",
        ),
        CheckConstraint(
            "internal_series_code IS NULL OR "
            "(LENGTH(internal_series_code) > 0 AND LENGTH(internal_series_code) <= 120)",
            name="ck_provider_sync_schedule_internal_series",
        ),
        CheckConstraint(
            "LENGTH(request_config_fingerprint) = 64",
            name="ck_provider_sync_schedule_fingerprint",
        ),
        CheckConstraint(
            f"LENGTH(CAST(request_config AS TEXT)) <= {MAX_REQUEST_CONFIG_BYTES}",
            name="ck_provider_sync_schedule_config_size",
        ),
        CheckConstraint(
            "cadence_type IN ('fixed_interval', 'daily_utc')",
            name="ck_provider_sync_schedule_cadence",
        ),
        CheckConstraint(
            "(cadence_type = 'fixed_interval' "
            f"AND interval_minutes BETWEEN {MIN_INTERVAL_MINUTES} AND {MAX_INTERVAL_MINUTES} "
            "AND daily_time_utc IS NULL) OR "
            "(cadence_type = 'daily_utc' AND interval_minutes IS NULL "
            "AND daily_time_utc IS NOT NULL)",
            name="ck_provider_sync_schedule_cadence_shape",
        ),
        CheckConstraint(
            "enabled = false OR next_run_at IS NOT NULL",
            name="ck_provider_sync_schedule_enabled_next",
        ),
        CheckConstraint(
            "last_scheduled_at IS NULL OR next_run_at IS NULL OR last_scheduled_at < next_run_at",
            name="ck_provider_sync_schedule_progress",
        ),
        CheckConstraint("lock_version > 0", name="ck_provider_sync_schedule_lock_version"),
        Index(
            "ix_provider_sync_schedule_due",
            "enabled",
            "next_run_at",
            "id",
        ),
        Index(
            "ix_provider_sync_schedule_provider_series",
            "provider",
            "provider_series_id",
        ),
        Index("ix_provider_sync_schedule_updated", "updated_at", "id"),
    )
    __mapper_args__ = {  # noqa: RUF012
        "version_id_col": lock_version,
        "version_id_generator": False,
    }


class ProviderSyncRun(Base):
    __tablename__ = "provider_sync_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_id: Mapped[int] = mapped_column(
        ForeignKey("provider_sync_schedules.id", ondelete="RESTRICT")
    )
    run_key: Mapped[str] = mapped_column(String(64), unique=True)
    trigger_type: Mapped[str] = mapped_column(String(16))
    provider: Mapped[str] = mapped_column(String(40))
    provider_series_id: Mapped[str] = mapped_column(String(120))
    concurrency_key: Mapped[str] = mapped_column(String(64))
    request_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    request_snapshot_fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    scheduled_for: Mapped[datetime] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    attempt_number: Mapped[int] = mapped_column(Integer, default=0)
    maximum_attempts: Mapped[int] = mapped_column(Integer, default=2)
    next_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_acquired_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    lease_generation: Mapped[int] = mapped_column(Integer, default=0)
    request_idempotency_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sync_idempotency_key: Mapped[str] = mapped_column(String(80), unique=True)
    import_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("data_import_batches.id", ondelete="RESTRICT"), nullable=True
    )
    observations_received: Mapped[int] = mapped_column(Integer, default=0)
    observations_accepted: Mapped[int] = mapped_column(Integer, default=0)
    observations_revised: Mapped[int] = mapped_column(Integer, default=0)
    observations_missing: Mapped[int] = mapped_column(Integer, default=0)
    observations_rejected: Mapped[int] = mapped_column(Integer, default=0)
    provider_replay: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)

    schedule: Mapped[ProviderSyncSchedule] = relationship(back_populates="runs")
    import_batch: Mapped[DataImportBatch | None] = relationship()

    __table_args__ = (
        UniqueConstraint(
            "schedule_id",
            "request_idempotency_hash",
            name="uq_provider_sync_run_manual_idempotency",
        ),
        CheckConstraint("LENGTH(run_key) = 64", name="ck_provider_sync_run_key"),
        CheckConstraint(
            "trigger_type IN ('scheduled', 'manual')",
            name="ck_provider_sync_run_trigger",
        ),
        CheckConstraint(
            "(trigger_type = 'manual' AND request_idempotency_hash IS NOT NULL) OR "
            "(trigger_type = 'scheduled' AND request_idempotency_hash IS NULL)",
            name="ck_provider_sync_run_manual_hash",
        ),
        CheckConstraint(
            "LENGTH(provider) > 0 AND LENGTH(provider) <= 40 AND provider = LOWER(provider)",
            name="ck_provider_sync_run_provider",
        ),
        CheckConstraint(
            "LENGTH(provider_series_id) > 0 AND LENGTH(provider_series_id) <= 120",
            name="ck_provider_sync_run_series",
        ),
        CheckConstraint(
            "LENGTH(concurrency_key) = 64",
            name="ck_provider_sync_run_concurrency_key",
        ),
        CheckConstraint(
            "LENGTH(request_snapshot_fingerprint) = 64",
            name="ck_provider_sync_run_fingerprint",
        ),
        CheckConstraint(
            f"LENGTH(CAST(request_snapshot AS TEXT)) <= {MAX_REQUEST_CONFIG_BYTES}",
            name="ck_provider_sync_run_snapshot_size",
        ),
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed')",
            name="ck_provider_sync_run_status",
        ),
        CheckConstraint(
            "attempt_number >= 0 AND maximum_attempts > 0 "
            "AND maximum_attempts <= 10 AND attempt_number <= maximum_attempts",
            name="ck_provider_sync_run_attempts",
        ),
        CheckConstraint("lease_generation >= 0", name="ck_provider_sync_run_lease_generation"),
        CheckConstraint(
            "observations_received >= 0 AND observations_accepted >= 0 "
            "AND observations_revised >= 0 AND observations_missing >= 0 "
            "AND observations_rejected >= 0",
            name="ck_provider_sync_run_counters",
        ),
        CheckConstraint(
            "observations_accepted + observations_rejected <= observations_received "
            "AND observations_revised <= observations_accepted "
            "AND observations_missing <= observations_received",
            name="ck_provider_sync_run_counter_relationships",
        ),
        CheckConstraint(
            "started_at IS NULL OR started_at >= created_at",
            name="ck_provider_sync_run_started_order",
        ),
        CheckConstraint(
            "completed_at IS NULL OR (started_at IS NOT NULL AND completed_at >= started_at)",
            name="ck_provider_sync_run_completed_order",
        ),
        CheckConstraint(
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
        CheckConstraint(
            "(status = 'succeeded' AND import_batch_id IS NOT NULL "
            "AND error_code IS NULL AND error_message IS NULL) OR "
            "(status = 'failed' AND error_code IS NOT NULL AND error_message IS NOT NULL) OR "
            "(status IN ('pending', 'running') AND import_batch_id IS NULL "
            "AND error_code IS NULL AND error_message IS NULL)",
            name="ck_provider_sync_run_terminal_result",
        ),
        CheckConstraint(
            "request_idempotency_hash IS NULL OR LENGTH(request_idempotency_hash) = 64",
            name="ck_provider_sync_run_idempotency_hash",
        ),
        CheckConstraint(
            "LENGTH(sync_idempotency_key) BETWEEN 1 AND 80",
            name="ck_provider_sync_run_sync_key",
        ),
        Index(
            "ix_provider_sync_run_eligible",
            "status",
            "next_attempt_at",
            "scheduled_for",
            "id",
        ),
        Index("ix_provider_sync_run_schedule_created", "schedule_id", "created_at", "id"),
        Index(
            "ix_provider_sync_run_concurrency_status",
            "concurrency_key",
            "status",
            "lease_expires_at",
        ),
        Index("ix_provider_sync_run_lease_owner", "lease_owner", "status"),
        Index("ix_provider_sync_run_import_batch", "import_batch_id"),
        Index(
            "uq_provider_sync_run_running_concurrency",
            "concurrency_key",
            unique=True,
            sqlite_where=text("status = 'running'"),
            postgresql_where=text("status = 'running'"),
        ),
    )


def _prevent_completed_run_change(
    _mapper: object,
    _connection: object,
    target: ProviderSyncRun,
) -> None:
    state: InstanceState[ProviderSyncRun] = inspect(target)
    session = object_session(target)
    if session is not None and not session.is_modified(target, include_collections=False):
        return
    history = state.attrs["status"].history
    original_status = history.deleted[0] if history.deleted else target.status
    if original_status in {
        ProviderSyncRunStatus.succeeded.value,
        ProviderSyncRunStatus.failed.value,
    }:
        raise ValueError("Completed provider synchronization runs are immutable")


def _prevent_run_delete(_mapper: object, _connection: object, _target: object) -> None:
    raise ValueError("Provider synchronization run history is immutable")


event.listen(ProviderSyncRun, "before_update", _prevent_completed_run_change)
event.listen(ProviderSyncRun, "before_delete", _prevent_run_delete)
