"use strict";
/* Analysis & Enforcement view — a live command center.
   The hero pipeline RUNS the real analysis (simulation -> pattern -> AI
   root-cause -> advisory -> enforcement) over a WebSocket, animating a stage tracker and a
   streaming console; result panels reveal with motion as fresh data lands.
   Cached artifacts are shown dimmed + badged until a live run replaces them. */
(function () {
  const $ = (id) => document.getElementById(id);
  const getJSON = async (u) => { try { const r = await fetch(u); return r.ok ? await r.json() : null; } catch { return null; } };
  const postJSON = async (u, body) => {
    try {
      const r = await fetch(u, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body || {}) });
      return r.ok ? await r.json() : null;
    } catch { return null; }
  };
  const COL = { fixed_time: "#f87171", max_pressure: "#38bdf8", rl: "#34d399" };
  const LABELS = { fixed_time: "Fixed timer", max_pressure: "Smart adaptive", rl: "Self-learning AI" };
  const LANGS = ["English", "Hindi", "Tamil", "Telugu", "Kannada", "Marathi", "Bengali", "Gujarati", "Punjabi", "Malayalam"];
  const PRESETS = {
    rush: { ew: 650, ns: 220, ped: 240 }, weekday: { ew: 550, ns: 180, ped: 160 },
    weekend: { ew: 500, ns: 450, ped: 480 }, offpeak: { ew: 300, ns: 120, ped: 60 },
  };
  const ANIM = { duration: 900, easing: "easeOutQuart" };
  const CT = window.ChartTheme;
  const barBg = (c) => (CT ? CT.barFill(c) : c);
  const ax = (o) => (CT ? CT.axes(o) : { x: {}, y: {} });
  // bars sweep up left→right on first paint
  const BAR_ANIM = { ...ANIM, delay: (c) => (c.type === "data" && c.mode === "default" ? c.dataIndex * 90 : 0) };

  let benchChart = null, causeChart = null, temporalChart = null;
  let advisoryData = null, currentScenario = "rush", prefLang = "English", running = false;
  let verdictEN = null, detailsEN = null;   // English originals (re-render / translation source)

  /* ------------------------- small animation helpers ------------------------- */
  function countUp(el, target, { suffix = "", decimals = 0, ms = 900 } = {}) {
    const t0 = performance.now();
    const step = (now) => {
      const k = Math.min((now - t0) / ms, 1);
      const eased = 1 - Math.pow(1 - k, 3);
      el.textContent = (target * eased).toFixed(decimals) + suffix;
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }
  function pop(panelId) {
    const p = $(panelId);
    if (!p) return;
    p.classList.remove("stale", "pop");
    void p.offsetWidth;            // restart the animation
    p.classList.add("pop");
  }
  function badge(id, fresh) {
    const b = $(id);
    if (b) { b.textContent = fresh ? "● live" : ""; b.classList.toggle("live", !!fresh); }
  }
  function setStale(panelId, stale) { const p = $(panelId); if (p) p.classList.toggle("stale", !!stale); }

  /* ------------------------------ console + pipeline ------------------------------ */
  function clog(msg, cls) {
    const box = $("ana-console");
    const line = document.createElement("div");
    line.className = "cline" + (cls ? " " + cls : "");
    const ts = new Date().toLocaleTimeString("en-IN", { hour12: false });
    line.innerHTML = `<span class="ts">${ts}</span>${msg}`;
    box.appendChild(line);
    box.scrollTop = box.scrollHeight;
  }
  function clearConsole() { $("ana-console").innerHTML = ""; }
  function setStage(key, status) {
    const step = document.querySelector(`.pstep[data-k="${key}"]`);
    const line = document.querySelector(`.pline[data-k="${key}"]`);
    if (step) step.className = "pstep " + status;
    if (line && status === "done") line.classList.add("done");
  }
  function resetPipeline() {
    document.querySelectorAll(".pstep").forEach((s) => s.className = "pstep");
    document.querySelectorAll(".pline").forEach((l) => l.classList.remove("done"));
  }

  /* ------------------------------- live pipeline ------------------------------- */
  function setRunning(b) {
    running = b;
    const btn = $("ana-run");
    btn.disabled = b;
    btn.textContent = b ? "⏳ Analysing…" : "▶ Run AI analysis";
    document.querySelectorAll("#ana-scenario button").forEach((x) => x.disabled = b);
  }

  $("ana-run").onclick = () => {
    if (running) return;
    resetPipeline(); clearConsole(); setRunning(true);
    clog(`▶ starting AI analysis for '<b>${currentScenario}</b>'`);
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/api/ws/analyze`);
    ws.onopen = () => ws.send(JSON.stringify({ scenario: currentScenario }));
    ws.onmessage = (e) => {
      const m = JSON.parse(e.data);
      if (m.type === "stage") setStage(m.key, m.status);
      else if (m.type === "log") clog(m.message, m.cls);
      else if (m.type === "benchmark") { renderBenchmark(m.benchmark, true); fillHeadlineBench(m.benchmark, m.overall); }
      else if (m.type === "verdict") {
        verdictEN = m.verdict;
        renderVerdict(m.verdict, true);
        if (m.verdict && m.verdict.confidence != null)
          countUp($("hl-cause"), Math.round(m.verdict.confidence * 100), { suffix: "%" });
      } else if (m.type === "advisory") {
        advisoryData = m.advisory;
        showAdvisory(true);
      } else if (m.type === "challans") {
        renderChallans(m.challans, true);
      } else if (m.type === "done") {
        clog(`✓ analysis complete in ${m.took_s}s`, "ok");
        toast("Live analysis complete");
        loadTemporal();                 // cross-day context, shown once the run completes
        setRunning(false);
        if (prefLang !== "English") applyLanguage(prefLang);  // show the whole page in the saved language
      } else if (m.type === "error") {
        clog("✗ " + m.message, "err");
        toast(m.message, true);
        setRunning(false);
      }
    };
    ws.onclose = () => { if (running) setRunning(false); };
    ws.onerror = ws.onclose;
  };

  /* ------------------------------ ready state ------------------------------ */
  // The page shows NOTHING until the user runs the analysis. Every panel sits in a
  // "press Run" state; the live pipeline fills them as each stage completes.
  function resetPanels() {
    ["hl-wait", "hl-cause", "hl-veh", "hl-challan"].forEach((id) => { if ($(id)) $(id).textContent = "–"; });
    ["benchmarkChart", "causeChart", "temporalChart"].forEach((id) => { const c = $(id); if (c && c.parentElement) c.parentElement.classList.remove("on"); });
    if (benchChart) { benchChart.destroy(); benchChart = null; }
    $("bench-metrics").innerHTML = `<p class="muted">Press <b>▶ Run AI analysis</b> to measure
      the before/after wait-time reduction for this scenario.</p>`;
    badge("b-bench", false); setStale("panel-bench", false);
    if (causeChart) { causeChart.destroy(); causeChart = null; }
    $("verdict-body").innerHTML = `<p class="muted">No verdict yet — press <b>▶ Run AI analysis</b>
      above and watch the cause being worked out from the live simulation.</p>`;
    badge("b-verdict", false); setStale("panel-verdict", false); setStale("panel-cause", false);
    const at = $("advisory-text");
    at.classList.add("muted");
    at.textContent = "No advisory yet — press ▶ Run AI analysis above.";
    badge("b-advisory", false); setStale("panel-advisory", false);
    $("details-body").innerHTML = `<p class="muted">No deep-dive yet. After the analysis runs you can
      re-run the simulation to pinpoint the worst moments and get a detailed AI review.</p>`;
    setStale("deepdive-panel", false);
    $("temporal-panel").classList.add("hidden");
    $("challan-list").innerHTML = `<p class="muted">No violations flagged yet. Press <b>▶ Run AI analysis</b>
      above — it watches the junction and drafts a challan for any vehicle it catches over-speeding.</p>`;
    $("pending-badge").textContent = "0 pending";
  }

  window.loadAnalysis = async function () {
    document.querySelectorAll("#ana-scenario button").forEach((b) => b.onclick = () => {
      if (running) return;
      document.querySelectorAll("#ana-scenario button").forEach((x) => x.classList.remove("on"));
      b.classList.add("on");
      currentScenario = b.dataset.val;
      advisoryData = null; verdictEN = null; detailsEN = null;
      resetPanels();                    // new scenario hasn't been run yet → back to ready
    });
    resetPanels();                      // immediate ready state — no "Loading…" flash
    loadChallans();                     // surface any challans already in the DB (not just fresh runs)
    const prefs = await getJSON("/api/prefs");
    if (prefs && prefs.advisory_lang) prefLang = prefs.advisory_lang;
    buildLangSelect();
  };

  /* ------------------------------ benchmark ------------------------------ */
  function renderBenchmark(b, fresh) {
    if (!b || !b.fixed_time) {
      $("bench-metrics").innerHTML = `<p class="muted">No before/after benchmark for this scenario.</p>`;
      if (benchChart) { benchChart.destroy(); benchChart = null; }
      badge("b-bench", false);
      return;
    }
    badge("b-bench", fresh); setStale("panel-bench", !fresh); if (fresh) pop("panel-bench");
    const keys = ["fixed_time", "max_pressure", "rl"].filter((k) => b[k]);
    $("bench-metrics").innerHTML = `
      <div class="metric"><div class="v accent" id="bm-1">0%</div><div class="k">less waiting with smart signals</div></div>
      <div class="metric"><div class="v" id="bm-2">0%</div><div class="k">pedestrian delay reduction</div></div>
      ${b.rl ? `<div class="metric"><div class="v good" id="bm-3">0%</div><div class="k">less waiting with self-learning AI</div></div>` : ""}`;
    countUp($("bm-1"), b.wait_reduction_pct, { suffix: "%", decimals: 1 });
    countUp($("bm-2"), b.ped_delay_reduction_pct, { suffix: "%", decimals: 1 });
    if (b.rl) countUp($("bm-3"), b.rl_wait_reduction_pct, { suffix: "%", decimals: 1 });
    if (benchChart) benchChart.destroy();
    const bcv = $("benchmarkChart"); bcv.parentElement.classList.add("on");
    benchChart = new Chart(bcv, {
      type: "bar",
      data: { labels: ["Avg vehicle wait (s)", "Avg pedestrian delay (s)"],
        datasets: keys.map((k) => ({ label: LABELS[k], backgroundColor: barBg(COL[k]),
          hoverBackgroundColor: COL[k], maxBarThickness: 64, data: [b[k].avg_wait_s, b[k].avg_ped_delay_s] })) },
      options: { responsive: true, maintainAspectRatio: false, animation: BAR_ANIM,
        scales: ax({ x: { grid: { display: false }, ticks: { color: "#e6edf6", font: { weight: "600" } } },
          y: { title: { display: true, text: "seconds — lower is better", color: "#8b98ad" } } }) },
    });
  }

  /* ------------------------------- verdict ------------------------------- */
  function renderVerdict(v, fresh) {
    const body = $("verdict-body");
    if (!v || !v.headline) {
      body.innerHTML = `<p class="muted">No verdict for '${currentScenario}' yet —
        press <b>▶ Run AI analysis</b> above and watch it being produced.</p>`;
      if (causeChart) { causeChart.destroy(); causeChart = null; }
      badge("b-verdict", false);
      return;
    }
    badge("b-verdict", fresh); setStale("panel-verdict", !fresh); setStale("panel-cause", !fresh);
    if (fresh) { pop("panel-verdict"); pop("panel-cause"); }
    const cb = v.cause_breakdown;
    body.innerHTML = `
      <p class="verdict-headline">${v.headline}</p>
      <div class="kv"><span class="label">Primary cause</span><span>${v.primary_cause}</span></div>
      <div class="kv"><span class="label">Confidence</span><span id="vd-conf">0%</span></div>
      <div class="reco"><strong>Recommendation:</strong> ${v.recommendation}<br><br><strong>Expected impact:</strong> ${v.expected_impact}</div>
      <button id="apply-reco" class="btn-primary" style="margin-top:4px">▶ See the fix in action — before vs after</button>
      <details><summary>Why — grounded in the computed features</summary><p>${v.justification}</p></details>`;
    countUp($("vd-conf"), Math.round(v.confidence * 100), { suffix: "%" });
    $("apply-reco").onclick = () =>
      Live.compareWithPreset(Object.fromEntries(
        Object.entries(PRESETS[currentScenario] || PRESETS.rush)));
    if (causeChart) causeChart.destroy();
    const ccv = $("causeChart"); ccv.parentElement.classList.add("on");
    causeChart = new Chart(ccv, {
      type: "doughnut",
      data: { labels: ["Vehicles", "Pedestrians", "Parking"],
        datasets: [{ data: [cb.vehicles, cb.pedestrians, cb.parking],
          backgroundColor: ["#38bdf8", "#c084fc", "#fbbf24"],
          hoverBackgroundColor: ["#7dd3fc", "#d8b4fe", "#fcd34d"],
          borderColor: "#0b1018", borderWidth: 3, hoverOffset: 10, hoverBorderColor: "#0b1018" }] },
      options: { responsive: true, maintainAspectRatio: false, cutout: "60%",
        animation: { animateRotate: true, animateScale: true, duration: 1100, easing: "easeOutQuart" },
        plugins: { legend: { position: "bottom", labels: { color: "#e6edf6" } },
          tooltip: { callbacks: { label: (c) => ` ${c.label}: ${c.parsed}%` } } } },
    });
  }

  /* ------------------- advisory (persisted language) ------------------- */
  function buildLangSelect() {
    const sel = $("advisory-lang");
    sel.innerHTML = LANGS.map((l) => `<option ${l === prefLang ? "selected" : ""}>${l}</option>`).join("");
    sel.onchange = async () => {
      prefLang = sel.value;
      await postJSON("/api/prefs", { advisory_lang: prefLang });
      applyLanguage(prefLang);
    };
  }

  // Render the ENTIRE analysis (verdict + advisory + deep-dive) in `lang`. English shows
  // the originals; any other language is translated by the AI (cached) and re-rendered.
  // Only acts once an analysis has been produced this session — otherwise the page stays
  // in its ready state and the chosen language applies to the next run.
  async function applyLanguage(lang) {
    if (!verdictEN) return;
    if (lang === "English") {
      renderVerdict(verdictEN, false);
      showAdvisory(false);
      if (detailsEN) renderDetails(detailsEN, false);
      return;
    }
    const at = $("advisory-text"); at.classList.add("muted");
    at.textContent = `Translating the analysis into ${lang}…`;
    toast(`Translating the analysis into ${lang}…`);
    const res = await postJSON(`/api/analysis/${currentScenario}/render`, { language: lang });
    if (res && res.ok) {
      renderVerdict(res.verdict, false);
      advisoryData = res.advisory;
      showAdvisory(false);
      if (res.details) renderDetails(res.details, false);
      else if (detailsEN) renderDetails(detailsEN, false);
      toast(`Analysis shown in ${lang}`);
    } else {
      showAdvisory(false);   // keep the English advisory we already had
      toast((res && res.error) || `Could not translate to ${lang} — check the AI configuration.`, true);
    }
  }

  function showAdvisory(fresh) {
    const txt = $("advisory-text");
    const key = prefLang === "English" ? "english" : prefLang;
    const value = (advisoryData || {})[key] || (advisoryData || {}).english;
    if (!value) return;
    txt.classList.remove("muted");
    txt.textContent = value;
    badge("b-advisory", fresh); setStale("panel-advisory", !fresh);
    if (fresh) pop("panel-advisory");
  }

  /* ------------------------------ temporal ------------------------------ */
  async function loadTemporal() {
    const t = await getJSON("/api/temporal");
    const panel = $("temporal-panel");
    if (!t || !t.scenarios) { panel.classList.add("hidden"); return; }
    panel.classList.remove("hidden");
    const entries = Object.entries(t.scenarios);
    if (temporalChart) temporalChart.destroy();
    const tcv = $("temporalChart"); tcv.parentElement.classList.add("on");
    temporalChart = new Chart(tcv, {
      type: "bar",
      data: { labels: entries.map(([, v]) => v.time_context),
        datasets: [
          { label: "avg vehicle wait (s)", backgroundColor: barBg("#38bdf8"), hoverBackgroundColor: "#38bdf8", data: entries.map(([, v]) => v.avg_vehicle_wait_s) },
          { label: "avg queue (veh)", backgroundColor: barBg("#c084fc"), hoverBackgroundColor: "#c084fc", data: entries.map(([, v]) => v.avg_total_queue_veh) },
        ] },
      options: { responsive: true, maintainAspectRatio: false, animation: BAR_ANIM,
        scales: ax({ x: { grid: { display: false }, ticks: { color: "#e6edf6", font: { size: 10, weight: "600" } } } }) },
    });
  }

  /* --------------------- deep-dive (instances + AI) --------------------- */
  function renderDetails(d, fresh) {
    const box = $("details-body");
    if (!d) {
      box.innerHTML = `<p class="muted">No deep-dive yet for this scenario. It re-runs the
        simulation, pinpoints the worst moments, and writes a detailed AI review.</p>`;
      return;
    }
    setStale("deepdive-panel", !fresh);
    if (fresh) pop("deepdive-panel");
    const a = d.analysis || {};
    const dirName = { NS: "North–South", EW: "East–West", PED: "pedestrian crossing" };
    const episodes = (d.episodes || []).map((e, i) => `
      <div class="episode pop" style="animation-delay:${i * 0.12}s">
        <div class="ep-clock">${e.at}</div>
        <div class="ep-body">
          <b>${e.total_queue} vehicles queued</b> while green was given to <b>${dirName[e.phase] || e.phase}</b>
          <div class="ep-queues">${Object.entries(e.queues).map(([k, v]) => `<span class="${v > 20 ? "hot" : ""}">${k}: ${v}</span>`).join(" ")}</div>
        </div>
      </div>`).join("");
    const worst = (d.worst_vehicles || []).map((w) =>
      `<span class="wv" title="entered from the ${w.approach} approach">${w.approach} approach · waited ${Math.round(w.wait_s)}s</span>`).join(" ");
    box.innerHTML = `
      <div class="dd-grid">
        <div>
          <h3>📍 Worst moments (time into the run)</h3>
          ${episodes || '<p class="muted">none recorded</p>'}
          <h3 style="margin-top:14px">🚗 Longest-waiting vehicles</h3>
          <div class="wv-row">${worst || '<span class="muted">none</span>'}</div>
          <p class="muted small" style="margin-top:10px">Pedestrian peak: ${d.ped_peak ? `${d.ped_peak.waiting} waiting at ${d.ped_peak.at}` : "–"} ·
             average wait ${d.summary ? d.summary.avg_vehicle_wait_s : "?"}s · worst queue ${d.summary ? d.summary.peak_total_queue : "?"} vehicles</p>
        </div>
        <div>
          <h3>🧠 Detailed diagnosis</h3>
          ${(a.diagnosis || "").split("\n").filter(Boolean).map((p) => `<p>${p}</p>`).join("")}
          <h3>🔎 Evidence</h3>
          <ul>${(a.evidence || []).map((e) => `<li>${e}</li>`).join("")}</ul>
          <h3>✅ Actions for the authority</h3>
          <ol>${(a.actions || []).map((e) => `<li>${e}</li>`).join("")}</ol>
          <div class="reco"><strong>Expected outcome:</strong> ${a.expected_outcome || "—"}</div>
        </div>
      </div>`;
  }

  $("details-btn").onclick = async () => {
    const btn = $("details-btn");
    btn.disabled = true; btn.textContent = "⏳ Re-running simulation + AI review… (~1 min)";
    const res = await postJSON(`/api/details/${currentScenario}/generate`);
    btn.disabled = false; btn.textContent = "🔬 Generate deep-dive analysis";
    if (res && res.ok) {
      detailsEN = res.details;
      renderDetails(res.details, true);
      toast("Deep-dive analysis ready");
      if (prefLang !== "English") applyLanguage(prefLang);   // match the selected language
    } else toast((res && res.error) || "Deep-dive failed — see server logs", true);
  };

  /* ------------------------------ headline band ------------------------------ */
  // Filled from the simulation/benchmark stage (wait reduction + vehicles handled);
  // the root-cause confidence is filled separately when the verdict lands.
  function fillHeadlineBench(b, overall) {
    if (b && b.wait_reduction_pct != null)
      countUp($("hl-wait"), b.wait_reduction_pct, { suffix: "%", decimals: 1 });
    if (overall && overall.num_vehicles != null) countUp($("hl-veh"), overall.num_vehicles, {});
  }

  /* ------------------------------ challans ------------------------------ */
  async function loadChallans() {
    const data = await getJSON("/api/challans");
    renderChallans((data && data.challans) || [], false);
  }

  function renderChallans(challans, fresh) {
    const list = $("challan-list");
    const pending = challans.filter((c) => c.status === "pending_review").length;
    if ($("pending-badge")) $("pending-badge").textContent = `${pending} pending`;
    if ($("challans-count")) $("challans-count").textContent = `${pending} pending`;
    if ($("hl-challan")) $("hl-challan").textContent = pending;
    if (!challans.length) {
      list.innerHTML = `<p class="muted">No violations flagged yet. Press <b>▶ Run AI analysis</b> above —
        it watches the junction and drafts a challan for any vehicle it catches over-speeding.</p>`;
      return;
    }
    list.innerHTML = challans.map((c, i) => `
      <div class="challan ${fresh ? "pop" : ""}" style="${fresh ? `animation-delay:${i * 0.12}s` : ""}">
        <div class="ch-head"><span class="plate">${c.plate}</span><span class="tag ${c.status}">${c.status.replace("_", " ")}</span></div>
        <div class="kv"><span class="label">Violation</span><span>${prettyViolation(c.violation_type)} · ₹${c.fine_amount_inr} · ${c.is_valid_violation ? "valid" : "not valid"}</span></div>
        <div class="notice">${c.draft_notice}</div>
        ${c.status === "pending_review" ? `<div class="ch-actions"><button class="btn-approve" data-id="${c.id}" data-s="approved">✓ Approve</button><button class="btn-reject" data-id="${c.id}" data-s="rejected">✕ Reject</button></div>` : ""}
      </div>`).join("");
    if (fresh && pending) toast(`${pending} challan(s) drafted from detected violations`);
    list.querySelectorAll(".ch-actions button").forEach((btn) => btn.onclick = async () => {
      await fetch(`/api/challans/${btn.dataset.id}/${btn.dataset.s}`, { method: "POST" });
      toast(btn.dataset.s === "approved" ? "Challan approved" : "Challan rejected");
      loadChallans();
    });
  }
  const prettyViolation = (t) => ({ over_speeding: "Over-speeding", red_light_jump: "Jumping the red light" }[t] || t.replace(/_/g, " "));

  /* ------------------------------- toast ------------------------------- */
  window.toast = function (msg, isError) {
    const el = document.createElement("div");
    el.className = "toast" + (isError ? " error" : "");
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => el.classList.add("show"), 10);
    setTimeout(() => { el.classList.remove("show"); setTimeout(() => el.remove(), 400); }, 3200);
  };
})();
