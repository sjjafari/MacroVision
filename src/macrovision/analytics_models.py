from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    event,
    func,
    inspect,
    text,
)
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Mapped, mapped_column, object_session, relationship
from sqlalchemy.orm.state import InstanceState
from sqlalchemy.sql.elements import ColumnElement

from macrovision.database import Base
from macrovision.macro_data_models import DataObservation, DataRevision, DataSeries, DataValue
from macrovision.persistence_types import UTCDateTime

MAX_PARAMETERS_BYTES = 4096
_HEX_CHARS = "0123456789abcdef"


def _only_characters(column: str, characters: str) -> str:
    expression = column
    for character in characters:
        escaped = character.replace("'", "''")
        expression = f"REPLACE({expression}, '{escaped}', '')"
    return f"LENGTH({expression}) = 0"


class CanonicalCodeExpression(ColumnElement[bool]):
    inherit_cache = True
    type = Boolean()


@compiles(CanonicalCodeExpression, "sqlite")
def _compile_sqlite_code_check(
    _element: CanonicalCodeExpression, _compiler: object, **_kwargs: object
) -> str:
    return (
        "LENGTH(code) BETWEEN 1 AND 120 AND code = UPPER(code) "
        "AND code GLOB '[A-Z]*' AND code NOT GLOB '*[^A-Z0-9_.-]*'"
    )


@compiles(CanonicalCodeExpression, "postgresql")
def _compile_postgresql_code_check(
    _element: CanonicalCodeExpression, _compiler: object, **_kwargs: object
) -> str:
    return "code ~ '^[A-Z][A-Z0-9_.-]{0,119}$'"


@compiles(CanonicalCodeExpression)
def _compile_default_code_check(
    _element: CanonicalCodeExpression, _compiler: object, **_kwargs: object
) -> str:
    return (
        "LENGTH(code) BETWEEN 1 AND 120 AND code = UPPER(code) "
        "AND SUBSTR(code, 1, 1) BETWEEN 'A' AND 'Z'"
    )


FINGERPRINT_CHECKS = {
    name: f"{name} IS NULL OR (LENGTH({name}) = 64 AND {name} = LOWER({name}) "
    f"AND {_only_characters(name, _HEX_CHARS)})"
    for name in ("snapshot_fingerprint", "reusable_fingerprint")
}
FINGERPRINT_CHECKS["request_fingerprint"] = (
    "LENGTH(request_fingerprint) = 64 AND request_fingerprint = LOWER(request_fingerprint) "
    f"AND {_only_characters('request_fingerprint', _HEX_CHARS)}"
)
PARAMETERS_FINGERPRINT_CHECK = (
    "LENGTH(parameters_fingerprint) = 64 "
    "AND parameters_fingerprint = LOWER(parameters_fingerprint) "
    f"AND {_only_characters('parameters_fingerprint', _HEX_CHARS)}"
)


class DerivedSeriesDefinition(Base):
    __tablename__ = "derived_series_definitions"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(120), unique=True)
    title: Mapped[str] = mapped_column(String(240))
    description: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    lock_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now()
    )

    versions: Mapped[list["DerivedSeriesDefinitionVersion"]] = relationship(
        back_populates="definition", cascade="save-update, merge", passive_deletes="all"
    )

    __table_args__ = (
        CheckConstraint(CanonicalCodeExpression(), name="ck_derived_definition_code"),
        CheckConstraint("LENGTH(title) BETWEEN 1 AND 240", name="ck_derived_definition_title"),
        CheckConstraint(
            "description IS NULL OR LENGTH(description) <= 2000",
            name="ck_derived_definition_description",
        ),
        CheckConstraint("lock_version > 0", name="ck_derived_definition_lock_version"),
        Index("ix_derived_definition_enabled_code", "enabled", "code", "id"),
    )
    __mapper_args__ = {  # noqa: RUF012
        "version_id_col": lock_version,
        "version_id_generator": False,
    }


class DerivedSeriesDefinitionVersion(Base):
    __tablename__ = "derived_series_definition_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    definition_id: Mapped[int] = mapped_column(
        ForeignKey("derived_series_definitions.id", ondelete="RESTRICT")
    )
    version: Mapped[int]
    transformation_type: Mapped[str] = mapped_column(String(48))
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    parameters_fingerprint: Mapped[str] = mapped_column(String(64))
    output_unit: Mapped[str] = mapped_column(String(80))
    output_frequency: Mapped[str] = mapped_column(String(16))
    output_geography: Mapped[str] = mapped_column(String(120))
    output_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    output_seasonal_adjustment: Mapped[str] = mapped_column(String(24))
    engine_contract_version: Mapped[str] = mapped_column(String(32))
    change_note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())

    definition: Mapped[DerivedSeriesDefinition] = relationship(back_populates="versions")
    inputs: Mapped[list["DerivedSeriesInput"]] = relationship(
        back_populates="definition_version",
        cascade="save-update, merge",
        passive_deletes="all",
        order_by="DerivedSeriesInput.position, DerivedSeriesInput.id",
    )
    runs: Mapped[list["AnalyticsRun"]] = relationship(
        back_populates="definition_version", cascade="save-update, merge", passive_deletes="all"
    )

    __table_args__ = (
        UniqueConstraint("definition_id", "version", name="uq_derived_version_number"),
        CheckConstraint("version > 0", name="ck_derived_version_positive"),
        CheckConstraint(
            "transformation_type IN "
            "('difference','percent_change','year_over_year_percent_change','ratio',"
            "'spread','moving_average','rolling_standard_deviation','rolling_z_score',"
            "'rebase_index')",
            name="ck_derived_version_transformation",
        ),
        CheckConstraint(
            f"LENGTH(CAST(parameters AS TEXT)) <= {MAX_PARAMETERS_BYTES}",
            name="ck_derived_version_parameters_size",
        ),
        CheckConstraint(
            PARAMETERS_FINGERPRINT_CHECK,
            name="ck_derived_version_parameters_fingerprint",
        ),
        CheckConstraint(
            "LENGTH(output_unit) BETWEEN 1 AND 80",
            name="ck_derived_version_output_unit",
        ),
        CheckConstraint(
            "output_frequency IN ('daily','weekly','monthly','quarterly','annual')",
            name="ck_derived_version_frequency",
        ),
        CheckConstraint(
            "LENGTH(output_geography) BETWEEN 1 AND 120",
            name="ck_derived_version_geography",
        ),
        CheckConstraint(
            "output_currency IS NULL OR LENGTH(output_currency) = 3",
            name="ck_derived_version_currency",
        ),
        CheckConstraint(
            "output_seasonal_adjustment IN ('adjusted','not_adjusted','not_applicable','unknown')",
            name="ck_derived_version_seasonal_adjustment",
        ),
        CheckConstraint(
            "LENGTH(engine_contract_version) BETWEEN 1 AND 32",
            name="ck_derived_version_engine_contract",
        ),
        CheckConstraint(
            "change_note IS NULL OR LENGTH(change_note) <= 1000",
            name="ck_derived_version_change_note",
        ),
        Index(
            "ix_derived_version_definition_version",
            "definition_id",
            "version",
            "id",
        ),
    )


class DerivedSeriesInput(Base):
    __tablename__ = "derived_series_inputs"

    id: Mapped[int] = mapped_column(primary_key=True)
    definition_version_id: Mapped[int] = mapped_column(
        ForeignKey("derived_series_definition_versions.id", ondelete="RESTRICT")
    )
    position: Mapped[int]
    alias: Mapped[str] = mapped_column(String(40))
    source_series_id: Mapped[int] = mapped_column(
        ForeignKey("data_series.id", ondelete="RESTRICT"), index=True
    )
    source_code_snapshot: Mapped[str] = mapped_column(String(120))
    source_unit_snapshot: Mapped[str] = mapped_column(String(80))
    source_frequency_snapshot: Mapped[str] = mapped_column(String(16))
    source_geography_snapshot: Mapped[str] = mapped_column(String(120))
    source_currency_snapshot: Mapped[str | None] = mapped_column(String(3), nullable=True)
    source_seasonal_adjustment_snapshot: Mapped[str] = mapped_column(String(24))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())

    definition_version: Mapped[DerivedSeriesDefinitionVersion] = relationship(
        back_populates="inputs"
    )
    source_series: Mapped[DataSeries] = relationship()

    __table_args__ = (
        UniqueConstraint("definition_version_id", "position", name="uq_derived_input_position"),
        UniqueConstraint("definition_version_id", "alias", name="uq_derived_input_alias"),
        CheckConstraint("position >= 0", name="ck_derived_input_position"),
        CheckConstraint(
            "LENGTH(alias) BETWEEN 1 AND 40 AND alias = LOWER(alias)",
            name="ck_derived_input_alias",
        ),
        CheckConstraint(
            "LENGTH(source_code_snapshot) BETWEEN 1 AND 120",
            name="ck_derived_input_source_code",
        ),
        CheckConstraint(
            "LENGTH(source_unit_snapshot) BETWEEN 1 AND 80",
            name="ck_derived_input_source_unit",
        ),
        CheckConstraint(
            "source_frequency_snapshot IN ('daily','weekly','monthly','quarterly','annual')",
            name="ck_derived_input_frequency",
        ),
        CheckConstraint(
            "LENGTH(source_geography_snapshot) BETWEEN 1 AND 120",
            name="ck_derived_input_geography",
        ),
        CheckConstraint(
            "source_currency_snapshot IS NULL OR LENGTH(source_currency_snapshot) = 3",
            name="ck_derived_input_currency",
        ),
        CheckConstraint(
            "source_seasonal_adjustment_snapshot IN "
            "('adjusted','not_adjusted','not_applicable','unknown')",
            name="ck_derived_input_seasonal_adjustment",
        ),
    )


class AnalyticsRun(Base):
    __tablename__ = "analytics_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    definition_version_id: Mapped[int] = mapped_column(
        ForeignKey("derived_series_definition_versions.id", ondelete="RESTRICT")
    )
    status: Mapped[str] = mapped_column(String(16))
    requested_start_at: Mapped[datetime] = mapped_column(UTCDateTime())
    requested_end_at: Mapped[datetime] = mapped_column(UTCDateTime())
    calculation_cutoff: Mapped[datetime] = mapped_column(UTCDateTime())
    engine_version: Mapped[str] = mapped_column(String(32))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    snapshot_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reusable_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    inputs_examined: Mapped[int] = mapped_column(Integer, default=0)
    outputs_present: Mapped[int] = mapped_column(Integer, default=0)
    outputs_missing: Mapped[int] = mapped_column(Integer, default=0)
    lineage_links: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    retry_of_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("analytics_runs.id", ondelete="RESTRICT"), nullable=True
    )

    definition_version: Mapped[DerivedSeriesDefinitionVersion] = relationship(back_populates="runs")
    retry_of: Mapped["AnalyticsRun | None"] = relationship(remote_side="AnalyticsRun.id")
    observations: Mapped[list["DerivedObservation"]] = relationship(
        back_populates="run",
        cascade="save-update, merge",
        passive_deletes="all",
        foreign_keys="[DerivedObservation.run_id, DerivedObservation.definition_version_id]",
        overlaps="definition_version",
    )

    __table_args__ = (
        UniqueConstraint(
            "id",
            "definition_version_id",
            name="uq_analytics_run_id_definition_version",
        ),
        CheckConstraint(
            "status IN ('pending','running','succeeded','failed')",
            name="ck_analytics_run_status",
        ),
        CheckConstraint(
            "requested_start_at <= requested_end_at",
            name="ck_analytics_run_requested_range",
        ),
        CheckConstraint(
            "inputs_examined >= 0 AND outputs_present >= 0 AND outputs_missing >= 0 "
            "AND lineage_links >= 0",
            name="ck_analytics_run_counters",
        ),
        CheckConstraint(
            "LENGTH(engine_version) BETWEEN 1 AND 32", name="ck_analytics_run_engine_version"
        ),
        CheckConstraint(
            FINGERPRINT_CHECKS["request_fingerprint"],
            name="ck_analytics_run_request_fingerprint",
        ),
        CheckConstraint(
            FINGERPRINT_CHECKS["snapshot_fingerprint"],
            name="ck_analytics_run_snapshot_fingerprint",
        ),
        CheckConstraint(
            FINGERPRINT_CHECKS["reusable_fingerprint"],
            name="ck_analytics_run_reusable_fingerprint",
        ),
        CheckConstraint(
            "reusable_fingerprint IS NULL OR status = 'succeeded'",
            name="ck_analytics_run_reusable_status",
        ),
        CheckConstraint(
            "retry_of_run_id IS NULL OR retry_of_run_id != id",
            name="ck_analytics_run_retry_not_self",
        ),
        CheckConstraint(
            "error_code IS NULL OR LENGTH(error_code) BETWEEN 1 AND 64",
            name="ck_analytics_run_error_code",
        ),
        CheckConstraint(
            "error_message IS NULL OR LENGTH(error_message) <= 500",
            name="ck_analytics_run_error_message",
        ),
        CheckConstraint(
            "(status = 'pending' AND started_at IS NULL AND completed_at IS NULL "
            "AND snapshot_fingerprint IS NULL AND reusable_fingerprint IS NULL "
            "AND error_code IS NULL AND error_message IS NULL) OR "
            "(status = 'running' AND started_at IS NOT NULL AND completed_at IS NULL "
            "AND reusable_fingerprint IS NULL AND error_code IS NULL AND error_message IS NULL) OR "
            "(status = 'succeeded' AND started_at IS NOT NULL AND completed_at IS NOT NULL "
            "AND snapshot_fingerprint IS NOT NULL AND reusable_fingerprint IS NOT NULL "
            "AND error_code IS NULL AND error_message IS NULL) OR "
            "(status = 'failed' AND completed_at IS NOT NULL "
            "AND reusable_fingerprint IS NULL AND error_code IS NOT NULL "
            "AND error_message IS NOT NULL)",
            name="ck_analytics_run_lifecycle_shape",
        ),
        CheckConstraint(
            "started_at IS NULL OR completed_at IS NULL OR completed_at >= started_at",
            name="ck_analytics_run_completion_order",
        ),
        Index(
            "ix_analytics_run_definition_created",
            "definition_version_id",
            "created_at",
            "id",
        ),
        Index("ix_analytics_run_status_created", "status", "created_at", "id"),
        Index("ix_analytics_run_cutoff", "calculation_cutoff", "id"),
        Index(
            "uq_analytics_run_active_request",
            "request_fingerprint",
            unique=True,
            sqlite_where=text("status IN ('pending','running')"),
            postgresql_where=text("status IN ('pending','running')"),
        ),
        Index(
            "uq_analytics_run_reusable",
            "reusable_fingerprint",
            unique=True,
            sqlite_where=text("reusable_fingerprint IS NOT NULL"),
            postgresql_where=text("reusable_fingerprint IS NOT NULL"),
        ),
    )


class DerivedObservation(Base):
    __tablename__ = "derived_observations"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(Integer)
    definition_version_id: Mapped[int] = mapped_column(
        ForeignKey("derived_series_definition_versions.id", ondelete="RESTRICT")
    )
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime())
    value: Mapped[Decimal | None] = mapped_column(DataValue, nullable=True)
    status: Mapped[str] = mapped_column(String(16))
    missing_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())

    run: Mapped[AnalyticsRun] = relationship(
        back_populates="observations",
        foreign_keys=[run_id, definition_version_id],
        overlaps="definition_version",
    )
    definition_version: Mapped[DerivedSeriesDefinitionVersion] = relationship(
        foreign_keys=[definition_version_id],
        overlaps="observations,run",
    )
    lineage: Mapped[list["DerivedObservationLineage"]] = relationship(
        back_populates="derived_observation",
        cascade="save-update, merge",
        passive_deletes="all",
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "definition_version_id"],
            ["analytics_runs.id", "analytics_runs.definition_version_id"],
            ondelete="RESTRICT",
            name="fk_derived_observation_run_definition",
        ),
        UniqueConstraint("run_id", "observed_at", name="uq_derived_observation_run_time"),
        CheckConstraint(
            "(status = 'present' AND value IS NOT NULL AND missing_reason IS NULL) OR "
            "(status = 'missing' AND value IS NULL AND missing_reason IN "
            "('source_missing','timestamp_absent','insufficient_history',"
            "'division_by_zero','non_finite_result','numeric_overflow'))",
            name="ck_derived_observation_shape",
        ),
        Index(
            "ix_derived_observation_definition_time",
            "definition_version_id",
            "observed_at",
            "id",
        ),
        Index("ix_derived_observation_run_time", "run_id", "observed_at", "id"),
    )


class DerivedObservationLineage(Base):
    __tablename__ = "derived_observation_lineage"

    id: Mapped[int] = mapped_column(primary_key=True)
    derived_observation_id: Mapped[int] = mapped_column(
        ForeignKey("derived_observations.id", ondelete="RESTRICT")
    )
    input_position: Mapped[int]
    source_observation_id: Mapped[int] = mapped_column(
        ForeignKey("data_observations.id", ondelete="RESTRICT")
    )
    source_revision_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_version_kind: Mapped[str] = mapped_column(String(16))
    source_version_id: Mapped[int]
    lineage_position: Mapped[int]
    source_knowledge_timestamp: Mapped[datetime] = mapped_column(UTCDateTime())

    derived_observation: Mapped[DerivedObservation] = relationship(back_populates="lineage")
    source_observation: Mapped[DataObservation] = relationship(
        foreign_keys=[source_observation_id],
        overlaps="source_revision",
    )
    source_revision: Mapped[DataRevision | None] = relationship(
        foreign_keys=[source_revision_id, source_observation_id],
        overlaps="source_observation",
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["source_revision_id", "source_observation_id"],
            ["data_revisions.id", "data_revisions.observation_id"],
            ondelete="RESTRICT",
            name="fk_derived_lineage_revision_observation",
        ),
        UniqueConstraint(
            "derived_observation_id",
            "input_position",
            "source_version_kind",
            "source_version_id",
            "lineage_position",
            name="uq_derived_lineage_version_position",
        ),
        CheckConstraint("input_position >= 0", name="ck_derived_lineage_input_position"),
        CheckConstraint("lineage_position >= 0", name="ck_derived_lineage_position"),
        CheckConstraint(
            "(source_revision_id IS NULL AND source_version_kind = 'original' "
            "AND source_version_id = source_observation_id) OR "
            "(source_revision_id IS NOT NULL AND source_version_kind = 'revision' "
            "AND source_version_id = source_revision_id)",
            name="ck_derived_lineage_source_shape",
        ),
        Index("ix_derived_lineage_source_observation", "source_observation_id"),
        Index("ix_derived_lineage_source_revision", "source_revision_id"),
        Index(
            "ix_derived_lineage_point_position",
            "derived_observation_id",
            "input_position",
            "lineage_position",
            "id",
        ),
    )


ImmutableAnalyticsRecord = (
    DerivedSeriesDefinitionVersion
    | DerivedSeriesInput
    | DerivedObservation
    | DerivedObservationLineage
)


def _prevent_immutable_change(
    _mapper: object, _connection: object, target: ImmutableAnalyticsRecord
) -> None:
    session = object_session(target)
    if session is not None and not session.is_modified(target, include_collections=False):
        return
    raise ValueError("Analytics definition and observation history is immutable")


def _prevent_immutable_delete(_mapper: object, _connection: object, _target: object) -> None:
    raise ValueError("Analytics definition and observation history is immutable")


def _prevent_terminal_run_change(
    _mapper: object, _connection: object, target: AnalyticsRun
) -> None:
    state: InstanceState[AnalyticsRun] = inspect(target)
    session = object_session(target)
    if session is not None and not session.is_modified(target, include_collections=False):
        return
    history = state.attrs["status"].history
    original = history.deleted[0] if history.deleted else target.status
    if original in {"succeeded", "failed"}:
        raise ValueError("Terminal analytics runs are immutable")


def _prevent_terminal_run_delete(
    _mapper: object, _connection: object, target: AnalyticsRun
) -> None:
    if target.status in {"succeeded", "failed"}:
        raise ValueError("Terminal analytics runs are immutable")


for immutable_model in (
    DerivedSeriesDefinitionVersion,
    DerivedSeriesInput,
    DerivedObservation,
    DerivedObservationLineage,
):
    event.listen(immutable_model, "before_update", _prevent_immutable_change)
    event.listen(immutable_model, "before_delete", _prevent_immutable_delete)

event.listen(AnalyticsRun, "before_update", _prevent_terminal_run_change)
event.listen(AnalyticsRun, "before_delete", _prevent_terminal_run_delete)
