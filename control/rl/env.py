"""Gymnasium environment for the single junction (Tier-2 RL).

Reuses the exact NS/EW/PED phase machinery from `control.phases` so a learned
policy is directly comparable to the fixed-time and max-pressure controllers —
the only difference is *how* the next phase is chosen.

  * observation : [NS queue, EW queue, pedestrians waiting, phase one-hot(3)]
  * action      : Discrete(3) -> target phase NS / EW / PED
  * reward      : drop in TOTAL waiting time (vehicles + pedestrians) over the
                  step (wait-shaped, not throughput) — pedestrians are weighted up
                  so the policy can't cut vehicle wait by starving the walk phase,
                  and stuck vehicles' accumulating wait penalises gridlock.

HARD GUARDRAIL (project spec): single junction only.
"""
from __future__ import annotations

import logging

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from config.settings import settings
from control.phases import classify
from sim.scenarios import loader
from sim.scenarios.loader import TLS_ID

log = logging.getLogger(__name__)

ACTIONS = ("NS", "EW", "PED")
OBS_DIM = 6
Q_NORM = 50.0
P_NORM = 10.0


def make_obs(ns_q: float, ew_q: float, ped: float, current_phase: str) -> np.ndarray:
    """Build the observation vector (shared by env and the RL controller)."""
    onehot = [1.0 if current_phase == a else 0.0 for a in ACTIONS]
    return np.array(
        [min(ns_q / Q_NORM, 2.0), min(ew_q / Q_NORM, 2.0), min(ped / P_NORM, 2.0), *onehot],
        dtype=np.float32,
    )


class JunctionEnv(gym.Env):
    """SUMO single-junction env with the shared NS/EW/PED phase model."""

    metadata = {"render_modes": []}

    def __init__(self, scenario: str = "rush", episode_seconds: int = 1200,
                 seed: int = 42, yellow: int = 3, all_red: int = 2,
                 veh_green: int = 10, ped_green: int = 12) -> None:
        super().__init__()
        self.scenario = scenario
        self.episode_seconds = episode_seconds
        self._seed = seed
        self.yellow, self.all_red = yellow, all_red
        self.veh_green, self.ped_green = veh_green, ped_green
        self.action_space = spaces.Discrete(3)
        self.observation_space = spaces.Box(low=0.0, high=2.0, shape=(OBS_DIM,), dtype=np.float32)
        self._started = False
        loader.build_network()

    # --- TraCI helpers ---
    def _traci(self):
        import traci
        return traci

    def _close(self) -> None:
        if self._started:
            try:
                self._traci().close()
            except Exception:
                pass
            self._started = False

    def _queue(self, group: str) -> int:
        traci = self._traci()
        return sum(traci.lane.getLastStepHaltingNumber(l) for l in self._lanes[group])

    def _ped_waiting(self) -> int:
        traci = self._traci()
        return sum(1 for p in traci.person.getIDList()
                   if traci.person.getRoadID(p) in self._walk
                   and traci.person.getSpeed(p) < 0.3)

    def _total_wait(self) -> float:
        """Total waiting time over vehicles AND pedestrians (pedestrians weighted
        up so the policy can't minimise vehicle wait by starving the walk phase).
        Stuck vehicles' waiting keeps accumulating here, so gridlock is penalised."""
        traci = self._traci()
        veh = sum(traci.vehicle.getWaitingTime(v) for v in traci.vehicle.getIDList())
        ped = sum(traci.person.getWaitingTime(p) for p in traci.person.getIDList())
        return veh + 2.0 * ped

    def _obs(self) -> np.ndarray:
        return make_obs(self._queue("NS"), self._queue("EW"), self._ped_waiting(), self.current)

    def _set(self, state: str) -> None:
        self._traci().trafficlight.setRedYellowGreenState(TLS_ID, state)

    def _advance(self, n: int) -> None:
        traci = self._traci()
        for _ in range(n):
            if (traci.simulation.getMinExpectedNumber() == 0
                    or traci.simulation.getTime() >= self.episode_seconds):
                break
            traci.simulationStep()

    # --- gym API ---
    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self._close()
        loader.ensure_sumo_on_path()
        traci = self._traci()
        traci.start(loader.sumo_cmd(self.scenario, seed=self._seed))
        self._started = True
        self.phases = classify(TLS_ID)
        self._lanes = {"NS": self.phases.incoming_lanes["NS"],
                       "EW": self.phases.incoming_lanes["EW"]}
        self._walk = set(self.phases.walk_edges)
        self.current = "NS"
        self._set(self.phases.green_state("NS"))
        return self._obs(), {}

    def step(self, action):
        traci = self._traci()
        target = ACTIONS[int(action)]
        wait_before = self._total_wait()

        if target != self.current:
            self._set(self.phases.yellow_state(self.current))
            self._advance(self.yellow)
            self._set(self.phases.all_red_state())
            self._advance(self.all_red)
            self.current = target
            self._set(self.phases.green_state(target))

        self._advance(self.ped_green if target == "PED" else self.veh_green)
        wait_after = self._total_wait()

        reward = (wait_before - wait_after) / 100.0
        terminated = traci.simulation.getMinExpectedNumber() == 0
        truncated = traci.simulation.getTime() >= self.episode_seconds
        obs = self._obs()
        if terminated or truncated:
            self._close()
        return obs, float(reward), bool(terminated), bool(truncated), {}

    def close(self):
        self._close()
