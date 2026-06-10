"""Tests for enforcement prompt + advisory text builders (pure, no LLM)."""
from __future__ import annotations

from agents.analyst import advisory_text
from agents.enforcement import build_prompt
from core.models import CauseBreakdown, RootCauseVerdict, ViolationEvent


def test_enforcement_prompt_contains_event_fields():
    event = ViolationEvent(
        plate="MH12AB1234", violation_type="red_light_jump", junction_id="C",
        timestamp="2026-06-10T18:42:11", evidence="captured by stop-line camera",
    )
    prompt = build_prompt(event)
    assert "MH12AB1234" in prompt
    assert "red_light_jump" in prompt
    assert "stop-line camera" in prompt


def test_advisory_text_includes_key_parts():
    verdict = RootCauseVerdict(
        junction_id="C", scenario="rush", headline="It congests.",
        primary_cause="vehicles",
        cause_breakdown=CauseBreakdown(vehicles=95, pedestrians=5, parking=0),
        recommendation="Deploy adaptive control.", expected_impact="44.6% lower wait",
        justification="j", confidence=0.95,
    )
    text = advisory_text(verdict)
    assert "C" in text
    assert "Deploy adaptive control." in text
    assert "44.6%" in text
