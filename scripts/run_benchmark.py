#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib  # noqa: E402

matplotlib.use("Agg")  # headless: render to file, no display
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from config.settings import settings  # noqa: E402
from control.fixed_time import FixedTimeController  # noqa: E402
from control.max_pressure import MaxPressureController  # noqa: E402
from core.metrics import SimMetrics, run_scenario  # noqa: E402
from sim.scenarios.loader import TLS_ID, SumoNotFoundError  # noqa: E402

log = logging.getLogger(__name__)

FIXED_COLOR = "#c0504d"
ADAPTIVE_COLOR = "#4f81bd"
RL_COLOR = "#27ae60"


def pct_reduction(before: float, after: float) -> float:
    """Positive % means `after` is lower (an improvement)."""
    return 100.0 * (before - after) / before if before else 0.0


def render_chart(scenario: str, series: list[tuple[str, SimMetrics, str]],
                 wait_red: float, ped_red: float, out_path: Path) -> Path:
    """Grouped bar chart over 1..N controllers (vehicle wait + pedestrian delay)."""
    labels = ["Avg vehicle wait (s)", "Avg pedestrian delay (s)"]
    x = np.arange(len(labels))
    n = len(series)
    width = 0.8 / n
    fig, ax = plt.subplots(figsize=(9, 5.5))
    for i, (label, m, color) in enumerate(series):
        vals = [m.avg_wait_s, m.avg_ped_delay_s]
        bars = ax.bar(x + (i - (n - 1) / 2) * width, vals, width, label=label, color=color)
        ax.bar_label(bars, fmt="%.1f", padding=2, fontsize=8)

    ax.set_ylabel("seconds (lower is better)")
    ax.set_title(
        f"Saarthi — '{scenario}' scenario\n"
        f"Adaptive control cuts vehicle wait by {wait_red:.1f}% "
        f"(and pedestrian delay by {ped_red:.1f}%)",
        fontsize=12, fontweight="bold",
    )
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.legend()
    ax.margins(y=0.18)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=130)
    plt.close(fig)
    return out_path


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario", nargs="?", default="rush")
    ap.add_argument("--rl", action="store_true",
                    help="also benchmark the trained RL controller "
                         "(needs data/outputs/rl_policy.zip)")
    args = ap.parse_args()
    scenario = args.scenario

    try:
        fixed = run_scenario(scenario, FixedTimeController(TLS_ID))
        adaptive = run_scenario(scenario, MaxPressureController(TLS_ID))
        rl = None
        if args.rl:
            model_path = settings.outputs_dir / "rl_policy.zip"
            if not model_path.exists():
                print(f"⚠️  --rl given but no model at {model_path} — run "
                      "scripts/train_rl.py first. Skipping RL.")
            else:
                from control.rl.rl_controller import RLController
                rl = run_scenario(scenario, RLController(TLS_ID, str(model_path)))
    except (SumoNotFoundError, ImportError) as exc:
        print(f"\n⚠️  SUMO is not available: {exc}\n")
        print("Install SUMO and re-run. See the README for setup.")
        return 2

    wait_red = pct_reduction(fixed.avg_wait_s, adaptive.avg_wait_s)
    ped_red = pct_reduction(fixed.avg_ped_delay_s, adaptive.avg_ped_delay_s)

    result = {
        "scenario": scenario,
        "fixed_time": fixed.to_dict(),
        "max_pressure": adaptive.to_dict(),
        "wait_reduction_pct": round(wait_red, 1),
        "ped_delay_reduction_pct": round(ped_red, 1),
    }
    series = [("Fixed-time (baseline)", fixed, FIXED_COLOR),
              ("Max-pressure (adaptive)", adaptive, ADAPTIVE_COLOR)]
    if rl:
        result["rl"] = rl.to_dict()
        result["rl_wait_reduction_pct"] = round(pct_reduction(fixed.avg_wait_s, rl.avg_wait_s), 1)
        series.append(("RL (PPO, Tier-2)", rl, RL_COLOR))

    blob = json.dumps(result, indent=2)
    settings.outputs_dir.mkdir(parents=True, exist_ok=True)
    # Per-scenario file (so the dashboard shows a real before/after for EVERY
    # scenario, not just rush) + the legacy global default used as a fallback.
    json_path = settings.outputs_dir / f"benchmark.{scenario}.json"
    json_path.write_text(blob)
    (settings.outputs_dir / "benchmark.json").write_text(blob)
    png_path = render_chart(scenario, series, wait_red, ped_red,
                            settings.outputs_dir / "benchmark.png")

    print(f"\n=== Saarthi benchmark — scenario '{scenario}' ===")
    for label, m, _ in series:
        print(f"  {label:26s} avg wait {m.avg_wait_s:7.2f}s | "
              f"ped delay {m.avg_ped_delay_s:6.2f}s | queue {m.avg_queue:.1f}")
    print(f"\n>>> HEADLINE: max-pressure reduces average vehicle wait by "
          f"{wait_red:.1f}% vs fixed-time.")
    if rl:
        verb = "BEATS" if rl.avg_wait_s < adaptive.avg_wait_s else "does NOT beat"
        print(f">>> RL: {result['rl_wait_reduction_pct']:.1f}% vs fixed-time; "
              f"RL {verb} max-pressure ({rl.avg_wait_s:.1f}s vs {adaptive.avg_wait_s:.1f}s).")
    print(f"\nSaved chart -> {png_path}")
    print(f"Saved data  -> {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
