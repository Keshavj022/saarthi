"""Root-cause Analyst agent — the spine of Saarthi.

Takes the COMPUTED feature dict (from `core.features`) plus the optional
fixed-time-vs-adaptive benchmark, and returns a structured `RootCauseVerdict`:
why the junction congests, attribution across factors, and what the authority
should do. It reasons over the supplied numbers — it does not see raw logs.
"""
from __future__ import annotations

import json
import logging

from core import llm
from core.models import RootCauseVerdict

log = logging.getLogger(__name__)

ANALYST_SYSTEM = """You are a senior traffic engineer advising an Indian city's \
traffic-control authority (control-room operators and enforcement officers, not \
commuters). You explain WHY a junction congests and WHAT to do about it.

Rules:
- Attribute congestion ONLY from the COMPUTED FEATURES given. Never invent data.
- `cause_breakdown` percentages (vehicles, pedestrians, parking) must sum to ~100.
  Parking / lane-encroachment is NOT measured in this simulation — set parking to
  0 unless the features say otherwise.
- Use the directional imbalance, per-approach queues, temporal profile and the
  pedestrian backup ratio to decide the primary cause. A high imbalance ratio with
  one axis far more queued means the fixed signal split — not pedestrians — is the
  problem. A pedestrian backup ratio well above 1 means the walk phase is holding
  vehicles up.
- Ground `expected_impact` in the BENCHMARK when provided: cite the % wait-time
  reduction adaptive (max-pressure) control achieves.
- Write `headline`, `recommendation` and `justification` in plain, specific
  language an operator can act on, citing concrete numbers (queues, ratios, times).
"""


def build_prompt(features: dict, benchmark: dict | None) -> str:
    parts = [
        "COMPUTED FEATURES (from a SUMO run under the current fixed-time signal):",
        json.dumps(features, indent=2),
    ]
    if benchmark:
        parts += [
            "\nBENCHMARK — same scenario, fixed-time vs adaptive max-pressure control:",
            json.dumps(benchmark, indent=2),
        ]
    parts.append("\nProduce the structured root-cause verdict for this junction.")
    return "\n".join(parts)


class AnalystAgent:
    """Wraps the Gemini call that turns features into a structured verdict."""

    name = "analyst"

    def analyze(self, features: dict, benchmark: dict | None = None) -> RootCauseVerdict:
        prompt = build_prompt(features, benchmark)
        verdict = llm.structured(prompt, RootCauseVerdict, system=ANALYST_SYSTEM)
        # Trust our own metadata over the model's echo.
        verdict.junction_id = features.get("junction_id", verdict.junction_id)
        verdict.scenario = features.get("scenario", verdict.scenario)
        log.info("Analyst verdict: primary_cause=%s confidence=%.2f",
                 verdict.primary_cause, verdict.confidence)
        return verdict
