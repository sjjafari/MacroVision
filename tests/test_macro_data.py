from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from macrovision import macro_data_models as models
from macrovision import macro_data_schemas as schemas
from macrovision import macro_data_services as services


def create_source(client: TestClient, code: str = "BLS") -> dict[str, Any]:
    response = client.post(
        "/api/v1/data-sources",
        json={
            "code": code,
            "name": f"{code} source",
            "description": "Documented source",
            "reference_url": "https://example.test/source",
        },
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def create_series(
    client: TestClient,
    source_id: int,
    *,
    code: str = "US.CPI",
    frequency: str = "monthly",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "source_id": source_id,
        "code": code,
        "name": f"{code} series",
        "description": "Macro series",
        "category": "inflation",
        "geography": "US",
        "frequency": frequency,
        "unit": "index",
        "seasonal_adjustment": "adjusted",
        "publication_lag_days": 14,
        "metadata": {"methodology": "documented"},
    }
    payload.update(extra or {})
    response = client.post("/api/v1/data-series", json=payload)
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def observation_payload(
    observed_at: str = "2026-01-01T00:00:00Z",
    publication_timestamp: str = "2026-01-15T12:00:00Z",
    value: str | None = "100.12345678",
    **extra: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "observed_at": observed_at,
        "publication_timestamp": publication_timestamp,
        "value": value,
        "status": "present" if value is not None else "missing",
        "source_reference": "release-1",
    }
    payload.update(extra)
    return payload


def test_sources_series_pagination_and_optimistic_patch(client: TestClient) -> None:
    source = create_source(client)
    second = create_source(client, "FED")
    assert [item["id"] for item in client.get("/api/v1/data-sources").json()] == [
        source["id"],
        second["id"],
    ]
    assert client.get("/api/v1/data-sources?limit=1&offset=1").json()[0]["id"] == second["id"]
    series = create_series(client, source["id"])
    assert series["metadata"] == {"methodology": "documented"}
    assert series["lock_version"] == 1
    patched = client.patch(
        f"/api/v1/data-series/{series['id']}",
        json={
            "expected_lock_version": 1,
            "name": "US CPI revised metadata",
            "is_active": False,
        },
    )
    assert patched.status_code == 200
    assert patched.json()["lock_version"] == 2
    stale = client.patch(
        f"/api/v1/data-series/{series['id']}",
        json={"expected_lock_version": 1, "name": "Stale"},
    )
    assert stale.status_code == 409
    assert client.get(f"/api/v1/data-series/{series['id']}").json()["name"] != "Stale"


def test_series_uniqueness_validation_and_missing_resources(client: TestClient) -> None:
    source = create_source(client)
    create_series(client, source["id"])
    assert (
        client.post(
            "/api/v1/data-series",
            json={
                **{
                    "source_id": source["id"],
                    "code": "US.CPI",
                    "name": "Duplicate",
                    "category": "inflation",
                    "geography": "US",
                    "frequency": "monthly",
                    "unit": "index",
                }
            },
        ).status_code
        == 409
    )
    assert client.get("/api/v1/data-sources/999").status_code == 404
    assert client.get("/api/v1/data-series/999").status_code == 404
    response = client.post(
        "/api/v1/data-series",
        json={
            "source_id": source["id"],
            "code": "BAD.RANGE",
            "name": "Bad",
            "category": "custom",
            "geography": "Global",
            "frequency": "irregular",
            "unit": "value",
            "minimum_value": "10",
            "maximum_value": "1",
        },
    )
    assert response.status_code == 422


def test_exact_observation_missing_status_and_utc_normalization(
    client: TestClient, db_session: Session
) -> None:
    series = create_series(client, create_source(client)["id"])
    response = client.post(
        f"/api/v1/data-series/{series['id']}/observations",
        json=observation_payload(
            observed_at="2026-01-01T03:30:00+03:30",
            publication_timestamp="2026-01-15T15:30:00+03:30",
        ),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["observed_at"] == "2026-01-01T00:00:00Z"
    assert body["publication_timestamp"] == "2026-01-15T12:00:00Z"
    assert body["value"] == "100.12345678"
    raw = db_session.execute(
        text("SELECT value FROM data_observations WHERE id = :id"),
        {"id": body["id"]},
    ).scalar_one()
    assert raw == 10_012_345_678

    missing = client.post(
        f"/api/v1/data-series/{series['id']}/observations",
        json=observation_payload("2026-02-01T00:00:00Z", "2026-02-15T00:00:00Z", None),
    )
    assert missing.status_code == 201
    assert missing.json()["status"] == "missing"
    assert missing.json()["value"] is None


@pytest.mark.parametrize(
    "payload",
    [
        observation_payload(
            observed_at="2026-01-01T00:00:00",
            publication_timestamp="2026-01-15T00:00:00Z",
        ),
        observation_payload(value=None, status="present"),
        observation_payload(value="1", status="missing"),
        observation_payload(
            observed_at="2026-02-01T00:00:00Z",
            publication_timestamp="2026-01-01T00:00:00Z",
        ),
        observation_payload(value="1.123456789"),
    ],
)
def test_observation_validation_rejects_ambiguous_or_inexact_data(
    client: TestClient, payload: dict[str, Any]
) -> None:
    series = create_series(client, create_source(client)["id"])
    assert (
        client.post(f"/api/v1/data-series/{series['id']}/observations", json=payload).status_code
        == 422
    )


def test_revisions_preserve_history_latest_and_as_of(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = create_source(client)
    series = create_series(client, source["id"])
    initial_ingestion = datetime(2026, 2, 1, tzinfo=UTC)
    revision_ingestion = datetime(2026, 3, 1, tzinfo=UTC)
    times = iter((initial_ingestion, revision_ingestion))
    monkeypatch.setattr(services, "_now", lambda: next(times))

    initial = client.post(
        f"/api/v1/data-series/{series['id']}/observations",
        json=observation_payload(),
    )
    assert initial.status_code == 201
    observation_id = initial.json()["id"]
    revised = client.post(
        f"/api/v1/data-series/{series['id']}/observations",
        json=observation_payload(
            value="101.00000000",
            publication_timestamp="2026-02-20T00:00:00Z",
            revision_reason="Seasonal benchmark revision",
            source_reference="release-2",
        ),
    )
    assert revised.status_code == 201, revised.text
    assert revised.json()["id"] == observation_id
    assert revised.json()["value"] == "101.00000000"
    assert revised.json()["revision_count"] == 1

    history = client.get(
        f"/api/v1/data-series/{series['id']}/observations/{observation_id}/revisions"
    ).json()
    assert len(history) == 1
    assert history[0]["previous_value"] == "100.12345678"
    assert history[0]["revised_value"] == "101.00000000"
    assert history[0]["reason"] == "Seasonal benchmark revision"

    before = client.get(
        f"/api/v1/data-series/{series['id']}/observations/as-of",
        params={"as_of": "2026-02-15T00:00:00Z"},
    )
    after = client.get(
        f"/api/v1/data-series/{series['id']}/observations/as-of",
        params={"as_of": "2026-03-02T00:00:00Z"},
    )
    assert before.json()[0]["value"] == "100.12345678"
    assert after.json()[0]["value"] == "101.00000000"
    assert (
        client.get(f"/api/v1/data-series/{series['id']}/latest").json()["value"] == "101.00000000"
    )


def test_duplicate_requires_reason_and_records_quality_issue(client: TestClient) -> None:
    series = create_series(client, create_source(client)["id"])
    path = f"/api/v1/data-series/{series['id']}/observations"
    assert client.post(path, json=observation_payload()).status_code == 201
    duplicate = client.post(path, json=observation_payload(value="101"))
    assert duplicate.status_code == 409
    issues = client.get("/api/v1/data-quality/issues").json()
    assert issues[0]["issue_type"] == "duplicate_observation"


def test_quality_range_change_frequency_and_issue_lifecycle(
    client: TestClient, db_session: Session
) -> None:
    series = create_series(
        client,
        create_source(client)["id"],
        frequency="monthly",
        extra={
            "minimum_value": "90",
            "maximum_value": "110",
            "max_change_percent": "5",
        },
    )
    path = f"/api/v1/data-series/{series['id']}/observations"
    assert client.post(path, json=observation_payload(value="100")).status_code == 201
    response = client.post(
        path,
        json=observation_payload("2026-01-05T00:00:00Z", "2026-01-20T00:00:00Z", "120"),
    )
    assert response.status_code == 201
    issues = client.get("/api/v1/data-quality/issues").json()
    assert {item["issue_type"] for item in issues} >= {
        "frequency_violation",
        "invalid_numeric_range",
        "large_unexpected_change",
    }
    issue = issues[0]
    acknowledged = client.post(
        f"/api/v1/data-quality/issues/{issue['id']}/acknowledge",
        json={
            "expected_lock_version": issue["lock_version"],
            "notes": "Reviewing",
            "actor_reference": "analyst@example.test",
        },
    )
    assert acknowledged.status_code == 200
    assert acknowledged.json()["acknowledged_at"] is not None
    stale = client.post(
        f"/api/v1/data-quality/issues/{issue['id']}/resolve",
        json={"expected_lock_version": issue["lock_version"], "notes": "Stale"},
    )
    assert stale.status_code == 409
    resolved = client.post(
        f"/api/v1/data-quality/issues/{issue['id']}/resolve",
        json={
            "expected_lock_version": acknowledged.json()["lock_version"],
            "notes": "Source confirmed",
        },
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"
    assert resolved.json()["resolution_notes"] == "Source confirmed"
    history = client.get(f"/api/v1/data-quality/issues/{issue['id']}/history").json()
    assert [(event["previous_status"], event["new_status"]) for event in history] == [
        ("open", "acknowledged"),
        ("acknowledged", "resolved"),
    ]
    assert history[0]["note"] == "Reviewing"
    assert history[0]["actor_reference"] == "analyst@example.test"
    event = db_session.get(models.DataQualityIssueEvent, history[0]["id"])
    assert event is not None
    event.note = "Attempted overwrite"
    with pytest.raises(ValueError, match="immutable"):
        db_session.commit()
    db_session.rollback()
    db_session.delete(event)
    with pytest.raises(ValueError, match="immutable"):
        db_session.commit()
    db_session.rollback()


def test_stale_series_detection_is_idempotent(client: TestClient) -> None:
    create_series(
        client,
        create_source(client)["id"],
        extra={"stale_after_days": 1},
    )
    assert client.get("/api/v1/data-quality/issues").json() == []
    first_scan = client.post("/api/v1/data-quality/scans/stale")
    second_scan = client.post("/api/v1/data-quality/scans/stale")
    assert first_scan.json() == {"inspected_count": 1, "created_count": 1}
    assert second_scan.json() == {"inspected_count": 1, "created_count": 0}
    first = client.get("/api/v1/data-quality/issues").json()
    second = client.get("/api/v1/data-quality/issues").json()
    assert len(first) == len(second) == 1
    assert first[0]["issue_type"] == "stale_series"


def test_import_atomic_partial_and_idempotent(client: TestClient, db_session: Session) -> None:
    source = create_source(client)
    series = create_series(client, source["id"])
    rows = [
        {"series_code": series["code"], **observation_payload()},
        {
            "series_code": "MISSING",
            **observation_payload("2026-02-01T00:00:00Z", "2026-02-15T00:00:00Z", "101"),
        },
    ]
    atomic = client.post(
        "/api/v1/data-imports",
        json={
            "source_id": source["id"],
            "idempotency_key": "atomic-1",
            "rows": rows,
        },
    )
    assert atomic.status_code == 409
    assert client.get(f"/api/v1/data-series/{series['id']}/observations").json() == []
    failed = client.get("/api/v1/data-imports").json()[0]
    assert failed["status"] == "failed"
    assert failed["failed_at"] is not None
    assert failed["accepted_rows"] == 0
    assert failed["rejected_rows"] == 2
    assert failed["errors"][0]["row_index"] == 1
    assert failed["errors"][0]["error_code"] == "series_unavailable"
    assert set(failed["errors"][0]["source_context"]) == {
        "series_code",
        "observed_at",
    }
    import_error = db_session.get(models.DataImportError, failed["errors"][0]["id"])
    assert import_error is not None
    import_error.message = "Attempted overwrite"
    with pytest.raises(ValueError, match="immutable"):
        db_session.commit()
    db_session.rollback()
    db_session.delete(import_error)
    with pytest.raises(ValueError, match="immutable"):
        db_session.commit()
    db_session.rollback()
    failed_replay = client.post(
        "/api/v1/data-imports",
        json={
            "source_id": source["id"],
            "idempotency_key": "atomic-1",
            "rows": rows,
        },
    )
    assert failed_replay.status_code == 409
    assert len(client.get("/api/v1/data-imports").json()) == 1

    partial_payload = {
        "source_id": source["id"],
        "idempotency_key": "partial-1",
        "partial_mode": True,
        "rows": rows,
    }
    partial = client.post("/api/v1/data-imports", json=partial_payload)
    assert partial.status_code == 201, partial.text
    assert partial.json()["accepted_rows"] == 1
    assert partial.json()["rejected_rows"] == 1
    assert partial.json()["errors"][0]["row_index"] == 1
    repeated = client.post("/api/v1/data-imports", json=partial_payload)
    assert repeated.status_code == 201
    assert repeated.json()["id"] == partial.json()["id"]
    changed_payload = {
        **partial_payload,
        "rows": [
            {
                "series_code": series["code"],
                **observation_payload(
                    "2026-03-01T00:00:00Z",
                    "2026-03-15T00:00:00Z",
                    "103",
                ),
            }
        ],
    }
    assert client.post("/api/v1/data-imports", json=changed_payload).status_code == 409
    assert len(client.get(f"/api/v1/data-series/{series['id']}/observations").json()) == 1


def test_import_limits_return_validation_errors(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from macrovision.config import get_settings

    source = create_source(client)
    series = create_series(client, source["id"])
    monkeypatch.setattr(get_settings(), "max_import_rows", 1)
    boundary = client.post(
        "/api/v1/data-imports",
        json={
            "source_id": source["id"],
            "idempotency_key": "at-limit",
            "rows": [{"series_code": series["code"], **observation_payload()}],
        },
    )
    assert boundary.status_code == 201
    too_many = client.post(
        "/api/v1/data-imports",
        json={
            "source_id": source["id"],
            "idempotency_key": "too-many",
            "rows": [
                {"series_code": series["code"], **observation_payload()},
                {
                    "series_code": series["code"],
                    **observation_payload(
                        "2026-02-01T00:00:00Z",
                        "2026-02-15T00:00:00Z",
                        "101",
                    ),
                },
            ],
        },
    )
    assert too_many.status_code == 422

    monkeypatch.setattr(get_settings(), "max_import_notes_length", 10)
    long_notes = client.post(
        "/api/v1/data-imports",
        json={
            "source_id": source["id"],
            "idempotency_key": "long-notes",
            "notes": "x" * 11,
            "rows": [{"series_code": series["code"], **observation_payload()}],
        },
    )
    assert long_notes.status_code == 422


def test_immutable_history_restricts_orm_and_parent_deletion(
    client: TestClient, db_session: Session
) -> None:
    series = create_series(client, create_source(client)["id"])
    created = client.post(
        f"/api/v1/data-series/{series['id']}/observations",
        json=observation_payload(),
    ).json()
    observation = db_session.get(models.DataObservation, created["id"])
    assert observation is not None
    observation.value = Decimal("999")
    with pytest.raises(ValueError, match="immutable"):
        db_session.commit()
    db_session.rollback()
    db_session.delete(observation)
    with pytest.raises(ValueError, match="immutable"):
        db_session.commit()
    db_session.rollback()
    with pytest.raises(IntegrityError):
        db_session.execute(delete(models.DataSeries).where(models.DataSeries.id == series["id"]))
    db_session.rollback()


def test_concurrent_series_updates_return_controlled_conflict(
    db_session: Session,
) -> None:
    source = services.create_source(db_session, schemas.DataSourceCreate(code="SRC", name="Source"))
    series = services.create_series(
        db_session,
        schemas.DataSeriesCreate(
            source_id=source.id,
            code="SERIES",
            name="Series",
            category=models.SeriesCategory.custom,
            geography="Global",
            frequency=models.DataFrequency.irregular,
            unit="value",
        ),
    )
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, expire_on_commit=False)
    stale_session = factory()
    winner_session = factory()
    try:
        stale = services.get_series(stale_session, series.id)
        winner = services.patch_series(
            winner_session,
            series.id,
            schemas.DataSeriesPatch(expected_lock_version=series.lock_version, name="Winner"),
        )
        assert winner.name == "Winner"
        with pytest.raises(services.DataConflictError):
            services.patch_series(
                stale_session,
                series.id,
                schemas.DataSeriesPatch(expected_lock_version=stale.lock_version, name="Loser"),
            )
    finally:
        stale_session.close()
        winner_session.close()


def test_macro_data_openapi_surface(client: TestClient) -> None:
    paths = set(client.get("/openapi.json").json()["paths"])
    assert {
        "/api/v1/data-sources",
        "/api/v1/data-sources/{source_id}",
        "/api/v1/data-series",
        "/api/v1/data-series/{series_id}",
        "/api/v1/data-series/{series_id}/observations",
        "/api/v1/data-series/{series_id}/latest",
        "/api/v1/data-series/{series_id}/observations/as-of",
        "/api/v1/data-series/{series_id}/observations/{observation_id}/revisions",
        "/api/v1/data-imports",
        "/api/v1/data-imports/{import_id}",
        "/api/v1/data-quality/issues",
        "/api/v1/data-quality/issues/{issue_id}",
        "/api/v1/data-quality/issues/{issue_id}/acknowledge",
        "/api/v1/data-quality/issues/{issue_id}/resolve",
    } <= paths


@pytest.mark.parametrize(
    "value",
    ["92233720368.54775808", "-92233720368.54775808", "NaN", "Infinity"],
)
def test_decimal_overflow_and_non_finite_values_return_validation_errors(
    client: TestClient, value: str
) -> None:
    series = create_series(client, create_source(client)["id"])
    response = client.post(
        f"/api/v1/data-series/{series['id']}/observations",
        json=observation_payload(value=value),
    )
    assert response.status_code == 422


def test_decimal_storage_boundaries_round_trip_exactly(client: TestClient) -> None:
    series = create_series(client, create_source(client)["id"], frequency="irregular")
    path = f"/api/v1/data-series/{series['id']}/observations"
    maximum = client.post(path, json=observation_payload(value="92233720368.54775807"))
    minimum = client.post(
        path,
        json=observation_payload(
            "2026-02-01T00:00:00Z",
            "2026-02-15T00:00:00Z",
            "-92233720368.54775807",
        ),
    )
    assert maximum.status_code == minimum.status_code == 201
    assert maximum.json()["value"] == "92233720368.54775807"
    assert minimum.json()["value"] == "-92233720368.54775807"


def test_observation_pagination_is_chronological_and_deterministic(
    client: TestClient,
) -> None:
    series = create_series(client, create_source(client)["id"], frequency="irregular")
    path = f"/api/v1/data-series/{series['id']}/observations"
    for observed, published, value in (
        ("2026-03-01T00:00:00Z", "2026-03-02T00:00:00Z", "3"),
        ("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", "1"),
        ("2026-02-01T00:00:00Z", "2026-02-02T00:00:00Z", "2"),
    ):
        assert (
            client.post(path, json=observation_payload(observed, published, value)).status_code
            == 201
        )
    first_page = client.get(path, params={"limit": 2, "offset": 0}).json()
    second_page = client.get(path, params={"limit": 2, "offset": 2}).json()
    assert [item["value"] for item in first_page + second_page] == [
        "1.00000000",
        "2.00000000",
        "3.00000000",
    ]


def test_revision_and_completed_import_are_immutable(
    client: TestClient, db_session: Session
) -> None:
    source = create_source(client)
    series = create_series(client, source["id"])
    path = f"/api/v1/data-series/{series['id']}/observations"
    created = client.post(path, json=observation_payload()).json()
    client.post(
        path,
        json=observation_payload(
            value="101",
            revision_reason="Correction",
        ),
    )
    revision = services.list_revisions(db_session, series["id"], created["id"])[0]
    revision.reason = "Attempted overwrite"
    with pytest.raises(ValueError, match="immutable"):
        db_session.commit()
    db_session.rollback()
    db_session.delete(revision)
    with pytest.raises(ValueError, match="immutable"):
        db_session.commit()
    db_session.rollback()

    imported = client.post(
        "/api/v1/data-imports",
        json={
            "source_id": source["id"],
            "idempotency_key": "immutable-import",
            "rows": [
                {
                    "series_code": series["code"],
                    **observation_payload(
                        "2026-02-01T00:00:00Z",
                        "2026-02-15T00:00:00Z",
                        "102",
                    ),
                }
            ],
        },
    ).json()
    batch = db_session.get(models.DataImportBatch, imported["id"])
    assert batch is not None
    batch.notes = "Attempted overwrite"
    with pytest.raises(ValueError, match="immutable"):
        db_session.commit()
    db_session.rollback()


def test_database_constraints_foreign_keys_and_indexes(
    db_session: Session,
) -> None:
    assert db_session.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
    restrict_tables = {
        "data_series": 1,
        "data_import_batches": 1,
        "data_observations": 2,
        "data_revisions": 2,
        "data_quality_issues": 2,
    }
    for table, expected_count in restrict_tables.items():
        foreign_keys = db_session.execute(text(f'PRAGMA foreign_key_list("{table}")')).all()
        assert len(foreign_keys) == expected_count
        assert {row[6] for row in foreign_keys} == {"RESTRICT"}
        indexes = db_session.execute(text(f'PRAGMA index_list("{table}")')).all()
        assert indexes


def test_failed_revision_does_not_leave_partial_history(
    client: TestClient,
) -> None:
    series = create_series(client, create_source(client)["id"])
    path = f"/api/v1/data-series/{series['id']}/observations"
    created = client.post(path, json=observation_payload()).json()
    invalid = client.post(
        path,
        json=observation_payload(
            value="92233720368.54775808",
            revision_reason="Overflow",
        ),
    )
    assert invalid.status_code == 422
    revisions = client.get(f"{path}/{created['id']}/revisions").json()
    assert revisions == []
    assert (
        client.get(f"/api/v1/data-series/{series['id']}/latest").json()["value"] == "100.12345678"
    )


def test_missing_quality_and_import_resources_return_404(
    client: TestClient,
) -> None:
    assert client.get("/api/v1/data-quality/issues/999").status_code == 404
    assert client.get("/api/v1/data-imports/999").status_code == 404
    assert (
        client.post(
            "/api/v1/data-quality/issues/999/acknowledge",
            json={"expected_lock_version": 1},
        ).status_code
        == 404
    )


def test_impossible_future_timestamp_records_issue_without_observation(
    client: TestClient,
) -> None:
    series = create_series(client, create_source(client)["id"])
    response = client.post(
        f"/api/v1/data-series/{series['id']}/observations",
        json=observation_payload(
            "2099-01-01T00:00:00Z",
            "2099-01-02T00:00:00Z",
            "1",
        ),
    )
    assert response.status_code == 409
    assert client.get(f"/api/v1/data-series/{series['id']}/observations").json() == []
    issues = client.get("/api/v1/data-quality/issues").json()
    assert len(issues) == 1
    assert issues[0]["issue_type"] == "impossible_timestamp"


def test_competing_revisions_return_conflict_and_preserve_winner(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = services.create_source(
        db_session, schemas.DataSourceCreate(code="CONCURRENT", name="Source")
    )
    series = services.create_series(
        db_session,
        schemas.DataSeriesCreate(
            source_id=source.id,
            code="CONCURRENT.SERIES",
            name="Series",
            category=models.SeriesCategory.custom,
            geography="Global",
            frequency=models.DataFrequency.irregular,
            unit="value",
        ),
    )
    initial_time = datetime(2026, 2, 1, tzinfo=UTC)
    monkeypatch.setattr(services, "_now", lambda: initial_time)
    observation = services.add_observation(
        db_session,
        series.id,
        schemas.ObservationWrite(**observation_payload()),
    )
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, expire_on_commit=False)
    stale_session = factory()
    winner_session = factory()
    verifier_session = factory()
    try:
        stale = stale_session.scalar(
            services._observation_statement().where(models.DataObservation.id == observation.id)
        )
        assert stale is not None
        monkeypatch.setattr(
            services,
            "_now",
            lambda: datetime(2026, 3, 1, tzinfo=UTC),
        )
        winner = services.add_observation(
            winner_session,
            series.id,
            schemas.ObservationWrite(
                **observation_payload(
                    value="101",
                    publication_timestamp="2026-02-20T00:00:00Z",
                    revision_reason="Winner",
                )
            ),
        )
        assert services.observation_to_read(winner).value == Decimal("101")

        with pytest.raises(services.DataConflictError):
            services.add_observation(
                stale_session,
                series.id,
                schemas.ObservationWrite(
                    **observation_payload(
                        value="102",
                        publication_timestamp="2026-02-21T00:00:00Z",
                        revision_reason="Loser",
                    )
                ),
            )

        revisions = services.list_revisions(verifier_session, series.id, observation.id)
        assert len(revisions) == 1
        assert revisions[0].reason == "Winner"
        assert revisions[0].revised_value == Decimal("101")
    finally:
        stale_session.close()
        winner_session.close()
        verifier_session.close()
