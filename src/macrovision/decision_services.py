from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.orm.exc import StaleDataError

from macrovision import decision_models as models
from macrovision import decision_schemas as schemas


class DecisionNotFoundError(Exception):
    pass


class DecisionDomainError(Exception):
    pass


def _commit_decision_change(session: Session) -> None:
    try:
        session.commit()
    except (IntegrityError, StaleDataError) as exc:
        session.rollback()
        raise DecisionDomainError(
            "Decision update conflicted with another write; reload and retry"
        ) from exc


def _decision_statement() -> Select[tuple[models.DecisionCase]]:
    return select(models.DecisionCase).options(
        selectinload(models.DecisionCase.hypotheses),
        selectinload(models.DecisionCase.supporting_evidence),
        selectinload(models.DecisionCase.opposing_evidence),
        selectinload(models.DecisionCase.critic_reviews),
        selectinload(models.DecisionCase.invalidation_rules),
        selectinload(models.DecisionCase.outcome),
        selectinload(models.DecisionCase.revisions),
    )


def get_decision(session: Session, decision_id: int) -> models.DecisionCase:
    decision = session.scalar(_decision_statement().where(models.DecisionCase.id == decision_id))
    if decision is None:
        raise DecisionNotFoundError("Decision case not found")
    return decision


def list_decisions(session: Session) -> list[models.DecisionCase]:
    return list(session.scalars(_decision_statement().order_by(models.DecisionCase.id)).unique())


def _append_revision(
    session: Session,
    decision: models.DecisionCase,
    event: models.RevisionEvent,
    change_summary: str,
    *,
    initial: bool = False,
) -> models.DecisionRevision:
    if not initial:
        decision.current_version += 1
    revision = models.DecisionRevision(
        decision=decision,
        version=decision.current_version,
        event=event,
        status=decision.status,
        probability=decision.probability,
        confidence=decision.confidence,
        rationale=decision.rationale,
        change_summary=change_summary,
    )
    session.add(revision)
    return revision


def create_decision(session: Session, payload: schemas.DecisionCreate) -> models.DecisionCase:
    decision = models.DecisionCase(
        title=payload.title,
        question=payload.question,
        context=payload.context,
        rationale=payload.rationale,
        probability=payload.probability,
        confidence=payload.confidence,
        status=models.DecisionStatus.draft,
        current_version=1,
    )
    session.add(decision)
    _append_revision(
        session,
        decision,
        models.RevisionEvent.created,
        "Initial decision case created",
        initial=True,
    )
    session.commit()
    return get_decision(session, decision.id)


def _ensure_editable(decision: models.DecisionCase) -> None:
    if decision.status in {
        models.DecisionStatus.invalidated,
        models.DecisionStatus.closed,
    }:
        raise DecisionDomainError(f"{decision.status.value} decisions cannot be edited")


def _mark_mutated(decision: models.DecisionCase) -> None:
    decision.lock_version += 1


def add_hypothesis(
    session: Session, decision_id: int, payload: schemas.HypothesisCreate
) -> models.DecisionHypothesis:
    decision = get_decision(session, decision_id)
    _ensure_editable(decision)
    hypothesis = models.DecisionHypothesis(
        decision=decision, statement=payload.statement, rationale=payload.rationale
    )
    _mark_mutated(decision)
    session.add(hypothesis)
    _commit_decision_change(session)
    session.refresh(hypothesis)
    return hypothesis


def add_evidence(
    session: Session, decision_id: int, payload: schemas.EvidenceCreate
) -> models.SupportingEvidence | models.OpposingEvidence:
    decision = get_decision(session, decision_id)
    _ensure_editable(decision)
    values = {
        "decision": decision,
        "source_title": payload.source_title,
        "source_type": payload.source_type,
        "publication_date": payload.publication_date,
        "reference": payload.reference,
        "reliability_score": payload.reliability_score,
        "relevance_score": payload.relevance_score,
        "notes": payload.notes,
    }
    if payload.side == models.EvidenceSide.supporting:
        evidence: models.SupportingEvidence | models.OpposingEvidence = models.SupportingEvidence(
            **values
        )
    else:
        evidence = models.OpposingEvidence(**values)
    _mark_mutated(decision)
    session.add(evidence)
    _commit_decision_change(session)
    session.refresh(evidence)
    return evidence


def add_critic_review(
    session: Session, decision_id: int, payload: schemas.CriticReviewCreate
) -> models.CriticReview:
    decision = get_decision(session, decision_id)
    _ensure_editable(decision)
    review = models.CriticReview(decision=decision, **payload.model_dump())
    _mark_mutated(decision)
    session.add(review)
    if decision.status == models.DecisionStatus.draft:
        decision.status = models.DecisionStatus.under_review
        _append_revision(
            session,
            decision,
            models.RevisionEvent.review_started,
            "Independent critic review started",
        )
    _commit_decision_change(session)
    session.refresh(review)
    return review


def add_invalidation_rule(
    session: Session,
    decision_id: int,
    payload: schemas.InvalidationRuleCreate,
) -> models.InvalidationRule:
    decision = get_decision(session, decision_id)
    _ensure_editable(decision)
    rule = models.InvalidationRule(decision=decision, **payload.model_dump())
    _mark_mutated(decision)
    session.add(rule)
    _commit_decision_change(session)
    session.refresh(rule)
    return rule


def _activation_gaps(decision: models.DecisionCase) -> list[str]:
    gaps: list[str] = []
    if not decision.hypotheses:
        gaps.append("hypothesis")
    if not decision.supporting_evidence:
        gaps.append("supporting evidence")
    if not decision.opposing_evidence:
        gaps.append("opposing evidence")
    if not decision.critic_reviews:
        gaps.append("critic review")
    if not decision.invalidation_rules:
        gaps.append("invalidation rule")
    return gaps


def activate_decision(session: Session, decision_id: int) -> models.DecisionCase:
    decision = get_decision(session, decision_id)
    _ensure_editable(decision)
    gaps = _activation_gaps(decision)
    if gaps:
        raise DecisionDomainError("Decision cannot become active; missing: " + ", ".join(gaps))
    if decision.status == models.DecisionStatus.active:
        raise DecisionDomainError("Decision is already active")
    if decision.status != models.DecisionStatus.under_review:
        raise DecisionDomainError("Only under_review decisions can become active")
    decision.status = models.DecisionStatus.active
    _mark_mutated(decision)
    _append_revision(session, decision, models.RevisionEvent.activated, "Decision activated")
    _commit_decision_change(session)
    return get_decision(session, decision_id)


def invalidate_decision(
    session: Session, decision_id: int, payload: schemas.InvalidateDecision
) -> models.DecisionCase:
    decision = get_decision(session, decision_id)
    if decision.status != models.DecisionStatus.active:
        raise DecisionDomainError("Only active decisions can be invalidated")
    if payload.rule_id is not None and not any(
        rule.id == payload.rule_id for rule in decision.invalidation_rules
    ):
        raise DecisionNotFoundError("Invalidation rule not found")
    decision.status = models.DecisionStatus.invalidated
    _mark_mutated(decision)
    suffix = f" (rule {payload.rule_id})" if payload.rule_id else ""
    _append_revision(
        session,
        decision,
        models.RevisionEvent.invalidated,
        f"{payload.reason}{suffix}",
    )
    _commit_decision_change(session)
    return get_decision(session, decision_id)


def revise_decision(
    session: Session, decision_id: int, payload: schemas.ReviseDecision
) -> models.DecisionCase:
    decision = get_decision(session, decision_id)
    _ensure_editable(decision)
    decision.probability = payload.probability
    decision.confidence = payload.confidence
    decision.rationale = payload.rationale
    if decision.status != models.DecisionStatus.draft:
        decision.status = models.DecisionStatus.under_review
    _mark_mutated(decision)
    _append_revision(
        session,
        decision,
        models.RevisionEvent.revised,
        payload.change_summary,
    )
    _commit_decision_change(session)
    return get_decision(session, decision_id)


def close_decision(
    session: Session, decision_id: int, payload: schemas.CloseDecision
) -> models.DecisionCase:
    decision = get_decision(session, decision_id)
    if decision.status != models.DecisionStatus.active:
        raise DecisionDomainError("Only active decisions can be closed")
    if decision.outcome is not None:
        raise DecisionDomainError("Decision already has an outcome")
    outcome = models.DecisionOutcome(decision=decision, **payload.model_dump())
    session.add(outcome)
    decision.status = models.DecisionStatus.closed
    _mark_mutated(decision)
    _append_revision(session, decision, models.RevisionEvent.closed, "Decision closed with outcome")
    _commit_decision_change(session)
    return get_decision(session, decision_id)


def list_history(session: Session, decision_id: int) -> list[models.DecisionRevision]:
    get_decision(session, decision_id)
    statement = (
        select(models.DecisionRevision)
        .where(models.DecisionRevision.decision_id == decision_id)
        .order_by(models.DecisionRevision.version)
    )
    return list(session.scalars(statement))


def evidence_to_read(
    evidence: models.SupportingEvidence | models.OpposingEvidence,
) -> schemas.EvidenceRead:
    side = (
        models.EvidenceSide.supporting
        if isinstance(evidence, models.SupportingEvidence)
        else models.EvidenceSide.opposing
    )
    return schemas.EvidenceRead(
        id=evidence.id,
        decision_id=evidence.decision_id,
        side=side,
        source_title=evidence.source_title,
        source_type=evidence.source_type,
        publication_date=evidence.publication_date,
        reference=evidence.reference,
        reliability_score=evidence.reliability_score,
        relevance_score=evidence.relevance_score,
        notes=evidence.notes,
        created_at=evidence.created_at,
    )


def decision_to_read(decision: models.DecisionCase) -> schemas.DecisionCaseRead:
    return schemas.DecisionCaseRead(
        id=decision.id,
        title=decision.title,
        question=decision.question,
        context=decision.context,
        rationale=decision.rationale,
        probability=decision.probability,
        confidence=decision.confidence,
        status=decision.status,
        current_version=decision.current_version,
        created_at=decision.created_at,
        updated_at=decision.updated_at,
        hypotheses=[
            schemas.HypothesisRead.model_validate(item)
            for item in sorted(decision.hypotheses, key=lambda value: value.id)
        ],
        supporting_evidence=[
            evidence_to_read(item)
            for item in sorted(decision.supporting_evidence, key=lambda value: value.id)
        ],
        opposing_evidence=[
            evidence_to_read(item)
            for item in sorted(decision.opposing_evidence, key=lambda value: value.id)
        ],
        critic_reviews=[
            schemas.CriticReviewRead.model_validate(item)
            for item in sorted(decision.critic_reviews, key=lambda value: value.id)
        ],
        invalidation_rules=[
            schemas.InvalidationRuleRead.model_validate(item)
            for item in sorted(decision.invalidation_rules, key=lambda value: value.id)
        ],
        outcome=(
            schemas.DecisionOutcomeRead.model_validate(decision.outcome)
            if decision.outcome
            else None
        ),
    )
