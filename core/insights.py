from __future__ import annotations

import logging
from typing import Optional

from config.settings import settings
from control.fixed_time import FixedTimeController
from core.metrics import summarize_tripinfo
from sim.scenarios import loader
from sim.scenarios.loader import TLS_ID

log = logging.getLogger(__name__)

def mmss(t: float) -> str:
    """Real elapsed simulation time as MM:SS (e.g. 12:00 = 12 minutes in)."""
    t = int(t)
    return f"{t // 60:02d}:{t % 60:02d}"


def top_episodes(samples: list[tuple[float, int]], k: int = 3,
                 min_gap: float = 300.0) -> list[tuple[float, int]]:
    """Pick the k highest-queue moments, at least `min_gap` seconds apart."""
    chosen: list[tuple[float, int]] = []
    pool = sorted(samples, key=lambda s: -s[1])
    for t, q in pool:
        if len(chosen) >= k:
            break
        if all(abs(t - ct) >= min_gap for ct, _ in chosen):
            chosen.append((t, q))
    return sorted(chosen)


def _collect_instances(scenario: str) -> dict:
    """One fixed-time run; returns summary + concrete instances."""
    loader.ensure_sumo_on_path()
    import traci

    settings.ensure_dirs()
    loader.build_network()
    controller = FixedTimeController(TLS_ID)
    tripinfo = settings.outputs_dir / f"{scenario}.details.tripinfo.xml"
    traci.start(loader.sumo_cmd(scenario, extra=["--tripinfo-output", str(tripinfo)]))

    samples: list[tuple[float, int]] = []
    detail_at: dict[float, dict] = {}
    veh_wait: dict[str, float] = {}
    ped_peak = (0.0, 0)
    max_steps = settings.sim_duration * 3
    step = 0
    try:
        controller.reset()
        lanes_by_approach: dict[str, list[str]] = {a: [] for a in "NSEW"}
        for lane in (controller.phases.incoming_lanes["NS"]
                     + controller.phases.incoming_lanes["EW"]):
            lanes_by_approach[lane[0]].append(lane)
        walk = set(controller.phases.walk_edges)

        while traci.simulation.getMinExpectedNumber() > 0 and step < max_steps:
            controller.step(traci.simulation.getTime())
            traci.simulationStep()
            t = traci.simulation.getTime()
            queues = {a: sum(traci.lane.getLastStepHaltingNumber(l) for l in ls)
                      for a, ls in lanes_by_approach.items()}
            total = sum(queues.values())
            samples.append((t, total))
            detail_at[t] = {"queues": queues, "phase": controller.current}
            for v in traci.vehicle.getIDList():
                veh_wait[v] = max(veh_wait.get(v, 0.0),
                                  traci.vehicle.getAccumulatedWaitingTime(v))
            waiting = sum(1 for p in traci.person.getIDList()
                          if traci.person.getRoadID(p) in walk
                          and traci.person.getSpeed(p) < 0.3)
            if waiting > ped_peak[1]:
                ped_peak = (t, waiting)
            step += 1
    finally:
        traci.close()

    episodes = []
    for t, q in top_episodes(samples, k=3):
        d = detail_at.get(t, {})
        episodes.append({
            "t": t, "at": mmss(t), "total_queue": q,
            "queues": d.get("queues", {}), "phase": d.get("phase", "?"),
        })
    worst = sorted(veh_wait.items(), key=lambda kv: -kv[1])[:5]
    worst_vehicles = [{"id": vid, "approach": vid[0], "wait_s": round(w, 1)}
                      for vid, w in worst]
    trip = summarize_tripinfo(tripinfo)
    timeline = [{"t": t, "q": q} for t, q in samples if int(t) % 60 == 0]
    return {
        "scenario": scenario,
        "summary": {
            "avg_vehicle_wait_s": round(trip["avg_wait_s"], 2),
            "avg_pedestrian_delay_s": round(trip["avg_ped_delay_s"], 2),
            "num_vehicles": int(trip["num_vehicles"]),
            "num_pedestrians": int(trip["num_pedestrians"]),
            "peak_total_queue": max((q for _, q in samples), default=0),
        },
        "episodes": episodes,
        "worst_vehicles": worst_vehicles,
        "ped_peak": {"t": ped_peak[0], "at": mmss(ped_peak[0]),
                     "waiting": ped_peak[1]},
        "timeline": timeline,
    }


DEEP_DIVE_SYSTEM = """You are a senior traffic engineer writing a detailed incident \
review for an Indian traffic-control room. You receive concrete INSTANCES from a \
simulation of one junction under its current fixed-timer signal: the worst congestion \
moments (with the time into the run as MM:SS, per-approach queues and which direction \
was being given green), the vehicles that waited longest, the pedestrian peak, and \
overall numbers — plus the before/after comparison for adaptive signal control.

Write a deep-dive the operator can act on:
- diagnosis: 2-4 plain-language paragraphs explaining the mechanism of the congestion,
  anchored to the actual instances (cite the MM:SS times and numbers).
- evidence: one bullet per instance, tying it to the diagnosis.
- actions: prioritised concrete steps (signal-timing change first, then supporting measures).
- expected_outcome: what the operator should expect after the fix, quantified from the
  comparison when available. Never invent numbers that are not in the data.

PLAIN LANGUAGE ONLY — a non-technical official must understand every word. Never use
jargon or software/algorithm names ("max-pressure", "reinforcement learning", "SUMO",
etc.). Say "adaptive signal control" / "smart signal timing"."""


def build_detailed_report(scenario: str, benchmark: Optional[dict] = None,
                          verdict: Optional[dict] = None) -> dict:
    """Collect instances from a run, then ask the AI for the deep-dive narrative."""
    import json

    from core import llm
    from core.models import DetailedAnalysis

    report = _collect_instances(scenario)
    prompt_parts = ["SIMULATION INSTANCES:", json.dumps(
        {k: report[k] for k in ("scenario", "summary", "episodes",
                                "worst_vehicles", "ped_peak")}, indent=2)]
    if benchmark and benchmark.get("scenario") == scenario:
        prompt_parts += ["\nBENCHMARK (fixed-time vs adaptive):",
                         json.dumps({k: benchmark[k] for k in
                                     ("wait_reduction_pct", "ped_delay_reduction_pct")
                                     if k in benchmark})]
    if verdict:
        prompt_parts += ["\nEXISTING ROOT-CAUSE VERDICT (be consistent with it):",
                         json.dumps({"primary_cause": verdict.get("primary_cause"),
                                     "headline": verdict.get("headline")})]
    prompt_parts.append("\nWrite the deep-dive review.")
    analysis: DetailedAnalysis = llm.structured(
        "\n".join(prompt_parts), DetailedAnalysis, system=DEEP_DIVE_SYSTEM)
    report["analysis"] = analysis.model_dump()
    return report
