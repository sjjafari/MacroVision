import hashlib
import json
import re
from datetime import UTC, datetime, time
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from macrovision import macro_data_models as models
from macrovision import macro_data_schemas as data_schemas
from macrovision import macro_data_services
from macrovision.config import get_settings
from macrovision.integrity import IntegrityConflictError, commit_or_conflict
from macrovision.provider_contracts import (
    ExternalDataProvider,
    ObservationQuery,
    ProviderError,
    ProviderErrorCode,
    ProviderObservation,
    ProviderSeriesMetadata,
    SeriesMetadataQuery,
)
from macrovision.provider_schemas import ProviderSeriesSyncRequest, ProviderSyncResult

_PROVIDER_CODE_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


def _json_size(value: dict[str, Any], *, label: str, maximum: int) -> None:
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    except (TypeError, ValueError) as exc:
        raise ProviderError(
            ProviderErrorCode.malformed_response,
            f"Provider {label} is not valid structured metadata",
            status_code=502,
        ) from exc
    if len(encoded) > maximum:
        raise ProviderError(
            ProviderErrorCode.response_too_large,
            f"Provider {label} exceeded the safe metadata limit",
            status_code=502,
        )


def _validate_provider_payload(
    provider: ExternalDataProvider,
    requested_series_id: str,
    metadata: ProviderSeriesMetadata,
    observations: list[ProviderObservation],
) -> None:
    identity = provider.identity
    if (
        not 1 <= len(identity.code) <= 80
        or _PROVIDER_CODE_PATTERN.fullmatch(identity.code) is None
        or not 1 <= len(identity.name) <= 180
        or len(identity.reference_url) > 500
        or not identity.reference_url.lower().startswith("https://")
    ):
        raise ProviderError(
            ProviderErrorCode.malformed_response,
            "Provider identity is invalid",
            status_code=502,
        )
    if (
        metadata.provider_series_id != requested_series_id
        or not 1 <= len(metadata.provider_series_id) <= 120
        or not 1 <= len(metadata.title) <= 240
        or len(metadata.description) > 20_000
        or not 1 <= len(metadata.unit) <= 80
    ):
        raise ProviderError(
            ProviderErrorCode.malformed_response,
            "Provider series metadata exceeded supported bounds",
            status_code=502,
        )
    if len(metadata.warnings) > 20 or any(len(item) > 500 for item in metadata.warnings):
        raise ProviderError(
            ProviderErrorCode.response_too_large,
            "Provider warning summaries exceeded supported bounds",
            status_code=502,
        )
    _json_size(metadata.provider_metadata, label="series metadata", maximum=100_000)
    if len(observations) > get_settings().provider_max_observations:
        raise ProviderError(
            ProviderErrorCode.response_too_large,
            "Provider observation count exceeded the configured limit",
            status_code=502,
        )
    for observation in observations:
        if len(
            observation.source_reference
        ) > 500 or not observation.source_reference.lower().startswith("https://"):
            raise ProviderError(
                ProviderErrorCode.malformed_response,
                "Provider observation source reference is invalid",
                status_code=502,
            )
        _json_size(
            observation.provider_metadata,
            label="observation metadata",
            maximum=10_000,
        )


def _midnight(value: Any) -> datetime:
    return datetime.combine(value, time.min, tzinfo=UTC)


def _payload_document(
    metadata: ProviderSeriesMetadata,
    observations: list[ProviderObservation],
    request: ProviderSeriesSyncRequest,
    provider_code: str,
) -> dict[str, Any]:
    return {
        "provider": provider_code,
        "provider_series_id": metadata.provider_series_id,
        "title": metadata.title,
        "description": metadata.description,
        "frequency": metadata.frequency,
        "unit": metadata.unit,
        "seasonal_adjustment": metadata.seasonal_adjustment,
        "provider_metadata": metadata.provider_metadata,
        "request": request.model_dump(
            mode="json",
            exclude={"idempotency_key", "expected_lock_version"},
        ),
        "observations": [
            {
                "date": item.observed_on.isoformat(),
                "value": None if item.value is None else str(item.value),
                "missing": item.is_missing,
                "publication_timestamp": (
                    None
                    if item.publication_timestamp is None
                    else item.publication_timestamp.isoformat()
                ),
                "vintage_start": (
                    None if item.vintage_start is None else item.vintage_start.isoformat()
                ),
                "vintage_end": (None if item.vintage_end is None else item.vintage_end.isoformat()),
                "provider_metadata": item.provider_metadata,
                "source_reference": item.source_reference,
            }
            for item in observations
        ],
    }


def _fingerprint(document: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _result_from_batch(batch: models.DataImportBatch, *, replay: bool) -> ProviderSyncResult:
    metadata = batch.provider_metadata
    return ProviderSyncResult(
        provider=str(metadata["provider"]),
        provider_series_id=str(metadata["provider_series_id"]),
        source_id=batch.source_id,
        series_id=int(metadata["series_id"]),
        import_batch_id=batch.id,
        synchronization_status=batch.status.value,
        observations_received=int(metadata["observations_received"]),
        observations_accepted=batch.accepted_rows,
        observations_revised=int(metadata["observations_revised"]),
        observations_missing=int(metadata["observations_missing"]),
        observations_rejected=batch.rejected_rows,
        idempotent_replay=replay,
        warnings=list(metadata.get("warnings", [])),
        request_metadata=dict(metadata.get("request", {})),
    )


def _find_or_create_source(session: Session, provider: ExternalDataProvider) -> models.DataSource:
    identity = provider.identity
    source = session.scalar(
        select(models.DataSource).where(models.DataSource.code == identity.code)
    )
    if source is not None:
        if source.reference_url != identity.reference_url:
            raise macro_data_services.DataConflictError(
                "Provider source code is already assigned to a different reference"
            )
        return source
    source = models.DataSource(
        code=identity.code,
        name=identity.name,
        description=f"External data provided by {identity.name}",
        reference_url=identity.reference_url,
    )
    session.add(source)
    session.flush()
    return source


def _series_metadata(
    metadata: ProviderSeriesMetadata,
    request: ProviderSeriesSyncRequest,
    provider_code: str,
) -> dict[str, Any]:
    return {
        "provider": provider_code,
        "provider_series_id": metadata.provider_series_id,
        "observation_start": (
            None if metadata.observation_start is None else metadata.observation_start.isoformat()
        ),
        "observation_end": (
            None if metadata.observation_end is None else metadata.observation_end.isoformat()
        ),
        "provider_realtime_start": (
            None if metadata.realtime_start is None else metadata.realtime_start.isoformat()
        ),
        "provider_realtime_end": (
            None if metadata.realtime_end is None else metadata.realtime_end.isoformat()
        ),
        "provider_details": metadata.provider_metadata,
        "user_notes": request.metadata_notes,
    }


def _find_or_create_series(
    session: Session,
    source: models.DataSource,
    metadata: ProviderSeriesMetadata,
    request: ProviderSeriesSyncRequest,
    provider_code: str,
) -> tuple[models.DataSeries, list[str]]:
    code = request.internal_series_code or f"{provider_code}.{metadata.provider_series_id}"
    frequency = models.DataFrequency(metadata.frequency.value)
    seasonal = models.SeasonalAdjustment(metadata.seasonal_adjustment.value)
    warnings = list(metadata.warnings)
    series = session.scalar(
        select(models.DataSeries).where(
            models.DataSeries.source_id == source.id,
            models.DataSeries.provider_series_id == metadata.provider_series_id,
        )
    )
    conflicting_code = session.scalar(
        select(models.DataSeries).where(models.DataSeries.code == code)
    )
    if series is None and conflicting_code is not None:
        raise macro_data_services.DataConflictError(
            "Internal series code already belongs to another data series"
        )
    provider_metadata = _series_metadata(metadata, request, provider_code)
    if series is None:
        series = models.DataSeries(
            source=source,
            code=code,
            provider_series_id=metadata.provider_series_id,
            name=metadata.title,
            description=metadata.description,
            category=request.category or models.SeriesCategory.custom,
            geography=request.geography or "US",
            frequency=frequency,
            unit=metadata.unit,
            currency=request.currency,
            seasonal_adjustment=seasonal,
            publication_lag_days=0,
            is_active=True if request.is_active is None else request.is_active,
            series_metadata=provider_metadata,
            lock_version=1,
        )
        session.add(series)
        session.flush()
        return series, warnings
    if series.source_id != source.id:
        raise macro_data_services.DataConflictError(
            "Internal series code already belongs to another data source"
        )
    if request.metadata_notes is None:
        provider_metadata["user_notes"] = series.series_metadata.get("user_notes")
    if (
        request.expected_lock_version is not None
        and request.expected_lock_version != series.lock_version
    ):
        raise macro_data_services.DataConflictError("Data series was changed; reload and retry")
    changed = False
    provider_changes: dict[str, Any] = {
        "name": metadata.title,
        "description": metadata.description,
        "frequency": frequency,
        "unit": metadata.unit,
        "seasonal_adjustment": seasonal,
        "series_metadata": provider_metadata,
    }
    user_changes: dict[str, Any] = {
        "category": request.category,
        "geography": request.geography,
        "currency": request.currency,
        "is_active": request.is_active,
    }
    for field, value in provider_changes.items():
        if getattr(series, field) != value:
            setattr(series, field, value)
            changed = True
    for field, value in user_changes.items():
        if value is not None and getattr(series, field) != value:
            setattr(series, field, value)
            changed = True
    if changed:
        series.lock_version += 1
        session.flush()
    return series, warnings


def _normalized_observation(
    observation: ProviderObservation,
    *,
    revision: bool,
) -> data_schemas.ProviderObservationWrite:
    try:
        return data_schemas.ProviderObservationWrite(
            observed_at=_midnight(observation.observed_on),
            publication_timestamp=observation.publication_timestamp,
            provider_vintage_start=observation.vintage_start,
            provider_vintage_end=observation.vintage_end,
            provider_metadata=observation.provider_metadata,
            value=observation.value,
            status=(
                models.ObservationStatus.missing
                if observation.is_missing
                else models.ObservationStatus.present
            ),
            source_reference=observation.source_reference,
            revision_reason=("Provider published a changed vintage" if revision else None),
        )
    except ValidationError as exc:
        raise ProviderError(
            ProviderErrorCode.malformed_response,
            "Provider observation could not be represented safely",
            status_code=502,
        ) from exc


def synchronize_provider_series(
    session: Session,
    provider: ExternalDataProvider,
    provider_series_id: str,
    request: ProviderSeriesSyncRequest,
) -> ProviderSyncResult:
    metadata = provider.get_series_metadata(
        provider_series_id,
        SeriesMetadataQuery(
            realtime_start=request.realtime_start,
            realtime_end=request.realtime_end,
        ),
    )
    observations = sorted(
        provider.get_observations(
            provider_series_id,
            ObservationQuery(
                observation_start=request.observation_start,
                observation_end=request.observation_end,
                realtime_start=request.realtime_start,
                realtime_end=request.realtime_end,
            ),
        ),
        key=lambda item: item.observed_on,
    )
    if len({item.observed_on for item in observations}) != len(observations):
        raise ProviderError(
            ProviderErrorCode.malformed_response,
            "Provider returned duplicate observation dates for one synchronization",
            status_code=502,
        )
    _validate_provider_payload(provider, provider_series_id, metadata, observations)
    provider_code = provider.identity.code
    document = _payload_document(metadata, observations, request, provider_code)
    fingerprint = _fingerprint(document)
    key_material = f"{provider_code}:{provider_series_id}:{fingerprint}".encode()
    key = request.idempotency_key or f"sync:{hashlib.sha256(key_material).hexdigest()}"
    existing_batch = session.scalar(
        select(models.DataImportBatch)
        .options(selectinload(models.DataImportBatch.errors))
        .where(models.DataImportBatch.idempotency_key == key)
    )
    if existing_batch is not None:
        if (
            existing_batch.request_fingerprint != fingerprint
            or existing_batch.provider_metadata.get("provider") != provider_code.lower()
            or existing_batch.provider_metadata.get("provider_series_id") != provider_series_id
        ):
            raise macro_data_services.DataConflictError(
                "Idempotency key was already used with different provider data"
            )
        return _result_from_batch(existing_batch, replay=True)

    try:
        source = _find_or_create_source(session, provider)
        series, warnings = _find_or_create_series(session, source, metadata, request, provider_code)
        received = len(observations)
        missing = sum(item.is_missing for item in observations)
        normalized: list[tuple[data_schemas.ProviderObservationWrite, bool]] = []
        for item in observations:
            observed_at = _midnight(item.observed_on)
            existing_observation = session.scalar(
                macro_data_services._observation_statement().where(
                    models.DataObservation.series_id == series.id,
                    models.DataObservation.observed_at == observed_at,
                )
            )
            is_revision = existing_observation is not None
            if existing_observation is not None:
                (
                    current_value,
                    current_status,
                    current_publication,
                    _,
                    current_reference,
                    _,
                    current_vintage_start,
                    current_vintage_end,
                    current_provider_metadata,
                ) = macro_data_services._effective_state(existing_observation)
                next_status = (
                    models.ObservationStatus.missing
                    if item.is_missing
                    else models.ObservationStatus.present
                )
                if (
                    current_value == item.value
                    and current_status == next_status
                    and current_publication == item.publication_timestamp
                    and current_reference == item.source_reference
                    and current_vintage_start == item.vintage_start
                    and current_vintage_end == item.vintage_end
                    and current_provider_metadata == item.provider_metadata
                ):
                    continue
            normalized.append(
                (
                    _normalized_observation(item, revision=is_revision),
                    is_revision,
                )
            )

        revised = sum(is_revision for _, is_revision in normalized)
        imported_at = datetime.now(UTC)
        batch_metadata = {
            "provider": provider_code.lower(),
            "provider_series_id": provider_series_id,
            "series_id": series.id,
            "observations_received": received,
            "observations_revised": revised,
            "observations_missing": missing,
            "warnings": warnings,
            "request": request.model_dump(
                mode="json",
                exclude={"idempotency_key", "expected_lock_version"},
            ),
        }
        batch = models.DataImportBatch(
            source=source,
            idempotency_key=key,
            request_fingerprint=fingerprint,
            imported_at=imported_at,
            status=models.ImportStatus.completed,
            row_count=len(normalized),
            accepted_rows=len(normalized),
            rejected_rows=0,
            partial_mode=False,
            notes=f"Manual {provider_code} synchronization for {provider_series_id}",
            provider_metadata=batch_metadata,
        )
        session.add(batch)
        session.flush()
        for observation, _ in normalized:
            macro_data_services._write_observation(
                session,
                series,
                observation,
                import_batch_id=batch.id,
                ingestion_timestamp=imported_at,
            )
        session.flush()
        commit_or_conflict(
            session,
            "Provider synchronization conflicted with existing or concurrent data",
        )
        session.refresh(batch)
        return _result_from_batch(batch, replay=False)
    except (IntegrityConflictError, macro_data_services.DataConflictError):
        session.rollback()
        raise
    except Exception:
        session.rollback()
        raise
