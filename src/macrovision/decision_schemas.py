from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

from macrovision.decision_models import (
    DecisionStatus,
    EvidenceSide,
    EvidenceSourceType,
    RevisionEvent,
)

Score = Annotated[
    Decimal,
    PlainSerializer(lambda value: format(value, ".6f"), return_type=str, when_used="json"),
]


class DecisionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    question: str = Field(min_length=1)
    context: str = ""
    rationale: str = Field(min_length=1)
    probability: Score = Field(ge=0, le=1, decimal_places=6)
    confidence: Score = Field(ge=0, le=1, decimal_places=6)


class HypothesisCreate(BaseModel):
    statement: str = Field(min_length=1)
    rationale: str = ""


class EvidenceCreate(BaseModel):
    side: EvidenceSide
    source_title: str = Field(min_length=1, max_length=240)
    source_type: EvidenceSourceType
    publication_date: date | None = None
    reference: str | None = Field(default=None, max_length=500)
    reliability_score: Score = Field(ge=0, le=1, decimal_places=6)
    relevance_score: Score = Field(ge=0, le=1, decimal_places=6)
    notes: str = ""


class CriticReviewCreate(BaseModel):
    reviewer: str = Field(min_length=1, max_length=160)
    analysis: str = Field(min_length=1)
    key_risks: str = Field(min_length=1)
    recommendation: str = Field(min_length=1)


class InvalidationRuleCreate(BaseModel):
    condition: str = Field(min_length=1)
    observation_source: str = Field(min_length=1, max_length=300)
    notes: str = ""


class InvalidateDecision(BaseModel):
    reason: str = Field(min_length=1)
    rule_id: int | None = Field(default=None, gt=0)


class ReviseDecision(BaseModel):
    probability: Score = Field(ge=0, le=1, decimal_places=6)
    confidence: Score = Field(ge=0, le=1, decimal_places=6)
    rationale: str = Field(min_length=1)
    change_summary: str = Field(min_length=1)


class CloseDecision(BaseModel):
    outcome: str = Field(min_length=1)
    lessons_learned: str = Field(min_length=1)
    accuracy_assessment: Score = Field(ge=0, le=1, decimal_places=6)


class HypothesisRead(HypothesisCreate):
    id: int
    decision_id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class EvidenceRead(BaseModel):
    id: int
    decision_id: int
    side: EvidenceSide
    source_title: str
    source_type: EvidenceSourceType
    publication_date: date | None
    reference: str | None
    reliability_score: Score
    relevance_score: Score
    notes: str
    created_at: datetime


class CriticReviewRead(CriticReviewCreate):
    id: int
    decision_id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class InvalidationRuleRead(InvalidationRuleCreate):
    id: int
    decision_id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class DecisionOutcomeRead(CloseDecision):
    id: int
    decision_id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class DecisionRevisionRead(BaseModel):
    id: int
    decision_id: int
    version: int
    event: RevisionEvent
    status: DecisionStatus
    probability: Score
    confidence: Score
    rationale: str
    change_summary: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class DecisionCaseRead(BaseModel):
    id: int
    title: str
    question: str
    context: str
    rationale: str
    probability: Score
    confidence: Score
    status: DecisionStatus
    current_version: int
    created_at: datetime
    updated_at: datetime
    hypotheses: list[HypothesisRead]
    supporting_evidence: list[EvidenceRead]
    opposing_evidence: list[EvidenceRead]
    critic_reviews: list[CriticReviewRead]
    invalidation_rules: list[InvalidationRuleRead]
    outcome: DecisionOutcomeRead | None
