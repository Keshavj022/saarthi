"""FastAPI backend for the Saarthi web app.

Serves the single-page frontend (backend/static) and provides:
  * REST — benchmark, verdict, advisory (+ render in any language), deep-dive
           details, temporal, perception, challan queue (+ approve/reject),
           network catalogue, user prefs, health: all from real pipeline outputs.
  * WS /api/ws/simulate   — one parameterized SUMO run (network, controller,
           demand, traffic mix); streams per-vehicle frames for the canvas.
  * WS /api/ws/experiment — batch comparison matrix (controllers × networks) with
           progress events; returns final metrics + queue timelines per combo.

Run:  uvicorn backend.app:app  (or: python scripts/run_app.py)
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from config.settings import settings  # noqa: E402
from dashboard import data  # noqa: E402 (reuse the real-output loaders)
from sim.live import LiveConfig, LiveSim, run_combo  # noqa: E402
from sim.network_defs import NETWORKS, descriptor  # noqa: E402

log = logging.getLogger(__name__)

app = FastAPI(title="Saarthi — Traffic Authority")
STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

_sim_lock = threading.Lock()  # one SUMO/TraCI connection at a time

CONTROLLER_NAMES = ("fixed_time", "max_pressure", "rl")


def _clamp(v, lo, hi, default):
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


# ------------------------------- REST API -------------------------------
PREFS_PATH = settings.outputs_dir / "prefs.json"


def _load_prefs() -> dict:
    if PREFS_PATH.exists():
        try:
            return json.loads(PREFS_PATH.read_text())
        except Exception:
            return {}
    return {}


@app.get("/api/health")
def api_health():
    return {
        "sumo": settings.resolved_sumo_home() is not None,
        "ai": bool(settings.anthropic_api_key),
        "rl_model": (settings.outputs_dir / "rl_policy.zip").exists(),
        "benchmark": (settings.outputs_dir / "benchmark.json").exists(),
    }


@app.get("/api/prefs")
def api_prefs():
    return _load_prefs()


@app.post("/api/prefs")
async def api_set_prefs(body: dict):
    prefs = _load_prefs()
    for key in ("advisory_lang",):
        if key in body:
            prefs[key] = str(body[key])[:40]
    PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PREFS_PATH.write_text(json.dumps(prefs, indent=2))
    return {"ok": True, **prefs}


@app.post("/api/advisory/{scenario}/render")
async def api_advisory_render(scenario: str, body: dict):
    """Render the advisory in any language via the AI and cache it."""
    lang = str(body.get("language") or "").strip()[:30]
    if not lang:
        return {"ok": False, "error": "language required"}
    verdict = data.load_verdict(scenario)
    if not verdict:
        return {"ok": False,
                "error": f"No verdict for '{scenario}' yet — run scripts/run_analysis.py {scenario}"}
    from agents.analyst import advisory_text
    from core.llm import LLMError, LLMNotConfigured, render_in_language
    from core.models import RootCauseVerdict

    english = advisory_text(RootCauseVerdict.model_validate(verdict))
    adv_path = settings.outputs_dir / f"advisory.{scenario}.json"
    adv = json.loads(adv_path.read_text()) if adv_path.exists() else {}
    adv.setdefault("english", english)
    if lang.lower() != "english" and lang not in adv:
        try:
            adv[lang] = await asyncio.to_thread(render_in_language, english, lang)
        except (LLMNotConfigured, LLMError) as exc:
            return {"ok": False, "error": str(exc)[:200]}
        adv_path.write_text(json.dumps(adv, indent=2, ensure_ascii=False))
    return {"ok": True, "advisory": adv}


@app.post("/api/analysis/{scenario}/render")
async def api_analysis_render(scenario: str, body: dict):
    """Translate the whole finished analysis (verdict + advisory + deep-dive) into a
    language, cached per language. The Analysis page calls this when a language is
    picked so the entire page renders in that language (English returns the originals)."""
    lang = str(body.get("language") or "English").strip()[:30]
    verdict = data.load_verdict(scenario)
    if not verdict:
        return {"ok": False, "error": f"No analysis for '{scenario}' yet — run it first."}
    advisory = data.load_advisory(scenario) or {}
    details_path = settings.outputs_dir / f"details.{scenario}.json"
    details = json.loads(details_path.read_text()) if details_path.exists() else None

    if lang.lower() == "english":
        return {"ok": True, "language": "English", "verdict": verdict,
                "advisory": advisory, "details": details}

    from agents.analyst import advisory_text, translate_details, translate_verdict
    from core.llm import LLMError, LLMNotConfigured, render_in_language
    from core.models import RootCauseVerdict

    vmodel = RootCauseVerdict.model_validate(verdict)
    try:
        # verdict — cached per language
        vpath = settings.outputs_dir / f"verdict.{scenario}.{lang}.json"
        if vpath.exists():
            tverdict = json.loads(vpath.read_text())
        else:
            tverdict = json.loads(
                (await asyncio.to_thread(translate_verdict, vmodel, lang)).model_dump_json())
            vpath.write_text(json.dumps(tverdict, indent=2, ensure_ascii=False))
        # advisory — cached inside advisory.<scenario>.json
        if lang not in advisory:
            english = advisory.get("english") or advisory_text(vmodel)
            advisory.setdefault("english", english)
            advisory[lang] = await asyncio.to_thread(render_in_language, english, lang)
            (settings.outputs_dir / f"advisory.{scenario}.json").write_text(
                json.dumps(advisory, indent=2, ensure_ascii=False))
        # deep-dive — cached per language (only if one was generated)
        tdetails = details
        if details:
            dpath = settings.outputs_dir / f"details.{scenario}.{lang}.json"
            if dpath.exists():
                tdetails = json.loads(dpath.read_text())
            else:
                tdetails = await asyncio.to_thread(translate_details, details, lang)
                dpath.write_text(json.dumps(tdetails, indent=2, ensure_ascii=False))
    except (LLMNotConfigured, LLMError) as exc:
        return {"ok": False, "error": str(exc)[:200]}
    return {"ok": True, "language": lang, "verdict": tverdict,
            "advisory": advisory, "details": tdetails}


@app.get("/api/details/{scenario}")
def api_details(scenario: str):
    path = settings.outputs_dir / f"details.{scenario}.json"
    return json.loads(path.read_text()) if path.exists() else {}


@app.post("/api/details/{scenario}/generate")
async def api_details_generate(scenario: str):
    """Run the scenario, extract concrete instances, get the AI deep-dive."""
    if scenario not in data.SCENARIOS:
        return {"ok": False, "error": "unknown scenario"}
    if not _sim_lock.acquire(blocking=False):
        return {"ok": False, "error": "A simulation is already running — try again in a moment."}
    try:
        from core.insights import build_detailed_report
        from core.llm import LLMError, LLMNotConfigured

        try:
            report = await asyncio.to_thread(
                build_detailed_report, scenario,
                data.load_benchmark(), data.load_verdict(scenario))
        except (LLMNotConfigured, LLMError) as exc:
            return {"ok": False, "error": str(exc)[:200]}
        path = settings.outputs_dir / f"details.{scenario}.json"
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
        return {"ok": True, "details": report}
    finally:
        _sim_lock.release()


@app.get("/api/scenarios")
def api_scenarios():
    return {"scenarios": list(data.SCENARIOS)}


@app.get("/api/networks")
def api_networks():
    return {"networks": [descriptor(n) for n in NETWORKS],
            "rl_available": (settings.outputs_dir / "rl_policy.zip").exists()}


@app.get("/api/benchmark")
def api_benchmark():
    return data.load_benchmark() or {}


@app.get("/api/verdict/{scenario}")
def api_verdict(scenario: str):
    return data.load_verdict(scenario) or {}


@app.get("/api/advisory/{scenario}")
def api_advisory(scenario: str):
    return data.load_advisory(scenario) or {}


@app.get("/api/temporal")
def api_temporal():
    return data.load_temporal() or {}


@app.get("/api/perception")
def api_perception():
    return data.load_perception() or {}


@app.get("/api/challans")
def api_challans():
    return {"challans": data.load_challans()}


@app.post("/api/challans/{challan_id}/{status}")
def api_set_challan(challan_id: int, status: str):
    if status not in ("approved", "rejected", "pending_review"):
        return {"ok": False, "error": "invalid status"}
    data.set_challan_status(challan_id, status)
    return {"ok": True}


def _parse_cfg(params: dict) -> LiveConfig:
    network = params.get("network", "cross")
    if network not in NETWORKS:
        network = "cross"
    mix = params.get("mix", "cars")
    return LiveConfig(
        controller=params.get("controller", "max_pressure"),
        network=network,
        mix=mix if mix in ("cars", "mixed") else "cars",
        ew_vph=_clamp(params.get("ew"), 50, 1200, 650),
        ns_vph=_clamp(params.get("ns"), 0, 900, 220),
        ped_per_hour=_clamp(params.get("ped"), 0, 800, 240),
        duration=_clamp(params.get("duration"), 60, 1800, 480),
    )


# --------------------------- live simulation WS ---------------------------
@app.websocket("/api/ws/simulate")
async def ws_simulate(ws: WebSocket):
    await ws.accept()
    try:
        params = await ws.receive_json()
    except Exception:
        await ws.close()
        return

    if not _sim_lock.acquire(blocking=False):
        await ws.send_json({"type": "error",
                            "message": "A simulation is already running — try again in a moment."})
        await ws.close()
        return

    cfg = _parse_cfg(params)
    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    stop = threading.Event()

    def producer():
        sim = LiveSim(cfg)
        gen = sim.stream_frames()
        try:
            for frame in gen:
                if stop.is_set():
                    gen.close()
                    break
                loop.call_soon_threadsafe(queue.put_nowait, frame)
        except Exception as exc:  # surface sim errors to the client
            loop.call_soon_threadsafe(
                queue.put_nowait, {"type": "error", "message": str(exc)[:200]})
        finally:
            loop.call_soon_threadsafe(
                queue.put_nowait, {"type": "done", "result": sim.result_dict()})

    threading.Thread(target=producer, daemon=True).start()

    try:
        await ws.send_json({"type": "network", **descriptor(cfg.network)})
        while True:
            frame = await queue.get()
            await ws.send_json(frame)
            if frame.get("type") == "done":
                break
            # Client buffers + interpolates playback; just yield control here.
            await asyncio.sleep(0.001)
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        stop.set()
        _sim_lock.release()
        try:
            await ws.close()
        except Exception:
            pass


# --------------------------- experiments WS ---------------------------
@app.websocket("/api/ws/experiment")
async def ws_experiment(ws: WebSocket):
    await ws.accept()
    try:
        p = await ws.receive_json()
    except Exception:
        await ws.close()
        return

    # signal-only: a roundabout has no controller, so it can't be in the matrix.
    networks = [n for n in p.get("networks", ["cross"])
                if n in NETWORKS and NETWORKS[n].get("kind", "signal") == "signal"][:3]
    ctrls = [c for c in p.get("controllers", ["fixed_time", "max_pressure"])
             if c in CONTROLLER_NAMES][:3]
    if not networks or not ctrls:
        await ws.send_json({"type": "error", "message": "Pick at least one network and controller."})
        await ws.close()
        return
    if "rl" in ctrls and not (settings.outputs_dir / "rl_policy.zip").exists():
        ctrls = [c for c in ctrls if c != "rl"]
        await ws.send_json({"type": "note",
                            "message": "RL model not found (run scripts/train_rl.py) — skipping RL."})

    ew = _clamp(p.get("ew"), 50, 1200, 650)
    ns = _clamp(p.get("ns"), 0, 900, 220)
    ped = _clamp(p.get("ped"), 0, 800, 240)
    duration = _clamp(p.get("duration"), 60, 900, 480)
    mix = p.get("mix", "cars")
    mix = mix if mix in ("cars", "mixed") else "cars"

    if not _sim_lock.acquire(blocking=False):
        await ws.send_json({"type": "error",
                            "message": "A simulation is already running — try again in a moment."})
        await ws.close()
        return

    combos = [(n, c) for n in networks for c in ctrls]
    results = []
    try:
        for i, (net, ctrl) in enumerate(combos):
            await ws.send_json({"type": "progress", "i": i, "n": len(combos),
                                "network": net, "controller": ctrl})
            try:
                result, timeline = await asyncio.to_thread(
                    run_combo, net, ctrl, ew=ew, ns=ns, ped=ped,
                    duration=duration, mix=mix)
                results.append({"network": net, "label": NETWORKS[net]["label"],
                                "controller": ctrl, "result": result,
                                "timeline": timeline})
            except Exception as exc:
                await ws.send_json({"type": "note",
                                    "message": f"{net}/{ctrl} failed: {str(exc)[:150]}"})
        await ws.send_json({"type": "results", "results": results,
                            "params": {"ew": ew, "ns": ns, "ped": ped,
                                       "duration": duration, "mix": mix}})
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        _sim_lock.release()
        try:
            await ws.close()
        except Exception:
            pass


# --------------------- live analysis pipeline (router) ---------------------
from backend.analysis_ws import router as analysis_router  # noqa: E402

app.include_router(analysis_router)

# ----------------------- static SPA (mounted last) -----------------------
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
