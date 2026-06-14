#!/usr/bin/env python3
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.settings import settings  # noqa: E402
from control.fixed_time import FixedTimeController  # noqa: E402
from control.max_pressure import MaxPressureController  # noqa: E402
from core.metrics import run_scenario  # noqa: E402
from sim.scenarios.loader import TLS_ID, SumoNotFoundError  # noqa: E402


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--timesteps", type=int, default=24000)
    ap.add_argument("--scenario", default="rush")
    ap.add_argument("--episode-seconds", type=int, default=3600)
    args = ap.parse_args()

    try:
        from stable_baselines3 import PPO
        from stable_baselines3.common.monitor import Monitor

        from control.rl.env import JunctionEnv

        settings.ensure_dirs()
        model_path = settings.outputs_dir / "rl_policy.zip"

        env = Monitor(JunctionEnv(scenario=args.scenario,
                                  episode_seconds=args.episode_seconds))
        model = PPO("MlpPolicy", env, n_steps=512, batch_size=64, gamma=0.99,
                    learning_rate=3e-4, verbose=1, seed=42)
        print(f"Training PPO for {args.timesteps} timesteps on '{args.scenario}'...")
        model.learn(total_timesteps=args.timesteps, progress_bar=False)
        model.save(str(model_path))
        env.close()
        print(f"Saved model -> {model_path}")
    except (SumoNotFoundError, ImportError) as exc:
        print(f"\n⚠️  Cannot train: {exc}")
        return 2

    # --- Evaluate all three controllers on the same scenario ---
    from control.rl.rl_controller import RLController

    print(f"\nEvaluating on '{args.scenario}' (full demand)...")
    results = {}
    for name, ctrl in [
        ("fixed_time", FixedTimeController(TLS_ID)),
        ("max_pressure", MaxPressureController(TLS_ID)),
        ("rl", RLController(TLS_ID, str(model_path))),
    ]:
        m = run_scenario(args.scenario, ctrl)
        results[name] = m
        print(f"  {name:13s}: avg wait {m.avg_wait_s:7.2f}s | "
              f"ped delay {m.avg_ped_delay_s:6.2f}s | vehicles {m.num_vehicles}")

    mp, rl = results["max_pressure"], results["rl"]
    # A win must be GENUINE: lower vehicle wait AND no gridlock (comparable
    # throughput) AND pedestrians not starved — otherwise the lower average is an
    # artifact (stuck vehicles excluded from the mean / pedestrians ignored).
    completed_ok = rl.num_vehicles >= 0.98 * mp.num_vehicles
    ped_ok = rl.avg_ped_delay_s <= 1.5 * max(mp.avg_ped_delay_s, 1.0)
    beats = rl.avg_wait_s < mp.avg_wait_s
    print()
    print(f"  RL cleared {rl.num_vehicles}/{mp.num_vehicles} vehicles "
          f"(no-gridlock={completed_ok}); ped delay {rl.avg_ped_delay_s:.1f}s vs "
          f"max-pressure {mp.avg_ped_delay_s:.1f}s (ok={ped_ok}).")
    if beats and completed_ok and ped_ok:
        print(f"✓ GENUINE WIN: RL {rl.avg_wait_s:.1f}s < max-pressure "
              f"{mp.avg_wait_s:.1f}s, all vehicles cleared, pedestrians not starved "
              f"— promote as the 3rd benchmark bar.")
    elif beats:
        print(f"✗ RL's lower vehicle wait ({rl.avg_wait_s:.1f}s) is NOT genuine "
              f"(gridlock and/or pedestrian starvation). Per the guardrail, "
              f"max-pressure stays the headline — RL not promoted.")
    else:
        print(f"✗ RL ({rl.avg_wait_s:.1f}s) does not beat max-pressure "
              f"({mp.avg_wait_s:.1f}s). Fall back to max-pressure.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
