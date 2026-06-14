"""No-signal controller for roundabout networks.

A roundabout has no traffic light to actuate — vehicles yield on entry and
circulate. This controller therefore does nothing per step; it exists only so
the live-simulation engine (`sim.live.LiveSim`) can drive a roundabout through
the same loop it uses for signalised junctions. It exposes the small surface
`LiveSim` reads: `reset()`, `step()`, `current`, `approach_signals()`, and a
`phases` object carrying the per-approach incoming lanes (for queue sensing).
"""
from __future__ import annotations

from dataclasses import dataclass, field

ARMS = ("N", "S", "E", "W")


@dataclass
class _RingPhases:
    """Minimal stand-in for `JunctionPhases` — only the fields LiveSim reads."""

    incoming_lanes: dict[str, list[str]]
    walk_edges: list[str] = field(default_factory=list)
    cross_edges: list[str] = field(default_factory=list)


class NullController:
    """Drives a roundabout: no signals, just observe and circulate."""

    def __init__(self, tls_id: str = "C") -> None:
        self.tls_id = tls_id
        self.current = "FLOW"
        self.phases: _RingPhases | None = None

    def reset(self) -> None:
        """Group the arm approach lanes into NS/EW for queue sensing (no TLS)."""
        import traci

        ns: list[str] = []
        ew: list[str] = []
        for arm in ARMS:
            edge = f"{arm}_in"
            try:
                n_lanes = traci.edge.getLaneNumber(edge)
            except traci.TraCIException:
                continue
            lanes = [f"{edge}_{i}" for i in range(n_lanes)]
            (ns if arm in ("N", "S") else ew).extend(lanes)
        self.phases = _RingPhases(incoming_lanes={"NS": ns, "EW": ew})

    def step(self, sim_time: float) -> None:  # nothing to actuate
        return

    def approach_signals(self) -> dict[str, str]:
        return {}  # no signal heads on a roundabout
