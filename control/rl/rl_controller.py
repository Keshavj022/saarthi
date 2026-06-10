"""RL Tier-2 controller — a learned policy over the shared NS/EW/PED phases.

At inference it is just another `PhasedController`: it reuses the same green→
yellow→all-red→green machinery and minimum-green timing, and only its
`select_phase` differs — it asks a trained stable-baselines3 policy which phase to
serve, from the same observation the env was trained on.
"""
from __future__ import annotations

import logging

from control.phases import PhasedController
from control.rl.env import ACTIONS, make_obs

log = logging.getLogger(__name__)


class RLController(PhasedController):
    """Uses a trained SB3 model to choose the next phase."""

    name = "rl"

    def __init__(self, tls_id: str, model_path: str) -> None:
        super().__init__(tls_id)
        from stable_baselines3 import PPO

        self.model = PPO.load(model_path)

    def select_phase(self, sim_time: float) -> str:
        obs = make_obs(
            self.vehicle_pressure("NS"),
            self.vehicle_pressure("EW"),
            self.pedestrian_demand()[0],
            self.current,
        )
        action, _ = self.model.predict(obs, deterministic=True)
        return ACTIONS[int(action)]
