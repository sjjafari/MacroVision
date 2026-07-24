import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from macrovision import models
from tests.test_investors import investor_payload


def test_journal_requires_evidence_and_supports_documented_learning(
    client: TestClient,
) -> None:
    investor = client.post("/api/v1/investors", json=investor_payload()).json()
    journal_payload = {
        "investor_id": investor["id"],
        "asset": "Cash",
        "hypothesis": "Cash protects optionality while valuations are unusually dispersed.",
        "evidence_for": "Liquidity needs and risk budget favor resilience.",
        "evidence_against": "Inflation can erode purchasing power.",
        "critic_review": "The evidence lacks a defined valuation threshold.",
        "probability": 0.65,
        "confidence": 0.55,
        "invalidation_conditions": "Real cash yields turn materially negative.",
        "decision": "Maintain a 15% cash allocation.",
        "status": "active",
    }

    created = client.post("/api/v1/journals", json=journal_payload)
    assert created.status_code == 201
    assert created.json()["outcome"] is None
    assert created.json()["status"] == "draft"

    journal_id = created.json()["id"]
    closed = client.post(
        f"/api/v1/journals/{journal_id}/close",
        json={
            "outcome": "Optionality was useful during a market drawdown.",
            "lessons": "Define deployment triggers when choosing a cash allocation.",
        },
    )
    assert closed.status_code == 200
    assert closed.json()["status"] == "closed"
    assert closed.json()["closed_at"] is not None
    assert closed.json()["lessons"].startswith("Define deployment")

    fetched = client.get(f"/api/v1/journals/{journal_id}")
    assert fetched.status_code == 200
    assert fetched.json()["outcome"] == closed.json()["outcome"]

    repeated = client.post(
        f"/api/v1/journals/{journal_id}/close",
        json={"outcome": "Overwrite", "lessons": "Overwrite"},
    )
    assert repeated.status_code == 409
    unchanged = client.get(f"/api/v1/journals/{journal_id}").json()
    assert unchanged["outcome"] == closed.json()["outcome"]
    assert unchanged["lessons"] == closed.json()["lessons"]


def test_closed_journal_rejects_direct_orm_mutation(
    client: TestClient, db_session: Session
) -> None:
    investor = client.post("/api/v1/investors", json=investor_payload()).json()
    payload = {
        "investor_id": investor["id"],
        "asset": "Cash",
        "hypothesis": "Preserve optionality.",
        "evidence_for": "Liquidity.",
        "evidence_against": "Inflation.",
        "critic_review": "Review real yields.",
        "probability": 0.6,
        "confidence": 0.5,
        "invalidation_conditions": "Real yields fall.",
    }
    journal = client.post("/api/v1/journals", json=payload).json()
    client.post(
        f"/api/v1/journals/{journal['id']}/close",
        json={"outcome": "Preserved", "lessons": "Document triggers"},
    )
    record = db_session.get(models.ResearchJournal, journal["id"])
    assert record is not None
    record.outcome = "Attempted overwrite"
    with pytest.raises(ValueError, match="immutable"):
        db_session.commit()
    db_session.rollback()


def test_legacy_journal_routes_are_deprecated(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert paths["/api/v1/journals"]["post"]["deprecated"] is True
    assert paths["/api/v1/journals/{journal_id}"]["get"]["deprecated"] is True
    assert paths["/api/v1/journals/{journal_id}/close"]["post"]["deprecated"] is True


def test_journal_rejects_certainty_above_probability_range(client: TestClient) -> None:
    response = client.post(
        "/api/v1/journals",
        json={
            "investor_id": 1,
            "asset": "Asset",
            "hypothesis": "A hypothesis",
            "evidence_for": "Supporting evidence",
            "evidence_against": "Opposing evidence",
            "critic_review": "Independent critique",
            "probability": 1.1,
            "confidence": 0.5,
            "invalidation_conditions": "A falsifier",
        },
    )
    assert response.status_code == 422


def test_journal_for_missing_investor_returns_not_found(client: TestClient) -> None:
    response = client.post(
        "/api/v1/journals",
        json={
            "investor_id": 999,
            "asset": "Cash",
            "hypothesis": "Cash is appropriate.",
            "evidence_for": "Liquidity.",
            "evidence_against": "Inflation.",
            "critic_review": "Check real yields.",
            "probability": 0.6,
            "confidence": 0.5,
            "invalidation_conditions": "Real yields fall.",
        },
    )
    assert response.status_code == 404
