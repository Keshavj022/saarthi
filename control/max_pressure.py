"""Max-pressure adaptive controller (Tier 1) — the "after" in the benchmark.

The fast reflexive layer of Saarthi's fast/slow architecture. There is no fixed
cycle and no preset countdown: every step (after a minimum green), it reads live
road state via TraCI and serves the phase with the greatest demand.

  * Vehicles: classic max-pressure — each vehicle phase's "pressure" is the
    number of queued vehicles on its incoming lanes; the heavier phase wins, so
    a busy arterial gets more green than a quiet side street.

  * Pedestrians: the exclusive PED phase is served **on demand** and **skipped
    when empty**, but *when* it is inserted self-adapts to vehicle load:
      - insert it cheaply while the current vehicle phase has drained (little
        traffic is being held up), or
      - defer it under heavy traffic until a fairness cap guarantees pedestrians
        are never starved.
    This keeps the controller from fragmenting green under heavy balanced
    traffic, while still cutting pedestrian delay when there is slack.

The signal changes because the road state changed, not because a timer expired.
"""
from __future__ import annotations

import logging

from control.phases import PhasedController

log = logging.getLogger(__name__)


class MaxPressureController(PhasedController):
    """Demand-responsive controller over the shared NS/EW/PED phases."""

    name = "max_pressure"

    # --- Pedestrian-responsiveness tuning ---
    ped_insert_queue: int = 6      # "current phase drained" if <= this many queued
    ped_min_headway: float = 30.0  # min gap between pedestrian phases (soft path)
    ped_count_threshold: int = 2   # peds gathered to trigger a cheap insert
    ped_wait_threshold: float = 15.0   # ...or someone waited this long (cheap insert)
    ped_hard_cap: float = 55.0     # fairness: serve PED no matter what past this wait
    max_ped_green: float = 14.0    # cap PED green so vehicles aren't starved

    def reset(self) -> None:
        super().reset()
        self._last_ped_end: float = -1e9  # allow an immediate first PED if needed

    def select_phase(self, sim_time: float) -> str:
        time_in_phase = sim_time - self._phase_start
        ns = self.vehicle_pressure("NS")
        ew = self.vehicle_pressure("EW")
        ped_count, ped_wait = self.pedestrian_demand()
        veh_best = "NS" if ns >= ew else "EW"  # max-pressure: heavier axis wins

        if self.current == "PED":
            # Leave PED once pedestrians have cleared or the green cap is reached.
            if ped_count == 0 or time_in_phase >= self.max_ped_green:
                self._last_ped_end = sim_time
                return veh_best
            return "PED"

        # In a vehicle phase. No pedestrians waiting -> pure vehicle max-pressure.
        if ped_count == 0:
            return veh_best

        # Pedestrians are waiting: serve them now only if it's cheap (the phase
        # being interrupted has drained) and spaced out, or if the fairness cap
        # has been hit. Otherwise keep serving vehicles. This makes PED frequency
        # self-adapt to vehicle load instead of fragmenting heavy green.
        current_queue = self.vehicle_pressure(self.current)
        since_ped = sim_time - self._last_ped_end
        cheap_insert = (
            current_queue <= self.ped_insert_queue
            and since_ped >= self.ped_min_headway
            and (ped_count >= self.ped_count_threshold
                 or ped_wait >= self.ped_wait_threshold)
        )
        if cheap_insert or ped_wait >= self.ped_hard_cap:
            return "PED"
        return veh_best
