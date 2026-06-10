#!/usr/bin/env python3
"""Run the root-cause analysis end-to-end and print the verdict.

Pipeline:  SUMO run (fixed-time)  ->  computed features  ->  supervisor/Analyst
(Gemini)  ->  structured root-cause verdict.

Usage:
    python scripts/run_analysis.py [scenario]      # default scenario: rush

Requires GEMINI_API_KEY in .env (see .env.example).
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.settings import settings  # noqa: E402
from core.features import compute_features  # noqa: E402
from core.llm import LLMError, LLMNotConfigured  # noqa: E402
from core.models import RootCauseVerdict  # noqa: E402
from sim.scenarios.loader import SumoNotFoundError  # noqa: E402


def _load_benchmark(scenario: str) -> dict | None:
    """Load the benchmark only if it was computed for THIS scenario.

    Prevents the verdict from citing another scenario's wait-time reduction.
    """
    path = settings.outputs_dir / "benchmark.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    if data.get("scenario") != scenario:
        print(f"  (note: benchmark.json is for '{data.get('scenario')}', not "
              f"'{scenario}' — skipping it; run `run_benchmark.py {scenario}` to "
              f"include a quantified impact.)")
        return None
    return data


def print_verdict(v: RootCauseVerdict, benchmark: dict | None) -> None:
    cb = v.cause_breakdown
    print("\n" + "=" * 68)
    print(f"  SAARTHI — ROOT-CAUSE VERDICT  |  junction {v.junction_id}  |  '{v.scenario}'")
    print("=" * 68)
    print(f"\n  {v.headline}\n")
    print(f"  Primary cause : {v.primary_cause}")
    print(f"  Attribution   : vehicles {cb.vehicles:.0f}%  |  "
          f"pedestrians {cb.pedestrians:.0f}%  |  parking {cb.parking:.0f}%")
    print(f"  Confidence    : {v.confidence:.0%}")
    print(f"\n  RECOMMENDATION:\n    {v.recommendation}")
    print(f"\n  EXPECTED IMPACT:\n    {v.expected_impact}")
    print(f"\n  WHY (grounded in the data):\n    {v.justification}")
    if v.temporal_note:
        print(f"\n  TEMPORAL PATTERN:\n    {v.temporal_note}")
    if benchmark:
        print(f"\n  (Benchmark chart: {settings.outputs_dir / 'benchmark.png'} — "
              f"adaptive control cuts vehicle wait by {benchmark.get('wait_reduction_pct')}%.)")
    print("=" * 68)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    scenario = sys.argv[1] if len(sys.argv) > 1 else "rush"

    # Local import so a missing key/SUMO is reported cleanly, not at import time.
    from agents.supervisor import build_supervisor

    try:
        print(f"Computing features for '{scenario}' (fixed-time baseline)...")
        features = compute_features(scenario)
    except (SumoNotFoundError, ImportError) as exc:
        print(f"\n⚠️  SUMO is not available: {exc}")
        return 2

    benchmark = _load_benchmark(scenario)

    try:
        print("Invoking supervisor -> analyst (Gemini)...")
        supervisor = build_supervisor()
        result = supervisor.invoke({"features": features, "benchmark": benchmark})
    except LLMNotConfigured as exc:
        print(f"\n⚠️  USER ACTION NEEDED — Gemini not configured: {exc}")
        print("Add GEMINI_API_KEY to .env, then re-run this script.")
        print("(The computed features above were produced fine; only the LLM "
              "verdict needs the key.)")
        return 3
    except LLMError as exc:
        print(f"\n⚠️  USER ACTION NEEDED — Gemini call failed:\n    {exc}")
        print("\n(The computed features were produced fine; only the LLM verdict "
              "is blocked. Fix billing/quota or GEMINI_MODEL, then re-run.)")
        return 4

    verdict: RootCauseVerdict = result["verdict"]
    print_verdict(verdict, benchmark)

    out = settings.outputs_dir / f"verdict.{scenario}.json"
    out.write_text(verdict.model_dump_json(indent=2))
    print(f"\nSaved verdict -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
