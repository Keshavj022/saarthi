from __future__ import annotations

import logging
import math
import subprocess
from pathlib import Path

from config.settings import settings

log = logging.getLogger(__name__)

ARM_LEN = 200.0
ARM_COORD = {"N": (0, ARM_LEN), "S": (0, -ARM_LEN), "E": (ARM_LEN, 0), "W": (-ARM_LEN, 0)}
RING_R = 22.0  # roundabout ring radius (world metres); shared with the renderer
METER_R = 34.0  # radius of the roundabout's entry meter signals (just outside the ring)

NETWORKS: dict[str, dict] = {
    "cross": {
        "label": "4-way crossroads",
        "blurb": "Balanced 4-way junction, 2 lanes per approach — the classic case.",
        "arms": {"N": 2, "S": 2, "E": 2, "W": 2},
    },
    "tee": {
        "label": "T-junction",
        "blurb": "3-arm junction (no south leg) — turning conflicts dominate.",
        "arms": {"N": 2, "E": 2, "W": 2},
    },
    "asym": {
        "label": "Arterial × side street",
        "blurb": "3-lane E-W arterial crossing a 1-lane side street — strong asymmetry.",
        "arms": {"N": 1, "S": 1, "E": 3, "W": 3},
    },
    "highway": {
        "label": "6-lane highway crossing",
        "blurb": "High-capacity 4-way, 3 lanes per approach — a heavy arterial crossing.",
        "arms": {"N": 3, "S": 3, "E": 3, "W": 3},
    },
    "boulevard": {
        "label": "Boulevard × cross-street",
        "blurb": "3-lane E-W boulevard meeting a 2-lane cross-street — moderate imbalance.",
        "arms": {"N": 2, "S": 2, "E": 3, "W": 3},
    },
    "roundabout": {
        "label": "Roundabout",
        "blurb": "Metered 4-arm roundabout — cars circulate the ring while signals meter each entry, so the signal method matters here too.",
        "arms": {"N": 1, "S": 1, "E": 1, "W": 1},
        "kind": "roundabout",
    },
}


def kind_of(name: str) -> str:
    return NETWORKS[name].get("kind", "signal")


def nod_xml(name: str) -> str:
    arms = NETWORKS[name]["arms"]
    nodes = ['    <node id="C" x="0" y="0" type="traffic_light"/>']
    for a in arms:
        x, y = ARM_COORD[a]
        nodes.append(f'    <node id="{a}" x="{x:.0f}" y="{y:.0f}" type="priority"/>')
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<nodes>\n'
            + "\n".join(nodes) + "\n</nodes>\n")


def edg_xml(name: str) -> str:
    arms = NETWORKS[name]["arms"]
    edges = []
    for a, lanes in arms.items():
        edges.append(f'    <edge id="{a}_in"  from="{a}" to="C" numLanes="{lanes}" '
                     f'speed="13.89" priority="2"/>')
        edges.append(f'    <edge id="{a}_out" from="C" to="{a}" numLanes="{lanes}" '
                     f'speed="13.89" priority="2"/>')
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<edges>\n'
            + "\n".join(edges) + "\n</edges>\n")


# ----------------------------- roundabout geometry -----------------------------
#: ring node for each arm (cars enter the ring at their own compass point and
#: circulate clockwise — N→E→S→W→N — matching left-hand-drive convention).
_RING_NODE = {"N": "RN", "E": "RE", "S": "RS", "W": "RW"}
_RING_COORD = {"RN": (0, RING_R), "RE": (RING_R, 0), "RS": (0, -RING_R), "RW": (-RING_R, 0)}
# clockwise circulation (left-hand drive): N(90°) -> E(0°) -> S(-90°) -> W(-180°) -> N.
# Each ring edge carries a curved `shape` tracing its 90° arc, so the ROAD is a
# smooth circle of radius RING_R (not a 4-sided diamond) and cars circulate on it.
_RING_SEQ = [("RN", "RE", 90, 0), ("RE", "RS", 0, -90), ("RS", "RW", -90, -180), ("RW", "RN", -180, -270)]
# entry meter nodes (one per arm, just outside the ring); all share TLS "C" so a
# single controller meters every entry — a signalised ("metered") roundabout.
_METER_NODE = {"N": "MN", "E": "ME", "S": "MS", "W": "MW"}
_METER_COORD = {"MN": (0, METER_R), "ME": (METER_R, 0), "MS": (0, -METER_R), "MW": (-METER_R, 0)}


def _arc_shape(a0_deg: float, a1_deg: float, n: int = 16) -> str:

    pts = []
    for i in range(n + 1):
        a = math.radians(a0_deg + (a1_deg - a0_deg) * i / n)
        pts.append(f"{RING_R * math.cos(a):.4f},{RING_R * math.sin(a):.4f}")
    return " ".join(pts)


def _round_nod_xml(name: str) -> str:
    arms = NETWORKS[name]["arms"]
    # radius="2.0" keeps each ring junction small so it doesn't eat into the arc.
    nodes = [f'    <node id="{n}" x="{x:.1f}" y="{y:.1f}" type="priority" radius="2.0"/>'
             for n, (x, y) in _RING_COORD.items()]
    for a in arms:
        x, y = ARM_COORD[a]
        nodes.append(f'    <node id="{a}" x="{x:.0f}" y="{y:.0f}" type="priority"/>')
        mn = _METER_NODE[a]
        mx, my = _METER_COORD[mn]
        nodes.append(f'    <node id="{mn}" x="{mx:.1f}" y="{my:.1f}" '
                     f'type="traffic_light" tl="C"/>')
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<nodes>\n'
            + "\n".join(nodes) + "\n</nodes>\n")


def _round_edg_xml(name: str) -> str:
    arms = NETWORKS[name]["arms"]
    edges = []
    for a, lanes in arms.items():
        rn = _RING_NODE[a]
        mn = _METER_NODE[a]
        # approach -> entry meter (TLS "C") -> ring node; the meter gates entry.
        edges.append(f'    <edge id="{a}_in" from="{a}" to="{mn}" numLanes="{lanes}" '
                     f'speed="13.89" priority="3"/>')
        edges.append(f'    <edge id="{a}_r"  from="{mn}" to="{rn}" numLanes="{lanes}" '
                     f'speed="11.0" priority="3"/>')
        edges.append(f'    <edge id="{a}_out" from="{rn}" to="{a}" numLanes="{lanes}" '
                     f'speed="13.89" priority="3"/>')
    for i, (u, v, a0, a1) in enumerate(_RING_SEQ):
        # priority 10 (vs arms 3) + curved shape: circulating traffic has right of way,
        # entering arms yield, and the carriageway follows the circle (spreadType=center).
        edges.append(f'    <edge id="ring{i}" from="{u}" to="{v}" numLanes="1" speed="8.33" '
                     f'priority="10" spreadType="center" shape="{_arc_shape(a0, a1)}"/>')
    # Explicit <roundabout> element → deterministic yield: entry connections build as
    # minor ("m"), the ring as major ("M"). Belt-and-suspenders with --roundabouts.guess.
    ring_nodes = " ".join(_RING_COORD.keys())
    ring_edges = " ".join(f"ring{i}" for i in range(len(_RING_SEQ)))
    edges.append(f'    <roundabout nodes="{ring_nodes}" edges="{ring_edges}"/>')
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<edges>\n'
            + "\n".join(edges) + "\n</edges>\n")


def net_file(name: str) -> Path:
    return settings.networks_dir / f"net_{name}.net.xml"


def build(name: str, force: bool = False) -> Path:
    """Build `net_<name>.net.xml` via netconvert (lazy; cached on disk)."""
    if name not in NETWORKS:
        raise ValueError(f"Unknown network {name!r}; choose from {list(NETWORKS)}")
    out = net_file(name)
    if out.exists() and not force:
        return out
    from sim.scenarios import loader  # late import to avoid cycles

    gen = settings.networks_dir / "gen"
    gen.mkdir(parents=True, exist_ok=True)
    nod = gen / f"{name}.nod.xml"
    edg = gen / f"{name}.edg.xml"
    netconvert = loader._binary("netconvert")
    if kind_of(name) == "roundabout":
        # Metered ("signalised") roundabout: cars circulate the ring, but a single
        # TLS "C" meters every entry (shared by the four meter nodes), so the same
        # controllers (fixed/adaptive/RL) drive it. No crossings (vehicle-only demo).
        nod.write_text(_round_nod_xml(name))
        edg.write_text(_round_edg_xml(name))
        cmd = [
            netconvert,
            "--node-files", str(nod),
            "--edge-files", str(edg),
            "--output-file", str(out),
            "--tls.default-type", "static",           # the entry meters are signalised
            "--roundabouts.guess", "true",            # belt-and-suspenders with the explicit element
            "--no-turnarounds", "true",
            "--offset.disable-normalization", "true",  # keep junction centred at (0,0)
            "--no-internal-links", "false",            # keep internal links → smooth circulation
            "--default.junctions.radius", "4",         # small, so junction areas don't eat the arc
            "--junctions.corner-detail", "20",         # smooth junction blending
            "--junctions.internal-link-detail", "10",  # smooth internal connecting lanes
            "--rectangular-lane-cut", "false",         # round (not blunt) lane ends
        ]
    else:
        nod.write_text(nod_xml(name))
        edg.write_text(edg_xml(name))
        cmd = [
            netconvert,
            "--node-files", str(nod),
            "--edge-files", str(edg),
            "--output-file", str(out),
            "--tls.default-type", "static",
            "--no-turnarounds", "true",
            "--sidewalks.guess", "true",
            "--crossings.guess", "true",
            "--walkingareas", "true",
            # Keep junction C at the origin so the canvas has one coordinate frame.
            "--offset.disable-normalization", "true",
        ]
    log.info("Building network '%s' (%s) -> %s", name, kind_of(name), out)
    subprocess.run(cmd, check=True, capture_output=True)
    return out


def descriptor(name: str) -> dict:
    """JSON-able geometry descriptor for the frontend renderer."""
    meta = NETWORKS[name]
    d = {"name": name, "label": meta["label"], "blurb": meta["blurb"],
         "arms": meta["arms"], "arm_len": ARM_LEN, "kind": kind_of(name)}
    if kind_of(name) == "roundabout":
        d["ring_r"] = RING_R
        d["meter_r"] = METER_R
    return d
