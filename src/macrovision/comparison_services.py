"""Bounded, persisted-only comparison reads.

The service intentionally returns independent series. It never aligns, resamples,
fills, interpolates, or calculates ratios/spreads in the reader path.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from macrovision import analytics_management_services as analytics
from macrovision import macro_data_services as macro
from macrovision.comparison_schemas import (
    ComparisonKind,
    ComparisonPoint,
    ComparisonPointStatus,
    ComparisonRead,
    ComparisonSeries,
    ComparisonWarningCode,
)
from macrovision.contracts import utc_timestamp


class ComparisonError(RuntimeError):
    pass


@dataclass(frozen=True)
class Selection:
    kind: ComparisonKind
    resource_id: int


def parse_selections(value: str) -> tuple[Selection, ...]:
    tokens = [token.strip() for token in value.split(",") if token.strip()]
    if not 1 <= len(tokens) <= 4:
        raise ComparisonError("comparison requires between one and four selections")
    result: list[Selection] = []
    seen: set[tuple[str, int]] = set()
    for token in tokens:
        parts = token.split(":", 1)
        if len(parts) != 2 or parts[0] not in {"raw", "derived"} or not parts[1].isdigit():
            raise ComparisonError("selection must use raw:<id> or derived:<id>")
        resource_id = int(parts[1])
        if resource_id <= 0:
            raise ComparisonError("comparison resource ids must be positive")
        key = (parts[0], resource_id)
        if key in seen:
            raise ComparisonError("comparison selections must be unique")
        seen.add(key)
        result.append(Selection(ComparisonKind(parts[0]), resource_id))
    return tuple(result)


def _raw_series(
    session: Session,
    selection: Selection,
    *,
    start: datetime,
    end: datetime,
    as_of: datetime | None,
) -> ComparisonSeries:
    source = macro.get_series(session, selection.resource_id)
    observations = (
        macro.observations_as_of(
            session,
            source.id,
            as_of=as_of,
            start=start,
            end=end,
            limit=200,
            offset=0,
        )
        if as_of is not None
        else macro.list_observations(
            session,
            source.id,
            start=start,
            end=end,
            limit=200,
            offset=0,
        )
    )
    points = [
        ComparisonPoint(
            observed_at=item.observed_at,
            value=macro.observation_to_read(item, as_of=as_of).value,
            status=ComparisonPointStatus(item.status),
        )
        for item in observations
    ]
    return ComparisonSeries(
        kind=ComparisonKind.raw,
        resource_id=source.id,
        code=source.code,
        title=source.name,
        frequency=source.frequency,
        unit=source.unit,
        geography=source.geography,
        currency=source.currency,
        axis_id="",
        points=points,
    )


def _derived_series(
    session: Session,
    selection: Selection,
    *,
    start: datetime,
    end: datetime,
    as_of: datetime | None,
) -> ComparisonSeries:
    definition = analytics.get_definition_read(session, selection.resource_id)
    version = analytics.get_version(
        session, selection.resource_id, definition.current_version.version
    )
    page = (
        analytics.observations_as_of(
            session,
            selection.resource_id,
            as_of=as_of,
            start=start,
            end=end,
            definition_version=None,
            limit=200,
            offset=0,
        )
        if as_of is not None
        else analytics.ranged_observations(
            session,
            selection.resource_id,
            start=start,
            end=end,
            definition_version=None,
            run_id=None,
            limit=200,
            offset=0,
        )
    )
    points = [
        ComparisonPoint(
            observed_at=item.observed_at,
            value=item.value,
            status=ComparisonPointStatus(item.status),
            missing_reason=item.missing_reason.value if item.missing_reason is not None else None,
        )
        for item in page.items
    ]
    return ComparisonSeries(
        kind=ComparisonKind.derived,
        resource_id=definition.id,
        code=definition.code,
        title=definition.title,
        frequency=version.output_frequency,
        unit=version.output_unit,
        geography=version.output_geography,
        currency=version.output_currency,
        axis_id="",
        definition_version=page.definition_version,
        run_id=page.run_id,
        points=points,
    )


def read_comparison(
    session: Session,
    *,
    selections: tuple[Selection, ...],
    start: datetime,
    end: datetime,
    as_of: datetime | None,
) -> ComparisonRead:
    start = utc_timestamp(start)
    end = utc_timestamp(end)
    normalized_as_of = utc_timestamp(as_of) if as_of is not None else None
    if start > end:
        raise ComparisonError("start must not exceed end")
    if normalized_as_of is not None and end > normalized_as_of:
        end = normalized_as_of
    loaded = [
        (
            _raw_series(session, item, start=start, end=end, as_of=normalized_as_of)
            if item.kind is ComparisonKind.raw
            else _derived_series(session, item, start=start, end=end, as_of=normalized_as_of)
        )
        for item in selections
    ]
    axis_ids: dict[tuple[str, str | None], str] = {}
    normalized: list[ComparisonSeries] = []
    for item in loaded:
        axis_key = (item.unit, item.currency)
        axis_id = axis_ids.setdefault(axis_key, f"axis-{len(axis_ids) + 1}")
        normalized.append(item.model_copy(update={"axis_id": axis_id}))
    frequencies = {item.frequency for item in normalized}
    warnings: list[ComparisonWarningCode] = []
    if len(frequencies) > 1:
        warnings.append(ComparisonWarningCode.frequency_mismatch)
    if len(axis_ids) > 1:
        warnings.append(ComparisonWarningCode.multiple_axes)
    return ComparisonRead(
        mode="historical_as_of" if normalized_as_of is not None else "current",
        requested_as_of=normalized_as_of,
        start=start,
        end=end,
        frequency_mismatch=len(frequencies) > 1,
        axis_count=len(axis_ids),
        warnings=warnings,
        series=normalized,
    )
