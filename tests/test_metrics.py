"""Tests for the pure metric-aggregation helpers (no SUMO required)."""
from __future__ import annotations

from core.metrics import aggregate_queue, summarize_tripinfo


def test_aggregate_queue_basic():
    mean, peak = aggregate_queue([0, 2, 4, 6])
    assert mean == 3.0
    assert peak == 6


def test_aggregate_queue_empty():
    assert aggregate_queue([]) == (0.0, 0)


def test_summarize_tripinfo(tmp_path):
    p = tmp_path / "trip.xml"
    p.write_text(
        '<tripinfos>'
        '  <tripinfo id="a" waitingTime="10" duration="100"/>'
        '  <tripinfo id="b" waitingTime="30" duration="140"/>'
        '</tripinfos>'
    )
    summary = summarize_tripinfo(p)
    assert summary["num_vehicles"] == 2
    assert summary["avg_wait_s"] == 20.0
    assert summary["avg_travel_time_s"] == 120.0


def test_summarize_tripinfo_empty(tmp_path):
    p = tmp_path / "empty.xml"
    p.write_text("<tripinfos></tripinfos>")
    summary = summarize_tripinfo(p)
    assert summary["num_vehicles"] == 0
    assert summary["avg_wait_s"] == 0.0
