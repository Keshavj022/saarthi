#!/usr/bin/env python3
"""Launch the Saarthi web app — FastAPI backend + canvas single-page frontend.

    python scripts/run_app.py          # -> http://127.0.0.1:8000

The page has two views: a live SUMO simulation (animated junction + interactive
charts, parameters you change) and Analysis & Enforcement (benchmark, verdict,
multilingual advisory, challan queue) — all from real pipeline outputs.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn  # noqa: E402

if __name__ == "__main__":
    host, port = "127.0.0.1", 8001
    print(f"\n  Saarthi web app  ->  http://{host}:{port}\n")
    uvicorn.run("backend.app:app", host=host, port=port, reload=False, log_level="warning")
