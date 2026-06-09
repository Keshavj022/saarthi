"""Tests for signal-phase state-string synthesis (pure logic, no SUMO)."""
from __future__ import annotations

from control.phases import JunctionPhases


def make_jp() -> JunctionPhases:
    # A toy 6-link junction: NS=0,1  EW=2,3  PED(crossings)=4,5
    return JunctionPhases(
        tls_id="C",
        n_links=6,
        phase_idx={"NS": [0, 1], "EW": [2, 3], "PED": [4, 5]},
        incoming_lanes={"NS": ["N_in_1"], "EW": ["E_in_1"]},
        walk_edges=[":C_w0"],
        cross_edges=[":C_c0"],
    )


def test_green_states_are_correct_and_disjoint():
    jp = make_jp()
    assert jp.green_state("NS") == "GGrrrr"
    assert jp.green_state("EW") == "rrGGrr"
    assert jp.green_state("PED") == "rrrrGG"


def test_yellow_state_vehicle_phase():
    # Departing vehicle movements go yellow; everything else red.
    assert make_jp().yellow_state("NS") == "yyrrrr"


def test_yellow_state_ped_phase_is_all_red():
    # Crossings can't show yellow -> drop straight to red (clearance follows).
    assert make_jp().yellow_state("PED") == "rrrrrr"


def test_all_red_state():
    assert make_jp().all_red_state() == "rrrrrr"
