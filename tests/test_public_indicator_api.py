from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from macrovision.macro_data_models import (
    DataFrequency,
    DataSeries,
    DataSource,
    SeasonalAdjustment,
    SeriesCategory,
)


def _series(session: Session, code: str) -> int:
    source = DataSource(
        code="FRED",
        name="Federal Reserve Economic Data",
        description="Public indicator test source",
        reference_url="https://fred.stlouisfed.org/",
    )
    series = DataSeries(
        source=source,
        code=code,
        name=code,
        description="Public indicator test series",
        category=SeriesCategory.inflation,
        geography="US",
        frequency=DataFrequency.monthly,
        unit="index",
        seasonal_adjustment=SeasonalAdjustment.adjusted,
        publication_lag_days=0,
        is_active=True,
        series_metadata={},
        lock_version=1,
    )
    session.add(series)
    session.commit()
    return series.id


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


def test_public_detail_fails_closed_for_private_or_unknown_series(
    client: TestClient, db_session: Session
) -> None:
    withheld_id = _series(db_session, "FRED.NFCI")
    unknown_id = _series(db_session, "PRIVATE.UNRELATED")
    for series_id in (withheld_id, unknown_id, 999999):
        response = client.get(f"/api/v1/public/indicator-catalog/{series_id}")
        assert response.status_code == 404


def test_public_detail_exposes_only_explicitly_eligible_series(
    client: TestClient, db_session: Session
) -> None:
    series_id = _series(db_session, "FRED.CPIAUCSL")
    response = client.get(f"/api/v1/public/indicator-catalog/{series_id}")
    assert response.status_code == 200
    payload: dict[str, Any] = response.json()
    assert payload["canonical"]["series_code"] == "FRED.CPIAUCSL"
    assert payload["curation"]["public_eligibility"] is True
    assert payload["curation"]["private_preview"] is False
