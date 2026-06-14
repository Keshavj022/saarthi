from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from config.settings import settings
from control.base import Controller
from sim.scenarios import loader

log = logging.getLogger(__name__)


@dataclass
class SimMetrics:
    """Summary metrics from a single scenario run under one controller."""

    scenario: str
    controller: str
    avg_wait_s: float
    avg_queue: float
    peak_queue: int
    num_vehicles: int
    avg_travel_time_s: float
    sim_steps: int
    num_pedestrians: int = 0
    avg_ped_delay_s: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    def save_json(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2))
        return path


def aggregate_queue(samples: list[int]) -> tuple[float, int]:
    """Return (mean, peak) of a list of per-step queue counts."""
    if not samples:
        return 0.0, 0
    return sum(samples) / len(samples), max(samples)


def summarize_tripinfo(path: str | Path) -> dict:
    """Parse a SUMO tripinfo XML and average over completed trips.

    Returns vehicle metrics (num_vehicles, avg_wait_s, avg_travel_time_s) and
    pedestrian metrics (num_pedestrians, avg_ped_delay_s) where pedestrian delay
    is SUMO `timeLoss` — time lost vs free-flow walking, i.e. crossing waits.
    """
    root = ET.parse(str(path)).getroot()
    waits: list[float] = []
    durations: list[float] = []
    for trip in root.findall("tripinfo"):
        waits.append(float(trip.get("waitingTime", 0.0)))
        durations.append(float(trip.get("duration", 0.0)))
    ped_delays: list[float] = [
        float(p.get("timeLoss", 0.0)) for p in root.findall("personinfo")
    ]
    n = len(waits)
    npd = len(ped_delays)
    return {
        "num_vehicles": n,
        "avg_wait_s": (sum(waits) / n) if n else 0.0,
        "avg_travel_time_s": (sum(durations) / n) if n else 0.0,
        "num_pedestrians": npd,
        "avg_ped_delay_s": (sum(ped_delays) / npd) if npd else 0.0,
    }


def run_scenario(
    scenario: str,
    controller: Controller,
    *,
    gui: bool | None = None,
    seed: int | None = None,
    max_steps: int | None = None,
) -> SimMetrics:
    """Run `scenario` under `controller` via TraCI and return its metrics.

    Raises SumoNotFoundError (or ImportError) if SUMO is not installed.
    """
    loader.ensure_sumo_on_path()  # fail fast & clearly if SUMO is missing
    import traci

    settings.ensure_dirs()
    loader.build_network()  # build the .net.xml from inputs if needed

    tripinfo = settings.outputs_dir / f"{scenario}.{controller.name}.tripinfo.xml"
    cmd = loader.sumo_cmd(
        scenario, gui=gui, seed=seed,
        extra=["--tripinfo-output", str(tripinfo)],
    )
    # Drain cap: keep stepping until all vehicles finish, but never hang forever.
    if max_steps is None:
        max_steps = settings.sim_duration * 3

    log.info("Starting SUMO: %s", " ".join(cmd))
    traci.start(cmd)
    try:
        controller.reset()
        lanes = loader.get_incoming_lanes(controller.tls_id)
        queue_samples: list[int] = []
        step = 0
        while traci.simulation.getMinExpectedNumber() > 0 and step < max_steps:
            controller.step(traci.simulation.getTime())
            traci.simulationStep()
            q = sum(traci.lane.getLastStepHaltingNumber(lane) for lane in lanes)
            queue_samples.append(q)
            step += 1
        if step >= max_steps and traci.simulation.getMinExpectedNumber() > 0:
            log.warning(
                "Hit max_steps=%d with %d vehicles still in the network "
                "(possible gridlock); metrics cover completed trips only.",
                max_steps, traci.simulation.getMinExpectedNumber(),
            )
    finally:
        traci.close()

    trip = summarize_tripinfo(tripinfo)
    avg_q, peak_q = aggregate_queue(queue_samples)
    metrics = SimMetrics(
        scenario=scenario,
        controller=controller.name,
        avg_wait_s=round(trip["avg_wait_s"], 2),
        avg_queue=round(avg_q, 2),
        peak_queue=int(peak_q),
        num_vehicles=int(trip["num_vehicles"]),
        avg_travel_time_s=round(trip["avg_travel_time_s"], 2),
        sim_steps=step,
        num_pedestrians=int(trip["num_pedestrians"]),
        avg_ped_delay_s=round(trip["avg_ped_delay_s"], 2),
    )
    log.info("Run complete: %s", metrics.to_dict())
    return metrics
