from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.export_openapi import PRIVATE_FINGERPRINT_FIELDS, export_openapi


def test_openapi_export_is_deterministic_and_public(tmp_path: Path) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"

    export_openapi(first)
    export_openapi(second)

    first_payload = first.read_text(encoding="utf-8")
    assert first_payload == second.read_text(encoding="utf-8")
    assert first_payload.endswith("\n")

    document = json.loads(first_payload)
    assert document["info"]["version"] == "0.7.0"
    assert "/api/v1/data-series" in document["paths"]
    assert "/api/v1/analytics-runs/{run_id}" in document["paths"]
    assert "/api/v1/dashboards" in document["paths"]
    assert "/api/v1/dashboards/{dashboard_code}" in document["paths"]
    assert "/api/v1/dashboards/{dashboard_code}/summary" in document["paths"]

    series_parameters = {
        parameter["name"]
        for parameter in document["paths"]["/api/v1/data-series"]["get"]["parameters"]
    }
    assert {
        "search",
        "code",
        "category",
        "geography",
        "frequency",
        "source_id",
        "is_active",
        "limit",
        "offset",
    } <= series_parameters

    for path in (
        "/api/v1/data-series/{series_id}/observations",
        "/api/v1/data-series/{series_id}/observations/as-of",
    ):
        parameters = {
            parameter["name"] for parameter in document["paths"][path]["get"]["parameters"]
        }
        assert {"start", "end", "limit", "offset"} <= parameters

    metric_schema = document["components"]["schemas"]["DashboardMetricSummary"]
    assert metric_schema["properties"]["value"]["anyOf"][0]["type"] == "string"
    assert not PRIVATE_FINGERPRINT_FIELDS.intersection(first_payload)


def test_openapi_export_rejects_invalid_output_path(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="directory"):
        export_openapi(tmp_path)

    with pytest.raises(ValueError, match="does not exist"):
        export_openapi(tmp_path / "missing" / "openapi.json")
