"""Tests for deep-dive helpers + new API endpoints (no SUMO run, no LLM)."""
from __future__ import annotations

from core.insights import mmss, top_episodes
from core.models import DetailedAnalysis
from core.violations import synth_plate


def test_top_episodes_picks_separated_peaks():
    samples = [(float(t), q) for t, q in
               [(0, 5), (100, 50), (150, 48), (500, 40), (900, 60), (950, 59)]]
    eps = top_episodes(samples, k=3, min_gap=300)
    times = [t for t, _ in eps]
    assert times == sorted(times)
    assert (900.0, 60) in eps and (100.0, 50) in eps
    assert (150.0, 48) not in eps  # within min_gap of the 100s peak
    assert (950.0, 59) not in eps  # within min_gap of the 900s peak


def test_top_episodes_empty():
    assert top_episodes([], k=3) == []


def test_mmss_elapsed_time():
    assert mmss(0) == "00:00"
    assert mmss(720) == "12:00"
    assert mmss(2525) == "42:05"


def test_synth_plate_format_and_deterministic():
    import re
    p = synth_plate("sp_we.12")
    assert re.match(r"^[A-Z]{2}[0-9]{2}[A-Z]{2}[0-9]{4}$", p), p
    assert synth_plate("sp_we.12") == p  # deterministic


def test_detailed_analysis_model():
    d = DetailedAnalysis(diagnosis="d", evidence=["e1"], actions=["a1", "a2"],
                         expected_outcome="o")
    assert d.actions[1] == "a2"


def test_health_and_prefs_endpoints():
    from fastapi.testclient import TestClient

    from backend.app import app

    client = TestClient(app)
    h = client.get("/api/health").json()
    assert set(h) >= {"sumo", "ai", "rl_model", "benchmark"}

    r = client.post("/api/prefs", json={"advisory_lang": "Tamil"}).json()
    assert r["ok"] and r["advisory_lang"] == "Tamil"
    assert client.get("/api/prefs").json()["advisory_lang"] == "Tamil"
    # restore default so a demo starts in Hindi
    client.post("/api/prefs", json={"advisory_lang": "Hindi"})
