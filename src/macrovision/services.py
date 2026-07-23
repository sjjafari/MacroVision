from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from macrovision import models, schemas


class NotFoundError(Exception):
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
    session.commit()
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
    journal = models.ResearchJournal(**payload.model_dump())
    session.add(journal)
    session.commit()
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
    journal.outcome = payload.outcome
    journal.lessons = payload.lessons
    journal.status = models.JournalStatus.closed
    session.commit()
    session.refresh(journal)
    return journal
