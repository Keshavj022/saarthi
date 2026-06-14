from __future__ import annotations

import logging
from abc import ABC, abstractmethod

log = logging.getLogger(__name__)


class Controller(ABC):

    name: str = "base"

    def __init__(self, tls_id: str) -> None:
        self.tls_id = tls_id

    def reset(self) -> None:
        """Called once after SUMO starts and TraCI connects. Optional override."""

    @abstractmethod
    def step(self, sim_time: float) -> None:
        raise NotImplementedError
