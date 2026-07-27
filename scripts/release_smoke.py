"""Smoke-test an installed MacroVision wheel without using the source package."""

from __future__ import annotations

import argparse
import json
import os
import uuid
from pathlib import Path
from typing import Any


def _response(response: Any, expected: int, label: str) -> dict[str, Any]:
    if response.status_code != expected:
        raise RuntimeError(f"{label} returned {response.status_code}: {response.text[:500]}")
    value: dict[str, Any] = response.json()
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    arguments = parser.parse_args()
    os.environ["MACROVISION_DATABASE_URL"] = arguments.database_url

    from alembic import command
    from alembic.config import Config
    from fastapi.testclient import TestClient

    import macrovision  # type: ignore[import-untyped]
    from macrovision.main import app  # type: ignore[import-untyped]

    package_root = Path(macrovision.__file__).resolve().parent
    command.upgrade(Config(str(package_root / "alembic.ini")), "head")

    token = uuid.uuid4().hex[:10].upper()
    private_fields = (
        "request_fingerprint",
        "snapshot_fingerprint",
        "reusable_fingerprint",
        "parameters_fingerprint",
    )
    with TestClient(app) as client:
        _response(client.get("/health"), 200, "health")
        openapi = _response(client.get("/openapi.json"), 200, "openapi")
        if openapi["info"]["version"] != "0.7.0":
            raise RuntimeError("Installed OpenAPI version is not 0.7.0")
        required_paths = {
            "/api/v1/derived-series",
            "/api/v1/derived-series/{definition_id}/runs",
            "/api/v1/analytics-runs/{run_id}/observations",
            "/api/v1/analytics-runs/{run_id}/observations/{observation_id}/lineage",
            "/api/v1/derived-series/{definition_id}/observations/latest",
            "/api/v1/derived-series/{definition_id}/observations/as-of",
        }
        if not required_paths <= set(openapi["paths"]):
            raise RuntimeError("Installed wheel is missing Analytics routes")
        if any(field in str(openapi) for field in private_fields):
            raise RuntimeError("OpenAPI exposed a private fingerprint")

        source = _response(
            client.post(
                "/api/v1/data-sources",
                json={"code": f"SMOKE.{token}", "name": "Release smoke source"},
            ),
            201,
            "source",
        )
        series = _response(
            client.post(
                "/api/v1/data-series",
                json={
                    "source_id": source["id"],
                    "code": f"SMOKE.{token}.SOURCE",
                    "name": "Synthetic release series",
                    "category": "custom",
                    "geography": "TEST",
                    "frequency": "monthly",
                    "unit": "index",
                    "seasonal_adjustment": "not_applicable",
                    "publication_lag_days": 0,
                    "metadata": {},
                },
            ),
            201,
            "series",
        )
        for month, value in enumerate(
            ("100.10000001", "101.20000002", "103.40000003", "106.80000004"),
            1,
        ):
            _response(
                client.post(
                    f"/api/v1/data-series/{series['id']}/observations",
                    json={
                        "observed_at": f"2025-{month:02d}-01T00:00:00Z",
                        "publication_timestamp": f"2025-{month:02d}-02T00:00:00Z",
                        "value": value,
                        "status": "present",
                        "source_reference": f"synthetic-{month}",
                    },
                ),
                201,
                f"observation-{month}",
            )

        def create_definition(suffix: str, parameters: dict[str, object]) -> int:
            result = _response(
                client.post(
                    "/api/v1/derived-series",
                    json={
                        "code": f"SMOKE.{token}.{suffix}",
                        "title": f"Release smoke {suffix}",
                        "initial_version": {
                            "parameters": parameters,
                            "inputs": [{"alias": "value", "source_series_id": series["id"]}],
                        },
                    },
                ),
                201,
                suffix,
            )
            return int(result["id"])

        def execute(definition_id: int, label: str) -> tuple[int, str]:
            payload = {
                "requested_start_at": "2025-02-01T00:00:00Z",
                "requested_end_at": "2025-04-01T00:00:00Z",
            }
            first = _response(
                client.post(f"/api/v1/derived-series/{definition_id}/runs", json=payload),
                201,
                f"{label}-first",
            )
            replay = _response(
                client.post(f"/api/v1/derived-series/{definition_id}/runs", json=payload),
                200,
                f"{label}-replay",
            )
            if replay["run"]["id"] != first["run"]["id"]:
                raise RuntimeError("Replay did not reuse the completed run")
            return int(first["run"]["id"]), str(first["run"]["calculation_cutoff"])

        difference_id = create_definition("DIFFERENCE", {"transformation_type": "difference"})
        moving_id = create_definition(
            "MOVING",
            {"transformation_type": "moving_average", "window": 2},
        )
        run_id, cutoff = execute(difference_id, "difference")
        execute(moving_id, "moving")
        exact = _response(
            client.get(f"/api/v1/analytics-runs/{run_id}/observations"),
            200,
            "exact observations",
        )
        if not exact["items"] or not all(
            isinstance(item["value"], str) for item in exact["items"] if item["value"] is not None
        ):
            raise RuntimeError("Installed-wheel Decimal serialization is not exact")
        latest = _response(
            client.get(f"/api/v1/derived-series/{difference_id}/observations/latest"),
            200,
            "latest",
        )
        historical = _response(
            client.get(
                f"/api/v1/derived-series/{difference_id}/observations/as-of",
                params={"as_of": cutoff},
            ),
            200,
            "as-of",
        )
        lineage = _response(
            client.get(
                f"/api/v1/analytics-runs/{run_id}/observations/{exact['items'][0]['id']}/lineage"
            ),
            200,
            "lineage",
        )
        public_payload = str((exact, latest, historical, lineage))
        if any(field in public_payload for field in private_fields):
            raise RuntimeError("Installed API exposed a private fingerprint")

    print(
        json.dumps(
            {
                "version": macrovision.__version__,
                "database": arguments.database_url.split(":", 1)[0],
                "difference_outputs": len(exact["items"]),
                "lineage_links": len(lineage["items"]),
                "network_calls": 0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
