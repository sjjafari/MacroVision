from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, cast

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    func,
    inspect,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, object_session, relationship
from sqlalchemy.orm.state import InstanceState

from macrovision.database import Base
from macrovision.persistence_types import ScaledDecimal, UTCDateTime

DATA_VALUE_SCALE = 8
DataValue = ScaledDecimal(DATA_VALUE_SCALE)


class SeriesCategory(StrEnum):
    inflation = "inflation"
    employment = "employment"
    growth = "growth"
    interest_rate = "interest_rate"
    currency = "currency"
    commodity = "commodity"
    equity_index = "equity_index"
    volatility = "volatility"
    liquidity = "liquidity"
    custom = "custom"


class DataFrequency(StrEnum):
    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"
    quarterly = "quarterly"
    annual = "annual"
    irregular = "irregular"


class SeasonalAdjustment(StrEnum):
    adjusted = "adjusted"
    not_adjusted = "not_adjusted"
    not_applicable = "not_applicable"
    unknown = "unknown"


class ObservationStatus(StrEnum):
    present = "present"
    missing = "missing"


class ImportStatus(StrEnum):
    processing = "processing"
    completed = "completed"
    completed_with_errors = "completed_with_errors"
    failed = "failed"


class QualityIssueType(StrEnum):
    duplicate_observation = "duplicate_observation"
    impossible_timestamp = "impossible_timestamp"
    frequency_violation = "frequency_violation"
    invalid_numeric_range = "invalid_numeric_range"
    stale_series = "stale_series"
    large_unexpected_change = "large_unexpected_change"


class QualityIssueStatus(StrEnum):
    open = "open"
    acknowledged = "acknowledged"
    resolved = "resolved"


class DataSource(Base):
    __tablename__ = "data_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(180), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    reference_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())

    series: Mapped[list["DataSeries"]] = relationship(
        back_populates="source", cascade="save-update, merge", passive_deletes="all"
    )
    import_batches: Mapped[list["DataImportBatch"]] = relationship(
        back_populates="source", cascade="save-update, merge", passive_deletes="all"
    )


class DataSeries(Base):
    __tablename__ = "data_series"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("data_sources.id", ondelete="RESTRICT"), index=True
    )
    code: Mapped[str] = mapped_column(String(120), unique=True)
    provider_series_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    name: Mapped[str] = mapped_column(String(240), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[SeriesCategory] = mapped_column(Enum(SeriesCategory), index=True)
    geography: Mapped[str] = mapped_column(String(120))
    frequency: Mapped[DataFrequency] = mapped_column(Enum(DataFrequency))
    unit: Mapped[str] = mapped_column(String(80))
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    seasonal_adjustment: Mapped[SeasonalAdjustment] = mapped_column(Enum(SeasonalAdjustment))
    publication_lag_days: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    series_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    minimum_value: Mapped[Decimal | None] = mapped_column(DataValue, nullable=True)
    maximum_value: Mapped[Decimal | None] = mapped_column(DataValue, nullable=True)
    max_change_percent: Mapped[Decimal | None] = mapped_column(DataValue, nullable=True)
    stale_after_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lock_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now()
    )

    source: Mapped[DataSource] = relationship(back_populates="series")
    observations: Mapped[list["DataObservation"]] = relationship(
        back_populates="series", cascade="save-update, merge", passive_deletes="all"
    )
    quality_issues: Mapped[list["DataQualityIssue"]] = relationship(
        back_populates="series", cascade="save-update, merge", passive_deletes="all"
    )

    __table_args__ = (
        CheckConstraint("publication_lag_days >= 0", name="ck_series_publication_lag"),
        CheckConstraint("stale_after_days IS NULL OR stale_after_days > 0", name="ck_series_stale"),
        CheckConstraint(
            "minimum_value IS NULL OR maximum_value IS NULL OR minimum_value <= maximum_value",
            name="ck_series_value_range",
        ),
        CheckConstraint(
            "max_change_percent IS NULL OR max_change_percent >= 0",
            name="ck_series_change_nonnegative",
        ),
        CheckConstraint("lock_version > 0", name="ck_series_lock_version"),
        CheckConstraint(
            "provider_series_id IS NULL OR LENGTH(provider_series_id) > 0",
            name="ck_series_provider_id_nonempty",
        ),
        UniqueConstraint(
            "source_id",
            "provider_series_id",
            name="uq_data_series_source_provider_id",
        ),
        Index("ix_data_series_active_category", "is_active", "category"),
    )
    __mapper_args__ = {  # noqa: RUF012
        "version_id_col": lock_version,
        "version_id_generator": False,
    }


class DataImportBatch(Base):
    __tablename__ = "data_import_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("data_sources.id", ondelete="RESTRICT"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True)
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    imported_at: Mapped[datetime] = mapped_column(UTCDateTime())
    failed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    failure_summary: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[ImportStatus] = mapped_column(Enum(ImportStatus))
    row_count: Mapped[int]
    accepted_rows: Mapped[int]
    rejected_rows: Mapped[int]
    partial_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")
    provider_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    source: Mapped[DataSource] = relationship(back_populates="import_batches")
    observations: Mapped[list["DataObservation"]] = relationship(
        back_populates="import_batch", cascade="save-update, merge", passive_deletes="all"
    )
    revisions: Mapped[list["DataRevision"]] = relationship(
        back_populates="import_batch", cascade="save-update, merge", passive_deletes="all"
    )
    errors: Mapped[list["DataImportError"]] = relationship(
        back_populates="import_batch",
        cascade="save-update, merge",
        passive_deletes="all",
        order_by="DataImportError.row_index, DataImportError.id",
    )

    __table_args__ = (
        CheckConstraint("row_count >= 0", name="ck_import_row_count"),
        CheckConstraint("accepted_rows >= 0", name="ck_import_accepted"),
        CheckConstraint("rejected_rows >= 0", name="ck_import_rejected"),
        CheckConstraint("accepted_rows + rejected_rows = row_count", name="ck_import_count_total"),
        CheckConstraint(
            "(status = 'failed' AND failed_at IS NOT NULL AND failure_summary IS NOT NULL) OR "
            "(status != 'failed' AND failed_at IS NULL AND failure_summary IS NULL)",
            name="ck_import_failure_details",
        ),
        Index("ix_import_source_imported", "source_id", "imported_at"),
    )


class DataImportError(Base):
    __tablename__ = "data_import_errors"

    id: Mapped[int] = mapped_column(primary_key=True)
    import_batch_id: Mapped[int] = mapped_column(
        ForeignKey("data_import_batches.id", ondelete="RESTRICT")
    )
    row_index: Mapped[int]
    error_code: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(String(500))
    source_context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())

    import_batch: Mapped[DataImportBatch] = relationship(back_populates="errors")

    __table_args__ = (
        CheckConstraint("row_index >= 0", name="ck_import_error_row_index"),
        Index("ix_import_error_batch_row", "import_batch_id", "row_index"),
    )


class DataObservation(Base):
    __tablename__ = "data_observations"

    id: Mapped[int] = mapped_column(primary_key=True)
    series_id: Mapped[int] = mapped_column(ForeignKey("data_series.id", ondelete="RESTRICT"))
    import_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("data_import_batches.id", ondelete="RESTRICT"), nullable=True
    )
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime())
    publication_timestamp: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    ingestion_timestamp: Mapped[datetime] = mapped_column(UTCDateTime())
    provider_vintage_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    provider_vintage_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    provider_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    value: Mapped[Decimal | None] = mapped_column(DataValue, nullable=True)
    status: Mapped[ObservationStatus] = mapped_column(Enum(ObservationStatus))
    source_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)

    series: Mapped[DataSeries] = relationship(back_populates="observations")
    import_batch: Mapped[DataImportBatch | None] = relationship(back_populates="observations")
    revisions: Mapped[list["DataRevision"]] = relationship(
        back_populates="observation", cascade="save-update, merge", passive_deletes="all"
    )
    quality_issues: Mapped[list["DataQualityIssue"]] = relationship(
        back_populates="observation", cascade="save-update, merge", passive_deletes="all"
    )

    __table_args__ = (
        UniqueConstraint("series_id", "observed_at", name="uq_observation_series_timestamp"),
        CheckConstraint(
            "(status = 'present' AND value IS NOT NULL) OR (status = 'missing' AND value IS NULL)",
            name="ck_observation_status_value",
        ),
        CheckConstraint(
            "publication_timestamp IS NULL OR publication_timestamp >= observed_at",
            name="ck_observation_publication_time",
        ),
        CheckConstraint(
            "publication_timestamp IS NULL OR ingestion_timestamp >= publication_timestamp",
            name="ck_observation_ingestion_time",
        ),
        CheckConstraint(
            "provider_vintage_end IS NULL OR provider_vintage_start IS NULL OR "
            "provider_vintage_end >= provider_vintage_start",
            name="ck_observation_vintage_range",
        ),
        Index("ix_observation_series_observed", "series_id", "observed_at"),
        Index("ix_observation_series_ingested", "series_id", "ingestion_timestamp"),
    )


class DataRevision(Base):
    __tablename__ = "data_revisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    observation_id: Mapped[int] = mapped_column(
        ForeignKey("data_observations.id", ondelete="RESTRICT")
    )
    import_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("data_import_batches.id", ondelete="RESTRICT"), nullable=True
    )
    sequence: Mapped[int]
    previous_value: Mapped[Decimal | None] = mapped_column(DataValue, nullable=True)
    revised_value: Mapped[Decimal | None] = mapped_column(DataValue, nullable=True)
    previous_status: Mapped[ObservationStatus] = mapped_column(Enum(ObservationStatus))
    revised_status: Mapped[ObservationStatus] = mapped_column(Enum(ObservationStatus))
    publication_timestamp: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    revision_timestamp: Mapped[datetime] = mapped_column(UTCDateTime())
    provider_vintage_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    provider_vintage_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    provider_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    reason: Mapped[str] = mapped_column(Text)
    source_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)

    observation: Mapped[DataObservation] = relationship(back_populates="revisions")
    import_batch: Mapped[DataImportBatch | None] = relationship(back_populates="revisions")

    __table_args__ = (
        UniqueConstraint("observation_id", "sequence", name="uq_revision_observation_sequence"),
        CheckConstraint("sequence > 0", name="ck_data_revision_sequence"),
        CheckConstraint(
            "(previous_status = 'present' AND previous_value IS NOT NULL) OR "
            "(previous_status = 'missing' AND previous_value IS NULL)",
            name="ck_revision_previous_status_value",
        ),
        CheckConstraint(
            "(revised_status = 'present' AND revised_value IS NOT NULL) OR "
            "(revised_status = 'missing' AND revised_value IS NULL)",
            name="ck_revision_revised_status_value",
        ),
        CheckConstraint(
            "provider_vintage_end IS NULL OR provider_vintage_start IS NULL OR "
            "provider_vintage_end >= provider_vintage_start",
            name="ck_revision_vintage_range",
        ),
        Index("ix_revision_observation_time", "observation_id", "revision_timestamp"),
    )


class DataQualityIssue(Base):
    __tablename__ = "data_quality_issues"

    id: Mapped[int] = mapped_column(primary_key=True)
    series_id: Mapped[int] = mapped_column(ForeignKey("data_series.id", ondelete="RESTRICT"))
    observation_id: Mapped[int | None] = mapped_column(
        ForeignKey("data_observations.id", ondelete="RESTRICT"), nullable=True
    )
    issue_type: Mapped[QualityIssueType] = mapped_column(Enum(QualityIssueType))
    status: Mapped[QualityIssueStatus] = mapped_column(
        Enum(QualityIssueStatus), default=QualityIssueStatus.open
    )
    message: Mapped[str] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    detected_at: Mapped[datetime] = mapped_column(UTCDateTime())
    acknowledged_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    resolution_notes: Mapped[str] = mapped_column(Text, default="")
    lock_version: Mapped[int] = mapped_column(Integer, default=1)

    series: Mapped[DataSeries] = relationship(back_populates="quality_issues")
    observation: Mapped[DataObservation | None] = relationship(back_populates="quality_issues")
    events: Mapped[list["DataQualityIssueEvent"]] = relationship(
        back_populates="issue",
        order_by="DataQualityIssueEvent.event_timestamp, DataQualityIssueEvent.id",
    )

    __table_args__ = (
        CheckConstraint("lock_version > 0", name="ck_quality_lock_version"),
        Index("ix_quality_status_detected", "status", "detected_at"),
        Index("ix_quality_series_type", "series_id", "issue_type"),
        Index(
            "uq_open_stale_issue_per_series",
            "series_id",
            unique=True,
            sqlite_where=text("issue_type = 'stale_series' AND status != 'resolved'"),
            postgresql_where=text("issue_type = 'stale_series' AND status != 'resolved'"),
        ),
    )
    __mapper_args__ = {  # noqa: RUF012
        "version_id_col": lock_version,
        "version_id_generator": False,
    }


class DataQualityIssueEvent(Base):
    __tablename__ = "data_quality_issue_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    issue_id: Mapped[int] = mapped_column(ForeignKey("data_quality_issues.id", ondelete="RESTRICT"))
    previous_status: Mapped[QualityIssueStatus] = mapped_column(Enum(QualityIssueStatus))
    new_status: Mapped[QualityIssueStatus] = mapped_column(Enum(QualityIssueStatus))
    event_timestamp: Mapped[datetime] = mapped_column(UTCDateTime())
    note: Mapped[str] = mapped_column(String(1000), default="")
    actor_reference: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_lock_version: Mapped[int] = mapped_column(Integer)

    issue: Mapped[DataQualityIssue] = relationship(back_populates="events")

    __table_args__ = (
        CheckConstraint("source_lock_version > 0", name="ck_quality_event_lock_version"),
        Index("ix_quality_event_issue_time", "issue_id", "event_timestamp", "id"),
    )


ImmutableDataRecord = (
    DataObservation | DataRevision | DataImportBatch | DataImportError | DataQualityIssueEvent
)


def _prevent_immutable_change(
    _mapper: object, _connection: object, _target: ImmutableDataRecord
) -> None:
    state = cast(InstanceState[ImmutableDataRecord], inspect(_target))
    if isinstance(_target, DataImportBatch):
        history = state.attrs["status"].history
        if history.deleted == [ImportStatus.processing] and history.added:
            return
    session = object_session(_target)
    if session is not None and not session.is_modified(_target, include_collections=False):
        return
    raise ValueError("Macro data observation, revision, and import history is immutable")


def _prevent_immutable_delete(_mapper: object, _connection: object, _target: object) -> None:
    raise ValueError("Macro data observation, revision, and import history is immutable")


for immutable_model in (
    DataObservation,
    DataRevision,
    DataImportBatch,
    DataImportError,
    DataQualityIssueEvent,
):
    event.listen(immutable_model, "before_update", _prevent_immutable_change)
    event.listen(immutable_model, "before_delete", _prevent_immutable_delete)
