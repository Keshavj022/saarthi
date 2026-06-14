from __future__ import annotations

import logging

from control.phases import PhasedController

log = logging.getLogger(__name__)


class MaxPressureController(PhasedController):

    name = "max_pressure"

    ped_insert_queue: int = 6      
    ped_min_headway: float = 30.0  
    ped_count_threshold: int = 2   
    ped_wait_threshold: float = 15.0   
    ped_hard_cap: float = 55.0     
    max_ped_green: float = 14.0    

    def reset(self) -> None:
        super().reset()
        self._last_ped_end: float = -1e9  

    def select_phase(self, sim_time: float) -> str:
        time_in_phase = sim_time - self._phase_start
        ns = self.vehicle_pressure("NS")
        ew = self.vehicle_pressure("EW")
        ped_count, ped_wait = self.pedestrian_demand()
        veh_best = "NS" if ns >= ew else "EW"  

        if self.current == "PED":
            
            if ped_count == 0 or time_in_phase >= self.max_ped_green:
                self._last_ped_end = sim_time
                return veh_best
            return "PED"

        
        if ped_count == 0:
            return veh_best

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
