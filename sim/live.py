from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Iterator, Optional

from config.settings import settings
from control.fixed_time import FixedTimeController
from control.max_pressure import MaxPressureController
from core.metrics import summarize_tripinfo
from sim import network_defs
from sim.scenarios import loader

log = logging.getLogger(__name__)

TLS_ID = "C"
APPROACHES = ("N", "S", "E", "W")
OPPOSITE = {"N": "S", "S": "N", "E": "W", "W": "E"}
AXIS = {"N": "ns", "S": "ns", "E": "ew", "W": "ew"}

#: Traffic mixes: vType id -> share of each flow. 'cars' is the clean baseline;
#: 'mixed' approximates Indian urban traffic (two-wheelers + buses in the stream).
MIXES = {
    "cars": {"car": 1.0},
    "mixed": {"car": 0.62, "moto": 0.28, "bus": 0.10},
}
VTYPE_XML = {
    "car": ('    <vType id="car" accel="2.6" decel="4.5" sigma="0.5" length="5.0" '
            'minGap="2.5" maxSpeed="13.89" guiShape="passenger"/>'),
    "moto": ('    <vType id="moto" vClass="motorcycle" accel="3.2" decel="5.0" '
             'sigma="0.6" length="2.2" minGap="1.2" maxSpeed="13.89"/>'),
    "bus": ('    <vType id="bus" vClass="bus" accel="1.3" decel="4.0" sigma="0.4" '
            'length="11.0" minGap="3.0" maxSpeed="11.0"/>'),
}


@dataclass
class LiveConfig:
    """Parameters chosen in the web app."""

    controller: str = "max_pressure"      # 'fixed_time' | 'max_pressure' | 'rl'
    network: str = "cross"                # see sim.network_defs.NETWORKS
    mix: str = "cars"                     # 'cars' | 'mixed'
    ew_vph: int = 650                     # E-W through volume per direction
    ns_vph: int = 220                     # N-S through volume per direction
    ped_per_hour: int = 240               # pedestrians/hour per crossing approach (per arm)
    duration: int = 480                   # simulated seconds of demand
    seed: int = 42


@dataclass
class StepState:
    """Coarse snapshot of the junction at one simulation step."""

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


def make_controller(name: str, tls_id: str = TLS_ID):
    """Instantiate a controller by name. 'rl' requires the trained model."""
    if name == "rl":
        model = settings.outputs_dir / "rl_policy.zip"
        if not model.exists():
            raise RuntimeError(
                "RL model not found — train it first: python scripts/train_rl.py")
        from control.rl.rl_controller import RLController

        return RLController(tls_id, str(model))
    cls = {"fixed_time": FixedTimeController,
           "max_pressure": MaxPressureController}.get(name)
    if cls is None:
        raise ValueError(f"Unknown controller {name!r}")
    return cls(tls_id)


def _flow_lines(cfg: LiveConfig, arms: dict[str, int]) -> list[str]:
    """Vehicle flows between every ordered arm pair, split across the mix."""
    shares = MIXES.get(cfg.mix, MIXES["cars"])
    rate_of = {a: (cfg.ew_vph if AXIS[a] == "ew" else cfg.ns_vph) for a in arms}
    lines: list[str] = []
    for a in arms:
        targets = [b for b in arms if b != a]
        if not targets:
            continue
        has_through = OPPOSITE[a] in arms
        for b in targets:
            through = OPPOSITE[a] == b
            base = rate_of[a] * (1.0 if through else (0.25 if has_through else 0.5))
            for vt, share in shares.items():
                vph = round(base * share)
                if vph <= 0:
                    continue
                lines.append(
                    f'    <flow id="{a}_{b}_{vt}" type="{vt}" begin="0" '
                    f'end="{cfg.duration}" from="{a}_in" to="{b}_out" '
                    f'vehsPerHour="{vph}" departLane="best" departSpeed="max"/>')
    return lines


def _ped_lines(cfg: LiveConfig, arms: dict[str, int]) -> list[str]:

    arm_list = list(arms)
    if len(arm_list) < 2 or cfg.ped_per_hour <= 0:
        return []
    # Spawn ~20 m back from the junction so people walk straight into frame. Must
    # stay safely below the netconvert-trimmed sidewalk length (≈ ARM_LEN minus the
    # junction radius, ~10 m), so ARM_LEN-20 keeps a comfortable margin on every net.
    near = max(network_defs.ARM_LEN - 20.0, 20.0)
    rate = max(cfg.ped_per_hour, 1)
    lines: list[str] = []
    for k, a in enumerate(arm_list):
        opp = OPPOSITE.get(a)
        dest = opp if opp in arms else next(b for b in arm_list if b != a)
        # NOTE: departPos must sit on the <personFlow>, not the <walk> — SUMO
        # ignores it on the walk stage and people then spawn at the far arm end
        # (off-camera). On the flow it places them near the junction as intended.
        lines.append(
            f'    <personFlow id="p{a}" type="ped" begin="0" end="{cfg.duration}" '
            f'perHour="{rate}" departPos="{near:.1f}"><walk from="{a}_in" '
            f'to="{dest}_out"/></personFlow>')
    return lines


def _routes_xml(cfg: LiveConfig) -> str:
    arms = network_defs.NETWORKS[cfg.network]["arms"]
    vtypes = [VTYPE_XML[vt] for vt in MIXES.get(cfg.mix, MIXES["cars"])]
    vtypes.append('    <vType id="ped" vClass="pedestrian"/>')
    # roundabouts are built signal- and crossing-free → vehicles only.
    peds = [] if network_defs.kind_of(cfg.network) == "roundabout" else _ped_lines(cfg, arms)
    body = "\n".join(vtypes + _flow_lines(cfg, arms) + peds)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<routes>\n{body}\n</routes>\n'


class LiveSim:
    """Runs one parameterized simulation; offers step/frame generators."""

    def __init__(self, cfg: LiveConfig) -> None:
        self.cfg = cfg
        self.result: Optional[LiveResult] = None

    # ------------------------- shared run scaffolding -------------------------
    def _launch(self):
        loader.ensure_sumo_on_path()
        import traci

        settings.ensure_dirs()
        net = network_defs.build(self.cfg.network)
        route_path = settings.outputs_dir / "_live.rou.xml"
        route_path.write_text(_routes_xml(self.cfg))
        self._tripinfo = settings.outputs_dir / "_live.tripinfo.xml"
        # The roundabout is now metered (a shared TLS "C" gates each entry), so it
        # runs under the chosen controller just like any signalised junction.
        controller = make_controller(self.cfg.controller)
        cmd = [
            loader._binary("sumo"), "-n", str(net), "-r", str(route_path),
            "--step-length", "1", "--seed", str(self.cfg.seed),
            "--no-warnings", "true", "--no-step-log", "true",
            "--duration-log.disable", "true", "--time-to-teleport", "-1",
            "--waiting-time-memory", "100000",
            "--tripinfo-output", str(self._tripinfo),
        ]
        traci.start(cmd)
        controller.reset()
        approach_lanes: dict[str, list[str]] = {a: [] for a in APPROACHES}
        for lane in (controller.phases.incoming_lanes["NS"]
                     + controller.phases.incoming_lanes["EW"]):
            approach_lanes[lane[0]].append(lane)
        walk_edges = set(controller.phases.walk_edges)
        return traci, controller, approach_lanes, walk_edges

    def _finalize(self, peak_q: int, steps: int) -> None:
        trip = summarize_tripinfo(self._tripinfo)
        self.result = LiveResult(
            avg_wait_s=round(trip["avg_wait_s"], 2),
            avg_ped_delay_s=round(trip["avg_ped_delay_s"], 2),
            peak_total_queue=int(peak_q),
            num_vehicles=int(trip["num_vehicles"]),
            num_pedestrians=int(trip["num_pedestrians"]),
            sim_steps=steps,
        )

    def result_dict(self) -> dict:
        return asdict(self.result) if self.result else {}

    # ------------------------------ consumers ------------------------------
    def steps(self) -> Iterator[StepState]:
        """Coarse per-step state (no per-vehicle payload)."""
        traci, controller, approach_lanes, walk_edges = self._launch()
        peak_q = step = 0
        per_veh_wait: dict[str, float] = {}
        max_steps = self.cfg.duration * 3
        try:
            while traci.simulation.getMinExpectedNumber() > 0 and step < max_steps:
                controller.step(traci.simulation.getTime())
                traci.simulationStep()
                queues = {a: sum(traci.lane.getLastStepHaltingNumber(l) for l in lanes)
                          for a, lanes in approach_lanes.items()}
                total_q = sum(queues.values())
                peak_q = max(peak_q, total_q)
                peds_waiting = sum(
                    1 for p in traci.person.getIDList()
                    if traci.person.getRoadID(p) in walk_edges
                    and traci.person.getSpeed(p) < 0.3)
                for v in traci.vehicle.getIDList():
                    per_veh_wait[v] = traci.vehicle.getAccumulatedWaitingTime(v)
                running = (sum(per_veh_wait.values()) / len(per_veh_wait)
                           if per_veh_wait else 0.0)
                step += 1
                yield StepState(
                    t=traci.simulation.getTime(), phase=controller.current,
                    queues=queues, total_queue=total_q, peds_waiting=peds_waiting,
                    arrived=traci.simulation.getArrivedNumber(),
                    running_avg_wait=round(running, 1))
        finally:
            traci.close()
        self._finalize(peak_q, step)

    def stream_frames(self) -> Iterator[dict]:
        """Rich frames with per-vehicle positions for the canvas animation."""
        traci, controller, approach_lanes, walk_edges = self._launch()
        peak_q = step = 0
        per_veh_wait: dict[str, float] = {}
        max_steps = self.cfg.duration * 3
        try:
            while traci.simulation.getMinExpectedNumber() > 0 and step < max_steps:
                controller.step(traci.simulation.getTime())
                traci.simulationStep()
                vehicles = []
                for v in traci.vehicle.getIDList():
                    x, y = traci.vehicle.getPosition(v)
                    vehicles.append({
                        "id": v, "x": round(x, 1), "y": round(y, 1),
                        "a": round(traci.vehicle.getAngle(v), 1),
                        "s": round(traci.vehicle.getSpeed(v), 1),
                        "t": traci.vehicle.getTypeID(v)[0],  # c / m / b
                    })
                peds = []
                for p in traci.person.getIDList():
                    x, y = traci.person.getPosition(p)
                    peds.append({"id": p, "x": round(x, 1), "y": round(y, 1),
                                 "a": round(traci.person.getAngle(p), 1),
                                 "w": 1 if traci.person.getSpeed(p) < 0.3 else 0})

                total_q = sum(traci.lane.getLastStepHaltingNumber(l)
                              for lanes in approach_lanes.values() for l in lanes)
                peak_q = max(peak_q, total_q)
                peds_waiting = sum(
                    1 for p in traci.person.getIDList()
                    if traci.person.getRoadID(p) in walk_edges
                    and traci.person.getSpeed(p) < 0.3)
                for v in traci.vehicle.getIDList():
                    per_veh_wait[v] = traci.vehicle.getAccumulatedWaitingTime(v)
                running = (sum(per_veh_wait.values()) / len(per_veh_wait)
                           if per_veh_wait else 0.0)
                step += 1
                yield {
                    "type": "frame",
                    "t": round(traci.simulation.getTime(), 0),
                    "phase": controller.current,
                    "signals": controller.approach_signals(),
                    "ped_phase": controller.current == "PED",
                    "vehicles": vehicles,
                    "peds": peds,
                    "metrics": {
                        "total_queue": total_q,
                        "peds_waiting": peds_waiting,
                        "avg_wait": round(running, 1),
                        "arrived": traci.simulation.getArrivedNumber(),
                    },
                }
        finally:
            traci.close()
        self._finalize(peak_q, step)


def run_combo(network: str, controller: str, *, ew: int, ns: int, ped: int,
              duration: int, mix: str = "cars",
              sample_every: float = 5.0) -> tuple[dict, list[dict]]:
    cfg = LiveConfig(controller=controller, network=network, mix=mix,
                     ew_vph=ew, ns_vph=ns, ped_per_hour=ped, duration=duration)
    sim = LiveSim(cfg)
    timeline: list[dict] = []
    last = -1e9
    for s in sim.steps():
        if s.t - last >= sample_every:
            timeline.append({"t": s.t, "q": s.total_queue, "w": s.running_avg_wait})
            last = s.t
    return sim.result_dict(), timeline
