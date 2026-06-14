#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.analyst import advisory_text  # noqa: E402
from config.settings import settings  # noqa: E402
from core.features import compute_features, compute_temporal_summary  # noqa: E402
from core.llm import LLMError, LLMNotConfigured, render_in_language  # noqa: E402
from core.models import RootCauseVerdict  # noqa: E402
from sim.scenarios.loader import SumoNotFoundError  # noqa: E402


def _load_benchmark(scenario: str) -> dict | None:

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


def _print_block(title: str, body: str) -> None:
    print("\n" + "-" * 68)
    print(f"  {title}")
    print("-" * 68)
    for line in body.splitlines():
        print(f"  {line}")
    print("-" * 68)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="Root-cause analysis + multilingual advisory.")
    ap.add_argument("scenario", nargs="?", default="rush")
    ap.add_argument("--advisory-lang", default="Hindi",
                    help="language to render the authority advisory in (default: Hindi)")
    ap.add_argument("--no-advisory", action="store_true",
                    help="skip the translated advisory")
    ap.add_argument("--temporal", action="store_true",
                    help="also report the cross-scenario temporal pattern "
                         "(runs the 4 profiles once, then cached)")
    args = ap.parse_args()
    scenario = args.scenario

    from agents.analyst import AnalystAgent
    from agents.supervisor import build_supervisor

    try:
        print(f"Computing features for '{scenario}' (fixed-time baseline)...")
        features = compute_features(scenario)
    except (SumoNotFoundError, ImportError) as exc:
        print(f"\n⚠️  SUMO is not available: {exc}")
        return 2

    benchmark = _load_benchmark(scenario)

    try:
        print("Invoking supervisor -> analyst (Claude)...")
        result = build_supervisor().invoke({"features": features, "benchmark": benchmark})
        verdict: RootCauseVerdict = result["verdict"]
        print_verdict(verdict, benchmark)
        out = settings.outputs_dir / f"verdict.{scenario}.json"
        out.write_text(verdict.model_dump_json(indent=2))
        print(f"\nSaved verdict -> {out}")

        # Multilingual advisory (output-side): render the advisory for the authority.
        if not args.no_advisory:
            print(f"\nRendering advisory in {args.advisory_lang}...")
            english = advisory_text(verdict)
            advisory = render_in_language(english, args.advisory_lang)
            _print_block(f"ADVISORY ({args.advisory_lang}) — for the authority", advisory)
            # Persist both languages for the dashboard's English/Hindi toggle.
            adv_path = settings.outputs_dir / f"advisory.{scenario}.json"
            adv = json.loads(adv_path.read_text()) if adv_path.exists() else {}
            adv["english"] = english
            adv[args.advisory_lang] = advisory
            adv_path.write_text(json.dumps(adv, indent=2, ensure_ascii=False))

        # Temporal pattern across the day/week contexts.
        if args.temporal:
            print("\nComputing temporal pattern across the 4 profiles "
                  "(cached after first run)...")
            temporal = compute_temporal_summary()
            pattern = AnalystAgent().temporal_pattern(temporal)
            _print_block("TEMPORAL PATTERN (off-peak / weekday / rush / weekend)", pattern)

    except LLMNotConfigured as exc:
        print(f"\n⚠️  USER ACTION NEEDED — AI not configured: {exc}")
        print("Add ANTHROPIC_API_KEY to .env, then re-run this script.")
        return 3
    except LLMError as exc:
        print(f"\n⚠️  USER ACTION NEEDED — AI call failed:\n    {exc}")
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
