from decimal import Decimal
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from macrovision import decision_models, decision_schemas, decision_services


def create_decision(client: TestClient) -> dict[str, Any]:
    response = client.post(
        "/api/v1/decisions",
        json={
            "title": "Capital preservation allocation",
            "question": "Should the portfolio maintain a defensive allocation?",
            "context": "Valuations are dispersed and liquidity has option value.",
            "rationale": "Preserve capital while retaining measured upside.",
            "probability": "0.650000",
            "confidence": "0.550000",
        },
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def add_hypothesis(client: TestClient, decision_id: int) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/decisions/{decision_id}/hypotheses",
        json={
            "statement": "A defensive allocation improves risk-adjusted outcomes.",
            "rationale": "Liquidity reduces forced selling risk.",
        },
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def add_evidence(client: TestClient, decision_id: int, side: str) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/decisions/{decision_id}/evidence",
        json={
            "side": side,
            "source_title": f"{side.title()} evidence source",
            "source_type": "research_paper",
            "publication_date": "2026-07-01",
            "reference": f"https://example.test/{side}",
            "reliability_score": "0.800000",
            "relevance_score": "0.750000",
            "notes": "Documented evidence.",
        },
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def add_review(client: TestClient, decision_id: int) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/decisions/{decision_id}/critic-reviews",
        json={
            "reviewer": "Independent Critic",
            "analysis": "The thesis depends on timing and opportunity cost.",
            "key_risks": "Inflation and premature defensiveness.",
            "recommendation": "Activate only with explicit invalidation conditions.",
        },
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def add_rule(client: TestClient, decision_id: int) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/decisions/{decision_id}/invalidation-rules",
        json={
            "condition": "Real cash yields remain below -2% for two quarters.",
            "observation_source": "Published central-bank and inflation data",
            "notes": "Review quarterly.",
        },
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def complete_decision(client: TestClient, decision_id: int) -> dict[str, Any]:
    add_hypothesis(client, decision_id)
    add_evidence(client, decision_id, "supporting")
    add_evidence(client, decision_id, "opposing")
    add_review(client, decision_id)
    return add_rule(client, decision_id)


def activate(client: TestClient, decision_id: int) -> dict[str, Any]:
    response = client.post(f"/api/v1/decisions/{decision_id}/activate")
    assert response.status_code == 200, response.text
    return cast(dict[str, Any], response.json())


def test_create_list_get_and_exact_score_persistence(
    client: TestClient, db_session: Session
) -> None:
    decision = create_decision(client)
    assert decision["status"] == "draft"
    assert decision["current_version"] == 1
    assert decision["probability"] == "0.650000"
    assert decision["confidence"] == "0.550000"

    listed = client.get("/api/v1/decisions")
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == decision["id"]
    assert client.get(f"/api/v1/decisions/{decision['id']}").json() == decision

    raw = db_session.execute(
        text("SELECT probability, confidence FROM decision_cases WHERE id = :decision_id"),
        {"decision_id": decision["id"]},
    ).one()
    assert raw == (650000, 550000)


def test_activation_reports_every_missing_requirement(client: TestClient) -> None:
    decision_id = int(create_decision(client)["id"])
    response = client.post(f"/api/v1/decisions/{decision_id}/activate")
    assert response.status_code == 409
    detail = response.json()["detail"]
    for requirement in (
        "hypothesis",
        "supporting evidence",
        "opposing evidence",
        "critic review",
        "invalidation rule",
    ):
        assert requirement in detail


def test_complete_workflow_separates_evidence_and_activates(client: TestClient) -> None:
    decision_id = int(create_decision(client)["id"])
    rule = complete_decision(client, decision_id)
    under_review = client.get(f"/api/v1/decisions/{decision_id}").json()
    assert under_review["status"] == "under_review"
    assert under_review["current_version"] == 2
    assert len(under_review["supporting_evidence"]) == 1
    assert len(under_review["opposing_evidence"]) == 1
    assert under_review["supporting_evidence"][0]["side"] == "supporting"
    assert under_review["opposing_evidence"][0]["side"] == "opposing"
    assert rule["condition"].startswith("Real cash")

    active = activate(client, decision_id)
    assert active["status"] == "active"
    assert active["current_version"] == 3
    assert client.post(f"/api/v1/decisions/{decision_id}/activate").status_code == 409


def test_revision_creates_new_version_without_overwriting_history(
    client: TestClient,
) -> None:
    decision_id = int(create_decision(client)["id"])
    complete_decision(client, decision_id)
    activate(client, decision_id)

    revised = client.post(
        f"/api/v1/decisions/{decision_id}/revise",
        json={
            "probability": "0.575000",
            "confidence": "0.700000",
            "rationale": "New evidence reduces upside probability.",
            "change_summary": "Updated after quarterly evidence review.",
        },
    )
    assert revised.status_code == 200
    assert revised.json()["status"] == "under_review"
    assert revised.json()["current_version"] == 4

    history = client.get(f"/api/v1/decisions/{decision_id}/history")
    assert history.status_code == 200
    body = history.json()
    assert [item["version"] for item in body] == [1, 2, 3, 4]
    assert body[0]["probability"] == "0.650000"
    assert body[-1]["probability"] == "0.575000"
    assert body[-1]["event"] == "revised"

    reactivated = activate(client, decision_id)
    assert reactivated["current_version"] == 5


def test_invalidation_references_rule_and_makes_case_terminal(client: TestClient) -> None:
    decision_id = int(create_decision(client)["id"])
    rule = complete_decision(client, decision_id)
    activate(client, decision_id)

    missing_rule = client.post(
        f"/api/v1/decisions/{decision_id}/invalidate",
        json={"reason": "Test", "rule_id": 999},
    )
    assert missing_rule.status_code == 404

    invalidated = client.post(
        f"/api/v1/decisions/{decision_id}/invalidate",
        json={"reason": "Rule condition observed", "rule_id": rule["id"]},
    )
    assert invalidated.status_code == 200
    assert invalidated.json()["status"] == "invalidated"
    assert invalidated.json()["current_version"] == 4

    assert (
        client.post(
            f"/api/v1/decisions/{decision_id}/hypotheses",
            json={"statement": "Late mutation"},
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/v1/decisions/{decision_id}/revise",
            json={
                "probability": "0.5",
                "confidence": "0.5",
                "rationale": "Forbidden",
                "change_summary": "Forbidden",
            },
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/v1/decisions/{decision_id}/close",
            json={
                "outcome": "No",
                "lessons_learned": "No",
                "accuracy_assessment": "0.5",
            },
        ).status_code
        == 409
    )


def test_close_records_outcome_and_locks_decision(client: TestClient) -> None:
    decision_id = int(create_decision(client)["id"])
    complete_decision(client, decision_id)
    activate(client, decision_id)

    closed = client.post(
        f"/api/v1/decisions/{decision_id}/close",
        json={
            "outcome": "Capital was preserved during the drawdown.",
            "lessons_learned": "Predefined deployment triggers improve discipline.",
            "accuracy_assessment": "0.850000",
        },
    )
    assert closed.status_code == 200
    body = closed.json()
    assert body["status"] == "closed"
    assert body["outcome"]["accuracy_assessment"] == "0.850000"
    assert client.post(f"/api/v1/decisions/{decision_id}/activate").status_code == 409
    assert (
        client.post(
            f"/api/v1/decisions/{decision_id}/critic-reviews",
            json={
                "reviewer": "Late",
                "analysis": "Late",
                "key_risks": "Late",
                "recommendation": "Late",
            },
        ).status_code
        == 409
    )


@pytest.mark.parametrize(
    "payload",
    [
        {
            "title": "Invalid",
            "question": "Invalid?",
            "rationale": "Invalid",
            "probability": "-0.1",
            "confidence": "0.5",
        },
        {
            "title": "Invalid",
            "question": "Invalid?",
            "rationale": "Invalid",
            "probability": "0.5",
            "confidence": "1.1",
        },
        {
            "title": "Invalid",
            "question": "Invalid?",
            "rationale": "Invalid",
            "probability": "0.1234567",
            "confidence": "0.5",
        },
    ],
)
def test_probability_and_confidence_validation(client: TestClient, payload: dict[str, str]) -> None:
    assert client.post("/api/v1/decisions", json=payload).status_code == 422


@pytest.mark.parametrize(
    ("field", "value"),
    [("reliability_score", "1.1"), ("relevance_score", "-0.1")],
)
def test_evidence_score_validation(client: TestClient, field: str, value: str) -> None:
    decision_id = int(create_decision(client)["id"])
    payload = {
        "side": "supporting",
        "source_title": "Evidence",
        "source_type": "other",
        "reliability_score": "0.5",
        "relevance_score": "0.5",
    }
    payload[field] = value
    assert client.post(f"/api/v1/decisions/{decision_id}/evidence", json=payload).status_code == 422


def test_audit_records_are_immutable_and_case_delete_is_restricted(
    db_session: Session,
) -> None:
    decision = decision_services.create_decision(
        db_session,
        decision_schemas.DecisionCreate(
            title="Audit",
            question="Is history retained?",
            rationale="Auditability is required.",
            probability=Decimal("0.5"),
            confidence=Decimal("0.5"),
        ),
    )
    hypothesis = decision_services.add_hypothesis(
        db_session,
        decision.id,
        decision_schemas.HypothesisCreate(statement="Immutable hypothesis"),
    )
    hypothesis.statement = "Attempted overwrite"
    with pytest.raises(ValueError, match="immutable"):
        db_session.commit()
    db_session.rollback()

    revision = decision_services.list_history(db_session, decision.id)[0]
    db_session.delete(revision)
    with pytest.raises(ValueError, match="immutable"):
        db_session.commit()
    db_session.rollback()

    with pytest.raises(IntegrityError):
        db_session.execute(
            delete(decision_models.DecisionCase).where(
                decision_models.DecisionCase.id == decision.id
            )
        )
    db_session.rollback()


def test_missing_resources_and_invalid_lifecycle_return_useful_errors(
    client: TestClient,
) -> None:
    assert client.get("/api/v1/decisions/999").status_code == 404
    assert client.get("/api/v1/decisions/999/history").status_code == 404
    assert (
        client.post("/api/v1/decisions/999/hypotheses", json={"statement": "Missing"}).status_code
        == 404
    )
    decision_id = int(create_decision(client)["id"])
    assert (
        client.post(
            f"/api/v1/decisions/{decision_id}/invalidate",
            json={"reason": "Not active"},
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/v1/decisions/{decision_id}/close",
            json={
                "outcome": "Not active",
                "lessons_learned": "Not active",
                "accuracy_assessment": "0.5",
            },
        ).status_code
        == 409
    )


def test_openapi_contains_complete_decision_surface(client: TestClient) -> None:
    paths = set(client.get("/openapi.json").json()["paths"])
    assert {
        "/api/v1/decisions",
        "/api/v1/decisions/{decision_id}",
        "/api/v1/decisions/{decision_id}/hypotheses",
        "/api/v1/decisions/{decision_id}/evidence",
        "/api/v1/decisions/{decision_id}/critic-reviews",
        "/api/v1/decisions/{decision_id}/invalidation-rules",
        "/api/v1/decisions/{decision_id}/activate",
        "/api/v1/decisions/{decision_id}/invalidate",
        "/api/v1/decisions/{decision_id}/revise",
        "/api/v1/decisions/{decision_id}/close",
        "/api/v1/decisions/{decision_id}/history",
    } <= paths


@pytest.mark.parametrize(
    ("omitted", "message"),
    [
        ("hypothesis", "hypothesis"),
        ("supporting", "supporting evidence"),
        ("opposing", "opposing evidence"),
        ("review", "critic review"),
        ("rule", "invalidation rule"),
    ],
)
def test_activation_rejects_each_individually_missing_requirement(
    client: TestClient, omitted: str, message: str
) -> None:
    decision_id = int(create_decision(client)["id"])
    if omitted != "hypothesis":
        add_hypothesis(client, decision_id)
    if omitted != "supporting":
        add_evidence(client, decision_id, "supporting")
    if omitted != "opposing":
        add_evidence(client, decision_id, "opposing")
    if omitted != "review":
        add_review(client, decision_id)
    if omitted != "rule":
        add_rule(client, decision_id)

    response = client.post(f"/api/v1/decisions/{decision_id}/activate")
    assert response.status_code == 409
    assert message in response.json()["detail"]


def test_draft_revision_stays_draft_until_first_critic_review(
    client: TestClient,
) -> None:
    decision_id = int(create_decision(client)["id"])
    revised = client.post(
        f"/api/v1/decisions/{decision_id}/revise",
        json={
            "probability": "0.600000",
            "confidence": "0.500000",
            "rationale": "Refined before independent review.",
            "change_summary": "Draft refinement.",
        },
    )
    assert revised.status_code == 200
    assert revised.json()["status"] == "draft"
    assert client.post(f"/api/v1/decisions/{decision_id}/activate").status_code == 409

    add_review(client, decision_id)
    add_review(client, decision_id)
    current = client.get(f"/api/v1/decisions/{decision_id}").json()
    assert current["status"] == "under_review"
    assert current["current_version"] == 3
    history = client.get(f"/api/v1/decisions/{decision_id}/history").json()
    assert [item["event"] for item in history] == [
        "created",
        "revised",
        "review_started",
    ]


def test_multiple_activation_components_do_not_distort_rules(
    client: TestClient,
) -> None:
    decision_id = int(create_decision(client)["id"])
    for _ in range(2):
        add_hypothesis(client, decision_id)
        add_evidence(client, decision_id, "supporting")
        add_evidence(client, decision_id, "opposing")
        add_review(client, decision_id)
        add_rule(client, decision_id)

    active = activate(client, decision_id)
    assert active["status"] == "active"
    assert active["current_version"] == 3


def test_detached_evidence_cannot_satisfy_activation(
    client: TestClient, db_session: Session
) -> None:
    decision_id = int(create_decision(client)["id"])
    complete_decision(client, decision_id)
    db_session.execute(
        delete(decision_models.SupportingEvidence).where(
            decision_models.SupportingEvidence.decision_id == decision_id
        )
    )
    db_session.commit()
    db_session.expire_all()

    response = client.post(f"/api/v1/decisions/{decision_id}/activate")
    assert response.status_code == 409
    assert "supporting evidence" in response.json()["detail"]


def test_decimal_boundaries_are_exact_and_serialized_stably(
    client: TestClient, db_session: Session
) -> None:
    response = client.post(
        "/api/v1/decisions",
        json={
            "title": "Boundary values",
            "question": "Are exact bounds preserved?",
            "rationale": "Validate scaled persistence.",
            "probability": "0",
            "confidence": "1",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["probability"] == "0.000000"
    assert body["confidence"] == "1.000000"
    raw = db_session.execute(
        text("SELECT probability, confidence FROM decision_cases WHERE id = :decision_id"),
        {"decision_id": body["id"]},
    ).one()
    assert raw == (0, 1_000_000)


def test_all_audit_entities_reject_orm_deletion(client: TestClient, db_session: Session) -> None:
    decision_id = int(create_decision(client)["id"])
    complete_decision(client, decision_id)
    activate(client, decision_id)
    response = client.post(
        f"/api/v1/decisions/{decision_id}/close",
        json={
            "outcome": "Observed result",
            "lessons_learned": "Document every outcome.",
            "accuracy_assessment": "0.750000",
        },
    )
    assert response.status_code == 200
    decision = decision_services.get_decision(db_session, decision_id)
    identifiers: list[tuple[type[Any], int]] = [
        (decision_models.DecisionHypothesis, decision.hypotheses[0].id),
        (decision_models.SupportingEvidence, decision.supporting_evidence[0].id),
        (decision_models.OpposingEvidence, decision.opposing_evidence[0].id),
        (decision_models.CriticReview, decision.critic_reviews[0].id),
        (decision_models.InvalidationRule, decision.invalidation_rules[0].id),
        (decision_models.DecisionOutcome, decision.outcome.id),
        (decision_models.DecisionRevision, decision.revisions[0].id),
    ]
    for model_type, record_id in identifiers:
        target = db_session.get(model_type, record_id)
        assert target is not None
        db_session.delete(target)
        with pytest.raises(ValueError, match="immutable"):
            db_session.commit()
        db_session.rollback()


def test_database_constraints_reject_duplicate_versions_outcomes_and_bad_scores(
    client: TestClient, db_session: Session
) -> None:
    decision_id = int(create_decision(client)["id"])
    decision = decision_services.get_decision(db_session, decision_id)
    db_session.add(
        decision_models.DecisionRevision(
            decision_id=decision_id,
            version=1,
            event="duplicate",
            status=decision.status,
            probability=decision.probability,
            confidence=decision.confidence,
            rationale=decision.rationale,
            change_summary="Must fail.",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                "INSERT INTO decision_cases "
                "(title, question, context, rationale, status, probability, confidence, "
                "current_version, lock_version, created_at, updated_at) "
                "VALUES ('Bad', 'Bad?', '', 'Bad', 'draft', 1000001, 0, 1, 1, "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
    db_session.rollback()
    versions = decision_services.list_history(db_session, decision_id)
    assert [revision.version for revision in versions] == [1]

    db_session.add(
        decision_models.DecisionOutcome(
            decision_id=decision_id,
            outcome="First outcome",
            lessons_learned="First lesson",
            accuracy_assessment=Decimal("0.500000"),
        )
    )
    db_session.commit()
    db_session.add(
        decision_models.DecisionOutcome(
            decision_id=decision_id,
            outcome="Duplicate outcome",
            lessons_learned="Must fail",
            accuracy_assessment=Decimal("0.500000"),
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_sqlite_foreign_keys_restrict_audit_history_and_indexes_exist(
    db_session: Session,
) -> None:
    assert db_session.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
    audit_tables = (
        "decision_hypotheses",
        "supporting_evidence",
        "opposing_evidence",
        "critic_reviews",
        "invalidation_rules",
        "decision_outcomes",
        "decision_revisions",
    )
    for table in audit_tables:
        foreign_keys = db_session.execute(text(f'PRAGMA foreign_key_list("{table}")')).all()
        assert len(foreign_keys) == 1
        assert foreign_keys[0][2] == "decision_cases"
        assert foreign_keys[0][6] == "RESTRICT"
        indexes = db_session.execute(text(f'PRAGMA index_list("{table}")')).all()
        assert indexes


def test_competing_revisions_return_conflict_and_leave_no_partial_version(
    db_session: Session,
) -> None:
    decision = decision_services.create_decision(
        db_session,
        decision_schemas.DecisionCreate(
            title="Concurrent revisions",
            question="Can competing writes duplicate a version?",
            rationale="Initial rationale.",
            probability=Decimal("0.500000"),
            confidence=Decimal("0.500000"),
        ),
    )
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, expire_on_commit=False)
    stale_session = factory()
    winner_session = factory()
    verifier_session = factory()
    try:
        stale = decision_services.get_decision(stale_session, decision.id)
        assert stale.current_version == 1
        winner = decision_services.revise_decision(
            winner_session,
            decision.id,
            decision_schemas.ReviseDecision(
                probability=Decimal("0.600000"),
                confidence=Decimal("0.650000"),
                rationale="Winner rationale.",
                change_summary="Winning write.",
            ),
        )
        assert winner.current_version == 2

        with pytest.raises(decision_services.DecisionDomainError, match="conflicted"):
            decision_services.revise_decision(
                stale_session,
                decision.id,
                decision_schemas.ReviseDecision(
                    probability=Decimal("0.700000"),
                    confidence=Decimal("0.750000"),
                    rationale="Stale rationale.",
                    change_summary="Competing write.",
                ),
            )

        current = decision_services.get_decision(verifier_session, decision.id)
        history = decision_services.list_history(verifier_session, decision.id)
        assert current.current_version == 2
        assert current.probability == Decimal("0.600000")
        assert current.rationale == "Winner rationale."
        assert [revision.version for revision in history] == [1, 2]
        assert history[-1].probability == current.probability
        assert history[-1].status == current.status
    finally:
        stale_session.close()
        winner_session.close()
        verifier_session.close()


def test_concurrent_terminal_transition_rejects_stale_child_mutation(
    client: TestClient, db_session: Session
) -> None:
    decision_id = int(create_decision(client)["id"])
    complete_decision(client, decision_id)
    activate(client, decision_id)
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, expire_on_commit=False)
    stale_session = factory()
    winner_session = factory()
    verifier_session = factory()
    try:
        stale = decision_services.get_decision(stale_session, decision_id)
        assert stale.status == decision_models.DecisionStatus.active
        decision_services.close_decision(
            winner_session,
            decision_id,
            decision_schemas.CloseDecision(
                outcome="Terminal outcome.",
                lessons_learned="Concurrency must preserve terminal state.",
                accuracy_assessment=Decimal("0.500000"),
            ),
        )
        with pytest.raises(decision_services.DecisionDomainError, match="conflicted"):
            decision_services.add_hypothesis(
                stale_session,
                decision_id,
                decision_schemas.HypothesisCreate(statement="Stale child"),
            )

        current = decision_services.get_decision(verifier_session, decision_id)
        assert current.status == decision_models.DecisionStatus.closed
        assert all(item.statement != "Stale child" for item in current.hypotheses)
    finally:
        stale_session.close()
        winner_session.close()
        verifier_session.close()
