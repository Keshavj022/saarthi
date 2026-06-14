from __future__ import annotations

import logging
from dataclasses import dataclass

from config.settings import settings
from control.max_pressure import MaxPressureController
from sim import network_defs
from sim.scenarios import loader
from sim.scenarios.loader import TLS_ID

log = logging.getLogger(__name__)

SPEED_LIMIT_KMH = 50.0
SPEED_LIMIT_MS = SPEED_LIMIT_KMH / 3.6  # 13.89 m/s

# Deterministic synthetic plate from a vehicle id (documented: no real camera).
_STATES = ["MH", "DL", "KA", "TN", "UP", "GJ", "RJ", "WB", "AP", "KL"]
_LETTERS = "ABCDEFGHJKLMNPRSTUVWXYZ"


def synth_plate(vehicle_id: str) -> str:
    h = 0
    for ch in vehicle_id:
        h = (h * 131 + ord(ch)) & 0xFFFFFFFF
    st = _STATES[h % len(_STATES)]
    rto = (h // 10) % 99 + 1
    s = _LETTERS[(h // 1000) % len(_LETTERS)] + _LETTERS[(h // 100) % len(_LETTERS)]
    num = (h // 7) % 9000 + 1000
    return f"{st}{rto:02d}{s}{num}"


@dataclass
class Violation:
    plate: str
    vehicle_id: str
    approach: str
    speed_kmh: float
    limit_kmh: float
    at_s: float


def _speeder_routes(ew: int, ns: int, duration: int) -> str:
    """A short demand with ~20% over-speeding drivers on each axis."""
    flows = []
    for fid, frm, to, rate in [("we", "W_in", "E_out", ew), ("ew", "E_in", "W_out", ew),
                               ("ns", "N_in", "S_out", ns), ("sn", "S_in", "N_out", ns)]:
        flows.append(f'<flow id="{fid}" type="car" begin="0" end="{duration}" '
                     f'from="{frm}" to="{to}" vehsPerHour="{int(rate * 0.8)}" '
                     f'departLane="best" departSpeed="max"/>')
        flows.append(f'<flow id="sp_{fid}" type="speeder" begin="0" end="{duration}" '
                     f'from="{frm}" to="{to}" vehsPerHour="{int(rate * 0.2)}" '
                     f'departLane="best" departSpeed="max"/>')
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<routes>\n'
        '  <vType id="car" length="5" minGap="2.5" maxSpeed="13.89"/>\n'
        '  <vType id="speeder" length="5" minGap="2.5" maxSpeed="26" '
        'speedFactor="1.45" speedDev="0.12"/>\n'
        '  ' + "\n  ".join(flows) + "\n</routes>\n")


def detect_violations(network: str = "cross", *, ew: int = 600, ns: int = 300,
                      duration: int = 240, limit: int = 8, progress=None) -> list[Violation]:
    """Run a short sim and return over-speed violations (highest first)."""
    loader.ensure_sumo_on_path()
    import traci

    settings.ensure_dirs()
    net = network_defs.build(network)
    route = settings.outputs_dir / "_violations.rou.xml"
    route.write_text(_speeder_routes(ew, ns, duration))
    controller = MaxPressureController(TLS_ID)
    traci.start([
        loader._binary("sumo"), "-n", str(net), "-r", str(route),
        "--step-length", "1", "--seed", "7", "--no-warnings", "true",
        "--no-step-log", "true", "--time-to-teleport", "-1",
    ])
    peak: dict[str, dict] = {}
    step = 0
    max_steps = duration * 2
    try:
        controller.reset()
        while traci.simulation.getMinExpectedNumber() > 0 and step < max_steps:
            controller.step(traci.simulation.getTime())
            traci.simulationStep()
            t = traci.simulation.getTime()
            for v in traci.vehicle.getIDList():
                sp = traci.vehicle.getSpeed(v)
                if sp > SPEED_LIMIT_MS * 1.10:
                    kmh = round(sp * 3.6, 1)
                    cur = peak.get(v)
                    if cur is None or kmh > cur["speed_kmh"]:
                        approach = traci.vehicle.getRoadID(v).split("_")[0]
                        peak[v] = {"speed_kmh": kmh,
                                   "approach": approach if approach in "NSEW" else v.split("_")[0],
                                   "at_s": t}
            step += 1
            if progress and step % 40 == 0:
                progress(t, len(peak))
    finally:
        traci.close()

    ranked = sorted(peak.items(), key=lambda kv: -kv[1]["speed_kmh"])[:limit]
    return [Violation(plate=synth_plate(vid), vehicle_id=vid, approach=d["approach"],
                      speed_kmh=d["speed_kmh"], limit_kmh=SPEED_LIMIT_KMH, at_s=d["at_s"])
            for vid, d in ranked]


def offline_challan_record(v: Violation) -> dict:
    """Deterministic challan from the REAL detected data — used when the AI is
    unavailable so a genuine violation is never dropped (only the wording is
    plainer than the AI draft)."""
    over = round(v.speed_kmh - v.limit_kmh, 1)
    fine = 2000 if over >= 20 else 1000
    notice = (
        "TRAFFIC VIOLATION NOTICE  (draft — for officer review)\n\n"
        f"Vehicle number: {v.plate}\n"
        "Violation: Over-speeding\n"
        f"Recorded speed: {v.speed_kmh} km/h in a {int(v.limit_kmh)} km/h zone "
        f"({over} km/h over the limit)\n"
        f"Location: Junction C, {v.approach} approach\n"
        f"Proposed fine: Rs {fine}\n\n"
        "This is a draft notice. It is subject to review by an enforcement officer "
        "and may be contested as per the rules.")
    return dict(
        plate=v.plate, violation_type="over_speeding", junction_id="C",
        timestamp=f"+{int(v.at_s)}s into the run", is_valid_violation=True,
        reasoning=(f"The camera measured {v.speed_kmh} km/h, {over} km/h over the "
                   f"{int(v.limit_kmh)} km/h limit — a clear, citable over-speeding case."),
        evidence_summary=(f"Measured {v.speed_kmh} km/h at junction C "
                          f"({v.approach} approach); speed limit {int(v.limit_kmh)} km/h."),
        fine_amount_inr=fine, draft_notice=notice, language="English", confidence=0.9)
