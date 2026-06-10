"""Pydantic data models for Saarthi's reasoning layer.

Phase 2 defines the root-cause verdict the Analyst produces. Enforcement/challan
models are added in Phase 4.
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
