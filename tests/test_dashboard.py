"""Tests for the dashboard data loaders (no streamlit, no LLM)."""
from __future__ import annotations

from dashboard import data


def test_load_json_missing_returns_none():
    assert data._load_json("definitely_not_a_real_output_xyz.json") is None


def test_load_challans_returns_list():
    assert isinstance(data.load_challans(), list)


def test_scenarios_constant():
    assert "rush" in data.SCENARIOS
