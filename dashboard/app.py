"""Saarthi — authority dashboard (Streamlit).

Two tabs:
  • Live Simulation — change demand/controller and watch the junction respond in
    real time (queues per approach, signal phase, pedestrians) with streaming
    metrics. Powered by SUMO via `sim.live`.
  • Analysis & Enforcement — the story from real pipeline outputs: before/after
    benchmark, root-cause verdict, English/Hindi advisory, and the human-review
    challan queue.

Run:  streamlit run dashboard/app.py
Nothing is mocked; state is session + SQLite + data/outputs (no browser storage).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

from dashboard import data  # noqa: E402

st.set_page_config(page_title="Saarthi — Traffic Authority", page_icon="🚦", layout="wide")

st.title("🚦 Saarthi — Traffic Authority Decision Support")
st.caption("Junction C · real-time adaptive control + AI root-cause reasoning + "
           "human-review enforcement")

st.sidebar.markdown(
    "**Two decision speeds**\n\n"
    "- *Fast:* max-pressure signal control (per-second).\n"
    "- *Slow:* LangGraph + Claude agents (root cause, advice, enforcement).\n\n"
    "The **Live Simulation** tab runs SUMO with your parameters. "
    "**Analysis & Enforcement** reads real pipeline outputs."
)
scenario = st.sidebar.selectbox("Scenario (for Analysis tab)", data.SCENARIOS, index=0)

tab_live, tab_analysis = st.tabs(["🔴 Live Simulation", "📊 Analysis & Enforcement"])


# ============================ LIVE SIMULATION ============================
with tab_live:
    st.subheader("Run a live junction simulation")
    st.caption("Set the demand and controller, then watch the junction respond. "
               "Run the same demand under each controller to compare.")

    c = st.columns(4)
    controller = c[0].selectbox(
        "Controller", ["max_pressure", "fixed_time"],
        format_func=lambda k: "Max-pressure (adaptive)" if k == "max_pressure"
        else "Fixed-time (baseline)")
    ew = c[1].slider("E-W demand (veh/h per dir)", 100, 900, 650, 50)
    ns = c[2].slider("N-S demand (veh/h per dir)", 50, 600, 220, 25)
    ped = c[3].slider("Pedestrians (per hour)", 0, 600, 240, 20)
    duration = st.slider("Duration (simulated seconds)", 120, 1200, 480, 60,
                         help="Longer is more realistic but takes longer to animate.")

    if st.button("▶ Run simulation", type="primary"):
        import matplotlib.pyplot as plt
        import pandas as pd

        from dashboard.viz import draw_junction
        from sim.live import LiveConfig, LiveSim

        cfg = LiveConfig(controller=controller, ew_vph=ew, ns_vph=ns,
                         ped_per_hour=ped, duration=duration)
        progress = st.progress(0.0, text="Starting SUMO…")
        top = st.columns(4)
        m_phase, m_q, m_wait, m_ped = (col.empty() for col in top)
        viz_col, chart_col = st.columns([1, 1])
        viz_ph = viz_col.empty()
        chart_ph = chart_col.empty()

        ts: list[float] = []
        totals: list[int] = []
        waits: list[float] = []
        sim = LiveSim(cfg)
        UI_EVERY = 4
        try:
            for i, s in enumerate(sim.steps()):
                if i % UI_EVERY:
                    continue
                fig = draw_junction(s)
                viz_ph.pyplot(fig)
                plt.close(fig)
                ts.append(s.t)
                totals.append(s.total_queue)
                waits.append(s.running_avg_wait)
                chart_ph.line_chart(pd.DataFrame(
                    {"total queue": totals, "avg wait (s)": waits}, index=ts))
                m_phase.metric("Phase", s.phase)
                m_q.metric("Total queue", s.total_queue)
                m_wait.metric("Avg wait", f"{s.running_avg_wait:.0f}s")
                m_ped.metric("Peds waiting", s.peds_waiting)
                progress.progress(min(s.t / duration, 1.0), text=f"Simulating… t={s.t:.0f}s")
        except Exception as exc:  # surface SUMO/TraCI issues in the UI
            st.error(f"Simulation error: {exc}")
        progress.progress(1.0, text="Done")

        r = sim.result
        if r:
            st.success(f"Done — {r.num_vehicles} vehicles & {r.num_pedestrians} "
                       f"pedestrians cleared over {r.sim_steps}s.")
            f = st.columns(4)
            f[0].metric("Avg vehicle wait", f"{r.avg_wait_s}s")
            f[1].metric("Avg pedestrian delay", f"{r.avg_ped_delay_s}s")
            f[2].metric("Peak total queue", r.peak_total_queue)
            f[3].metric("Controller",
                        "Max-pressure" if controller == "max_pressure" else "Fixed-time")
            st.info("Tip: keep the demand fixed and switch the controller to see "
                    "the wait-time difference adaptive control makes.")
    else:
        st.info("Set parameters above and press **Run simulation**.")


# ========================= ANALYSIS & ENFORCEMENT =========================
with tab_analysis:
    # 1 · Benchmark
    st.header("1 · Before / after — adaptive signal control")
    bench = data.load_benchmark()
    if bench:
        ft, mp = bench["fixed_time"], bench["max_pressure"]
        has_rl = "rl" in bench
        cols = st.columns(4 if has_rl else 3)
        cols[0].metric("Avg vehicle wait (max-pressure)", f"{mp['avg_wait_s']:.0f}s",
                       delta=f"{mp['avg_wait_s'] - ft['avg_wait_s']:.0f}s vs fixed-time",
                       delta_color="inverse")
        cols[1].metric("Vehicle wait reduction", f"{bench['wait_reduction_pct']}%")
        cols[2].metric("Pedestrian delay reduction", f"{bench['ped_delay_reduction_pct']}%")
        if has_rl:
            cols[3].metric("RL wait reduction (Tier-2)",
                           f"{bench.get('rl_wait_reduction_pct')}%",
                           help="Learned PPO policy — optional upside; max-pressure "
                                "remains the robust deployable headline.")
        img = data.benchmark_image()
        if img:
            st.image(str(img), caption=f"Fixed-time vs max-pressure — '{bench['scenario']}'")
        if bench["scenario"] != scenario:
            st.caption(f"(Benchmark shown is for '{bench['scenario']}'. "
                       f"Run `python scripts/run_benchmark.py {scenario}` for this scenario.)")
    else:
        st.info("No benchmark yet — run `python scripts/run_benchmark.py rush`.")

    # 2 · Verdict
    st.header("2 · Root-cause verdict")
    verdict = data.load_verdict(scenario)
    if verdict:
        st.subheader(verdict["headline"])
        cb = verdict["cause_breakdown"]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Vehicles", f"{cb['vehicles']:.0f}%")
        c2.metric("Pedestrians", f"{cb['pedestrians']:.0f}%")
        c3.metric("Parking", f"{cb['parking']:.0f}%")
        c4.metric("Confidence", f"{verdict['confidence'] * 100:.0f}%")
        st.markdown(f"**Primary cause:** {verdict['primary_cause']}")
        st.success(f"**Recommendation:** {verdict['recommendation']}")
        st.markdown(f"**Expected impact:** {verdict['expected_impact']}")
        with st.expander("Why — grounded in the computed features"):
            st.write(verdict["justification"])
        if verdict.get("temporal_note"):
            with st.expander("Temporal note"):
                st.write(verdict["temporal_note"])
    else:
        st.info(f"No verdict yet — run `python scripts/run_analysis.py {scenario}`.")

    # 3 · Advisory
    st.header("3 · Advisory (multilingual)")
    advisory = data.load_advisory(scenario)
    if advisory:
        keys = list(advisory.keys())
        label = st.radio("Language", keys, horizontal=True,
                         format_func=lambda k: "English" if k == "english" else k)
        st.info(advisory[label])
    else:
        st.info(f"No advisory yet — run `python scripts/run_analysis.py {scenario}` "
                "(renders a Hindi advisory).")

    # 4 · Challans
    st.header("4 · Enforcement — challan queue (human review)")
    st.caption("Challans are DRAFTS. Nothing is auto-issued — an officer approves "
               "or rejects each one.")
    challans = data.load_challans()
    if not challans:
        st.info("No challans yet — run `python scripts/run_enforcement.py`.")
    else:
        pending = [c for c in challans if c["status"] == "pending_review"]
        st.metric("Pending review", len(pending))
        for c in challans:
            status = c["status"].replace("_", " ").upper()
            with st.expander(f"#{c['id']} · {c['plate']} · {c['violation_type']} · {status}"):
                st.write(f"**Valid violation?** {bool(c['is_valid_violation'])} "
                         f"(confidence {c.get('confidence')})")
                st.write(f"**Proposed fine:** ₹{c['fine_amount_inr']}")
                st.write(f"**Reasoning:** {c['reasoning']}")
                st.write(f"**Evidence:** {c['evidence_summary']}")
                st.markdown(f"**Draft notice ({c['language']}):**")
                st.code(c["draft_notice"])
                if c["status"] == "pending_review":
                    a, r = st.columns(2)
                    if a.button("✅ Approve", key=f"approve_{c['id']}"):
                        data.set_challan_status(c["id"], "approved")
                        st.rerun()
                    if r.button("❌ Reject", key=f"reject_{c['id']}"):
                        data.set_challan_status(c["id"], "rejected")
                        st.rerun()

    # extras
    temporal = data.load_temporal()
    if temporal:
        with st.expander("Temporal pattern — congestion by time context"):
            st.dataframe([
                {"context": v["time_context"], "scenario": k,
                 "avg wait (s)": v["avg_vehicle_wait_s"],
                 "avg queue": v["avg_total_queue_veh"],
                 "dominant axis": v["dominant_axis"], "imbalance": v["imbalance_ratio"]}
                for k, v in temporal["scenarios"].items()
            ], hide_index=True)

    perception = data.load_perception()
    if perception:
        with st.expander("Perception — last analysed clip"):
            s = perception["detection_summary"]
            st.write(f"Source: `{perception['source']}`")
            st.write(f"Unique vehicles: {s['unique_vehicles']} · "
                     f"unique pedestrians: {s['unique_pedestrians']}")
            if perception.get("plates"):
                st.write("Plates read:", ", ".join(p["text"] for p in perception["plates"]))
