"""Shared signal-phase machinery for the single junction.

Both the fixed-time baseline and the max-pressure controller drive the same
three logical phases, so the benchmark compares *policies* (how a phase is
chosen), not different signal plans:

  * NS  — vehicles on the North & South approaches get green (all else red),
  * EW  — vehicles on the East & West approaches get green,
  * PED — an exclusive pedestrian phase: all vehicles red, all crossings green.

`classify()` discovers which TLS link indices belong to each phase at runtime
(from `getControlledLinks`), so the code is not tied to a hand-counted signal
state string. `PhasedController` implements the green→yellow→all-red→green state
machine and re-asserts the desired light state every step (robust against SUMO's
built-in program trying to advance underneath us). Subclasses implement only
`select_phase()` — the decision policy.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from control.base import Controller

log = logging.getLogger(__name__)

GREEN, YELLOW, RED = "G", "y", "r"
PHASES = ("NS", "EW", "PED")


@dataclass
class JunctionPhases:
    """Link-index layout of one junction, plus the lanes/edges used for sensing."""

    tls_id: str
    n_links: int
    phase_idx: dict[str, list[int]]            # "NS"/"EW"/"PED" -> link indices
    incoming_lanes: dict[str, list[str]]       # "NS"/"EW" -> vehicle approach lanes
    walk_edges: list[str]                      # junction walking areas (:C_w*)
    cross_edges: list[str]                     # junction crossings (:C_c*)
    _sets: dict[str, set[int]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._sets = {p: set(self.phase_idx.get(p, [])) for p in PHASES}

    def green_state(self, phase: str) -> str:
        on = self._sets[phase]
        return "".join(GREEN if i in on else RED for i in range(self.n_links))

    def yellow_state(self, phase: str) -> str:
        """Yellow for the *vehicle* movements leaving green; crossings drop to red
        (pedestrian clearance is handled by the following all-red interval)."""
        if phase == "PED":
            return RED * self.n_links
        on = self._sets[phase]
        return "".join(YELLOW if i in on else RED for i in range(self.n_links))

    def all_red_state(self) -> str:
        return RED * self.n_links


def _edge_of(lane_id: str) -> str:
    import traci

    try:
        return traci.lane.getEdgeID(lane_id)
    except traci.TraCIException:
        return lane_id.rsplit("_", 1)[0]


def classify(tls_id: str) -> JunctionPhases:
    """Inspect the live TLS and group its controlled links into NS/EW/PED."""
    import traci

    links = traci.trafficlight.getControlledLinks(tls_id)
    n = len(links)
    phase_idx: dict[str, list[int]] = {"NS": [], "EW": [], "PED": []}
    ns_lanes: set[str] = set()
    ew_lanes: set[str] = set()
    walk: set[str] = set()
    cross: set[str] = set()

    for i, link_list in enumerate(links):
        if not link_list:
            continue
        from_lane, to_lane, via = link_list[0]
        via_lane = via or to_lane
        allowed = traci.lane.getAllowed(via_lane) if via_lane else ()
        is_crossing = ("pedestrian" in allowed) or ("_c" in (via or ""))
        if is_crossing:
            phase_idx["PED"].append(i)
            if via:
                cross.add(_edge_of(via))
            walk.add(_edge_of(from_lane))
            walk.add(_edge_of(to_lane))
            continue
        approach = from_lane.split("_")[0]  # 'N_in_1' -> 'N'
        if approach in ("N", "S"):
            phase_idx["NS"].append(i)
            ns_lanes.add(from_lane)
        else:
            phase_idx["EW"].append(i)
            ew_lanes.add(from_lane)

    jp = JunctionPhases(
        tls_id=tls_id,
        n_links=n,
        phase_idx=phase_idx,
        incoming_lanes={"NS": sorted(ns_lanes), "EW": sorted(ew_lanes)},
        walk_edges=sorted(e for e in walk if e.startswith(":")),
        cross_edges=sorted(cross),
    )
    log.info(
        "Junction %s classified: NS=%s EW=%s PED=%s",
        tls_id, jp.phase_idx["NS"], jp.phase_idx["EW"], jp.phase_idx["PED"],
    )
    return jp


class PhasedController(Controller):
    """Green→yellow→all-red→green state machine over the NS/EW/PED phases.

    Subclasses implement `select_phase(sim_time) -> phase` (the policy). Timing
    constants are safety/realism parameters shared by both controllers.
    """

    yellow_time: float = 3.0
    all_red_time: float = 2.0
    veh_min_green: float = 10.0
    ped_min_green: float = 12.0  # enough time to walk across an arm

    def __init__(self, tls_id: str) -> None:
        super().__init__(tls_id)
        self.phases: JunctionPhases | None = None
        self.current: str = "NS"
        self._mode: str = "green"            # green | yellow | allred
        self._state: str = ""
        self._phase_start: float = 0.0
        self._mode_until: float = 0.0
        self._pending: str | None = None

    # --- lifecycle ---
    def reset(self) -> None:
        self.phases = classify(self.tls_id)
        self.current = "NS"
        self._mode = "green"
        self._phase_start = 0.0
        self._state = self.phases.green_state("NS")

    def min_green_for(self, phase: str) -> float:
        return self.ped_min_green if phase == "PED" else self.veh_min_green

    # --- per-step ---
    def step(self, sim_time: float) -> None:
        import traci

        if self._mode == "green":
            if sim_time - self._phase_start >= self.min_green_for(self.current):
                nxt = self.select_phase(sim_time)
                if nxt != self.current:
                    self._begin_yellow(sim_time, nxt)
        elif self._mode == "yellow":
            if sim_time >= self._mode_until:
                self._begin_allred(sim_time)
        elif self._mode == "allred":
            if sim_time >= self._mode_until:
                self._begin_green(sim_time, self._pending or self.current)

        # Re-assert the desired light state every step.
        traci.trafficlight.setRedYellowGreenState(self.tls_id, self._state)

    # --- transitions ---
    def _begin_yellow(self, t: float, nxt: str) -> None:
        self._state = self.phases.yellow_state(self.current)
        self._pending = nxt
        self._mode = "yellow"
        self._mode_until = t + self.yellow_time

    def _begin_allred(self, t: float) -> None:
        self._state = self.phases.all_red_state()
        self._mode = "allred"
        self._mode_until = t + self.all_red_time

    def _begin_green(self, t: float, phase: str) -> None:
        self.current = phase
        self._pending = None
        self._state = self.phases.green_state(phase)
        self._mode = "green"
        self._phase_start = t

    # --- sensing helpers (shared) ---
    def vehicle_pressure(self, group: str) -> int:
        """Queued (halting) vehicles on a vehicle phase's incoming lanes."""
        import traci

        return sum(
            traci.lane.getLastStepHaltingNumber(lane)
            for lane in self.phases.incoming_lanes[group]
        )

    def pedestrian_demand(self) -> tuple[int, float]:
        """(count, longest_wait) of pedestrians stopped at the junction's
        walking areas — i.e. waiting for a crossing."""
        import traci

        zone = set(self.phases.walk_edges) | set(self.phases.cross_edges)
        count = 0
        longest = 0.0
        for p in traci.person.getIDList():
            if traci.person.getRoadID(p) in zone and traci.person.getSpeed(p) < 0.3:
                count += 1
                longest = max(longest, traci.person.getWaitingTime(p))
        return count, longest

    def approach_signals(self) -> dict[str, str]:
        """Current light colour per approach ('G'/'y'/'r') for visualization."""
        green_group = {"NS": ("N", "S"), "EW": ("E", "W"), "PED": ()}[self.current]
        colour = {"green": "G", "yellow": "y", "allred": "r"}[self._mode]
        return {a: (colour if a in green_group else "r") for a in ("N", "S", "E", "W")}

    # --- policy (subclasses implement) ---
    def select_phase(self, sim_time: float) -> str:  # pragma: no cover - abstract
        raise NotImplementedError
