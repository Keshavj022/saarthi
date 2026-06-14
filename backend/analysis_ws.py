"""Live analysis pipeline over WebSocket.

`/api/ws/analyze` runs the FULL reasoning pipeline for a scenario while the
client watches: SUMO simulation (with streamed progress), computed diagnostic
features, the AI root-cause verdict, and the advisory in the user's saved
language. Each stage emits events so the UI can animate a pipeline stepper and
a console. Results are persisted to the same artifact files the rest of the app
reads (verdict.<scenario>.json, advisory.<scenario>.json).
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from config.settings import settings
from dashboard import data

log = logging.getLogger(__name__)
router = APIRouter()


def _run_pipeline(scenario: str, emit) -> None:
    """Blocking pipeline body (runs in a worker thread). `emit(dict)` is thread-safe."""
    t0 = time.time()
    from agents.analyst import AnalystAgent, advisory_text
    from core.features import compute_features
    from core.llm import LLMError, LLMNotConfigured, render_in_language

    # ---- stage 1+2: simulate + compute features ----
    emit({"type": "stage", "key": "sim", "status": "running"})
    emit({"type": "log", "message": f"Simulating the '{scenario}' junction with today's fixed-timer signal…"})
    last_logged = {"t": -600.0}

    def progress(t, q):
        if t - last_logged["t"] >= 600:
            last_logged["t"] = t
            emit({"type": "log", "message": f"{int(t // 60)} min in · {q} vehicles waiting in the queues"})

    feats = compute_features(scenario, progress_cb=progress)
    o, di, pd = feats["overall"], feats["directional_imbalance"], feats["pedestrians"]
    emit({"type": "stage", "key": "sim", "status": "done"})
    emit({"type": "log", "message":
          f"simulation done: {o['num_vehicles']} vehicles & {o['num_pedestrians']} pedestrians passed, "
          f"average wait {o['avg_vehicle_wait_s']}s, worst queue {o['peak_total_queue_veh']} vehicles"})
    emit({"type": "stage", "key": "feat", "status": "done"})
    heavy, light = max(di['ew_avg_queue'], di['ns_avg_queue']), min(di['ew_avg_queue'], di['ns_avg_queue'])
    busy = "East–West" if di['dominant_axis'] == "EW" else "North–South"
    emit({"type": "log", "cls": "ok", "message":
          f"pattern found: {busy} traffic is far heavier — {heavy} vs {light} vehicles queued "
          f"({di['imbalance_ratio']}× as much); pedestrians are not the bottleneck"})

    # The before/after benchmark is a pure-simulation result (no AI) — push it now so the
    # Before/after panel + headline fill from the run itself, even if the AI is unavailable.
    benchmark = data.load_benchmark()
    if benchmark and benchmark.get("scenario") != scenario:
        benchmark = None
    emit({"type": "benchmark", "benchmark": benchmark, "overall": o})

    # ---- stage 3: AI root-cause (resilient — pipeline continues if AI is down) ----
    emit({"type": "stage", "key": "verdict", "status": "running"})
    emit({"type": "log", "message": "AI is working out the root cause from the numbers…"})
    # The live run always produces ENGLISH. The Analysis page's language dropdown
    # translates the finished analysis on demand (POST /api/analysis/<scenario>/render),
    # so the whole page stays in one language instead of a mid-run English/other mix.
    lang = "English"

    verdict = None
    try:
        verdict = AnalystAgent().analyze(feats, benchmark)
    except (LLMNotConfigured, LLMError) as exc:
        emit({"type": "stage", "key": "verdict", "status": "fail"})
        emit({"type": "stage", "key": "advisory", "status": "fail"})
        emit({"type": "log", "cls": "err",
              "message": f"AI unavailable for the verdict ({str(exc)[:110]}). "
                         f"Continuing with the parts that don't need AI."})

    if verdict is not None:
        (settings.outputs_dir / f"verdict.{scenario}.json").write_text(
            verdict.model_dump_json(indent=2))
        emit({"type": "stage", "key": "verdict", "status": "done"})
        cb = verdict.cause_breakdown
        emit({"type": "log", "cls": "ok", "message":
              f"cause found: {cb.vehicles:.0f}% vehicle demand · {cb.pedestrians:.0f}% pedestrians · "
              f"{cb.parking:.0f}% parking  ({verdict.confidence:.0%} sure)"})
        emit({"type": "verdict", "verdict": json.loads(verdict.model_dump_json())})

        # ---- stage 4: advisory in the saved language ----
        emit({"type": "stage", "key": "advisory", "status": "running"})
        english = advisory_text(verdict)
        adv_path = settings.outputs_dir / f"advisory.{scenario}.json"
        adv = json.loads(adv_path.read_text()) if adv_path.exists() else {}
        adv["english"] = english
        if lang.lower() != "english":
            emit({"type": "log", "message": f"writing the advisory in {lang}…"})
            try:
                adv[lang] = render_in_language(english, lang)
            except (LLMNotConfigured, LLMError) as exc:
                emit({"type": "log", "cls": "err",
                      "message": f"could not write {lang}: {str(exc)[:110]} — English kept"})
        adv_path.write_text(json.dumps(adv, indent=2, ensure_ascii=False))
        emit({"type": "stage", "key": "advisory", "status": "done"})
        emit({"type": "advisory", "advisory": adv, "language": lang})

    # ---- stage 5: enforcement — catch real violations, draft challans ----
    emit({"type": "stage", "key": "enforce", "status": "running"})
    emit({"type": "log", "message": "Watching the junction for traffic violations…"})
    try:
        from agents.enforcement import EnforcementAgent
        from core import db
        from core.models import ViolationEvent
        from core.violations import detect_violations, offline_challan_record

        violations = detect_violations(network="cross", ew=600, ns=320, duration=240,
                                       limit=4)
        if not violations:
            emit({"type": "log", "message": "no violations detected in this window"})
        else:
            emit({"type": "log", "cls": "ok",
                  "message": f"caught {len(violations)} over-speeding vehicles — drafting challans for review"})
            db.clear_pending()  # fresh queue for this run's detections
            agent = EnforcementAgent()
            for v in violations:
                ev = ViolationEvent(
                    plate=v.plate, violation_type="over_speeding", junction_id="C",
                    timestamp=f"+{int(v.at_s)}s into the run",
                    evidence=(f"Speed camera at junction C measured vehicle {v.plate} doing "
                              f"{v.speed_kmh} km/h in a {int(v.limit_kmh)} km/h zone "
                              f"(approach {v.approach}). Clear reading, daylight."),
                    source="simulation", citizen_language=lang)
                try:
                    cid, draft = agent.process(ev)   # richer AI-written notice
                    fine = draft.fine_amount_inr
                except (LLMNotConfigured, LLMError):
                    cid = db.insert_challan(offline_challan_record(v))  # resilient fallback
                    fine = (2000 if v.speed_kmh - v.limit_kmh >= 20 else 1000)
                emit({"type": "log",
                      "message": f"  challan #{cid}: {v.plate} · {v.speed_kmh} km/h · ₹{fine}"})
            emit({"type": "challans", "challans": db.list_challans()})
    except Exception as exc:
        emit({"type": "log", "cls": "err", "message": f"enforcement skipped: {str(exc)[:120]}"})
    emit({"type": "stage", "key": "enforce", "status": "done"})

    emit({"type": "done", "took_s": round(time.time() - t0, 1), "scenario": scenario})


@router.websocket("/api/ws/analyze")
async def ws_analyze(ws: WebSocket):
    from backend.app import _sim_lock  # shared single-TraCI lock

    await ws.accept()
    try:
        params = await ws.receive_json()
    except Exception:
        await ws.close()
        return
    scenario = params.get("scenario", "rush")
    if scenario not in data.SCENARIOS:
        await ws.send_json({"type": "error", "message": "unknown scenario"})
        await ws.close()
        return
    if not _sim_lock.acquire(blocking=False):
        await ws.send_json({"type": "error",
                            "message": "A simulation is already running — try again in a moment."})
        await ws.close()
        return

    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def emit(ev: dict) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, ev)

    def producer():
        try:
            _run_pipeline(scenario, emit)
        except Exception as exc:  # surface anything unexpected to the console
            emit({"type": "error", "message": str(exc)[:200]})

    threading.Thread(target=producer, daemon=True).start()
    try:
        while True:
            ev = await queue.get()
            await ws.send_json(ev)
            if ev.get("type") in ("done", "error"):
                break
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        _sim_lock.release()
        try:
            await ws.close()
        except Exception:
            pass
