from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    Date,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from macrovision.database import Base
from macrovision.persistence_types import ScaledDecimal, UTCDateTime

SCORE_SCALE = 6
ScoreValue = ScaledDecimal(SCORE_SCALE)
SCORE_MAX_STORED = 1_000_000


class DecisionStatus(StrEnum):
    draft = "draft"
    under_review = "under_review"
    active = "active"
    invalidated = "invalidated"
    closed = "closed"


class EvidenceSourceType(StrEnum):
    research_paper = "research_paper"
    financial_statement = "financial_statement"
    market_data = "market_data"
    news = "news"
    expert_opinion = "expert_opinion"
    internal_analysis = "internal_analysis"
    other = "other"


class EvidenceSide(StrEnum):
    supporting = "supporting"
    opposing = "opposing"


class RevisionEvent(StrEnum):
    created = "created"
    review_started = "review_started"
    revised = "revised"
    activated = "activated"
    invalidated = "invalidated"
    closed = "closed"


class DecisionCase(Base):
    __tablename__ = "decision_cases"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(180), index=True)
    question: Mapped[str] = mapped_column(Text)
    context: Mapped[str] = mapped_column(Text, default="")
    rationale: Mapped[str] = mapped_column(Text)
    probability: Mapped[Decimal] = mapped_column(ScoreValue)
    confidence: Mapped[Decimal] = mapped_column(ScoreValue)
    status: Mapped[DecisionStatus] = mapped_column(
        Enum(DecisionStatus), default=DecisionStatus.draft
    )
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    lock_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now()
    )

    hypotheses: Mapped[list["DecisionHypothesis"]] = relationship(
        back_populates="decision", cascade="save-update, merge", passive_deletes="all"
    )
    supporting_evidence: Mapped[list["SupportingEvidence"]] = relationship(
        back_populates="decision", cascade="save-update, merge", passive_deletes="all"
    )
    opposing_evidence: Mapped[list["OpposingEvidence"]] = relationship(
        back_populates="decision", cascade="save-update, merge", passive_deletes="all"
    )
    critic_reviews: Mapped[list["CriticReview"]] = relationship(
        back_populates="decision", cascade="save-update, merge", passive_deletes="all"
    )
    invalidation_rules: Mapped[list["InvalidationRule"]] = relationship(
        back_populates="decision", cascade="save-update, merge", passive_deletes="all"
    )
    outcome: Mapped["DecisionOutcome | None"] = relationship(
        back_populates="decision",
        cascade="save-update, merge",
        passive_deletes="all",
        uselist=False,
    )
    revisions: Mapped[list["DecisionRevision"]] = relationship(
        back_populates="decision", cascade="save-update, merge", passive_deletes="all"
    )

    __table_args__ = (
        CheckConstraint(
            f"probability >= 0 AND probability <= {SCORE_MAX_STORED}",
            name="ck_decision_probability_range",
        ),
        CheckConstraint(
            f"confidence >= 0 AND confidence <= {SCORE_MAX_STORED}",
            name="ck_decision_confidence_range",
        ),
        CheckConstraint("current_version > 0", name="ck_decision_version_positive"),
        CheckConstraint("lock_version > 0", name="ck_decision_lock_version_positive"),
        Index("ix_decision_status_updated", "status", "updated_at"),
    )
    __mapper_args__ = {  # noqa: RUF012
        "version_id_col": lock_version,
        "version_id_generator": False,
    }


class DecisionHypothesis(Base):
    __tablename__ = "decision_hypotheses"

    id: Mapped[int] = mapped_column(primary_key=True)
    decision_id: Mapped[int] = mapped_column(ForeignKey("decision_cases.id", ondelete="RESTRICT"))
    statement: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())
    decision: Mapped[DecisionCase] = relationship(back_populates="hypotheses")
    __table_args__ = (Index("ix_hypothesis_decision_created", "decision_id", "created_at"),)


class SupportingEvidence(Base):
    __tablename__ = "supporting_evidence"

    id: Mapped[int] = mapped_column(primary_key=True)
    decision_id: Mapped[int] = mapped_column(ForeignKey("decision_cases.id", ondelete="RESTRICT"))
    source_title: Mapped[str] = mapped_column(String(240))
    source_type: Mapped[EvidenceSourceType] = mapped_column(Enum(EvidenceSourceType))
    publication_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    reliability_score: Mapped[Decimal] = mapped_column(ScoreValue)
    relevance_score: Mapped[Decimal] = mapped_column(ScoreValue)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())
    decision: Mapped[DecisionCase] = relationship(back_populates="supporting_evidence")
    __table_args__ = (
        CheckConstraint(
            f"reliability_score >= 0 AND reliability_score <= {SCORE_MAX_STORED}",
            name="ck_support_reliability_range",
        ),
        CheckConstraint(
            f"relevance_score >= 0 AND relevance_score <= {SCORE_MAX_STORED}",
            name="ck_support_relevance_range",
        ),
        Index("ix_support_decision_created", "decision_id", "created_at"),
    )


class OpposingEvidence(Base):
    __tablename__ = "opposing_evidence"

    id: Mapped[int] = mapped_column(primary_key=True)
    decision_id: Mapped[int] = mapped_column(ForeignKey("decision_cases.id", ondelete="RESTRICT"))
    source_title: Mapped[str] = mapped_column(String(240))
    source_type: Mapped[EvidenceSourceType] = mapped_column(Enum(EvidenceSourceType))
    publication_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    reliability_score: Mapped[Decimal] = mapped_column(ScoreValue)
    relevance_score: Mapped[Decimal] = mapped_column(ScoreValue)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())
    decision: Mapped[DecisionCase] = relationship(back_populates="opposing_evidence")
    __table_args__ = (
        CheckConstraint(
            f"reliability_score >= 0 AND reliability_score <= {SCORE_MAX_STORED}",
            name="ck_oppose_reliability_range",
        ),
        CheckConstraint(
            f"relevance_score >= 0 AND relevance_score <= {SCORE_MAX_STORED}",
            name="ck_oppose_relevance_range",
        ),
        Index("ix_oppose_decision_created", "decision_id", "created_at"),
    )


class CriticReview(Base):
    __tablename__ = "critic_reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    decision_id: Mapped[int] = mapped_column(ForeignKey("decision_cases.id", ondelete="RESTRICT"))
    reviewer: Mapped[str] = mapped_column(String(160))
    analysis: Mapped[str] = mapped_column(Text)
    key_risks: Mapped[str] = mapped_column(Text)
    recommendation: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())
    decision: Mapped[DecisionCase] = relationship(back_populates="critic_reviews")
    __table_args__ = (Index("ix_critic_decision_created", "decision_id", "created_at"),)


class InvalidationRule(Base):
    __tablename__ = "invalidation_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    decision_id: Mapped[int] = mapped_column(ForeignKey("decision_cases.id", ondelete="RESTRICT"))
    condition: Mapped[str] = mapped_column(Text)
    observation_source: Mapped[str] = mapped_column(String(300))
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())
    decision: Mapped[DecisionCase] = relationship(back_populates="invalidation_rules")
    __table_args__ = (Index("ix_rule_decision_created", "decision_id", "created_at"),)


class DecisionOutcome(Base):
    __tablename__ = "decision_outcomes"

    id: Mapped[int] = mapped_column(primary_key=True)
    decision_id: Mapped[int] = mapped_column(
        ForeignKey("decision_cases.id", ondelete="RESTRICT"), unique=True
    )
    outcome: Mapped[str] = mapped_column(Text)
    lessons_learned: Mapped[str] = mapped_column(Text)
    accuracy_assessment: Mapped[Decimal] = mapped_column(ScoreValue)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())
    decision: Mapped[DecisionCase] = relationship(back_populates="outcome")
    __table_args__ = (
        CheckConstraint(
            f"accuracy_assessment >= 0 AND accuracy_assessment <= {SCORE_MAX_STORED}",
            name="ck_outcome_accuracy_range",
        ),
    )


class DecisionRevision(Base):
    __tablename__ = "decision_revisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    decision_id: Mapped[int] = mapped_column(ForeignKey("decision_cases.id", ondelete="RESTRICT"))
    version: Mapped[int]
    event: Mapped[RevisionEvent] = mapped_column(Enum(RevisionEvent))
    status: Mapped[DecisionStatus] = mapped_column(Enum(DecisionStatus))
    probability: Mapped[Decimal] = mapped_column(ScoreValue)
    confidence: Mapped[Decimal] = mapped_column(ScoreValue)
    rationale: Mapped[str] = mapped_column(Text)
    change_summary: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())
    decision: Mapped[DecisionCase] = relationship(back_populates="revisions")
    __table_args__ = (
        UniqueConstraint("decision_id", "version", name="uq_revision_decision_version"),
        CheckConstraint("version > 0", name="ck_revision_version_positive"),
        CheckConstraint(
            f"probability >= 0 AND probability <= {SCORE_MAX_STORED}",
            name="ck_revision_probability_range",
        ),
        CheckConstraint(
            f"confidence >= 0 AND confidence <= {SCORE_MAX_STORED}",
            name="ck_revision_confidence_range",
        ),
    )


AuditRecord = (
    DecisionHypothesis
    | SupportingEvidence
    | OpposingEvidence
    | CriticReview
    | InvalidationRule
    | DecisionOutcome
    | DecisionRevision
)


def _prevent_audit_mutation(_mapper: object, _connection: object, _target: AuditRecord) -> None:
    raise ValueError("Decision audit records are immutable")


for audit_model in (
    DecisionHypothesis,
    SupportingEvidence,
    OpposingEvidence,
    CriticReview,
    InvalidationRule,
    DecisionOutcome,
    DecisionRevision,
):
    event.listen(audit_model, "before_update", _prevent_audit_mutation)
    event.listen(audit_model, "before_delete", _prevent_audit_mutation)
