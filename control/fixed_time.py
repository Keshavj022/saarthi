from __future__ import annotations

import logging

from control.phases import PhasedController

log = logging.getLogger(__name__)


class FixedTimeController(PhasedController):
    
    name = "fixed_time"

    
    durations = {"NS": 30.0, "EW": 30.0, "PED": 13.0}
    order = ("NS", "EW", "PED")

    def select_phase(self, sim_time: float) -> str:

        if sim_time - self._phase_start < self.durations[self.current]:
            return self.current
    
        n = len(self.order)
        i = self.order.index(self.current)
        for step in range(1, n + 1):
            cand = self.order[(i + step) % n]
            if self.phases.phase_idx.get(cand):
                return cand
        return self.current
