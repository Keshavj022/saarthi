"""Parameterized live simulation engine for the dashboard.

Builds a demand profile from dashboard parameters (East-West / North-South
vehicle rates + pedestrian rate), runs the chosen controller via TraCI, and
streams per-step state (queues per approach, current phase, pedestrians waiting,
running average wait) so the UI can animate it. Final metrics come from SUMO's
tripinfo. Kept independent of Streamlit so it can be tested headless.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional

from config.settings import settings
from control.fixed_time import FixedTimeController
from control.max_pressure import MaxPressureController
from core.metrics import summarize_tripinfo
from sim.scenarios import loader
from sim.scenarios.loader import TLS_ID

log = logging.getLogger(__name__)

CONTROLLERS = {
    "fixed_time": FixedTimeController,
    "max_pressure": MaxPressureController,
}
APPROACHES = ("N", "S", "E", "W")


@dataclass
class LiveConfig:
    """Parameters chosen in the dashboard."""

    controller: str = "max_pressure"      # 'fixed_time' | 'max_pressure'
    ew_vph: int = 650                     # E-W through volume per direction
    ns_vph: int = 220                     # N-S through volume per direction
    ped_per_hour: int = 240               # total pedestrians/hour across crossings
    duration: int = 600                   # simulated seconds
    seed: int = 42


@dataclass
class StepState:
    """Snapshot of the junction at one simulation step."""

    t: float
    phase: str
    queues: dict[str, int]
    total_queue: int
    peds_waiting: int
    arrived: int
    running_avg_wait: float


@dataclass
class LiveResult:
    """Final metrics after a live run (from tripinfo)."""

    avg_wait_s: float = 0.0
    avg_ped_delay_s: float = 0.0
    peak_total_queue: int = 0
    num_vehicles: int = 0
    num_pedestrians: int = 0
    sim_steps: int = 0


def _routes_xml(cfg: LiveConfig) -> str:
    ew_turn = round(cfg.ew_vph * 0.2)
    ns_turn = round(cfg.ns_vph * 0.3)
    pf = max(cfg.ped_per_hour // 8, 0)
    flows = [
        ("W_E", "W_in", "E_out", cfg.ew_vph), ("W_N", "W_in", "N_out", ew_turn),
        ("W_S", "W_in", "S_out", ew_turn),
        ("E_W", "E_in", "W_out", cfg.ew_vph), ("E_N", "E_in", "N_out", ew_turn),
        ("E_S", "E_in", "S_out", ew_turn),
        ("N_S", "N_in", "S_out", cfg.ns_vph), ("N_E", "N_in", "E_out", ns_turn),
        ("N_W", "N_in", "W_out", ns_turn),
        ("S_N", "S_in", "N_out", cfg.ns_vph), ("S_E", "S_in", "E_out", ns_turn),
        ("S_W", "S_in", "W_out", ns_turn),
    ]
    veh = "\n".join(
        f'    <flow id="{i}" type="car" begin="0" end="{cfg.duration}" '
        f'from="{frm}" to="{to}" vehsPerHour="{v}" departLane="best" departSpeed="max"/>'
        for (i, frm, to, v) in flows if v > 0
    )
    ped_pairs = [("W_in", "N_out"), ("W_in", "S_out"), ("E_in", "N_out"),
                 ("E_in", "S_out"), ("N_in", "E_out"), ("N_in", "W_out"),
                 ("S_in", "E_out"), ("S_in", "W_out")]
    peds = "\n".join(
        f'    <personFlow id="p{k}" type="ped" begin="0" end="{cfg.duration}" '
        f'perHour="{pf}"><walk from="{frm}" to="{to}"/></personFlow>'
        for k, (frm, to) in enumerate(ped_pairs)
    ) if pf > 0 else ""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<routes>\n'
        '    <vType id="car" accel="2.6" decel="4.5" sigma="0.5" length="5.0" '
        'minGap="2.5" maxSpeed="13.89" guiShape="passenger"/>\n'
        '    <vType id="ped" vClass="pedestrian"/>\n'
        f"{veh}\n{peds}\n</routes>\n"
    )


class LiveSim:
    """Runs a parameterized sim, yielding per-step state; sets `result` at the end."""

    def __init__(self, cfg: LiveConfig) -> None:
        self.cfg = cfg
        self.result: Optional[LiveResult] = None

    def steps(self) -> Iterator[StepState]:
        loader.ensure_sumo_on_path()
        import traci

        settings.ensure_dirs()
        loader.build_network()
        route_path = settings.outputs_dir / "_live.rou.xml"
        route_path.write_text(_routes_xml(self.cfg))
        tripinfo = settings.outputs_dir / "_live.tripinfo.xml"

        ctrl_cls = CONTROLLERS.get(self.cfg.controller, MaxPressureController)
        controller = ctrl_cls(TLS_ID)

        binary = loader._binary("sumo")
        cmd = [
            binary, "-n", str(loader.NET_FILE), "-r", str(route_path),
            "--step-length", "1", "--seed", str(self.cfg.seed),
            "--no-warnings", "true", "--no-step-log", "true",
            "--duration-log.disable", "true", "--time-to-teleport", "-1",
            "--waiting-time-memory", "100000", "--tripinfo-output", str(tripinfo),
        ]

        traci.start(cmd)
        peak_q = 0
        step = 0
        max_steps = self.cfg.duration * 3
        per_veh_wait: dict[str, float] = {}
        try:
            controller.reset()
            ns_lanes = controller.phases.incoming_lanes["NS"]
            ew_lanes = controller.phases.incoming_lanes["EW"]
            approach_lanes: dict[str, list[str]] = {a: [] for a in APPROACHES}
            for lane in ns_lanes + ew_lanes:
                approach_lanes[lane[0]].append(lane)
            walk_edges = set(controller.phases.walk_edges)

            while traci.simulation.getMinExpectedNumber() > 0 and step < max_steps:
                controller.step(traci.simulation.getTime())
                traci.simulationStep()
                t = traci.simulation.getTime()

                queues = {
                    a: sum(traci.lane.getLastStepHaltingNumber(l) for l in lanes)
                    for a, lanes in approach_lanes.items()
                }
                total_q = sum(queues.values())
                peak_q = max(peak_q, total_q)

                peds_waiting = sum(
                    1 for p in traci.person.getIDList()
                    if traci.person.getRoadID(p) in walk_edges
                    and traci.person.getSpeed(p) < 0.3
                )
                for v in traci.vehicle.getIDList():
                    per_veh_wait[v] = traci.vehicle.getAccumulatedWaitingTime(v)
                running_avg = (sum(per_veh_wait.values()) / len(per_veh_wait)
                               if per_veh_wait else 0.0)

                step += 1
                yield StepState(
                    t=t, phase=controller.current, queues=queues,
                    total_queue=total_q, peds_waiting=peds_waiting,
                    arrived=traci.simulation.getArrivedNumber(),
                    running_avg_wait=round(running_avg, 1),
                )
        finally:
            traci.close()

        trip = summarize_tripinfo(tripinfo)
        self.result = LiveResult(
            avg_wait_s=round(trip["avg_wait_s"], 2),
            avg_ped_delay_s=round(trip["avg_ped_delay_s"], 2),
            peak_total_queue=int(peak_q),
            num_vehicles=int(trip["num_vehicles"]),
            num_pedestrians=int(trip["num_pedestrians"]),
            sim_steps=step,
        )
