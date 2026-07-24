from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    event,
    func,
    inspect,
)
from sqlalchemy.orm import Mapped, mapped_column, object_session, relationship

from macrovision.database import Base


class RiskTolerance(StrEnum):
    conservative = "conservative"
    moderate = "moderate"
    growth = "growth"
    aggressive = "aggressive"


class JournalStatus(StrEnum):
    draft = "draft"
    active = "active"
    invalidated = "invalidated"
    closed = "closed"


class InvestorProfile(Base):
    __tablename__ = "investor_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    base_currency: Mapped[str] = mapped_column(String(3), default="USD")
    investment_horizon_years: Mapped[int]
    liquidity_need: Mapped[float] = mapped_column(Float, default=0.0)
    objectives: Mapped[str] = mapped_column(Text)
    constraints: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    risk_profile: Mapped["RiskProfile"] = relationship(
        back_populates="investor", cascade="all, delete-orphan", uselist=False
    )
    journals: Mapped[list["ResearchJournal"]] = relationship(back_populates="investor")

    __table_args__ = (
        CheckConstraint("investment_horizon_years > 0", name="ck_profile_horizon_positive"),
        CheckConstraint(
            "liquidity_need >= 0 AND liquidity_need <= 1", name="ck_profile_liquidity_range"
        ),
    )


class RiskProfile(Base):
    __tablename__ = "risk_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    investor_id: Mapped[int] = mapped_column(
        ForeignKey("investor_profiles.id", ondelete="CASCADE"), unique=True
    )
    tolerance: Mapped[RiskTolerance] = mapped_column(Enum(RiskTolerance))
    max_drawdown: Mapped[float] = mapped_column(Float)
    loss_capacity: Mapped[float] = mapped_column(Float)
    notes: Mapped[str] = mapped_column(Text, default="")

    investor: Mapped[InvestorProfile] = relationship(back_populates="risk_profile")
    risk_budget: Mapped["RiskBudget"] = relationship(
        back_populates="risk_profile", cascade="all, delete-orphan", uselist=False
    )

    __table_args__ = (
        CheckConstraint("max_drawdown >= 0 AND max_drawdown <= 1", name="ck_risk_drawdown_range"),
        CheckConstraint("loss_capacity >= 0 AND loss_capacity <= 1", name="ck_risk_capacity_range"),
    )


class RiskBudget(Base):
    __tablename__ = "risk_budgets"

    id: Mapped[int] = mapped_column(primary_key=True)
    risk_profile_id: Mapped[int] = mapped_column(
        ForeignKey("risk_profiles.id", ondelete="CASCADE"), unique=True
    )
    total_risk_budget: Mapped[float] = mapped_column(Float)
    per_decision_limit: Mapped[float] = mapped_column(Float)
    minimum_cash_allocation: Mapped[float] = mapped_column(Float, default=0.0)

    risk_profile: Mapped[RiskProfile] = relationship(back_populates="risk_budget")

    __table_args__ = (
        CheckConstraint(
            "total_risk_budget >= 0 AND total_risk_budget <= 1", name="ck_budget_total_range"
        ),
        CheckConstraint(
            "per_decision_limit >= 0 AND per_decision_limit <= total_risk_budget",
            name="ck_budget_decision_limit",
        ),
        CheckConstraint(
            "minimum_cash_allocation >= 0 AND minimum_cash_allocation <= 1",
            name="ck_budget_cash_range",
        ),
    )


class ResearchJournal(Base):
    __tablename__ = "research_journals"

    id: Mapped[int] = mapped_column(primary_key=True)
    investor_id: Mapped[int] = mapped_column(ForeignKey("investor_profiles.id"))
    asset: Mapped[str] = mapped_column(String(120), index=True)
    hypothesis: Mapped[str] = mapped_column(Text)
    evidence_for: Mapped[str] = mapped_column(Text)
    evidence_against: Mapped[str] = mapped_column(Text)
    critic_review: Mapped[str] = mapped_column(Text)
    probability: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    invalidation_conditions: Mapped[str] = mapped_column(Text)
    decision: Mapped[str] = mapped_column(Text, default="No action")
    outcome: Mapped[str | None] = mapped_column(Text, nullable=True)
    lessons: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[JournalStatus] = mapped_column(Enum(JournalStatus), default=JournalStatus.draft)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    lock_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    investor: Mapped[InvestorProfile] = relationship(back_populates="journals")

    __table_args__ = (
        CheckConstraint(
            "probability >= 0 AND probability <= 1", name="ck_journal_probability_range"
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_journal_confidence_range"),
        CheckConstraint("lock_version > 0", name="ck_journal_lock_version_positive"),
    )
    __mapper_args__ = {  # noqa: RUF012
        "version_id_col": lock_version,
        "version_id_generator": False,
    }


def _prevent_closed_journal_mutation(
    _mapper: object, _connection: object, target: ResearchJournal
) -> None:
    state = inspect(target)
    status_history = state.attrs["status"].history
    closing_now = (
        status_history.deleted
        and status_history.deleted[0] != JournalStatus.closed
        and status_history.added == [JournalStatus.closed]
    )
    session = object_session(target)
    if (
        target.status == JournalStatus.closed
        and not closing_now
        and session is not None
        and session.is_modified(target, include_collections=False)
    ):
        raise ValueError("Closed research journals are immutable")


event.listen(ResearchJournal, "before_update", _prevent_closed_journal_mutation)
