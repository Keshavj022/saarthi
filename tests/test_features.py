"""Tests for the pure feature-aggregation helpers, the analyst prompt builder,
and the verdict model (no SUMO, no LLM call)."""
from __future__ import annotations

from agents.analyst import build_prompt
from core.features import bucketize, series_stats, trend
from core.models import CauseBreakdown, RootCauseVerdict


def test_series_stats():
    assert series_stats([1, 2, 3, 4]) == {"avg": 2.5, "peak": 4}
    assert series_stats([]) == {"avg": 0.0, "peak": 0.0}


def test_bucketize():
    buckets = bucketize([0, 100, 300, 400], [10, 20, 30, 50], 300)
    assert buckets[0] == {"t_start": 0, "t_end": 300, "avg_total_queue": 15.0}
    assert buckets[1]["t_start"] == 300
    assert buckets[1]["avg_total_queue"] == 40.0


def test_trend():
    assert trend([1, 1, 1, 1, 1, 1, 10, 10, 10, 10, 10, 10]) == "rising"
    assert trend([10] * 6 + [1] * 6) == "falling"
    assert trend([5] * 12) == "stable"
    assert trend([1, 2]) == "stable"  # too short


def test_build_prompt_includes_features_and_benchmark():
    prompt = build_prompt({"junction_id": "C"}, {"wait_reduction_pct": 44.6})
    assert "COMPUTED FEATURES" in prompt
    assert "BENCHMARK" in prompt
    assert "44.6" in prompt


def test_build_prompt_without_benchmark():
    prompt = build_prompt({"junction_id": "C"}, None)
    assert "COMPUTED FEATURES" in prompt
    assert "BENCHMARK" not in prompt


def test_verdict_model_roundtrip():
    v = RootCauseVerdict(
        junction_id="C", scenario="rush", headline="h", primary_cause="vehicles",
        cause_breakdown=CauseBreakdown(vehicles=90, pedestrians=10, parking=0),
        recommendation="r", expected_impact="i", justification="j", confidence=0.9,
    )
    assert v.cause_breakdown.vehicles == 90
    assert RootCauseVerdict.model_validate_json(v.model_dump_json()).confidence == 0.9
