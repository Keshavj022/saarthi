from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

from config.settings import settings

log = logging.getLogger(__name__)

# --- Network constants (must match the .nod.xml / .edg.xml inputs) ---
TLS_ID = "C"          # traffic-light-controlled junction (node id)
JUNCTION_ID = "C"

NODE_FILE = settings.networks_dir / "intersection.nod.xml"
EDGE_FILE = settings.networks_dir / "intersection.edg.xml"
NET_FILE = settings.networks_dir / "intersection.net.xml"


class SumoNotFoundError(RuntimeError):
    """Raised when SUMO_HOME is not set / SUMO is not installed."""


def ensure_sumo_on_path() -> str:
    """Validate SUMO is available and add its `tools/` dir to sys.path.

    Returns the resolved SUMO_HOME. Raises SumoNotFoundError if unset.
    """
    home = settings.resolved_sumo_home()
    if not home:
        raise SumoNotFoundError(
            "SUMO_HOME is not set. Install SUMO (system-level) and export "
            "SUMO_HOME, or set it in .env. See README for OS-specific steps."
        )
    tools = os.path.join(home, "tools")
    if os.path.isdir(tools) and tools not in sys.path:
        sys.path.append(tools)
    return home


def _binary(name: str) -> str:
    """Resolve a SUMO binary (prefers $SUMO_HOME/bin via sumolib, else PATH)."""
    try:
        ensure_sumo_on_path()
        from sumolib import checkBinary  # type: ignore

        return checkBinary(name)
    except SumoNotFoundError:
        raise
    except Exception:  # sumolib missing — fall back to PATH lookup
        return name


def build_network(force: bool = False) -> Path:
    """Build `intersection.net.xml` from the node/edge inputs via netconvert.

    No-op if the network already exists (unless `force`). Requires SUMO.
    """
    if NET_FILE.exists() and not force:
        return NET_FILE
    netconvert = _binary("netconvert")
    cmd = [
        netconvert,
        "--node-files", str(NODE_FILE),
        "--edge-files", str(EDGE_FILE),
        "--output-file", str(NET_FILE),
        "--tls.default-type", "static",   # fixed-time program (the baseline)
        "--no-turnarounds", "true",
        # Pedestrian infrastructure: sidewalks on every arm + signalized
        # crossings across each arm (4 walking areas + 4 crossings at junction C).
        # The controllers synthesize their own NS/EW/PED phases at runtime, so we
        # don't rely on netconvert's default (concurrent-crossing) TLS program.
        "--sidewalks.guess", "true",
        "--crossings.guess", "true",
        "--walkingareas", "true",
    ]
    log.info("Building SUMO network -> %s", NET_FILE)
    subprocess.run(cmd, check=True)
    return NET_FILE


def scenario_cfg(name: str) -> Path:
    """Return the path to a scenario's `.sumocfg`, erroring if missing."""
    cfg = settings.scenarios_dir / f"{name}.sumocfg"
    if not cfg.exists():
        raise FileNotFoundError(f"Scenario config not found: {cfg}")
    return cfg


def sumo_cmd(
    scenario: str,
    *,
    gui: bool | None = None,
    seed: int | None = None,
    extra: list[str] | None = None,
) -> list[str]:
    """Assemble the SUMO command line for `traci.start(...)`."""
    gui = settings.sumo_gui if gui is None else gui
    seed = settings.sim_seed if seed is None else seed
    binary = _binary("sumo-gui" if gui else "sumo")
    cfg = scenario_cfg(scenario)
    cmd = [
        binary,
        "-c", str(cfg),
        "--step-length", str(settings.sim_step_length),
        "--seed", str(seed),
        "--no-step-log", "true",
        "--no-warnings", "true",
        "--duration-log.disable", "true",
        # Track whole-trip accumulated waiting time (large memory window).
        "--waiting-time-memory", "100000",
    ]
    if extra:
        cmd += extra
    return cmd


def get_incoming_lanes(tls_id: str) -> list[str]:
    """De-duplicated list of lanes feeding into a traffic light (via TraCI)."""
    import traci  # lazy: only needed during a live run

    seen: set[str] = set()
    lanes: list[str] = []
    for lane in traci.trafficlight.getControlledLanes(tls_id):
        if lane not in seen:
            seen.add(lane)
            lanes.append(lane)
    return lanes
