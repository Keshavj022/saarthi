"""Computed diagnostic features for the Analyst.

Runs a scenario (default: under the fixed-time baseline — the status quo we want
to *explain*) and distils the simulation into a clean, JSON-able feature dict:
per-approach queues, directional imbalance, a temporal profile (peak window +
trend), and pedestrian features including how vehicle backup correlates with the
pedestrian phase.

These COMPUTED features are what make the LLM's attribution credible — the model
reasons over numbers, it does not guess from raw logs.

Pure aggregation helpers (`series_stats`, `bucketize`, `trend`) are kept
side-effect-free for unit testing without SUMO.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from config.settings import settings
from control.base import Controller
from control.fixed_time import FixedTimeController
from core.metrics import summarize_tripinfo
from sim.scenarios import loader
from sim.scenarios.loader import TLS_ID

log = logging.getLogger(__name__)

# The demand profiles double as time-of-day / day-of-week contexts so the Analyst
# can state temporal patterns ("congests during the weekday evening peak").
SCENARIO_TIME_LABELS = {
    "rush": "weekday evening peak (approx. 6-8 PM)",
    "weekday": "typical weekday daytime",
    "weekend": "weekend daytime",
    "offpeak": "off-peak / late-night",
}


# --------------------------- pure helpers (testable) ---------------------------
def series_stats(samples: list[float]) -> dict:
    if not samples:
        return {"avg": 0.0, "peak": 0.0}
    return {"avg": round(sum(samples) / len(samples), 2), "peak": round(max(samples), 2)}


def bucketize(times: list[float], values: list[float], bucket_seconds: int) -> list[dict]:
    """Average `values` into fixed time buckets keyed by bucket start time."""
    buckets: dict[int, list[float]] = {}
    for t, v in zip(times, values):
        key = int(t // bucket_seconds) * bucket_seconds
        buckets.setdefault(key, []).append(v)
    return [
        {"t_start": k, "t_end": k + bucket_seconds,
         "avg_total_queue": round(sum(vs) / len(vs), 2)}
        for k, vs in sorted(buckets.items())
    ]


def trend(samples: list[float]) -> str:
    """Coarse direction of a series: rising / falling / stable (first vs last third)."""
    if len(samples) < 6:
        return "stable"
    third = len(samples) // 3
    first = sum(samples[:third]) / third
    last = sum(samples[-third:]) / third
    if last > first * 1.25:
        return "rising"
    if last < first * 0.75:
        return "falling"
    return "stable"


# ------------------------------- feature builder -------------------------------
def compute_features(
    scenario: str,
    controller: Optional[Controller] = None,
    *,
    bucket_seconds: int = 300,
    max_steps: Optional[int] = None,
) -> dict:
    """Run `scenario` and return a structured feature dict for the Analyst."""
    loader.ensure_sumo_on_path()
    import traci

    settings.ensure_dirs()
    loader.build_network()
    controller = controller or FixedTimeController(TLS_ID)

    tripinfo = settings.outputs_dir / f"{scenario}.features.tripinfo.xml"
    cmd = loader.sumo_cmd(scenario, extra=["--tripinfo-output", str(tripinfo)])
    if max_steps is None:
        max_steps = settings.sim_duration * 3

    traci.start(cmd)
    try:
        controller.reset()
        ns_lanes = controller.phases.incoming_lanes["NS"]
        ew_lanes = controller.phases.incoming_lanes["EW"]
        approach_lanes: dict[str, list[str]] = {a: [] for a in "NSEW"}
        for lane in ns_lanes + ew_lanes:
            approach_lanes[lane[0]].append(lane)
        walk_edges = set(controller.phases.walk_edges)

        times: list[float] = []
        per_approach: dict[str, list[float]] = {a: [] for a in "NSEW"}
        total_q: list[float] = []
        ped_wait: list[float] = []
        q_during = {"PED": [], "VEH": []}

        step = 0
        while traci.simulation.getMinExpectedNumber() > 0 and step < max_steps:
            controller.step(traci.simulation.getTime())
            traci.simulationStep()
            t = traci.simulation.getTime()
            tot = 0
            for ap, lanes in approach_lanes.items():
                q = sum(traci.lane.getLastStepHaltingNumber(l) for l in lanes)
                per_approach[ap].append(q)
                tot += q
            total_q.append(tot)
            times.append(t)
            waiting = sum(
                1 for p in traci.person.getIDList()
                if traci.person.getRoadID(p) in walk_edges
                and traci.person.getSpeed(p) < 0.3
            )
            ped_wait.append(waiting)
            q_during["PED" if controller.current == "PED" else "VEH"].append(tot)
            step += 1
    finally:
        traci.close()

    trip = summarize_tripinfo(tripinfo)

    # Per-approach + directional imbalance.
    approach_feat = {a: series_stats(per_approach[a]) for a in "NSEW"}
    ns_avg = sum(approach_feat[a]["avg"] for a in "NS")
    ew_avg = sum(approach_feat[a]["avg"] for a in "EW")
    dominant = "EW" if ew_avg >= ns_avg else "NS"
    imbalance_ratio = round(max(ns_avg, ew_avg) / max(min(ns_avg, ew_avg), 0.1), 2)

    # Temporal profile.
    buckets = bucketize(times, total_q, bucket_seconds)
    peak_window = max(buckets, key=lambda b: b["avg_total_queue"]) if buckets else None

    # Pedestrian correlation.
    q_ped = series_stats(q_during["PED"])["avg"]
    q_veh = series_stats(q_during["VEH"])["avg"]
    ped_phase_share = round(100 * len(q_during["PED"]) / max(len(total_q), 1), 1)

    return {
        "junction_id": TLS_ID,
        "scenario": scenario,
        "controller": controller.name,
        "duration_s": int(times[-1]) if times else 0,
        "overall": {
            "avg_vehicle_wait_s": round(trip["avg_wait_s"], 2),
            "avg_pedestrian_delay_s": round(trip["avg_ped_delay_s"], 2),
            "avg_total_queue_veh": series_stats(total_q)["avg"],
            "peak_total_queue_veh": series_stats(total_q)["peak"],
            "num_vehicles": int(trip["num_vehicles"]),
            "num_pedestrians": int(trip["num_pedestrians"]),
        },
        "per_approach_queue": approach_feat,
        "directional_imbalance": {
            "ns_avg_queue": round(ns_avg, 2),
            "ew_avg_queue": round(ew_avg, 2),
            "dominant_axis": dominant,
            "imbalance_ratio": imbalance_ratio,
        },
        "temporal": {
            "bucket_seconds": bucket_seconds,
            "buckets": buckets,
            "peak_window": peak_window,
            "queue_trend": trend(total_q),
        },
        "pedestrians": {
            "avg_waiting_count": series_stats(ped_wait)["avg"],
            "peak_waiting_count": series_stats(ped_wait)["peak"],
            "ped_phase_time_share_pct": ped_phase_share,
            "avg_vehicle_queue_during_ped_phase": q_ped,
            "avg_vehicle_queue_during_vehicle_phase": q_veh,
            "ped_phase_backup_ratio": round(q_ped / max(q_veh, 0.1), 2),
        },
    }


def compute_temporal_summary(
    scenarios: tuple[str, ...] = ("offpeak", "weekday", "rush", "weekend"),
    *,
    use_cache: bool = True,
) -> dict:
    """Congestion metrics for the junction across time contexts (the 4 profiles).

    Feeds the Analyst's temporal-pattern statement. Results are deterministic
    (fixed seed) so they're cached to data/outputs/temporal.json after the first
    (multi-simulation) run.
    """
    cache_path = settings.outputs_dir / "temporal.json"
    if use_cache and cache_path.exists():
        return json.loads(cache_path.read_text())

    summary: dict = {"junction_id": TLS_ID, "scenarios": {}}
    for scen in scenarios:
        f = compute_features(scen)
        summary["scenarios"][scen] = {
            "time_context": SCENARIO_TIME_LABELS.get(scen, scen),
            "avg_vehicle_wait_s": f["overall"]["avg_vehicle_wait_s"],
            "avg_total_queue_veh": f["overall"]["avg_total_queue_veh"],
            "peak_total_queue_veh": f["overall"]["peak_total_queue_veh"],
            "dominant_axis": f["directional_imbalance"]["dominant_axis"],
            "imbalance_ratio": f["directional_imbalance"]["imbalance_ratio"],
            "avg_pedestrian_delay_s": f["overall"]["avg_pedestrian_delay_s"],
            "peak_pedestrian_waiting": f["pedestrians"]["peak_waiting_count"],
        }
    settings.ensure_dirs()
    cache_path.write_text(json.dumps(summary, indent=2))
    return summary
