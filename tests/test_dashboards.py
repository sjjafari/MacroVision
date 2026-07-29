from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from macrovision import dashboard_services, provider_services
from macrovision.analytics_models import (
    AnalyticsRun,
    DerivedObservation,
    DerivedSeriesDefinition,
    DerivedSeriesDefinitionVersion,
)
from macrovision.dashboard_catalog import (
    DASHBOARD_CATALOG,
    VALIDATED_DASHBOARD_CATALOG,
)
from macrovision.dashboard_schemas import DashboardDefinition
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


def _seed_cpi(
    session: Session,
    *,
    previous_value: str | None = "1234567880.12345678",
    current_value: str | None = "1234567890.12345678",
    stale_after_days: int = 9999,
    with_derived: bool = True,
    derived_frequency: str = "monthly",
    derived_observed_at: datetime | None = None,
) -> DataSeries:
    source = DataSource(
        code="FRED",
        name="Federal Reserve Economic Data",
        description="Reviewed source",
        reference_url="https://fred.stlouisfed.org/",
    )
    series = DataSeries(
        source=source,
        code="FRED.CPIAUCSL",
        name="Consumer Price Index",
        description="Headline CPI",
        category=SeriesCategory.inflation,
        geography="US",
        frequency=DataFrequency.monthly,
        unit="index",
        seasonal_adjustment=SeasonalAdjustment.adjusted,
        publication_lag_days=10,
        is_active=True,
        series_metadata={},
        stale_after_days=stale_after_days,
        lock_version=1,
    )
    previous = DataObservation(
        series=series,
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        publication_timestamp=datetime(2026, 1, 10, tzinfo=UTC),
        ingestion_timestamp=datetime(2026, 1, 10, 1, tzinfo=UTC),
        provider_metadata={},
        value=Decimal(previous_value) if previous_value is not None else None,
        status=(
            ObservationStatus.present if previous_value is not None else ObservationStatus.missing
        ),
        source_reference="fred/cpi/previous",
    )
    current = DataObservation(
        series=series,
        observed_at=datetime(2026, 2, 1, tzinfo=UTC),
        publication_timestamp=datetime(2026, 2, 10, tzinfo=UTC),
        ingestion_timestamp=datetime(2026, 2, 10, 1, tzinfo=UTC),
        provider_metadata={},
        value=Decimal("1234567889.12345678") if current_value is not None else None,
        status=(
            ObservationStatus.present if current_value is not None else ObservationStatus.missing
        ),
        source_reference="fred/cpi/original",
    )
    if current_value is not None:
        current.revisions.append(
            DataRevision(
                sequence=1,
                previous_value=current.value,
                revised_value=Decimal(current_value),
                previous_status=ObservationStatus.present,
                revised_status=ObservationStatus.present,
                publication_timestamp=datetime(2026, 2, 11, tzinfo=UTC),
                revision_timestamp=datetime(2026, 2, 12, tzinfo=UTC),
                provider_metadata={},
                reason="Reviewed revision",
                source_reference="fred/cpi/revision",
            )
        )
    session.add_all([previous, current])
    if with_derived:
        definition = DerivedSeriesDefinition(
            code="ANALYTICS.CPI.YOY",
            title="CPI year-over-year",
            description="Persisted Analytics result",
            enabled=True,
            lock_version=1,
        )
        version = DerivedSeriesDefinitionVersion(
            definition=definition,
            version=1,
            transformation_type="year_over_year_percent_change",
            parameters={"transformation_type": "year_over_year_percent_change"},
            parameters_fingerprint="a" * 64,
            output_unit="percent",
            output_frequency=derived_frequency,
            output_geography="US",
            output_currency=None,
            output_seasonal_adjustment="adjusted",
            engine_contract_version="1",
            change_note="Initial",
        )
        run = AnalyticsRun(
            definition_version=version,
            status="succeeded",
            requested_start_at=datetime(2025, 1, 1, tzinfo=UTC),
            requested_end_at=datetime(2026, 2, 1, tzinfo=UTC),
            calculation_cutoff=datetime(2026, 2, 12, tzinfo=UTC),
            engine_version="test",
            request_fingerprint="b" * 64,
            snapshot_fingerprint="c" * 64,
            reusable_fingerprint="d" * 64,
            inputs_examined=14,
            outputs_present=2,
            outputs_missing=0,
            lineage_links=2,
            started_at=datetime(2026, 2, 12, 1, tzinfo=UTC),
            completed_at=datetime(2026, 2, 12, 2, tzinfo=UTC),
        )
        run.observations.append(
            DerivedObservation(
                definition_version=version,
                observed_at=derived_observed_at or datetime(2026, 2, 1, tzinfo=UTC),
                value=Decimal("3.25000000"),
                status="present",
            )
        )
        session.add(definition)
    session.commit()
    return series


def _metric(summary: dict[str, Any], metric_key: str) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        next(
            metric
            for group in summary["groups"]
            for metric in group["metrics"]
            if metric["metric_key"] == metric_key
        ),
    )


def test_private_dashboard_catalog_is_deterministic_and_validated(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/dashboards")
    assert response.status_code == 200
    body = response.json()
    assert [item["dashboard_code"] for item in body] == ["home", "markets", "macro"]
    assert [group["group_code"] for group in body[2]["groups"]] == [
        "inflation",
        "interest_rates",
        "labor_market",
        "economic_growth",
        "liquidity_money",
        "yield_curve",
        "currencies",
        "commodities_energy",
        "financial_conditions",
        "geopolitical_risk",
    ]
    for dashboard in body:
        keys = [
            metric["metric_key"] for group in dashboard["groups"] for metric in group["metrics"]
        ]
        assert len(keys) == len(set(keys))
        assert all(
            metric["kind"] in {"raw", "derived"}
            for group in dashboard["groups"]
            for metric in group["metrics"]
        )
        assert all(
            metric["comparison"]["type"]
            in {"none", "previous_observation", "existing_derived_metric"}
            for group in dashboard["groups"]
            for metric in group["metrics"]
        )
        for group in dashboard["groups"]:
            for metric in group["metrics"]:
                if metric["kind"] == "raw":
                    assert metric["freshness_policy"]["type"] == "raw_series_stale_after_days"
                    assert metric["freshness_policy"]["age_basis"] == "observed_at"
                else:
                    assert metric["freshness_policy"] == {
                        "type": "not_configured",
                        "stale_after_days": None,
                        "age_basis": "not_applicable",
                    }
        assert not any(
            isinstance(value, int)
            for group in dashboard["groups"]
            for metric in group["metrics"]
            for key, value in metric.items()
            if key.endswith("_id")
        )
    assert client.get("/api/v1/dashboards/unknown").status_code == 404
    assert client.get("/api/v1/dashboards/unknown/summary").status_code == 404
    assert tuple(DASHBOARD_CATALOG) == VALIDATED_DASHBOARD_CATALOG


def test_duplicate_metric_keys_fail_catalog_validation() -> None:
    payload = DASHBOARD_CATALOG[0].model_dump()
    payload["groups"][1]["metrics"][0]["metric_key"] = payload["groups"][0]["metrics"][0][
        "metric_key"
    ]
    with pytest.raises(ValidationError, match="metric keys must be unique"):
        DashboardDefinition.model_validate(payload)


def test_metric_kind_and_comparison_type_reject_incompatible_policies() -> None:
    raw_payload = DASHBOARD_CATALOG[0].model_dump()
    raw_payload["groups"][0]["metrics"][0]["freshness_policy"] = {
        "type": "not_configured",
        "age_basis": "not_applicable",
    }
    with pytest.raises(ValidationError, match="raw metrics require"):
        DashboardDefinition.model_validate(raw_payload)

    derived_payload = DASHBOARD_CATALOG[0].model_dump()
    derived_payload["groups"][2]["metrics"][0]["freshness_policy"] = {
        "type": "raw_series_stale_after_days",
        "age_basis": "observed_at",
    }
    with pytest.raises(ValidationError, match="derived metrics cannot"):
        DashboardDefinition.model_validate(derived_payload)

    anchor_payload = DASHBOARD_CATALOG[0].model_dump()
    anchor_payload["groups"][0]["metrics"][0]["comparison"]["anchor_policy"] = (
        "previous_observation"
    )
    with pytest.raises(ValidationError, match="matching anchor policy"):
        DashboardDefinition.model_validate(anchor_payload)


def test_empty_database_returns_ordered_explicit_missing_states(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/dashboards/macro/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["dashboard_code"] == "macro"
    assert body["latest_knowledge_cutoff"] is None
    assert all(
        metric["state"] == "missing" for group in body["groups"] for metric in group["metrics"]
    )
    assert body["stale_metric_count"] == 0
    assert all(
        metric["freshness"]["status"] == "unavailable"
        for group in body["groups"]
        for metric in group["metrics"]
    )
    assert _metric(body, "cpi_level")["raw_identity"] == {
        "series_id": None,
        "series_code": "FRED.CPIAUCSL",
        "observation_id": None,
    }


def test_summary_preserves_exact_raw_revision_derived_identity_and_cutoffs(
    client: TestClient, db_session: Session
) -> None:
    series = _seed_cpi(db_session)

    macro = client.get("/api/v1/dashboards/macro/summary")
    assert macro.status_code == 200, macro.text
    metric = _metric(macro.json(), "cpi_level")
    assert metric["state"] == "available"
    assert metric["value"] == "1234567890.12345678"
    assert metric["comparison"]["reference_value"] == "1234567880.12345678"
    assert metric["comparison"]["absolute_change"] == "10.00000000"
    assert metric["comparison"]["percentage_change"] == "0.00000081"
    assert metric["raw_identity"]["series_id"] == series.id
    assert metric["raw_identity"]["observation_id"] is not None
    assert metric["knowledge_cutoff"] == "2026-02-12T00:00:00Z"
    assert metric["calculation_cutoff"] is None
    assert metric["source"] == {
        "source_id": series.source.id,
        "source_code": "FRED",
        "source_name": "Federal Reserve Economic Data",
        "reference_url": "https://fred.stlouisfed.org/",
        "source_reference": "fred/cpi/revision",
    }

    home = client.get("/api/v1/dashboards/home/summary").json()
    cpi = _metric(home, "headline_cpi")
    assert cpi["comparison"]["derived_value"] == "3.25000000"
    assert cpi["comparison"]["anchor_policy"] == "same_observed_at"
    assert cpi["comparison"]["current_observed_at"] == "2026-02-01T00:00:00Z"
    assert cpi["comparison"]["derived_observed_at"] == "2026-02-01T00:00:00Z"
    assert cpi["comparison"]["derived_identity"]["definition_code"] == "ANALYTICS.CPI.YOY"
    assert cpi["comparison"]["derived_identity"]["definition_version"] == 1
    assert cpi["comparison"]["derived_identity"]["run_id"] is not None
    assert cpi["comparison"]["derived_identity"]["observation_id"] is not None
    rendered = str(home)
    for private in (
        "request_fingerprint",
        "snapshot_fingerprint",
        "reusable_fingerprint",
        "parameters_fingerprint",
    ):
        assert private not in rendered

    derived = _metric(macro.json(), "cpi_yoy")
    assert derived["value"] == "3.25000000"
    assert derived["knowledge_cutoff"] == "2026-02-12T00:00:00Z"
    assert derived["calculation_cutoff"] == "2026-02-12T00:00:00Z"
    assert derived["analytics_completed_at"] == "2026-02-12T02:00:00Z"
    assert derived["freshness"] == {
        "policy": "not_configured",
        "status": "not_configured",
        "stale_after_days": None,
        "age_basis": "not_applicable",
        "evaluated_at": derived["freshness"]["evaluated_at"],
    }


def test_absolute_difference_outside_decimal_bounds_is_incomparable(
    client: TestClient, db_session: Session
) -> None:
    _seed_cpi(
        db_session,
        previous_value=str(MIN_DATA_VALUE),
        current_value=str(MAX_DATA_VALUE),
        with_derived=False,
    )

    response = client.get("/api/v1/dashboards/macro/summary")
    assert response.status_code == 200, response.text
    metric = _metric(response.json(), "cpi_level")
    comparison = metric["comparison"]
    assert metric["state"] == "available"
    assert metric["value"] == str(MAX_DATA_VALUE)
    assert comparison["reference_value"] == str(MIN_DATA_VALUE)
    assert comparison["state"] == "incomparable"
    assert comparison["state_reason"] == "absolute_change_not_representable"
    assert comparison["absolute_change"] is None
    assert comparison["percentage_change"] is None
    assert "Infinity" not in response.text
    assert "NaN" not in response.text


def test_percentage_difference_outside_decimal_bounds_is_incomparable(
    client: TestClient, db_session: Session
) -> None:
    _seed_cpi(
        db_session,
        previous_value="0.00000001",
        current_value=str(MAX_DATA_VALUE),
        with_derived=False,
    )

    response = client.get("/api/v1/dashboards/macro/summary")
    assert response.status_code == 200
    metric = _metric(response.json(), "cpi_level")
    comparison = metric["comparison"]
    assert metric["state"] == "available"
    assert comparison["state"] == "incomparable"
    assert comparison["state_reason"] == "percentage_change_not_representable"
    assert comparison["absolute_change"] == str(MAX_DATA_VALUE - Decimal("0.00000001"))
    assert comparison["percentage_change"] is None


def test_zero_reference_is_incomparable_without_non_finite_output(
    client: TestClient, db_session: Session
) -> None:
    _seed_cpi(
        db_session,
        previous_value="0.00000000",
        current_value="1.00000000",
        with_derived=False,
    )
    metric = _metric(client.get("/api/v1/dashboards/macro/summary").json(), "cpi_level")
    assert metric["state"] == "available"
    assert metric["state_reason"] is None
    assert metric["comparison"]["anchor_policy"] == "previous_observation"
    assert metric["comparison"]["state_reason"] == "percentage_reference_is_zero"
    assert metric["comparison"]["reference_value"] == "0.00000000"
    assert metric["comparison"]["percentage_change"] is None
    assert "Infinity" not in str(metric)
    assert "NaN" not in str(metric)


def test_missing_current_and_previous_values_remain_explicit(
    client: TestClient, db_session: Session
) -> None:
    _seed_cpi(db_session, current_value=None, with_derived=False)
    current = _metric(client.get("/api/v1/dashboards/macro/summary").json(), "cpi_level")
    assert current["state"] == "missing"
    assert current["state_reason"] == "current_observation_missing"
    assert current["value"] is None
    assert current["freshness"]["status"] == "unavailable"


def test_missing_previous_and_derived_frequency_mismatch_are_not_collapsed(
    client: TestClient, db_session: Session
) -> None:
    _seed_cpi(db_session, previous_value=None, derived_frequency="quarterly")
    macro = client.get("/api/v1/dashboards/macro/summary").json()
    previous = _metric(macro, "cpi_level")
    assert previous["state"] == "available"
    assert previous["comparison"]["state"] == "incomparable"
    assert previous["state_reason"] is None
    assert previous["comparison"]["state_reason"] == "previous_observation_has_no_value"
    assert previous["comparison"]["reference_observation_id"] is not None

    home = client.get("/api/v1/dashboards/home/summary").json()
    mismatch = _metric(home, "headline_cpi")
    assert mismatch["state"] == "available"
    assert mismatch["comparison"]["state"] == "frequency_mismatch"


def test_stale_state_and_missing_derived_result_do_not_execute_or_mutate(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_cpi(db_session, stale_after_days=1, with_derived=False)

    def fail_commit() -> None:
        raise AssertionError("dashboard reads must not commit")

    def fail_provider_request(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("dashboard reads must not synchronize a provider")

    monkeypatch.setattr(db_session, "commit", fail_commit)
    monkeypatch.setattr(
        provider_services,
        "synchronize_provider_series",
        fail_provider_request,
    )
    home = client.get("/api/v1/dashboards/home/summary")
    assert home.status_code == 200
    current = _metric(home.json(), "headline_cpi")
    assert current["state"] == "stale"
    assert current["state_reason"] == "series_stale"
    assert current["freshness"]["status"] == "stale"
    assert current["freshness"]["policy"] == "raw_series_stale_after_days"
    assert current["comparison"]["state"] == "missing"
    assert current["comparison"]["state_reason"] == "derived_comparison_missing"
    assert current["comparison"]["derived_identity"] == {
        "definition_id": None,
        "definition_code": "ANALYTICS.CPI.YOY",
        "definition_version": None,
        "run_id": None,
        "observation_id": None,
    }
    assert _metric(home.json(), "real_gdp_yoy")["state"] == "missing"
    stale_raw = _metric(client.get("/api/v1/dashboards/macro/summary").json(), "cpi_level")
    assert stale_raw["state"] == "stale"


@pytest.mark.parametrize(
    "derived_observed_at",
    [
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 3, 1, tzinfo=UTC),
    ],
)
def test_derived_comparison_requires_exact_observation_anchor(
    client: TestClient,
    db_session: Session,
    derived_observed_at: datetime,
) -> None:
    _seed_cpi(db_session, derived_observed_at=derived_observed_at)
    metric = _metric(client.get("/api/v1/dashboards/home/summary").json(), "headline_cpi")
    comparison = metric["comparison"]
    assert metric["state"] == "available"
    assert comparison["state"] == "incomparable"
    assert comparison["state_reason"] == "derived_comparison_anchor_mismatch"
    assert comparison["current_observed_at"] == "2026-02-01T00:00:00Z"
    assert comparison["derived_observed_at"] == derived_observed_at.isoformat().replace(
        "+00:00", "Z"
    )
    assert comparison["derived_identity"]["run_id"] is not None
    assert comparison["derived_identity"]["observation_id"] is not None


def test_derived_comparison_normalizes_equal_utc_instants(
    client: TestClient, db_session: Session
) -> None:
    offset = timezone(timedelta(hours=4))
    _seed_cpi(
        db_session,
        derived_observed_at=datetime(2026, 2, 1, 4, tzinfo=offset),
    )
    comparison = _metric(
        client.get("/api/v1/dashboards/home/summary").json(),
        "headline_cpi",
    )["comparison"]
    assert comparison["state"] == "available"
    assert comparison["anchor_policy"] == "same_observed_at"
    assert comparison["derived_observed_at"] == "2026-02-01T00:00:00Z"


def test_stale_metric_count_uses_freshness_not_comparison_state(
    client: TestClient, db_session: Session
) -> None:
    _seed_cpi(db_session, stale_after_days=1, with_derived=False)
    home = client.get("/api/v1/dashboards/home/summary").json()
    assert _metric(home, "headline_cpi")["comparison"]["state"] == "missing"
    assert home["stale_metric_count"] == 1
    assert home["stale_metric_count"] == sum(
        metric["freshness"]["status"] == "stale"
        for group in home["groups"]
        for metric in group["metrics"]
    )

    macro = client.get("/api/v1/dashboards/macro/summary").json()
    assert _metric(macro, "cpi_yoy")["freshness"]["status"] == "unavailable"
    assert macro["stale_metric_count"] == 1


def test_stale_metric_count_includes_incomparable_comparison(
    client: TestClient, db_session: Session
) -> None:
    _seed_cpi(
        db_session,
        previous_value="0.00000000",
        current_value="1.00000000",
        stale_after_days=1,
        with_derived=False,
    )
    macro = client.get("/api/v1/dashboards/macro/summary").json()
    metric = _metric(macro, "cpi_level")
    assert metric["state"] == "stale"
    assert metric["comparison"]["state"] == "incomparable"
    assert macro["stale_metric_count"] == 1


def test_dashboard_summary_uses_a_bounded_query_set(
    db_session: Session,
) -> None:
    _seed_cpi(db_session)
    engine = cast(Engine, db_session.get_bind())
    select_count = 0

    def count_selects(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        nonlocal select_count
        if statement.lstrip().upper().startswith("SELECT"):
            select_count += 1

    event.listen(engine, "before_cursor_execute", count_selects)
    try:
        summary = dashboard_services.dashboard_summary(
            db_session,
            "macro",
            now=datetime(2026, 3, 1, tzinfo=UTC),
        )
    finally:
        event.remove(engine, "before_cursor_execute", count_selects)
    assert summary.dashboard_code == "macro"
    assert select_count <= 7
