"""Tests for parking (stationary-vs-moving) classification + analyst hook (no LLM)."""
from __future__ import annotations

from agents.analyst import build_prompt
from perception.parking import classify_tracks


def _moving(n: int = 60):
    return [(i, 100 + i * 5, 200) for i in range(n)]  # centre travels far


def _stationary(n: int = 60):
    return [(i, 300 + (i % 2), 400) for i in range(n)]  # ±1px jitter only


def test_classify_separates_stationary_and_moving():
    tracks = {1: _moving(), 2: _stationary(), 3: _stationary()}
    rep = classify_tracks(tracks, move_threshold_px=15, min_frames=10)
    assert rep.stationary_count == 2
    assert rep.moving_count == 1
    assert rep.encroachment is True
    assert set(rep.stationary_ids) == {2, 3}


def test_classify_ignores_short_tracks():
    tracks = {1: [(i, 300, 400) for i in range(5)]}  # 5 frames < min_frames
    rep = classify_tracks(tracks, min_frames=10)
    assert rep.stationary_count == 0 and rep.moving_count == 0
    assert rep.encroachment is False


def test_build_prompt_includes_parking():
    prompt = build_prompt({"junction_id": "C"}, None,
                          {"stationary_count": 3, "encroachment": True})
    assert "PARKING" in prompt
    assert "stationary_count" in prompt


def test_build_prompt_omits_parking_when_none():
    assert "PARKING" not in build_prompt({"junction_id": "C"}, None, None)
