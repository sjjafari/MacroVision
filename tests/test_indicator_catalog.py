from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import event, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from macrovision.analytics_models import (
    AnalyticsRun,
    DerivedObservation,
    DerivedSeriesDefinition,
    DerivedSeriesDefinitionVersion,
)
from macrovision.indicator_catalog import (
    INDICATOR_CATALOG,
    REVIEWED_INDICATOR_CATALOG,
    IndicatorCatalogEntry,
    RelatedDerivedSpecification,
    validate_indicator_catalog,
)
from macrovision.indicator_schemas import (
    IndicatorCurationStatus,
    IndicatorRelationCode,
    IndicatorSeasonalAdjustmentStatus,
)
from macrovision.macro_data_models import (
    DataFrequency,
    DataObservation,
    DataRevision,
    DataSeries,
    DataSource,
    ObservationStatus,
    SeasonalAdjustment,
    SeriesCategory,
)
from macrovision.macro_data_schemas import MAX_DATA_VALUE, MIN_DATA_VALUE


def _entry(**overrides: Any) -> IndicatorCatalogEntry:
    payload: dict[str, Any] = {
        "series_code": "FRED.CPIAUCSL",
        "catalog_order": 1,
        "curation_status": IndicatorCurationStatus.reviewed_private,
        "display_name_fa": "شاخص قیمت",
        "description_fa": "شرح شاخص",
        "methodology_summary_fa": "خلاصه روش‌شناسی",
        "localized_unit_label": "واحد شاخص",
        "source_attribution_fa": "منبع بازبینی‌شده",
        "editorial_updated_at": datetime(2026, 7, 30, tzinfo=UTC),
        "seasonal_adjustment_status": (IndicatorSeasonalAdjustmentStatus.seasonally_adjusted),
        "source_methodology_url": "https://example.com/method",
        "related_derived": (),
    }
    payload.update(overrides)
    return IndicatorCatalogEntry(**payload)


def _seed_series(
    session: Session,
    *,
    code: str = "FRED.CPIAUCSL",
    name: str = "Consumer Price Index",
    description: str = "Canonical CPI description",
    category: SeriesCategory = SeriesCategory.inflation,
    frequency: DataFrequency = DataFrequency.monthly,
    is_active: bool = True,
    stale_after_days: int | None = 99999,
    source: DataSource | None = None,
) -> DataSeries:
    if source is None:
        source = session.scalar(select(DataSource).where(DataSource.code == "FRED"))
    source = source or DataSource(
        code="FRED",
        name="Federal Reserve Economic Data",
        description="Canonical source description",
        reference_url="https://fred.stlouisfed.org/",
    )
    series = DataSeries(
        source=source,
        code=code,
        name=name,
        description=description,
        category=category,
        geography="US",
        frequency=frequency,
        unit="index",
        seasonal_adjustment=SeasonalAdjustment.adjusted,
        publication_lag_days=5,
        is_active=is_active,
        series_metadata={"provider_internal": "must-not-leak"},
        stale_after_days=stale_after_days,
        lock_version=1,
    )
    session.add(series)
    session.commit()
    return series


def _observation(
    series: DataSeries,
    *,
    observed_at: datetime,
    ingested_at: datetime,
    value: str | None,
) -> DataObservation:
    return DataObservation(
        series=series,
        observed_at=observed_at,
        publication_timestamp=ingested_at - timedelta(hours=1),
        ingestion_timestamp=ingested_at,
        provider_metadata={},
        value=Decimal(value) if value is not None else None,
        status=ObservationStatus.present if value is not None else ObservationStatus.missing,
        source_reference="reviewed/source",
    )


def _seed_snapshot_history(session: Session, series: DataSeries) -> tuple[int, int]:
    previous = _observation(
        series,
        observed_at=datetime(2025, 12, 1, tzinfo=UTC),
        ingested_at=datetime(2025, 12, 10, tzinfo=UTC),
        value="1234567880.12345678",
    )
    current = _observation(
        series,
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        ingested_at=datetime(2026, 1, 10, tzinfo=UTC),
        value="1234567889.12345678",
    )
    current.revisions.append(
        DataRevision(
            sequence=1,
            previous_value=Decimal("1234567889.12345678"),
            revised_value=Decimal("1234567890.12345678"),
            previous_status=ObservationStatus.present,
            revised_status=ObservationStatus.present,
            publication_timestamp=datetime(2026, 1, 11, tzinfo=UTC),
            revision_timestamp=datetime(2026, 1, 12, tzinfo=UTC),
            provider_metadata={},
            reason="Reviewed correction",
            source_reference="reviewed/revision",
        )
    )
    session.add_all([previous, current])
    session.commit()
    return previous.id, current.id


def _seed_derived(
    session: Session,
    series: DataSeries,
    *,
    code: str = "ANALYTICS.CPI.YOY",
    enabled: bool = True,
    with_result: bool = True,
) -> DerivedSeriesDefinition:
    definition = DerivedSeriesDefinition(
        code=code,
        title="CPI year over year",
        description="Persisted result",
        enabled=enabled,
        lock_version=1,
    )
    version = DerivedSeriesDefinitionVersion(
        definition=definition,
        version=3,
        transformation_type="year_over_year_percent_change",
        parameters={"periods": 12},
        parameters_fingerprint="a" * 64,
        output_unit="percent",
        output_frequency="monthly",
        output_geography="US",
        output_currency=None,
        output_seasonal_adjustment="adjusted",
        engine_contract_version="1",
        change_note="Reviewed",
    )
    if with_result:
        run = AnalyticsRun(
            definition_version=version,
            status="succeeded",
            requested_start_at=datetime(2025, 1, 1, tzinfo=UTC),
            requested_end_at=datetime(2026, 1, 1, tzinfo=UTC),
            calculation_cutoff=datetime(2026, 1, 12, tzinfo=UTC),
            engine_version="test",
            request_fingerprint="b" * 64,
            snapshot_fingerprint="c" * 64,
            reusable_fingerprint="d" * 64,
            inputs_examined=13,
            outputs_present=1,
            outputs_missing=0,
            lineage_links=1,
            started_at=datetime(2026, 1, 12, 1, tzinfo=UTC),
            completed_at=datetime(2026, 1, 12, 2, tzinfo=UTC),
        )
        run.observations.append(
            DerivedObservation(
                definition_version=version,
                observed_at=datetime(2026, 1, 1, tzinfo=UTC),
                value=Decimal("3.25000000"),
                status="present",
            )
        )
    session.add(definition)
    session.commit()
    return definition


def test_catalog_configuration_is_deterministic_and_has_no_database_ids() -> None:
    assert [entry.catalog_order for entry in REVIEWED_INDICATOR_CATALOG] == [
        10,
        20,
        30,
        40,
        50,
        60,
    ]
    assert len({entry.series_code for entry in INDICATOR_CATALOG}) == len(INDICATOR_CATALOG)
    assert len({entry.catalog_order for entry in INDICATOR_CATALOG}) == len(INDICATOR_CATALOG)
    assert all("id" not in entry.model_dump() for entry in INDICATOR_CATALOG)


@pytest.mark.parametrize(
    "overrides",
    [
        {"display_name_fa": " "},
        {"description_fa": "x" * 2001},
        {"editorial_updated_at": datetime(2026, 1, 1)},
        {"source_methodology_url": "ftp://example.com/method"},
        {"source_methodology_url": "https://user:secret@example.com/method"},
        {"source_methodology_url": "https://example.com/method?api_key=secret"},
        {"source_methodology_url": "https://example.com/method#token"},
        {"seasonal_adjustment_status": "unsupported"},
    ],
)
def test_catalog_rejects_invalid_bounded_configuration(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _entry(**overrides)


def test_catalog_rejects_duplicate_series_orders_and_related_codes() -> None:
    with pytest.raises(ValueError, match="series codes"):
        validate_indicator_catalog((_entry(), _entry(catalog_order=2)))
    with pytest.raises(ValueError, match="catalog_order"):
        validate_indicator_catalog((_entry(), _entry(series_code="FRED.UNRATE")))
    relation = RelatedDerivedSpecification(
        definition_code="ANALYTICS.CPI.YOY",
        relation_code=IndicatorRelationCode.year_over_year,
        relation_label_fa="تغییر سالانه",
        description_fa="شرح",
        relation_order=1,
    )
    with pytest.raises(ValidationError, match="definition codes"):
        _entry(related_derived=(relation, relation.model_copy(update={"relation_order": 2})))


def test_catalog_list_is_reviewed_ordered_paginated_and_missing_explicit(
    client: TestClient, db_session: Session
) -> None:
    reviewed = _seed_series(db_session)
    _seed_series(
        db_session,
        code="FRED.NFCI",
        name="Active but withheld",
        category=SeriesCategory.volatility,
    )
    _seed_series(
        db_session,
        code="FRED.NOT_CONFIGURED",
        name="Active but unconfigured",
    )
    response = client.get("/api/v1/indicator-catalog?limit=2&offset=0")
    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 2
    assert body["offset"] == 0
    assert body["total"] == 6
    assert [item["catalog_order"] for item in body["items"]] == [10, 20]
    assert body["items"][0]["series_id"] == reviewed.id
    assert body["items"][1]["availability"] == "configured_series_missing"
    assert "FRED.NFCI" not in {item["series_code"] for item in body["items"]}


@pytest.mark.parametrize(
    ("query", "expected_total"),
    [
        ("search=مصرف‌کننده", 1),
        ("search=consumer", 1),
        ("search=fred.cpiau", 1),
        ("search=قیمت مصرف‌کننده شهری", 1),
        ("category=inflation", 1),
        ("geography=us", 1),
        ("frequency=monthly", 1),
        ("source_id=1", 1),
        ("operational_is_active=true", 1),
        ("operational_is_active=false", 0),
        ("category=inflation&geography=US&frequency=monthly&operational_is_active=true", 1),
    ],
)
def test_catalog_filters_are_and_combined_and_case_insensitive(
    client: TestClient,
    db_session: Session,
    query: str,
    expected_total: int,
) -> None:
    _seed_series(db_session)
    response = client.get(f"/api/v1/indicator-catalog?{query}")
    assert response.status_code == 200
    assert response.json()["total"] == expected_total


def test_catalog_filter_validation_is_controlled(client: TestClient) -> None:
    assert client.get("/api/v1/indicator-catalog?source_id=0").status_code == 422
    assert client.get(f"/api/v1/indicator-catalog?search={'x' * 121}").status_code == 422


def test_reviewed_inactive_detail_preserves_canonical_source_and_curation(
    client: TestClient, db_session: Session
) -> None:
    series = _seed_series(db_session, is_active=False)
    response = client.get(f"/api/v1/indicator-catalog/{series.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["curation"] == {
        "curation_status": "reviewed_private",
        "catalog_order": 10,
        "editorial_updated_at": "2026-07-30T00:00:00Z",
        "private_preview": True,
        "public_eligibility": False,
    }
    assert body["presentation"]["original_name"] == "Consumer Price Index"
    assert body["presentation"]["display_name_fa"] == "شاخص قیمت مصرف‌کننده"
    assert body["canonical"]["name"] == "Consumer Price Index"
    assert body["canonical"]["description"] == "Canonical CPI description"
    assert body["canonical"]["is_active"] is False
    assert body["source"]["source_code"] == "FRED"
    serialized = response.text
    assert "provider_internal" not in serialized
    assert "fingerprint" not in serialized
    assert "secret" not in serialized


def test_unconfigured_withheld_and_missing_detail_are_indistinguishable(
    client: TestClient, db_session: Session
) -> None:
    unconfigured = _seed_series(db_session, code="FRED.NOT_CONFIGURED")
    withheld = _seed_series(
        db_session,
        code="FRED.NFCI",
        category=SeriesCategory.volatility,
    )
    bodies = []
    for series_id in (unconfigured.id, withheld.id, 999999):
        response = client.get(f"/api/v1/indicator-catalog/{series_id}")
        assert response.status_code == 404
        bodies.append(response.json())
    assert bodies[0] == bodies[1] == bodies[2]


def test_current_snapshot_preserves_exact_revision_and_previous_comparison(
    client: TestClient, db_session: Session
) -> None:
    series = _seed_series(db_session)
    previous_id, current_id = _seed_snapshot_history(db_session, series)
    response = client.get(f"/api/v1/indicator-catalog/{series.id}/snapshot")
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "current"
    assert body["requested_as_of"] is None
    assert body["state"] == "available"
    assert body["value"] == "1234567890.12345678"
    assert body["observation_identity"] == {
        "series_id": series.id,
        "observation_id": current_id,
        "revision_count": 1,
    }
    assert body["knowledge_cutoff"] == "2026-01-12T00:00:00Z"
    comparison = body["comparison"]
    assert comparison["reference_observation_id"] == previous_id
    assert comparison["reference_value"] == "1234567880.12345678"
    assert comparison["absolute_change"] == "10.00000000"
    assert comparison["percentage_change"] == "0.00000081"


def test_historical_snapshot_normalizes_offset_and_hides_future_revision(
    client: TestClient, db_session: Session
) -> None:
    series = _seed_series(db_session)
    _seed_snapshot_history(db_session, series)
    response = client.get(
        f"/api/v1/indicator-catalog/{series.id}/snapshot",
        params={"as_of": "2026-01-11T04:30:00+04:30"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "historical_as_of"
    assert body["requested_as_of"] == "2026-01-11T00:00:00Z"
    assert body["value"] == "1234567889.12345678"
    assert body["knowledge_cutoff"] == "2026-01-10T00:00:00Z"
    assert body["freshness"]["evaluated_at"] == "2026-01-11T00:00:00Z"


def test_historical_snapshot_never_leaks_future_observation(
    client: TestClient, db_session: Session
) -> None:
    series = _seed_series(db_session)
    _seed_snapshot_history(db_session, series)
    response = client.get(
        f"/api/v1/indicator-catalog/{series.id}/snapshot",
        params={"as_of": "2025-12-11T00:00:00Z"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["value"] == "1234567880.12345678"
    assert body["observed_at"] == "2025-12-01T00:00:00Z"
    assert body["comparison"]["state"] == "incomparable"


def test_historical_snapshot_rejects_future_observed_at_even_if_ingested_early(
    client: TestClient, db_session: Session
) -> None:
    series = _seed_series(db_session)
    visible = _observation(
        series,
        observed_at=datetime(2025, 12, 1, tzinfo=UTC),
        ingested_at=datetime(2025, 12, 2, tzinfo=UTC),
        value="100.00000000",
    )
    impossible_future = DataObservation(
        series=series,
        observed_at=datetime(2027, 1, 1, tzinfo=UTC),
        publication_timestamp=None,
        ingestion_timestamp=datetime(2025, 12, 3, tzinfo=UTC),
        provider_metadata={},
        value=Decimal("999.00000000"),
        status=ObservationStatus.present,
    )
    db_session.add_all([visible, impossible_future])
    db_session.commit()
    body = client.get(
        f"/api/v1/indicator-catalog/{series.id}/snapshot",
        params={"as_of": "2026-01-01T00:00:00Z"},
    ).json()
    assert body["value"] == "100.00000000"
    assert body["observed_at"] == "2025-12-01T00:00:00Z"


def test_current_present_point_can_be_stale_without_losing_comparison(
    client: TestClient, db_session: Session
) -> None:
    series = _seed_series(db_session, stale_after_days=1)
    _seed_snapshot_history(db_session, series)
    body = client.get(f"/api/v1/indicator-catalog/{series.id}/snapshot").json()
    assert body["state"] == "stale"
    assert body["state_reason"] == "series_stale"
    assert body["freshness"]["status"] == "stale"
    assert body["comparison"]["reference_value"] == "1234567880.12345678"


def test_snapshot_rejects_naive_timestamp_and_handles_missing_and_stale(
    client: TestClient, db_session: Session
) -> None:
    series = _seed_series(db_session, stale_after_days=1)
    missing = _observation(
        series,
        observed_at=datetime(2020, 1, 1, tzinfo=UTC),
        ingested_at=datetime(2020, 1, 2, tzinfo=UTC),
        value=None,
    )
    db_session.add(missing)
    db_session.commit()
    assert (
        client.get(
            f"/api/v1/indicator-catalog/{series.id}/snapshot",
            params={"as_of": "2026-01-01T00:00:00"},
        ).status_code
        == 422
    )
    body = client.get(f"/api/v1/indicator-catalog/{series.id}/snapshot").json()
    assert body["state"] == "missing"
    assert body["value"] is None
    assert body["freshness"]["status"] == "unavailable"
    assert body["comparison"]["state"] == "missing"


def test_snapshot_and_related_hide_unconfigured_series(
    client: TestClient, db_session: Session
) -> None:
    series = _seed_series(db_session, code="FRED.NOT_CONFIGURED")
    for suffix in ("snapshot", "related-derived"):
        response = client.get(f"/api/v1/indicator-catalog/{series.id}/{suffix}")
        assert response.status_code == 404
        assert response.json()["message"] == "Indicator was not found"


@pytest.mark.parametrize(
    ("previous", "current", "reason"),
    [
        ("0.00000000", "1.00000000", "percentage_reference_is_zero"),
        (str(MIN_DATA_VALUE), str(MAX_DATA_VALUE), "absolute_change_not_representable"),
        ("0.00000001", str(MAX_DATA_VALUE), "percentage_change_not_representable"),
    ],
)
def test_snapshot_comparison_failures_are_safe_and_finite(
    client: TestClient,
    db_session: Session,
    previous: str,
    current: str,
    reason: str,
) -> None:
    series = _seed_series(db_session)
    db_session.add_all(
        [
            _observation(
                series,
                observed_at=datetime(2026, 1, 1, tzinfo=UTC),
                ingested_at=datetime(2026, 1, 2, tzinfo=UTC),
                value=previous,
            ),
            _observation(
                series,
                observed_at=datetime(2026, 2, 1, tzinfo=UTC),
                ingested_at=datetime(2026, 2, 2, tzinfo=UTC),
                value=current,
            ),
        ]
    )
    db_session.commit()
    response = client.get(f"/api/v1/indicator-catalog/{series.id}/snapshot")
    assert response.status_code == 200
    comparison = response.json()["comparison"]
    assert comparison["state"] == "incomparable"
    assert comparison["state_reason"] == reason
    assert "Infinity" not in response.text
    assert "NaN" not in response.text


def test_related_derived_returns_exact_persisted_identity_without_fingerprints(
    client: TestClient, db_session: Session
) -> None:
    series = _seed_series(db_session)
    definition = _seed_derived(db_session, series)
    response = client.get(f"/api/v1/indicator-catalog/{series.id}/related-derived")
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["relation_code"] == "year_over_year"
    assert item["state"] == "available"
    assert item["definition_id"] == definition.id
    assert item["definition_version"] == 3
    assert item["value"] == "3.25000000"
    assert item["run_id"] is not None
    assert item["observation_id"] is not None
    assert item["calculation_cutoff"] == "2026-01-12T00:00:00Z"
    assert item["completed_at"] == "2026-01-12T02:00:00Z"
    assert "fingerprint" not in response.text


@pytest.mark.parametrize(
    ("seed_mode", "expected_state"),
    [
        ("missing", "definition_missing"),
        ("disabled", "definition_disabled"),
        ("no_result", "persisted_result_missing"),
    ],
)
def test_related_derived_explicit_unavailable_states(
    client: TestClient,
    db_session: Session,
    seed_mode: str,
    expected_state: str,
) -> None:
    series = _seed_series(db_session)
    if seed_mode == "disabled":
        _seed_derived(db_session, series, enabled=False)
    elif seed_mode == "no_result":
        _seed_derived(db_session, series, with_result=False)
    response = client.get(f"/api/v1/indicator-catalog/{series.id}/related-derived")
    assert response.status_code == 200
    assert response.json()["items"][0]["state"] == expected_state


def test_indicator_reads_do_not_commit_and_use_bounded_queries(
    client: TestClient, db_session: Session
) -> None:
    series = _seed_series(db_session)
    _seed_snapshot_history(db_session, series)
    _seed_derived(db_session, series)
    commits = 0
    statements = 0

    def before_commit(_: Session) -> None:
        nonlocal commits
        commits += 1

    def before_cursor_execute(
        _connection: Any,
        _cursor: Any,
        _statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        nonlocal statements
        statements += 1

    event.listen(db_session, "before_commit", before_commit)
    engine = db_session.get_bind()
    assert isinstance(engine, Engine)
    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    try:
        assert client.get("/api/v1/indicator-catalog").status_code == 200
        assert client.get(f"/api/v1/indicator-catalog/{series.id}/snapshot").status_code == 200
        assert (
            client.get(f"/api/v1/indicator-catalog/{series.id}/related-derived").status_code == 200
        )
    finally:
        event.remove(db_session, "before_commit", before_commit)
        event.remove(engine, "before_cursor_execute", before_cursor_execute)
    assert commits == 0
    assert statements <= 15


def test_indicator_openapi_contract_is_private_typed_and_fingerprint_free(
    client: TestClient,
) -> None:
    document = client.get("/openapi.json").json()
    paths = document["paths"]
    assert "/api/v1/indicator-catalog" in paths
    assert "/api/v1/indicator-catalog/{series_id}" in paths
    assert "/api/v1/indicator-catalog/{series_id}/snapshot" in paths
    assert "/api/v1/indicator-catalog/{series_id}/related-derived" in paths
    serialized = str(
        {
            key: value
            for key, value in document["components"]["schemas"].items()
            if key.startswith("Indicator") or key.startswith("RelatedDerived")
        }
    )
    for fingerprint in (
        "request_fingerprint",
        "snapshot_fingerprint",
        "reusable_fingerprint",
        "parameters_fingerprint",
    ):
        assert fingerprint not in serialized
