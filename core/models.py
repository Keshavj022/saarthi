"""Pydantic data models for Saarthi's reasoning layer.

Phase 2: the root-cause verdict the Analyst produces.
Phase 4: the violation event + challan draft the Enforcement agent produces.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class CauseBreakdown(BaseModel):
    """Percent attribution of the junction's congestion to each factor.

    The three should add up to roughly 100. `parking` (illegal parking /
    lane-narrowing) is not yet measured in simulation (Phase 6), so it is
    normally 0 unless perception data says otherwise.
    """

    vehicles: float = Field(ge=0, le=100, description="share due to vehicle demand / signal split")
    pedestrians: float = Field(ge=0, le=100, description="share due to pedestrian crossing activity")
    parking: float = Field(ge=0, le=100, description="share due to illegal parking / encroachment (usually 0; not yet measured)")


class RootCauseVerdict(BaseModel):
    """Structured root-cause attribution + recommendation for one junction."""

    junction_id: str = Field(description="the junction this verdict is about")
    scenario: str = Field(description="the demand scenario analysed, e.g. 'rush'")
    headline: str = Field(description="one plain-language sentence: why this junction congests")
    primary_cause: str = Field(description="the single biggest contributor, named plainly")
    cause_breakdown: CauseBreakdown
    recommendation: str = Field(description="the concrete action the authority should take")
    expected_impact: str = Field(description="expected benefit, quantified from the benchmark when available")
    justification: str = Field(description="why this verdict follows from the computed features (cite the numbers)")
    temporal_note: str = Field(default="", description="time-of-day / day-of-week pattern, if evident")
    confidence: float = Field(ge=0, le=1, description="confidence in this attribution, 0-1")


class DetailedAnalysis(BaseModel):
    """Deep-dive narrative the Analyst produces from concrete sim instances."""

    diagnosis: str = Field(description="detailed multi-paragraph diagnosis of why the junction congests, citing the instances")
    evidence: list[str] = Field(description="bullet points, each tying one concrete instance (time, queue, vehicle) to the diagnosis")
    actions: list[str] = Field(description="numbered, concrete steps the authority should take, in priority order")
    expected_outcome: str = Field(description="what changes after the fix, quantified from the benchmark when available")


# --------------------------- Phase 4: enforcement ----------------------------
class ViolationEvent(BaseModel):
    """A potential traffic violation flagged for enforcement review.

    In production this comes from perception (a plate read while the signal was
    red, etc.). Without footage it is a clearly-labelled simulated event.
    """

    plate: str = Field(description="the vehicle's number plate")
    violation_type: str = Field(description="e.g. 'red_light_jump', 'stop_line_crossing'")
    junction_id: str
    timestamp: str = Field(description="when it occurred (ISO time or sim-time label)")
    evidence: str = Field(description="evidence description: signal state, frame ref, speed, etc.")
    source: str = Field(default="simulated", description="'video' or 'simulated'")
    citizen_language: str = Field(default="Hindi", description="language to draft the challan in")


class ChallanDraft(BaseModel):
    """The Enforcement agent's structured judgment + drafted citation.

    This is only ever a DRAFT — a human officer reviews it. Never auto-issued.
    """

    is_valid_violation: bool = Field(description="whether this is a real, citable violation")
    reasoning: str = Field(description="why it is or isn't a valid, citable violation")
    evidence_summary: str = Field(description="evidence assembled to support the citation")
    fine_amount_inr: int = Field(ge=0, description="proposed fine in INR for this violation type")
    draft_notice: str = Field(description="the challan notice text, in the citizen's language")
    confidence: float = Field(ge=0, le=1)
