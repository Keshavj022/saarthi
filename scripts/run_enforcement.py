#!/usr/bin/env python3
"""Draft a challan for a flagged violation (human-review queue).

The violation TRIGGER here is SIMULATED and configurable — we have no footage yet.
In production the event would come from perception (a plate read by ANPR while the
signal was red). If a `data/outputs/perception.json` exists, the first plate read
from your footage is used; otherwise a sample plate is used. Either way the event
is clearly labelled, and nothing is auto-issued: the challan lands in SQLite with
status `pending_review` for an officer to approve or reject.

Usage:
    python scripts/run_enforcement.py [--plate MH12AB1234] [--type red_light_jump] [--lang Hindi]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.settings import settings  # noqa: E402
from core import db  # noqa: E402
from core.llm import LLMError, LLMNotConfigured  # noqa: E402
from core.models import ViolationEvent  # noqa: E402
from sim.scenarios.loader import TLS_ID  # noqa: E402


def _plate_from_perception() -> str | None:
    path = settings.outputs_dir / "perception.json"
    if path.exists():
        plates = json.loads(path.read_text()).get("plates", [])
        if plates:
            return plates[0]["text"]
    return None


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--plate", default=None)
    ap.add_argument("--type", default="red_light_jump")
    ap.add_argument("--lang", default="Hindi", help="citizen's language for the challan")
    args = ap.parse_args()

    plate = args.plate or _plate_from_perception() or "MH12AB1234"
    plate_source = ("your footage (perception.json)" if (not args.plate and _plate_from_perception())
                    else "CLI/sample")

    event = ViolationEvent(
        plate=plate,
        violation_type=args.type,
        junction_id=TLS_ID,
        timestamp="2026-06-10T18:42:11",
        evidence=("Stop-line camera at junction C captured the vehicle crossing the "
                  "stop line and entering the intersection 1.8s AFTER the signal phase "
                  "turned red; through-speed 34 km/h; plate read by ANPR at confidence "
                  "0.86; clear daylight, frontal plate. (Representative/simulated event "
                  "— see note below — but the evidence describes a concrete capture.)"),
        source="simulated",
        citizen_language=args.lang,
    )

    # Route through the supervisor (violation-only -> enforcement node).
    from agents.supervisor import build_supervisor

    print(f"Flagged violation: {event.violation_type} | plate {event.plate} "
          f"(from {plate_source}) | junction {event.junction_id}")
    try:
        result = build_supervisor().invoke({"violation_event": event})
    except LLMNotConfigured as exc:
        print(f"\n⚠️  USER ACTION NEEDED — AI not configured: {exc}")
        return 3
    except LLMError as exc:
        print(f"\n⚠️  AI call failed:\n    {exc}")
        return 4

    challan_id = result["challan_id"]
    draft = result["challan"]

    print("\n" + "=" * 68)
    print(f"  DRAFTED CHALLAN #{challan_id}   (status: PENDING_REVIEW — not issued)")
    print("=" * 68)
    print(f"  Plate            : {event.plate}")
    print(f"  Violation        : {event.violation_type} @ junction {event.junction_id}")
    print(f"  Valid violation? : {draft.is_valid_violation}  (confidence {draft.confidence:.0%})")
    print(f"  Proposed fine    : ₹{draft.fine_amount_inr}")
    print(f"  Reasoning        : {draft.reasoning}")
    print(f"  Evidence         : {draft.evidence_summary}")
    print(f"\n  DRAFT NOTICE ({event.citizen_language}):\n")
    for line in draft.draft_notice.splitlines():
        print(f"    {line}")
    print("=" * 68)

    pending = db.list_challans(status="pending_review")
    print(f"\nHuman-review queue: {len(pending)} challan(s) pending "
          f"(officer approves/rejects each). DB: {settings.db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
