"""Fixed-time baseline controller — the "before" in the before/after benchmark.

It does not make decisions: it ensures the junction runs SUMO's built-in static
(fixed-cycle) signal program and lets SUMO advance it at its preset green/yellow
durations. The adaptive controllers (Phase 1+) must beat this.
"""
from __future__ import annotations

import logging

from control.base import Controller

log = logging.getLogger(__name__)

# Default program id that netconvert assigns to a generated static TLS program.
DEFAULT_PROGRAM = "0"


class FixedTimeController(Controller):
    """Runs the junction's preset fixed-time program; never overrides phases."""

    name = "fixed_time"

    def reset(self) -> None:
        import traci  # lazy: only available during a live run

        try:
            traci.trafficlight.setProgram(self.tls_id, DEFAULT_PROGRAM)
        except traci.TraCIException:  # already on the default program
            log.debug("Could not set program %s on %s; using current program.",
                      DEFAULT_PROGRAM, self.tls_id)

    def step(self, sim_time: float) -> None:
        # Intentional no-op: SUMO drives the fixed-time program by itself.
        return
