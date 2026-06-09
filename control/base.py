"""Controller interface for a single traffic-light-controlled junction.

The contract (the "fast control layer" of Saarthi's fast/slow architecture):

    observe  ->  decide phase  ->  apply

Lifecycle during a run (driven by `core.metrics.run_scenario`):
  1. SUMO starts and TraCI connects.
  2. `reset()` is called once.
  3. `step(sim_time)` is called once per simulation step, *before*
     `traci.simulationStep()`, so a decision applies to the step about to run.

Controllers are stateful across a run (e.g. tracking time-in-phase for a
minimum-green constraint). TraCI is imported lazily by subclasses so this module
imports without SUMO installed.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod

log = logging.getLogger(__name__)


class Controller(ABC):
    """Base class for signal controllers operating on one junction."""

    #: Short identifier used in metrics/output (override in subclasses).
    name: str = "base"

    def __init__(self, tls_id: str) -> None:
        self.tls_id = tls_id

    def reset(self) -> None:
        """Called once after SUMO starts and TraCI connects. Optional override."""

    @abstractmethod
    def step(self, sim_time: float) -> None:
        """Observe the junction and apply a signal decision for this step.

        Args:
            sim_time: current simulation time in seconds.
        """
        raise NotImplementedError
