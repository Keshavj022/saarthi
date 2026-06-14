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


def load_benchmark(scenario: Optional[str] = None) -> Optional[dict]:
    """Per-scenario before/after benchmark, falling back to the global default.

    `benchmark.<scenario>.json` is preferred so every scenario shows a real
    before/after; `benchmark.json` is the legacy/default (rush) fallback.
    """
    if scenario:
        per = _load_json(f"benchmark.{scenario}.json")
        if per:
            return per
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
