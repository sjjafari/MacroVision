from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from macrovision import models, schemas
from macrovision.integrity import commit_or_conflict


class NotFoundError(Exception):
    pass


class JournalConflictError(Exception):
    pass


def create_investor_profile(
    session: Session, payload: schemas.InvestorProfileCreate
) -> models.InvestorProfile:
    risk = payload.risk_profile
    budget = risk.risk_budget
    profile = models.InvestorProfile(
        name=payload.name,
        base_currency=payload.base_currency.upper(),
        investment_horizon_years=payload.investment_horizon_years,
        liquidity_need=payload.liquidity_need,
        objectives=payload.objectives,
        constraints=payload.constraints,
        risk_profile=models.RiskProfile(
            tolerance=risk.tolerance,
            max_drawdown=risk.max_drawdown,
            loss_capacity=risk.loss_capacity,
            notes=risk.notes,
            risk_budget=models.RiskBudget(**budget.model_dump()),
        ),
    )
    session.add(profile)
    commit_or_conflict(session, "Investor profile creation conflicted")
    return get_investor_profile(session, profile.id)


def get_investor_profile(session: Session, profile_id: int) -> models.InvestorProfile:
    statement = (
        select(models.InvestorProfile)
        .options(
            selectinload(models.InvestorProfile.risk_profile).selectinload(
                models.RiskProfile.risk_budget
            )
        )
        .where(models.InvestorProfile.id == profile_id)
    )
    profile = session.scalar(statement)
    if profile is None:
        raise NotFoundError("Investor profile not found")
    return profile


def create_journal(session: Session, payload: schemas.JournalCreate) -> models.ResearchJournal:
    get_investor_profile(session, payload.investor_id)
    journal = models.ResearchJournal(
        **payload.model_dump(),
        status=models.JournalStatus.draft,
        lock_version=1,
    )
    session.add(journal)
    commit_or_conflict(session, "Research journal creation conflicted")
    session.refresh(journal)
    return journal


def get_journal(session: Session, journal_id: int) -> models.ResearchJournal:
    journal = session.get(models.ResearchJournal, journal_id)
    if journal is None:
        raise NotFoundError("Research journal not found")
    return journal


def close_journal(
    session: Session, journal_id: int, payload: schemas.JournalClose
) -> models.ResearchJournal:
    journal = get_journal(session, journal_id)
    if (
        journal.status in {models.JournalStatus.closed, models.JournalStatus.invalidated}
        or journal.outcome is not None
        or journal.lessons is not None
        or journal.closed_at is not None
    ):
        raise JournalConflictError("Research journal is already terminal or closed")
    journal.outcome = payload.outcome
    journal.lessons = payload.lessons
    journal.status = models.JournalStatus.closed
    journal.closed_at = datetime.now(UTC).replace(tzinfo=None)
    journal.lock_version += 1
    commit_or_conflict(
        session,
        "Research journal changed concurrently; reload and retry",
    )
    session.refresh(journal)
    return journal
