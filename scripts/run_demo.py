#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config.settings import settings  # noqa: E402
from core import db  # noqa: E402

SCENARIO = "rush"


def _have(name: str) -> bool:
    return (settings.outputs_dir / name).exists()


def _run(script: str, *args: str) -> None:
    print(f"\n>>> {script} {' '.join(args)}")
    subprocess.run([sys.executable, str(ROOT / "scripts" / script), *args], check=True)


def main() -> int:
    print("Saarthi — demo prep (idempotent; existing outputs are reused)\n")

    if not _have("benchmark.json"):
        _run("run_benchmark.py", SCENARIO)
    else:
        print("✓ benchmark.json present")

    if not (_have(f"verdict.{SCENARIO}.json") and _have(f"advisory.{SCENARIO}.json")):
        _run("run_analysis.py", SCENARIO)
    else:
        print("✓ verdict + advisory present")

    if not db.list_challans():
        _run("run_enforcement.py")
    else:
        print(f"✓ {len(db.list_challans())} challan(s) present")

    print("\n" + "=" * 64)
    print("  DEMO NARRATIVE")
    print("=" * 64)
    print("  problem  ->  perception input (YOLO + ANPR)")
    print("           ->  benchmark headline (adaptive control, big wait cut)")
    print("           ->  root-cause verdict (why it congests)")
    print("           ->  plain-Hindi advisory for the authority")
    print("           ->  drafted challan (pending officer review)")
    print("           ->  close")
    print("=" * 64)
    print("\nNow launch the web app:")
    print("    python scripts/run_app.py        # -> http://127.0.0.1:8000")
    print("(legacy Streamlit fallback: streamlit run dashboard/app.py)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
