from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from macrovision import models
from macrovision.config import Settings
from macrovision.persistence_types import UTCDateTime
from tests.test_investors import investor_payload
from tests.test_portfolios import create_portfolio, record


@pytest.mark.parametrize(
    ("supplied", "expected"),
    [
        ("2026-01-01T12:00:00+05:30", "2026-01-01T06:30:00Z"),
        ("2026-01-01T12:00:00-07:00", "2026-01-01T19:00:00Z"),
        ("2026-07-01T12:00:00-04:00", "2026-07-01T16:00:00Z"),
    ],
)
def test_public_timestamps_normalize_to_utc(
    client: TestClient, supplied: str, expected: str
) -> None:
    portfolio_id = create_portfolio(client)["id"]
    transaction = record(
        client,
        portfolio_id,
        "deposit",
        amount="10",
        occurred_at=supplied,
    )
    assert transaction["occurred_at"] == expected


def test_naive_timestamp_and_pagination_errors_use_shared_contract(
    client: TestClient,
) -> None:
    portfolio_id = create_portfolio(client)["id"]
    naive = client.post(
        f"/api/v1/portfolios/{portfolio_id}/transactions",
        json={
            "transaction_type": "deposit",
            "currency": "USD",
            "amount": "10",
            "occurred_at": "2026-01-01T12:00:00",
        },
    )
    assert naive.status_code == 422
    assert naive.json()["code"] == "validation_error"
    assert "UTC offset" in naive.json()["details"][0]["message"]

    invalid_page = client.get("/api/v1/portfolios?limit=201")
    assert invalid_page.status_code == 422
    assert invalid_page.json()["code"] == "validation_error"

    missing = client.get("/api/v1/portfolios/999")
    assert missing.status_code == 404
    assert missing.json()["code"] == "resource_not_found"
    assert client.get("/api/v1/portfolios?limit=200").status_code == 200
    operation = client.get("/openapi.json").json()["paths"]["/api/v1/portfolios"]["get"]
    assert operation["responses"]["404"]["content"]["application/json"]["schema"]
    assert operation["responses"]["409"]["content"]["application/json"]["schema"]
    assert operation["responses"]["422"]["content"]["application/json"]["schema"]


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/investors/999",
        "/api/v1/journals/999",
        "/api/v1/portfolios/999",
        "/api/v1/decisions/999",
        "/api/v1/data-sources/999",
        "/api/v1/data-series/999",
        "/api/v1/data-imports/999",
        "/api/v1/data-quality/issues/999",
    ],
)
def test_missing_resources_share_stable_404_contract(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 404
    assert response.json()["code"] == "resource_not_found"
    assert response.json()["message"]
    assert "sql" not in response.json()["message"].lower()


def test_portfolio_pages_are_stable_without_duplicates(client: TestClient) -> None:
    identifiers = [create_portfolio(client, f"Portfolio {index}")["id"] for index in range(5)]
    first = client.get("/api/v1/portfolios", params={"limit": 2, "offset": 0}).json()
    second = client.get("/api/v1/portfolios", params={"limit": 2, "offset": 2}).json()
    third = client.get("/api/v1/portfolios", params={"limit": 2, "offset": 4}).json()
    assert [item["id"] for item in first + second + third] == identifiers


def test_every_list_and_history_contract_exposes_shared_pagination(
    client: TestClient,
) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    paginated_paths = (
        "/api/v1/investors",
        "/api/v1/journals",
        "/api/v1/portfolios",
        "/api/v1/portfolios/{portfolio_id}/transactions",
        "/api/v1/portfolios/{portfolio_id}/snapshots",
        "/api/v1/decisions",
        "/api/v1/decisions/{decision_id}/history",
        "/api/v1/data-sources",
        "/api/v1/data-series",
        "/api/v1/data-series/{series_id}/observations",
        "/api/v1/data-series/{series_id}/observations/as-of",
        "/api/v1/data-series/{series_id}/observations/{observation_id}/revisions",
        "/api/v1/data-imports",
        "/api/v1/data-quality/issues",
        "/api/v1/data-quality/issues/{issue_id}/history",
    )
    for path in paginated_paths:
        query_parameters = {
            parameter["name"]
            for parameter in paths[path]["get"]["parameters"]
            if parameter["in"] == "query"
        }
        assert {"limit", "offset"} <= query_parameters, path


def test_legacy_ratios_round_half_even_and_round_trip_exactly(
    client: TestClient, db_session: Session
) -> None:
    payload = investor_payload()
    payload["liquidity_need"] = "0.1234565"
    risk_profile = cast(dict[str, Any], payload["risk_profile"])
    risk_profile["max_drawdown"] = "1"
    risk_profile["loss_capacity"] = "0"
    response = client.post("/api/v1/investors", json=payload)
    assert response.status_code == 201, response.text
    assert response.json()["liquidity_need"] == "0.123456"
    assert response.json()["risk_profile"]["max_drawdown"] == "1.000000"
    assert response.json()["risk_profile"]["loss_capacity"] == "0.000000"
    profile = db_session.scalar(select(models.InvestorProfile))
    assert profile is not None
    assert profile.liquidity_need == Decimal("0.123456")

    for invalid in ("NaN", "Infinity", "-0.000001", "1.000001"):
        invalid_payload = investor_payload()
        invalid_payload["liquidity_need"] = invalid
        rejected = client.post("/api/v1/investors", json=invalid_payload)
        assert rejected.status_code == 422
        assert rejected.json()["code"] == "validation_error"


def test_utc_datetime_sqlite_round_trip_and_legacy_interpretation(db_session: Session) -> None:
    column = UTCDateTime()
    dialect = db_session.get_bind().dialect
    supplied = datetime.fromisoformat("2026-07-01T12:00:00-04:00")
    stored = column.process_bind_param(supplied, dialect)
    assert stored == datetime(2026, 7, 1, 16, 0)
    restored = column.process_result_value(stored, dialect)
    assert restored == datetime(2026, 7, 1, 16, 0, tzinfo=UTC)


def test_utc_datetime_uses_postgresql_timestamptz() -> None:
    column = UTCDateTime()
    dialect = postgresql.dialect()  # type: ignore[no-untyped-call]
    implementation = column.load_dialect_impl(dialect)
    assert implementation.timezone is True
    supplied = datetime.fromisoformat("2026-01-01T12:00:00+05:30")
    assert column.process_bind_param(supplied, dialect) == datetime(2026, 1, 1, 6, 30, tzinfo=UTC)


def test_unknown_settings_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, unknown_critical_setting="unsafe")  # type: ignore[call-arg]
