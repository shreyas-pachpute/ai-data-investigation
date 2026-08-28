"""Pydantic models for every structured LLM input/output boundary.

Every LLM call in the investigation loop returns one of these — no
free-text parsing anywhere between the model and the rest of the system
(RESEARCH_NOTES.md Section 3: "every boundary between an LLM step and the
rest of the system should be a typed structured output").
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class RootCauseCategory(str, Enum):
    DATA_QUALITY_ISSUE = "data_quality_issue"
    GENUINE_BUSINESS_CHANGE = "genuine_business_change"
    SEASONAL_EXPECTED_VARIATION = "seasonal_expected_variation"
    DEFINITIONAL_CHANGE = "definitional_change"
    INCONCLUSIVE = "inconclusive"


class PriorLikelihood(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class HypothesisStatus(str, Enum):
    UNTESTED = "untested"
    TESTING = "testing"
    CONFIRMED = "confirmed"
    RULED_OUT = "ruled_out"
    INCONCLUSIVE = "inconclusive"


class Hypothesis(BaseModel):
    hypothesis_id: str = Field(description="Short stable id, e.g. 'h1', 'h2'.")
    category: RootCauseCategory
    description: str = Field(description="The specific candidate explanation, concrete not generic.")
    rationale: str = Field(description="Why this is plausible given the anomaly's shape.")
    prior_likelihood: PriorLikelihood
    status: HypothesisStatus = HypothesisStatus.UNTESTED


class HypothesisGenerationOutput(BaseModel):
    hypotheses: list[Hypothesis] = Field(max_length=5)


class QueryProposal(BaseModel):
    sql: str = Field(description="A single read-only SELECT statement testing the hypothesis.")
    purpose: str = Field(description="What this specific query is meant to reveal.")


class VerdictOutput(BaseModel):
    verdict: str = Field(description="One of: supports, contradicts, inconclusive.")
    reasoning: str = Field(description="Grounded in the actual query result, not general knowledge.")
    new_status: HypothesisStatus
    refined_hypothesis: Hypothesis | None = Field(
        default=None,
        description="Only set if this result suggests a new, more specific hypothesis worth adding.",
    )


class EvidenceCitation(BaseModel):
    query_id: int = Field(description="Must reference an actually-executed query id from the trace.")
    finding: str


class RuledOutHypothesis(BaseModel):
    hypothesis_id: str
    description: str
    reason: str


class FinalReport(BaseModel):
    conclusion_category: RootCauseCategory
    conclusion_summary: str
    confidence: PriorLikelihood
    confidence_score: float = Field(ge=0.0, le=1.0)
    evidence: list[EvidenceCitation]
    ruled_out: list[RuledOutHypothesis]
    investigation_complete: bool = Field(
        description="False if budget was exhausted without a conclusive answer."
    )
