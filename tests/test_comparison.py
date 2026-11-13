from typing import Any, cast

from fastapi.testclient import TestClient

from macrovision.comparison_services import ComparisonError, parse_selections


def _source(client: TestClient) -> dict[str, Any]:
    response = client.post(
        "/api/v1/data-sources",
        json={"code": "CMP", "name": "Comparison source", "description": "", "reference_url": None},
    )
    assert response.status_code == 201
    return cast(dict[str, Any], response.json())


def _series(client: TestClient, source_id: int, code: str, frequency: str = "monthly") -> dict[str, Any]:
    response = client.post(
        "/api/v1/data-series",
        json={
            "source_id": source_id,
            "code": code,
            "name": code,
            "description": "",
            "category": "inflation",
            "geography": "US",
            "frequency": frequency,
            "unit": "index",
            "seasonal_adjustment": "unknown",
            "publication_lag_days": 0,
            "metadata": {},
        },
    )
    assert response.status_code == 201
    return cast(dict[str, Any], response.json())


def _observation(client: TestClient, series_id: int, observed_at: str, value: str) -> None:
    response = client.post(
        f"/api/v1/data-series/{series_id}/observations",
        json={
            "observed_at": observed_at,
            "publication_timestamp": observed_at,
            "value": value,
            "status": "present",
            "source_reference": "comparison-test",
        },
    )
    assert response.status_code == 201


def test_selection_parser_is_bounded_and_unique() -> None:
    assert [(item.kind.value, item.resource_id) for item in parse_selections("raw:1,derived:2")] == [
        ("raw", 1),
        ("derived", 2),
    ]
    for invalid in ("", "raw:1,raw:1", "raw:0", "other:1", "raw:1,raw:2,raw:3,raw:4,raw:5"):
        try:
            parse_selections(invalid)
        except ComparisonError:
            pass
        else:
            raise AssertionError(f"selection should fail: {invalid}")


def test_raw_comparison_preserves_exact_values_and_independent_frequencies(client: TestClient) -> None:
    source = _source(client)
    monthly = _series(client, source["id"], "CMP.MONTHLY", "monthly")
    daily = _series(client, source["id"], "CMP.DAILY", "daily")
    _observation(client, monthly["id"], "2026-01-01T00:00:00Z", "100.12000000")
    _observation(client, daily["id"], "2026-01-02T00:00:00Z", "9.87654321")

    response = client.get(
        "/api/v1/comparison",
        params={
            "items": f"raw:{monthly['id']},raw:{daily['id']}",
            "start": "2026-01-01T00:00:00Z",
            "end": "2026-01-31T23:59:59Z",
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["mode"] == "current"
    assert payload["frequency_mismatch"] is True
    assert "frequency_mismatch" in payload["warnings"]
    assert payload["series"][0]["points"][0]["value"] == "100.12000000"
    assert payload["series"][1]["points"][0]["value"] == "9.87654321"
    assert payload["series"][0]["points"][0]["observed_at"] != payload["series"][1]["points"][0]["observed_at"]


def test_comparison_rejects_bad_range_and_missing_resource(client: TestClient) -> None:
    bad_range = client.get(
        "/api/v1/comparison",
        params={
            "items": "raw:1",
            "start": "2026-02-01T00:00:00Z",
            "end": "2026-01-01T00:00:00Z",
        },
    )
    assert bad_range.status_code == 422
    missing = client.get(
        "/api/v1/comparison",
        params={
            "items": "raw:999999",
            "start": "2026-01-01T00:00:00Z",
            "end": "2026-02-01T00:00:00Z",
        },
    )
    assert missing.status_code == 404


def test_historical_comparison_does_not_show_future_ingestion(client: TestClient) -> None:
    source = _source(client)
    series = _series(client, source["id"], "CMP.ASOF")
    _observation(client, series["id"], "2026-01-01T00:00:00Z", "1.00000000")
    response = client.get(
        "/api/v1/comparison",
        params={
            "items": f"raw:{series['id']}",
            "start": "2025-01-01T00:00:00Z",
            "end": "2025-12-31T23:59:59Z",
            "as_of": "2025-12-31T23:59:59Z",
        },
    )
    assert response.status_code == 200
    assert response.json()["mode"] == "historical_as_of"
    assert response.json()["series"][0]["points"] == []
