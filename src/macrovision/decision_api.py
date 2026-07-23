from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from macrovision import decision_schemas as schemas
from macrovision import decision_services as services
from macrovision.database import get_db

router = APIRouter(prefix="/decisions", tags=["decisions"])
DbSession = Annotated[Session, Depends(get_db)]


def _http_error(exc: Exception) -> HTTPException:
    status_code = 404 if isinstance(exc, services.DecisionNotFoundError) else 409
    return HTTPException(status_code=status_code, detail=str(exc))


@router.post("", response_model=schemas.DecisionCaseRead, status_code=status.HTTP_201_CREATED)
def create_decision(
    payload: schemas.DecisionCreate, session: DbSession
) -> schemas.DecisionCaseRead:
    return services.decision_to_read(services.create_decision(session, payload))


@router.get("", response_model=list[schemas.DecisionCaseRead])
def list_decisions(session: DbSession) -> list[schemas.DecisionCaseRead]:
    return [services.decision_to_read(decision) for decision in services.list_decisions(session)]


@router.get("/{decision_id}", response_model=schemas.DecisionCaseRead)
def get_decision(decision_id: int, session: DbSession) -> schemas.DecisionCaseRead:
    try:
        return services.decision_to_read(services.get_decision(session, decision_id))
    except services.DecisionNotFoundError as exc:
        raise _http_error(exc) from exc


@router.post(
    "/{decision_id}/hypotheses",
    response_model=schemas.HypothesisRead,
    status_code=status.HTTP_201_CREATED,
)
def add_hypothesis(
    decision_id: int, payload: schemas.HypothesisCreate, session: DbSession
) -> schemas.HypothesisRead:
    try:
        return schemas.HypothesisRead.model_validate(
            services.add_hypothesis(session, decision_id, payload)
        )
    except (services.DecisionNotFoundError, services.DecisionDomainError) as exc:
        raise _http_error(exc) from exc


@router.post(
    "/{decision_id}/evidence",
    response_model=schemas.EvidenceRead,
    status_code=status.HTTP_201_CREATED,
)
def add_evidence(
    decision_id: int, payload: schemas.EvidenceCreate, session: DbSession
) -> schemas.EvidenceRead:
    try:
        return services.evidence_to_read(services.add_evidence(session, decision_id, payload))
    except (services.DecisionNotFoundError, services.DecisionDomainError) as exc:
        raise _http_error(exc) from exc


@router.post(
    "/{decision_id}/critic-reviews",
    response_model=schemas.CriticReviewRead,
    status_code=status.HTTP_201_CREATED,
)
def add_critic_review(
    decision_id: int, payload: schemas.CriticReviewCreate, session: DbSession
) -> schemas.CriticReviewRead:
    try:
        return schemas.CriticReviewRead.model_validate(
            services.add_critic_review(session, decision_id, payload)
        )
    except (services.DecisionNotFoundError, services.DecisionDomainError) as exc:
        raise _http_error(exc) from exc


@router.post(
    "/{decision_id}/invalidation-rules",
    response_model=schemas.InvalidationRuleRead,
    status_code=status.HTTP_201_CREATED,
)
def add_invalidation_rule(
    decision_id: int,
    payload: schemas.InvalidationRuleCreate,
    session: DbSession,
) -> schemas.InvalidationRuleRead:
    try:
        return schemas.InvalidationRuleRead.model_validate(
            services.add_invalidation_rule(session, decision_id, payload)
        )
    except (services.DecisionNotFoundError, services.DecisionDomainError) as exc:
        raise _http_error(exc) from exc


@router.post("/{decision_id}/activate", response_model=schemas.DecisionCaseRead)
def activate_decision(decision_id: int, session: DbSession) -> schemas.DecisionCaseRead:
    try:
        return services.decision_to_read(services.activate_decision(session, decision_id))
    except (services.DecisionNotFoundError, services.DecisionDomainError) as exc:
        raise _http_error(exc) from exc


@router.post("/{decision_id}/invalidate", response_model=schemas.DecisionCaseRead)
def invalidate_decision(
    decision_id: int, payload: schemas.InvalidateDecision, session: DbSession
) -> schemas.DecisionCaseRead:
    try:
        return services.decision_to_read(
            services.invalidate_decision(session, decision_id, payload)
        )
    except (services.DecisionNotFoundError, services.DecisionDomainError) as exc:
        raise _http_error(exc) from exc


@router.post("/{decision_id}/revise", response_model=schemas.DecisionCaseRead)
def revise_decision(
    decision_id: int, payload: schemas.ReviseDecision, session: DbSession
) -> schemas.DecisionCaseRead:
    try:
        return services.decision_to_read(services.revise_decision(session, decision_id, payload))
    except (services.DecisionNotFoundError, services.DecisionDomainError) as exc:
        raise _http_error(exc) from exc


@router.post("/{decision_id}/close", response_model=schemas.DecisionCaseRead)
def close_decision(
    decision_id: int, payload: schemas.CloseDecision, session: DbSession
) -> schemas.DecisionCaseRead:
    try:
        return services.decision_to_read(services.close_decision(session, decision_id, payload))
    except (services.DecisionNotFoundError, services.DecisionDomainError) as exc:
        raise _http_error(exc) from exc


@router.get("/{decision_id}/history", response_model=list[schemas.DecisionRevisionRead])
def list_history(decision_id: int, session: DbSession) -> list[schemas.DecisionRevisionRead]:
    try:
        return [
            schemas.DecisionRevisionRead.model_validate(revision)
            for revision in services.list_history(session, decision_id)
        ]
    except services.DecisionNotFoundError as exc:
        raise _http_error(exc) from exc
