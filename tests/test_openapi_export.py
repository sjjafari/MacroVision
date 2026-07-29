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
    assert not PRIVATE_FINGERPRINT_FIELDS.intersection(first_payload)


def test_openapi_export_rejects_invalid_output_path(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="directory"):
        export_openapi(tmp_path)

    with pytest.raises(ValueError, match="does not exist"):
        export_openapi(tmp_path / "missing" / "openapi.json")
