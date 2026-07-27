from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, event, func, select, update
from sqlalchemy.orm import Session

import macrovision.analytics_services as analytics_execution
from macrovision import analytics_api
from macrovision import analytics_management_services as analytics_management
from macrovision.analytics_models import (
    AnalyticsRun,
    DerivedSeriesDefinitionVersion,
    DerivedSeriesInput,
)
from macrovision.macro_data_models import DataSeries
from tests.test_analytics_services import FEB, JAN, MAR, _observation, _series


def _definition_payload(
    source_id: int,
    *,
    code: str = "api.difference",
    transformation_type: str = "difference",
    alias: str = "value",
) -> dict[str, Any]:
    return {
        "code": code,
        "title": "API difference",
        "description": "Safe synthetic definition",
        "enabled": True,
        "initial_version": {
            "parameters": {"transformation_type": transformation_type},
            "inputs": [{"alias": alias, "source_series_id": source_id}],
            "change_note": "Initial public contract",
        },
    }


def _execution_payload(*, as_of: str = "2026-05-01T00:00:00Z") -> dict[str, Any]:
    return {
        "requested_start_at": "2026-02-01T00:00:00Z",
        "requested_end_at": "2026-03-01T00:00:00Z",
        "as_of": as_of,
    }


def _seed_source(session: Session, code: str = "S.API") -> int:
    series = _series(session, code)
    _observation(session, series, JAN, "10")
    _observation(session, series, FEB, "20")
    _observation(session, series, MAR, "30")
    session.commit()
    return series.id


def _create_definition(
    client: TestClient, source_id: int, *, code: str = "api.difference"
) -> dict[str, Any]:
    response = client.post("/api/v1/derived-series", json=_definition_payload(source_id, code=code))
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def _assert_private_fields_absent(value: object) -> None:
    rendered = str(value)
    for private in (
        "request_fingerprint",
        "snapshot_fingerprint",
        "reusable_fingerprint",
        "parameters_fingerprint",
    ):
        assert private not in rendered


def test_definition_management_versioning_and_optimistic_lock(
    client: TestClient, db_session: Session
) -> None:
    source_id = _seed_source(db_session)
    created = _create_definition(client, source_id)
    assert created["code"] == "API.DIFFERENCE"
    assert created["lock_version"] == 1
    assert created["current_version"]["version"] == 1
    _assert_private_fields_absent(created)

    duplicate = client.post(
        "/api/v1/derived-series",
        json=_definition_payload(source_id, code="Api.Difference"),
    )
    assert duplicate.status_code == 409
    patched = client.patch(
        f"/api/v1/derived-series/{created['id']}",
        json={"expected_lock_version": 1, "title": "Updated title"},
    )
    assert patched.status_code == 200
    assert patched.json()["lock_version"] == 2
    stale = client.patch(
        f"/api/v1/derived-series/{created['id']}",
        json={"expected_lock_version": 1, "title": "Stale"},
    )
    assert stale.status_code == 409

    disabled = client.post(
        f"/api/v1/derived-series/{created['id']}/disable",
        json={"expected_lock_version": 2},
    )
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    assert disabled.json()["lock_version"] == 3
    enabled = client.post(
        f"/api/v1/derived-series/{created['id']}/enable",
        json={"expected_lock_version": 3},
    )
    assert enabled.status_code == 200
    assert enabled.json()["lock_version"] == 4

    version = client.post(
        f"/api/v1/derived-series/{created['id']}/versions",
        json={
            "expected_lock_version": 4,
            "parameters": {"transformation_type": "moving_average", "window": 2},
            "inputs": [{"alias": "value", "source_series_id": source_id}],
            "change_note": "Use a rolling mean",
        },
    )
    assert version.status_code == 201, version.text
    body = version.json()
    assert body["version"] == 2
    assert body["output_unit"] == "index"
    assert body["inputs"][0]["source_code"] == "S.API"
    _assert_private_fields_absent(body)
    versions = client.get(f"/api/v1/derived-series/{created['id']}/versions")
    assert versions.status_code == 200
    assert [item["version"] for item in versions.json()["items"]] == [2, 1]

    first = db_session.scalar(
        select(DerivedSeriesDefinitionVersion).where(
            DerivedSeriesDefinitionVersion.definition_id == created["id"],
            DerivedSeriesDefinitionVersion.version == 1,
        )
    )
    assert first is not None
    assert first.transformation_type == "difference"
    assert db_session.scalar(select(func.count(DerivedSeriesInput.id))) == 2


def test_definition_validation_pagination_and_server_owned_fields(
    client: TestClient, db_session: Session
) -> None:
    source_id = _seed_source(db_session)
    for code in ("Z.SERIES", "A.SERIES"):
        payload = _definition_payload(source_id, code=code)
        assert client.post("/api/v1/derived-series", json=payload).status_code == 201
    page = client.get("/api/v1/derived-series?limit=1&offset=0")
    assert page.status_code == 200
    assert [item["code"] for item in page.json()["items"]] == ["A.SERIES"]
    assert client.get("/api/v1/derived-series?limit=201").status_code == 422

    unsafe = _definition_payload(source_id, code="UNSAFE")
    unsafe["id"] = 99
    assert client.post("/api/v1/derived-series", json=unsafe).status_code == 422
    initial = unsafe["initial_version"]
    assert isinstance(initial, dict)
    initial["parameters_fingerprint"] = "a" * 64
    assert client.post("/api/v1/derived-series", json=unsafe).status_code == 422

    inactive = db_session.get(DataSeries, source_id)
    assert inactive is not None
    inactive.is_active = False
    db_session.commit()
    rejected = client.post(
        "/api/v1/derived-series",
        json=_definition_payload(source_id, code="INACTIVE.SOURCE"),
    )
    assert rejected.status_code == 422


def test_definition_list_uses_one_bounded_query(client: TestClient, db_session: Session) -> None:
    source_id = _seed_source(db_session, "S.API.QUERY")
    _create_definition(client, source_id, code="API.QUERY.COUNT")
    statements: list[str] = []
    bind = db_session.get_bind()

    def count_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        statements.append(statement)

    event.listen(bind, "before_cursor_execute", count_statement)
    try:
        response = client.get("/api/v1/derived-series?limit=100&offset=0")
    finally:
        event.remove(bind, "before_cursor_execute", count_statement)
    assert response.status_code == 200
    assert len(statements) == 1


def test_execution_dispositions_and_disabled_definition(
    client: TestClient, db_session: Session
) -> None:
    source_id = _seed_source(db_session)
    definition = _create_definition(client, source_id)
    path = f"/api/v1/derived-series/{definition['id']}/runs"
    first = client.post(path, json=_execution_payload())
    assert first.status_code == 201, first.text
    assert first.json()["disposition"] == "created"
    run_id = first.json()["run"]["id"]
    _assert_private_fields_absent(first.json())

    replay = client.post(path, json=_execution_payload())
    assert replay.status_code == 200
    assert replay.json()["disposition"] == "completed_existing"
    assert replay.json()["run"]["id"] == run_id

    completed = db_session.get(AnalyticsRun, run_id)
    assert completed is not None
    active = AnalyticsRun(
        definition_version_id=completed.definition_version_id,
        status="pending",
        requested_start_at=completed.requested_start_at,
        requested_end_at=completed.requested_end_at,
        calculation_cutoff=completed.calculation_cutoff,
        engine_version=completed.engine_version,
        request_fingerprint=completed.request_fingerprint,
        inputs_examined=0,
        outputs_present=0,
        outputs_missing=0,
        lineage_links=0,
    )
    db_session.add(active)
    db_session.commit()
    active_response = client.post(path, json=_execution_payload())
    assert active_response.status_code == 202
    assert active_response.json()["disposition"] == "active_existing"
    assert active_response.json()["run"]["id"] == active.id

    db_session.delete(active)
    db_session.commit()
    disabled = client.post(
        f"/api/v1/derived-series/{definition['id']}/disable",
        json={"expected_lock_version": 1},
    )
    assert disabled.status_code == 200
    rejected = client.post(
        path,
        json=_execution_payload(as_of="2026-05-02T00:00:00Z"),
    )
    assert rejected.status_code == 422
    _assert_private_fields_absent(rejected.json())


def test_execution_route_enters_executor_with_fresh_session(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_id = _seed_source(db_session, "S.API.FRESH")
    definition = _create_definition(client, source_id, code="API.FRESH.SESSION")
    original = analytics_execution.execute_analytics_run_outcome

    def assert_fresh(
        session: Session,
        request: analytics_execution.AnalyticsExecutionRequest,
    ) -> analytics_execution.AnalyticsExecutionOutcome:
        assert not session.in_transaction()
        return original(session, request)

    monkeypatch.setattr(analytics_execution, "execute_analytics_run_outcome", assert_fresh)
    response = client.post(
        f"/api/v1/derived-series/{definition['id']}/runs",
        json=_execution_payload(),
    )
    assert response.status_code == 201


def test_run_observation_latest_range_as_of_and_lineage_reads(
    client: TestClient, db_session: Session
) -> None:
    source_id = _seed_source(db_session)
    definition = _create_definition(client, source_id)
    execution = client.post(
        f"/api/v1/derived-series/{definition['id']}/runs",
        json=_execution_payload(),
    )
    assert execution.status_code == 201
    run_id = execution.json()["run"]["id"]

    run = client.get(f"/api/v1/analytics-runs/{run_id}")
    assert run.status_code == 200
    assert run.json()["definition_id"] == definition["id"]
    _assert_private_fields_absent(run.json())
    runs = client.get(f"/api/v1/analytics-runs?definition_id={definition['id']}&status=succeeded")
    assert runs.status_code == 200
    assert [item["id"] for item in runs.json()["items"]] == [run_id]

    observations = client.get(f"/api/v1/analytics-runs/{run_id}/observations")
    assert observations.status_code == 200
    assert [item["value"] for item in observations.json()["items"]] == [
        "10.00000000",
        "10.00000000",
    ]
    observation_id = observations.json()["items"][0]["id"]
    lineage = client.get(f"/api/v1/analytics-runs/{run_id}/observations/{observation_id}/lineage")
    assert lineage.status_code == 200
    assert [item["lineage_position"] for item in lineage.json()["items"]] == [0, 1]
    assert {item["input_alias"] for item in lineage.json()["items"]} == {"value"}
    _assert_private_fields_absent(lineage.json())

    latest = client.get(f"/api/v1/derived-series/{definition['id']}/observations/latest")
    assert latest.status_code == 200
    assert latest.json()["run_id"] == run_id
    assert latest.json()["observation"]["observed_at"].startswith("2026-03-01")
    ranged = client.get(
        f"/api/v1/derived-series/{definition['id']}/observations",
        params={
            "run_id": run_id,
            "start": "2026-03-01T00:00:00Z",
            "end": "2026-03-01T00:00:00Z",
        },
    )
    assert ranged.status_code == 200
    assert len(ranged.json()["items"]) == 1
    historical = client.get(
        f"/api/v1/derived-series/{definition['id']}/observations/as-of",
        params={"as_of": "2027-05-01T00:00:00Z"},
    )
    assert historical.status_code == 200
    assert historical.json()["run_id"] == run_id

    other_source = _seed_source(db_session, "S.API.OTHER")
    other_definition = _create_definition(client, other_source, code="API.OTHER.DIFFERENCE")
    other_run = client.post(
        f"/api/v1/derived-series/{other_definition['id']}/runs",
        json=_execution_payload(),
    ).json()["run"]["id"]
    cross_run = client.get(
        f"/api/v1/analytics-runs/{other_run}/observations/{observation_id}/lineage"
    )
    assert cross_run.status_code == 404


def test_zero_output_and_failed_runs_are_safe(client: TestClient, db_session: Session) -> None:
    source_id = _seed_source(db_session)
    definition = _create_definition(client, source_id)
    empty = client.post(
        f"/api/v1/derived-series/{definition['id']}/runs",
        json={
            "requested_start_at": "2025-01-01T00:00:00Z",
            "requested_end_at": "2025-01-01T00:00:00Z",
            "as_of": "2026-05-01T00:00:00Z",
        },
    )
    assert empty.status_code == 201
    assert empty.json()["run"]["outputs_present"] == 0
    page = client.get(f"/api/v1/analytics-runs/{empty.json()['run']['id']}/observations")
    assert page.status_code == 200
    assert page.json()["items"] == []

    future = client.post(
        f"/api/v1/derived-series/{definition['id']}/runs",
        json=_execution_payload(as_of="2100-01-01T00:00:00Z"),
    )
    assert future.status_code == 422
    assert "Traceback" not in future.text
    _assert_private_fields_absent(future.json())


def test_failed_execution_retry_is_audited_without_private_details(
    client: TestClient, db_session: Session
) -> None:
    series = _series(db_session, "S.API.REBASE.FAIL")
    _observation(db_session, series, JAN, "0")
    _observation(db_session, series, FEB, "20")
    db_session.commit()
    response = client.post(
        "/api/v1/derived-series",
        json={
            "code": "API.REBASE.FAIL",
            "title": "Failing rebase",
            "initial_version": {
                "parameters": {
                    "transformation_type": "rebase_index",
                    "base_timestamp": "2026-01-01T00:00:00Z",
                    "base_value": "100.00000000",
                },
                "inputs": [{"alias": "value", "source_series_id": series.id}],
            },
        },
    )
    assert response.status_code == 201
    definition_id = response.json()["id"]
    request: dict[str, Any] = {
        "requested_start_at": "2026-02-01T00:00:00Z",
        "requested_end_at": "2026-02-01T00:00:00Z",
        "as_of": "2026-05-01T00:00:00Z",
    }
    failed = client.post(f"/api/v1/derived-series/{definition_id}/runs", json=request)
    assert failed.status_code == 500
    assert failed.json()["message"] == "Analytics execution failed"
    _assert_private_fields_absent(failed.json())
    audit = db_session.scalar(select(AnalyticsRun).where(AnalyticsRun.status == "failed"))
    assert audit is not None
    assert audit.error_message is not None
    assert "0.00000000" not in audit.error_message
    audit_id = audit.id
    db_session.rollback()

    retry = dict(request)
    retry["retry_of_run_id"] = audit_id
    retried = client.post(f"/api/v1/derived-series/{definition_id}/runs", json=retry)
    assert retried.status_code == 500
    failed_count = db_session.scalar(
        select(func.count(AnalyticsRun.id)).where(AnalyticsRun.status == "failed")
    )
    assert failed_count == 2
    db_session.rollback()
    incompatible = dict(request)
    incompatible["requested_end_at"] = "2026-03-01T00:00:00Z"
    incompatible["retry_of_run_id"] = audit_id
    rejected = client.post(f"/api/v1/derived-series/{definition_id}/runs", json=incompatible)
    assert rejected.status_code in {409, 422}
    db_session.execute(
        update(AnalyticsRun)
        .where(AnalyticsRun.retry_of_run_id.is_not(None))
        .values(retry_of_run_id=None)
    )
    db_session.execute(delete(AnalyticsRun))
    db_session.commit()


def test_latest_version_no_stitching_and_explicit_old_run(
    client: TestClient, db_session: Session
) -> None:
    source_id = _seed_source(db_session, "S.API.VERSION")
    definition = _create_definition(client, source_id, code="API.VERSION.SELECTION")
    definition_id = definition["id"]
    old_run = client.post(
        f"/api/v1/derived-series/{definition_id}/runs",
        json=_execution_payload(),
    )
    assert old_run.status_code == 201
    old_run_id = old_run.json()["run"]["id"]
    version = client.post(
        f"/api/v1/derived-series/{definition_id}/versions",
        json={
            "expected_lock_version": 1,
            "parameters": {
                "transformation_type": "moving_average",
                "window": 2,
            },
            "inputs": [{"alias": "value", "source_series_id": source_id}],
        },
    )
    assert version.status_code == 201
    assert (
        client.get(f"/api/v1/derived-series/{definition_id}/observations/latest").status_code == 404
    )
    exact_old = client.get(
        f"/api/v1/derived-series/{definition_id}/observations",
        params={"run_id": old_run_id},
    )
    assert exact_old.status_code == 200
    assert exact_old.json()["definition_version"] == 1
    incompatible = client.get(
        f"/api/v1/derived-series/{definition_id}/observations",
        params={"run_id": old_run_id, "definition_version": 2},
    )
    assert incompatible.status_code == 404
    historical_old = client.get(
        f"/api/v1/derived-series/{definition_id}/observations/as-of",
        params={
            "as_of": "2027-01-01T00:00:00Z",
            "definition_version": 1,
        },
    )
    assert historical_old.status_code == 200
    assert historical_old.json()["run_id"] == old_run_id

    current = client.post(
        f"/api/v1/derived-series/{definition_id}/runs",
        json={**_execution_payload(), "definition_version": 2},
    )
    assert current.status_code == 201
    latest = client.get(f"/api/v1/derived-series/{definition_id}/observations/latest")
    assert latest.status_code == 200
    assert latest.json()["run_id"] == current.json()["run"]["id"]
    assert latest.json()["definition_version"] == 2

    partial_definition = _create_definition(client, source_id, code="API.NO.STITCH")
    first = client.post(
        f"/api/v1/derived-series/{partial_definition['id']}/runs",
        json={
            "requested_start_at": "2026-02-01T00:00:00Z",
            "requested_end_at": "2026-02-01T00:00:00Z",
            "as_of": "2026-05-01T00:00:00Z",
        },
    )
    second = client.post(
        f"/api/v1/derived-series/{partial_definition['id']}/runs",
        json={
            "requested_start_at": "2026-03-01T00:00:00Z",
            "requested_end_at": "2026-03-01T00:00:00Z",
            "as_of": "2026-05-01T00:00:00Z",
        },
    )
    assert first.status_code == second.status_code == 201
    stitched = client.get(
        f"/api/v1/derived-series/{partial_definition['id']}/observations",
        params={
            "start": "2026-02-01T00:00:00Z",
            "end": "2026-03-01T00:00:00Z",
        },
    )
    assert stitched.status_code == 404


def test_float_and_naive_timestamp_requests_are_rejected(
    client: TestClient, db_session: Session
) -> None:
    source_id = _seed_source(db_session, "S.API.STRICT")
    payload = {
        "code": "API.STRICT.REBASE",
        "title": "Strict",
        "initial_version": {
            "parameters": {
                "transformation_type": "rebase_index",
                "base_timestamp": "2026-01-01T00:00:00Z",
                "base_value": 100.5,
            },
            "inputs": [{"alias": "value", "source_series_id": source_id}],
        },
    }
    assert client.post("/api/v1/derived-series", json=payload).status_code == 422
    definition = _create_definition(client, source_id, code="API.STRICT.TIMESTAMP")
    naive = client.post(
        f"/api/v1/derived-series/{definition['id']}/runs",
        json={
            "requested_start_at": "2026-02-01T00:00:00",
            "requested_end_at": "2026-03-01T00:00:00Z",
        },
    )
    assert naive.status_code == 422


def test_analytics_openapi_inventory_and_privacy(client: TestClient) -> None:
    document = client.get("/openapi.json")
    assert document.status_code == 200
    payload = document.json()
    expected = {
        "/api/v1/derived-series",
        "/api/v1/derived-series/{definition_id}",
        "/api/v1/derived-series/{definition_id}/versions",
        "/api/v1/derived-series/{definition_id}/runs",
        "/api/v1/analytics-runs",
        "/api/v1/analytics-runs/{run_id}",
        "/api/v1/analytics-runs/{run_id}/observations",
        "/api/v1/analytics-runs/{run_id}/observations/{observation_id}/lineage",
        "/api/v1/derived-series/{definition_id}/observations/latest",
        "/api/v1/derived-series/{definition_id}/observations",
        "/api/v1/derived-series/{definition_id}/observations/as-of",
    }
    assert expected <= set(payload["paths"])
    assert payload["info"]["version"] == "0.6.0"
    _assert_private_fields_absent(payload)
    rendered = str(payload)
    assert "formula" not in rendered.lower()
    assert "python" not in rendered.lower()


def test_missing_resources_invalid_ranges_and_filters_are_controlled(
    client: TestClient, db_session: Session
) -> None:
    source_id = _seed_source(db_session, "S.API.ERRORS")
    definition = _create_definition(client, source_id, code="API.ERRORS")
    definition_id = definition["id"]

    assert client.get("/api/v1/derived-series/999999").status_code == 404
    assert (
        client.patch(
            "/api/v1/derived-series/999999",
            json={"expected_lock_version": 1, "title": "missing"},
        ).status_code
        == 404
    )
    assert client.get("/api/v1/derived-series/999999/versions").status_code == 404
    assert client.get(f"/api/v1/derived-series/{definition_id}/versions/999999").status_code == 404
    assert (
        client.post(
            "/api/v1/derived-series/999999/versions",
            json={
                "expected_lock_version": 1,
                "parameters": {"transformation_type": "difference"},
                "inputs": [{"alias": "value", "source_series_id": source_id}],
            },
        ).status_code
        == 404
    )
    assert client.get("/api/v1/analytics-runs/999999").status_code == 404
    assert client.get("/api/v1/analytics-runs/999999/observations").status_code == 404
    assert (
        client.get("/api/v1/analytics-runs/999999/observations/999999/lineage").status_code == 404
    )
    assert (
        client.get(f"/api/v1/derived-series/{definition_id}/observations/latest").status_code == 404
    )

    reversed_range = {
        "start": "2026-03-01T00:00:00Z",
        "end": "2026-02-01T00:00:00Z",
    }
    assert (
        client.get(
            f"/api/v1/derived-series/{definition_id}/observations",
            params=reversed_range,
        ).status_code
        == 422
    )
    assert (
        client.get(
            f"/api/v1/derived-series/{definition_id}/observations/as-of",
            params={"as_of": "2026-05-01T00:00:00Z", **reversed_range},
        ).status_code
        == 422
    )
    assert (
        client.get(
            "/api/v1/analytics-runs",
            params={
                "created_from": "2026-03-01T00:00:00Z",
                "created_to": "2026-02-01T00:00:00Z",
            },
        ).status_code
        == 422
    )
    assert (
        client.get(
            "/api/v1/derived-series",
            params={"code": "not valid whitespace"},
        ).status_code
        == 422
    )


def test_api_error_mapping_and_execution_session_cleanup() -> None:
    assert (
        analytics_api._management_error(
            analytics_management.AnalyticsNotFoundError("missing")
        ).status_code
        == 404
    )
    assert (
        analytics_api._management_error(
            analytics_management.AnalyticsConflictError("conflict")
        ).status_code
        == 409
    )
    assert (
        analytics_api._management_error(
            analytics_management.AnalyticsValidationError("invalid")
        ).status_code
        == 422
    )
    assert (
        analytics_api._execution_error(
            analytics_execution.AnalyticsNotFoundError("missing")
        ).status_code
        == 404
    )
    assert (
        analytics_api._execution_error(
            analytics_execution.AnalyticsConflictError("conflict")
        ).status_code
        == 409
    )
    assert (
        analytics_api._execution_error(
            analytics_execution.AnalyticsResourceLimitError("bounded")
        ).status_code
        == 422
    )
    assert analytics_api._execution_error(RuntimeError("private")).detail == (
        "Analytics execution failed"
    )

    dependency = analytics_api.get_analytics_execution_db()
    session = next(dependency)
    assert not session.in_transaction()
    dependency.close()
    assert session.is_active
