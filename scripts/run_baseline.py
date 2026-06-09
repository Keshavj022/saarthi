#!/usr/bin/env python3
"""Run the fixed-time baseline scenario and print + save its metrics.

Usage:
    python scripts/run_baseline.py

Requires SUMO installed and SUMO_HOME set (see README). On a fresh checkout this
also builds the SUMO network from its inputs on first run.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

# Make the project root importable when run as `python scripts/run_baseline.py`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.settings import settings  # noqa: E402
from control.fixed_time import FixedTimeController  # noqa: E402
from core.metrics import run_scenario  # noqa: E402
from sim.scenarios.loader import TLS_ID, SumoNotFoundError  # noqa: E402


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )

    try:
        controller = FixedTimeController(TLS_ID)
        metrics = run_scenario("baseline", controller)
    except (SumoNotFoundError, ImportError) as exc:
        print(f"\n⚠️  SUMO is not available: {exc}\n")
        print("Install SUMO (system-level), set SUMO_HOME, then re-run this "
              "script. Setup steps are in the README.")
        return 2

    out_path = settings.outputs_dir / "baseline.json"
    metrics.save_json(out_path)

    print("\n=== Saarthi — Fixed-time baseline ===")
    print(f"Scenario             : {metrics.scenario}")
    print(f"Controller           : {metrics.controller}")
    print(f"Vehicles (completed) : {metrics.num_vehicles}")
    print(f"Avg waiting time     : {metrics.avg_wait_s:.2f} s/veh   <-- headline")
    print(f"Avg travel time      : {metrics.avg_travel_time_s:.2f} s/veh")
    print(f"Avg queue (halting)  : {metrics.avg_queue:.2f} veh")
    print(f"Peak queue           : {metrics.peak_queue} veh")
    print(f"Sim steps            : {metrics.sim_steps}")
    print(f"\nSaved metrics -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
