from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from macrovision.contracts import Ratio
from macrovision.models import JournalStatus, RiskTolerance


class RiskBudgetCreate(BaseModel):
    total_risk_budget: Ratio
    per_decision_limit: Ratio
    minimum_cash_allocation: Ratio = Decimal("0")

    @model_validator(mode="after")
    def decision_limit_within_budget(self) -> "RiskBudgetCreate":
        if self.per_decision_limit > self.total_risk_budget:
            raise ValueError("per_decision_limit cannot exceed total_risk_budget")
        return self


class RiskBudgetRead(RiskBudgetCreate):
    id: int
    model_config = ConfigDict(from_attributes=True)


class RiskProfileCreate(BaseModel):
    tolerance: RiskTolerance
    max_drawdown: Ratio
    loss_capacity: Ratio
    notes: str = ""
    risk_budget: RiskBudgetCreate


class RiskProfileRead(BaseModel):
    id: int
    tolerance: RiskTolerance
    max_drawdown: Ratio
    loss_capacity: Ratio
    notes: str
    risk_budget: RiskBudgetRead
    model_config = ConfigDict(from_attributes=True)


class InvestorProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    base_currency: str = Field(default="USD", min_length=3, max_length=3)
    investment_horizon_years: int = Field(gt=0)
    liquidity_need: Ratio = Decimal("0")
    objectives: str = Field(min_length=1)
    constraints: str = ""
    risk_profile: RiskProfileCreate


class InvestorProfileRead(BaseModel):
    id: int
    name: str
    base_currency: str
    investment_horizon_years: int
    liquidity_need: Ratio
    objectives: str
    constraints: str
    created_at: datetime
    risk_profile: RiskProfileRead
    model_config = ConfigDict(from_attributes=True)


class JournalCreate(BaseModel):
    investor_id: int
    asset: str = Field(min_length=1, max_length=120)
    hypothesis: str = Field(min_length=1)
    evidence_for: str = Field(min_length=1)
    evidence_against: str = Field(min_length=1)
    critic_review: str = Field(min_length=1)
    probability: Ratio
    confidence: Ratio
    invalidation_conditions: str = Field(min_length=1)
    decision: str = "No action"


class JournalClose(BaseModel):
    outcome: str = Field(min_length=1)
    lessons: str = Field(min_length=1)


class JournalRead(JournalCreate):
    id: int
    outcome: str | None
    lessons: str | None
    status: JournalStatus
    closed_at: datetime | None
    lock_version: int
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)
