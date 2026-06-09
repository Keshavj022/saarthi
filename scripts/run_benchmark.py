#!/usr/bin/env python3
"""Before/after benchmark: fixed-time vs max-pressure on the SAME scenario.

Runs both controllers on one scenario, computes the % wait-time reduction (the
project's headline number), prints a comparison, saves the raw results to
data/outputs/benchmark.json, and renders a labeled bar chart to
data/outputs/benchmark.png.

Usage:
    python scripts/run_benchmark.py [scenario]      # default scenario: rush
"""
from __future__ import annotations

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


def pct_reduction(before: float, after: float) -> float:
    """Positive % means `after` is lower (an improvement)."""
    return 100.0 * (before - after) / before if before else 0.0


def render_chart(scenario: str, fixed: SimMetrics, adaptive: SimMetrics,
                 wait_red: float, ped_red: float, out_path: Path) -> Path:
    labels = ["Avg vehicle wait (s)", "Avg pedestrian delay (s)"]
    fixed_vals = [fixed.avg_wait_s, fixed.avg_ped_delay_s]
    adaptive_vals = [adaptive.avg_wait_s, adaptive.avg_ped_delay_s]

    x = np.arange(len(labels))
    width = 0.36
    fig, ax = plt.subplots(figsize=(8.5, 5.5))
    b1 = ax.bar(x - width / 2, fixed_vals, width,
                label="Fixed-time (baseline)", color=FIXED_COLOR)
    b2 = ax.bar(x + width / 2, adaptive_vals, width,
                label="Max-pressure (adaptive)", color=ADAPTIVE_COLOR)

    ax.set_ylabel("seconds (lower is better)")
    ax.set_title(
        f"Saarthi — '{scenario}' scenario\n"
        f"Adaptive control cuts vehicle wait by {wait_red:.1f}% "
        f"(and pedestrian delay by {ped_red:.1f}%)",
        fontsize=12, fontweight="bold",
    )
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.bar_label(b1, fmt="%.1f", padding=3)
    ax.bar_label(b2, fmt="%.1f", padding=3)
    ax.legend()
    ax.margins(y=0.18)

    # Headline annotation on the vehicle-wait group.
    top = max(fixed_vals[0], adaptive_vals[0])
    ax.annotate(
        f"↓ {wait_red:.1f}%",
        xy=(0, top), xytext=(0, top * 1.12),
        ha="center", fontsize=14, fontweight="bold", color="#2e7d32",
    )
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=130)
    plt.close(fig)
    return out_path


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    scenario = sys.argv[1] if len(sys.argv) > 1 else "rush"

    try:
        fixed = run_scenario(scenario, FixedTimeController(TLS_ID))
        adaptive = run_scenario(scenario, MaxPressureController(TLS_ID))
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
    json_path = settings.outputs_dir / "benchmark.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(result, indent=2))

    png_path = render_chart(
        scenario, fixed, adaptive, wait_red, ped_red,
        settings.outputs_dir / "benchmark.png",
    )

    print(f"\n=== Saarthi benchmark — scenario '{scenario}' ===")
    print(f"{'metric':24s}{'fixed-time':>14s}{'max-pressure':>15s}{'change':>10s}")
    print("-" * 63)
    print(f"{'avg vehicle wait (s)':24s}{fixed.avg_wait_s:>14.2f}"
          f"{adaptive.avg_wait_s:>15.2f}{-wait_red:>9.1f}%")
    print(f"{'avg pedestrian delay (s)':24s}{fixed.avg_ped_delay_s:>14.2f}"
          f"{adaptive.avg_ped_delay_s:>15.2f}{-ped_red:>9.1f}%")
    print(f"{'avg vehicle travel (s)':24s}{fixed.avg_travel_time_s:>14.2f}"
          f"{adaptive.avg_travel_time_s:>15.2f}")
    print(f"{'avg queue (veh)':24s}{fixed.avg_queue:>14.2f}{adaptive.avg_queue:>15.2f}")
    print(f"{'vehicles / pedestrians':24s}"
          f"{f'{fixed.num_vehicles}/{fixed.num_pedestrians}':>14s}"
          f"{f'{adaptive.num_vehicles}/{adaptive.num_pedestrians}':>15s}")
    print("-" * 63)
    print(f"\n>>> HEADLINE: max-pressure reduces average vehicle wait by "
          f"{wait_red:.1f}% vs fixed-time.")
    print(f"\nSaved chart -> {png_path}")
    print(f"Saved data  -> {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
