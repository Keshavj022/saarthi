"""Fixed-time baseline controller — the "before" in the before/after benchmark.

It cycles NS → EW → PED at fixed green durations, **ignoring demand** — including
serving the pedestrian phase every cycle whether or not anyone is waiting. This
is the classic dumb fixed plan the adaptive controller must beat, and it lets the
benchmark compare the *policy* against an identical phase set.
"""
from __future__ import annotations

import logging

from control.phases import PhasedController

log = logging.getLogger(__name__)


class FixedTimeController(PhasedController):
    """Demand-blind fixed cycle over the shared NS/EW/PED phases."""

    name = "fixed_time"

    #: Fixed green durations (seconds) per phase, applied in `order`.
    durations = {"NS": 30.0, "EW": 30.0, "PED": 13.0}
    order = ("NS", "EW", "PED")

    def select_phase(self, sim_time: float) -> str:
        # Stay in the current phase until its fixed green has elapsed, then
        # advance to the next phase in the cycle — regardless of demand.
        if sim_time - self._phase_start < self.durations[self.current]:
            return self.current
        i = self.order.index(self.current)
        return self.order[(i + 1) % len(self.order)]
