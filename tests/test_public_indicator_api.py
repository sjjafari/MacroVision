from typing import Any, cast

from fastapi.testclient import TestClient


def _source(client: TestClient) -> int:
    response = client.post(
        "/api/v1/data-sources",
        json={"code": "PUBLIC", "name": "Public source", "description": "", "reference_url": None},
    )
    assert response.status_code == 201
    return cast(int, response.json()["id"])


def _series(client: TestClient, source_id: int, code: str) -> int:
    response = client.post(
        "/api/v1/data-series",
        json={
            "source_id": source_id,
            "code": code,
            "name": code,
            "description": "",
            "category": "inflation",
            "geography": "US",
            "frequency": "monthly",
            "unit": "index",
            "seasonal_adjustment": "seasonally_adjusted",
            "publication_lag_days": 0,
            "metadata": {},
        },
    )
    assert response.status_code == 201
    return cast(int, response.json()["id"])


def test_public_catalog_is_explicit_allowlist_not_private_curation(client: TestClient) -> None:
    response = client.get("/api/v1/public/indicator-catalog")
    assert response.status_code == 200
    payload = response.json()
    codes = {item["series_code"] for item in payload["items"]}
    assert codes == {
        "FRED.CPIAUCSL",
        "FRED.FEDFUNDS",
        "FRED.UNRATE",
        "FRED.M2SL",
        "FRED.DCOILWTICO",
        "FRED.GEPUCURRENT",
    }
    assert "FRED.NFCI" not in codes
    assert all(item["public_eligibility"] is True for item in payload["items"])
    assert all(item["private_preview"] is False for item in payload["items"])


def test_public_detail_fails_closed_for_private_or_unknown_series(client: TestClient) -> None:
    source_id = _source(client)
    withheld_id = _series(client, source_id, "FRED.NFCI")
    unknown_id = _series(client, source_id, "PRIVATE.UNRELATED")
    for series_id in (withheld_id, unknown_id, 999999):
        response = client.get(f"/api/v1/public/indicator-catalog/{series_id}")
        assert response.status_code == 404


def test_public_detail_exposes_only_explicitly_eligible_series(client: TestClient) -> None:
    source_id = _source(client)
    series_id = _series(client, source_id, "FRED.CPIAUCSL")
    response = client.get(f"/api/v1/public/indicator-catalog/{series_id}")
    assert response.status_code == 200
    payload: dict[str, Any] = response.json()
    assert payload["canonical"]["series_code"] == "FRED.CPIAUCSL"
    assert payload["curation"]["public_eligibility"] is True
    assert payload["curation"]["private_preview"] is False
