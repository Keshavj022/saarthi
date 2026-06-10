"""Data access for the authority dashboard.

Reads REAL pipeline outputs only — the benchmark, verdict, advisory, temporal and
perception JSON written by the scripts, plus the challan queue from SQLite. No
mocks, no streamlit here (kept import-clean and testable).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from config.settings import settings
from core import db

SCENARIOS = ("rush", "weekday", "weekend", "offpeak")


def _load_json(name: str) -> Optional[dict]:
    path = settings.outputs_dir / name
    if path.exists():
        return json.loads(path.read_text())
    return None


def load_benchmark() -> Optional[dict]:
    return _load_json("benchmark.json")


def benchmark_image() -> Optional[Path]:
    path = settings.outputs_dir / "benchmark.png"
    return path if path.exists() else None


def load_verdict(scenario: str = "rush") -> Optional[dict]:
    return _load_json(f"verdict.{scenario}.json")


def load_advisory(scenario: str = "rush") -> Optional[dict]:
    """{'english': ..., 'Hindi': ...} written by run_analysis."""
    return _load_json(f"advisory.{scenario}.json")


def load_temporal() -> Optional[dict]:
    return _load_json("temporal.json")


def load_perception() -> Optional[dict]:
    return _load_json("perception.json")


def load_challans(status: Optional[str] = None) -> list[dict]:
    try:
        return db.list_challans(status=status)
    except Exception:
        return []


def set_challan_status(challan_id: int, status: str) -> None:
    db.update_status(challan_id, status)
