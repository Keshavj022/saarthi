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
from core.models import DetailedAnalysis, RootCauseVerdict

log = logging.getLogger(__name__)

ANALYST_SYSTEM = """You are a senior traffic engineer advising an Indian city's \
traffic-control authority (control-room operators and enforcement officers, not \
commuters). You explain WHY a junction congests and WHAT to do about it.

Rules:
- Attribute congestion ONLY from the COMPUTED FEATURES given. Never invent data.
- `cause_breakdown` percentages (vehicles, pedestrians, parking) must sum to ~100.
  Parking / lane-encroachment is measured ONLY when a PARKING/ENCROACHMENT report
  is provided: if one shows stationary vehicles, attribute a share to parking
  proportional to its severity. Otherwise set parking to 0.
- Use the directional imbalance, per-approach queues, temporal profile and the
  pedestrian backup ratio to decide the primary cause. A high imbalance ratio with
  one axis far more queued means the fixed signal split — not pedestrians — is the
  problem. A pedestrian backup ratio well above 1 means the walk phase is holding
  vehicles up.
- Ground `expected_impact` in the BENCHMARK when provided: cite the % wait-time
  reduction that adaptive signal control achieves.
- Write `headline`, `recommendation` and `justification` in plain, specific
  language an operator can act on, citing concrete numbers (queues, ratios, times).
- PLAIN LANGUAGE ONLY. A non-technical official must understand every word. Do NOT
  use jargon or software/algorithm names — never write "max-pressure",
  "reinforcement learning", "RL", "PPO", "SUMO", "TraCI", "LLM". Say "adaptive
  signal control" or "smart signal timing", and "the analysis"/"the simulation".
"""


def build_prompt(features: dict, benchmark: dict | None,
                 parking: dict | None = None) -> str:
    parts = [
        "COMPUTED FEATURES (from a SUMO run under the current fixed-time signal):",
        json.dumps(features, indent=2),
    ]
    if benchmark:
        parts += [
            "\nBENCHMARK — same scenario, fixed-time vs adaptive max-pressure control:",
            json.dumps(benchmark, indent=2),
        ]
    if parking:
        parts += [
            "\nPARKING/ENCROACHMENT report (from perception — stationary vehicles):",
            json.dumps(parking, indent=2),
        ]
    parts.append("\nProduce the structured root-cause verdict for this junction.")
    return "\n".join(parts)


def advisory_text(verdict) -> str:
    """A short, plain-language advisory built from a verdict — the thing we render
    into Hindi (or another language) for the authority."""
    return (
        f"Junction {verdict.junction_id}: {verdict.headline} "
        f"Recommended action: {verdict.recommendation} "
        f"Expected impact: {verdict.expected_impact}"
    )


def translate_verdict(verdict: RootCauseVerdict, language: str) -> RootCauseVerdict:
    """Return the verdict with its human-readable text translated into `language`.

    Numbers (cause_breakdown, confidence) and identifiers are kept exactly the same —
    only the prose fields are translated — so the whole Analysis page can render in
    one language without re-running the simulation.
    """
    if language.strip().lower() == "english":
        return verdict
    prompt = (
        f"Translate the human-readable text of this traffic root-cause verdict into plain, "
        f"natural {language} for a control-room operator. Translate these fields: headline, "
        f"primary_cause, recommendation, expected_impact, justification, temporal_note. Keep "
        f"cause_breakdown, confidence, junction_id, scenario, and every number / percentage / "
        f"place name EXACTLY the same. No jargon, no transliteration notes.\n\n"
        f"{verdict.model_dump_json(indent=2)}"
    )
    return llm.structured(
        prompt, RootCauseVerdict,
        system=f"You translate traffic-authority analysis into {language}. Return the same "
               f"structured fields with the text translated and every number unchanged.")


def translate_details(details: dict, language: str) -> dict:
    """Return a deep-dive report with its narrative translated into `language`.

    The concrete instances (episodes, queues, times) stay as-is; only the AI narrative
    (diagnosis / evidence / actions / expected_outcome) is translated.
    """
    if language.strip().lower() == "english":
        return details
    a = details.get("analysis") or {}
    src = {"diagnosis": a.get("diagnosis", ""), "evidence": a.get("evidence", []),
           "actions": a.get("actions", []), "expected_outcome": a.get("expected_outcome", "")}
    prompt = (
        f"Translate this traffic deep-dive analysis into plain, natural {language}. Keep all "
        f"numbers, times and place names. Return the same four fields, translated.\n\n"
        f"{json.dumps(src, ensure_ascii=False)}"
    )
    t = llm.structured(
        prompt, DetailedAnalysis,
        system=f"You translate traffic-authority analysis into {language}; return the same fields translated.")
    out = dict(details)
    out["analysis"] = {**a, "diagnosis": t.diagnosis, "evidence": t.evidence,
                       "actions": t.actions, "expected_outcome": t.expected_outcome}
    return out


class AnalystAgent:
    """Wraps the AI call that turns features into a structured verdict."""

    name = "analyst"

    def analyze(self, features: dict, benchmark: dict | None = None,
                parking: dict | None = None) -> RootCauseVerdict:
        prompt = build_prompt(features, benchmark, parking)
        verdict = llm.structured(prompt, RootCauseVerdict, system=ANALYST_SYSTEM)
        # Trust our own metadata over the model's echo.
        verdict.junction_id = features.get("junction_id", verdict.junction_id)
        verdict.scenario = features.get("scenario", verdict.scenario)
        log.info("Analyst verdict: primary_cause=%s confidence=%.2f",
                 verdict.primary_cause, verdict.confidence)
        return verdict

    def temporal_pattern(self, temporal_summary: dict) -> str:
        """State the time-based congestion pattern across the day/week contexts."""
        prompt = (
            "Junction congestion metrics across time-of-day / day-of-week contexts:\n"
            + json.dumps(temporal_summary, indent=2)
            + "\n\nDescribe the time-based congestion pattern."
        )
        return llm.chat(prompt, system=TEMPORAL_SYSTEM, temperature=0.2)


TEMPORAL_SYSTEM = """You are a traffic engineer briefing a control-room operator. \
Given congestion metrics for ONE junction across different time-of-day / day-of-week \
contexts, state the time-based congestion pattern in 2-4 plain sentences: when it is \
worst and best, and what changes between contexts (queue levels, directional \
imbalance, pedestrian load). Cite specific numbers. Be concise and operational. Use \
plain language only — no technical jargon or software/algorithm names."""
