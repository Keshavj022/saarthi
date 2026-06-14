from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Circle, Rectangle  # noqa: E402

QMAX = 25.0  # queue length that fills an arm completely
GREEN, RED = "#27ae60", "#c0392b"
ARM_BG = "#ecf0f1"


def _signal_color(phase: str, approach: str) -> str:
    if phase == "PED":
        return RED
    green = ("N", "S") if phase == "NS" else ("E", "W")
    return GREEN if approach in green else RED


def _queue_color(q: int) -> str:
    if q < 5:
        return "#2ecc71"
    if q < 15:
        return "#f39c12"
    return "#e74c3c"


def draw_junction(state) -> "plt.Figure":
    fig, ax = plt.subplots(figsize=(5, 5))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    ax.set_aspect("equal")
    ax.axis("off")

    # Arm backgrounds (light roads).
    ax.add_patch(Rectangle((4.2, 6), 1.6, 4, facecolor=ARM_BG))      # N
    ax.add_patch(Rectangle((4.2, 0), 1.6, 4, facecolor=ARM_BG))      # S
    ax.add_patch(Rectangle((6, 4.2), 4, 1.6, facecolor=ARM_BG))      # E
    ax.add_patch(Rectangle((0, 4.2), 4, 1.6, facecolor=ARM_BG))      # W

    q = state.queues
    fills = {a: min(q.get(a, 0) / QMAX, 1.0) * 4 for a in ("N", "S", "E", "W")}

    # Queue bars grow from the junction outward.
    ax.add_patch(Rectangle((4.2, 6), 1.6, fills["N"], facecolor=_queue_color(q["N"])))
    ax.add_patch(Rectangle((4.2, 4 - fills["S"]), 1.6, fills["S"], facecolor=_queue_color(q["S"])))
    ax.add_patch(Rectangle((6, 4.2), fills["E"], 1.6, facecolor=_queue_color(q["E"])))
    ax.add_patch(Rectangle((4 - fills["W"], 4.2), fills["W"], 1.6, facecolor=_queue_color(q["W"])))

    # Signal lights at the junction end of each arm.
    for approach, (x, y) in {"N": (5, 6.25), "S": (5, 3.75),
                             "E": (6.25, 5), "W": (3.75, 5)}.items():
        ax.add_patch(Circle((x, y), 0.22, facecolor=_signal_color(state.phase, approach),
                            edgecolor="white", zorder=5))

    # Queue counts.
    for approach, (x, y) in {"N": (5, 9.6), "S": (5, 0.4),
                             "E": (9.6, 5), "W": (0.4, 5)}.items():
        ax.text(x, y, str(q.get(approach, 0)), ha="center", va="center",
                fontsize=11, fontweight="bold", color="#2c3e50")

    # Centre: junction box + phase.
    is_ped = state.phase == "PED"
    ax.add_patch(Rectangle((4, 4), 2, 2, facecolor="#2980b9" if is_ped else "#2c3e50"))
    ax.text(5, 5.15, "WALK" if is_ped else state.phase, ha="center", va="center",
            color="white", fontsize=13, fontweight="bold")
    ax.text(5, 4.55, f"t={state.t:.0f}s", ha="center", va="center",
            color="#bdc3c7", fontsize=8)

    ax.set_title(f"pedestrians waiting: {state.peds_waiting}   |   "
                 f"total queue: {state.total_queue}", fontsize=10)
    fig.tight_layout()
    return fig
