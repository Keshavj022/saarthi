"use strict";
/* Live-simulation view. Two modes:
     single — one run, buffered + interpolated 60fps playback.
     ab     — "see the fix in action": SAME demand under the fixed timer then
              smart adaptive signals, played side-by-side, synchronized, with a live
              comparison chart and a delta strip.
   Exposes window.Live = { start, stop, isRunning, compareWithPreset }. */
(function () {
  const $ = (id) => document.getElementById(id);
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

  let mode = "single";          // 'single' | 'ab'
  let running = false, playing = false;
  let liveChart = null, lastChartT = -10;
  let sides = [];               // [{buffer, renderer, captionEl, name, result}]
  let playT = 0, lastNow = 0, simDone = false;
  let activeWs = null;

  const abRenderers = {};       // lazy per-canvas renderers

  function setConn(state) {
    const el = $("conn"); el.textContent = state;
    el.className = "status-pill" + (state === "live" ? " live" : state === "busy" ? " busy" : "");
  }
  function setRunning(b) {
    running = b; const btn = $("run");
    btn.textContent = b ? "■ Stop" : (mode === "ab" ? "▶ Run before vs after" : "▶ Run simulation");
    btn.classList.toggle("stop", b);
    // while running, the layout / signal method / mode / traffic mix are locked
    // (they only take effect at the start of a run, so editing them mid-run is misleading)
    ["network", "controller", "simmode", "mix"].forEach((id) => { const el = $(id); if (el) el.classList.toggle("locked", b); });
  }
  function setMode(m) {
    mode = m;
    $("stage-single").classList.toggle("hidden", m !== "single");
    $("stage-ab").classList.toggle("hidden", m !== "ab");
    $("controller-row").classList.toggle("hidden", m === "ab");
    $("run").textContent = m === "ab" ? "▶ Run before vs after" : "▶ Run simulation";
    $("ab-delta").classList.add("hidden");
  }
  document.querySelectorAll("#simmode button").forEach((b) => b.onclick = () => {
    if (running) return;
    document.querySelectorAll("#simmode button").forEach((x) => x.classList.remove("on"));
    b.classList.add("on"); setMode(b.dataset.val);
  });

  /* ---------------- chart ---------------- */
  function initChart(datasets) {
    if (liveChart) liveChart.destroy();
    lastChartT = -10;
    const lcv = $("liveChart"); lcv.parentElement.classList.add("on");
    const ax = (window.ChartTheme ? ChartTheme.axes({ x: { ticks: { maxTicksLimit: 6 } } })
      : { x: {}, y: {} });
    liveChart = new Chart(lcv, {
      type: "line",
      data: { labels: [], datasets },
      // live telemetry: instant streaming updates (per-point update('none')),
      // but the points carry soft gradient fills for depth.
      options: {
        responsive: true, maintainAspectRatio: false, animation: false,
        scales: ax,
        plugins: { legend: { labels: { color: "#e6edf6" } } },
      },
    });
  }
  const TPAL = (window.ChartTheme && ChartTheme.PAL) ||
    { sky: "#38bdf8", warn: "#fbbf24", bad: "#f87171", good: "#34d399" };
  const fill = (c, top) => (window.ChartTheme ? ChartTheme.fadeFill(c, top) : "transparent");

  /* ---------------- interpolation ---------------- */
  function angLerp(a, b, al) { const d = ((b - a + 540) % 360) - 180; return a + d * al; }
  function interp(a, b, al) {
    const am = new Map(a.vehicles.map((v) => [v.id, v]));
    const vehicles = b.vehicles.map((vb) => {
      const va = am.get(vb.id);
      return va ? { ...vb, x: va.x + (vb.x - va.x) * al, y: va.y + (vb.y - va.y) * al, a: angLerp(va.a, vb.a, al) } : vb;
    });
    const pm = new Map(a.peds.map((p) => [p.id, p]));
    const peds = b.peds.map((pb) => {
      const pa = pm.get(pb.id);
      return pa ? { ...pb, x: pa.x + (pb.x - pa.x) * al, y: pa.y + (pb.y - pa.y) * al,
        a: (pa.a != null && pb.a != null) ? angLerp(pa.a, pb.a, al) : pb.a } : pb;
    });
    return { ...b, vehicles, peds };
  }
  function frameAt(buffer, t) {
    let i = 0;
    while (i < buffer.length - 1 && buffer[i + 1].t <= t) i++;
    const a = buffer[i], b = buffer[Math.min(i + 1, buffer.length - 1)];
    const al = b.t > a.t ? clamp((t - a.t) / (b.t - a.t), 0, 1) : 0;
    return interp(a, b, al);
  }

  /* ---------------- playback ---------------- */
  function loop(now) {
    if (!playing) return;
    const dt = (now - lastNow) / 1000; lastNow = now;
    const speed = window.AppState ? window.AppState.playSpeed : 4;
    const endT = Math.min(...sides.map((s) => s.buffer.length ? s.buffer[s.buffer.length - 1].t : 0));
    playT = Math.min(playT + dt * speed, endT);
    for (const s of sides) {
      if (!s.buffer.length) continue;
      const st = frameAt(s.buffer, playT);
      s.renderer.drawScene(st);
      if (s.captionEl) s.captionEl.textContent =
        `${s.label} — queue ${st.metrics.total_queue} · wait ${st.metrics.avg_wait}s · ${st.ped_phase ? "WALK" : st.phase}`;
      if (mode === "single") {
        $("m-time").textContent = Math.round(playT) + "s";
        $("m-phase").textContent = st.ped_phase ? "WALK" : st.phase;
        $("m-queue").textContent = st.metrics.total_queue;
        $("m-peds").textContent = st.metrics.peds_waiting;
      }
    }
    if (mode === "ab") $("ab-time").textContent = Math.round(playT) + "s";
    if (playT - lastChartT >= 4 && liveChart) {
      lastChartT = playT;
      liveChart.data.labels.push(Math.round(playT));
      sides.forEach((s, i) => {
        if (!s.buffer.length) return;
        const st = frameAt(s.buffer, playT);
        if (mode === "single") {
          liveChart.data.datasets[0].data.push(st.metrics.total_queue);
          liveChart.data.datasets[1].data.push(st.metrics.avg_wait);
        } else {
          liveChart.data.datasets[i].data.push(st.metrics.total_queue);
        }
      });
      liveChart.update("none");
    }
    if (simDone && playT >= endT - 1e-6) { playing = false; finish(); return; }
    requestAnimationFrame(loop);
  }

  function finish() {
    setRunning(false); setConn("ready");
    if (mode === "single") {
      const r = sides[0] && sides[0].result;
      if (r && r.num_vehicles) {
        $("r-wait").textContent = r.avg_wait_s + "s";
        $("r-ped").textContent = r.avg_ped_delay_s + "s";
        $("r-peak").textContent = r.peak_total_queue;
        $("r-veh").textContent = r.num_vehicles;
        $("result").classList.remove("hidden");
      }
    } else {
      const [a, b] = sides.map((s) => s.result || {});
      if (a.num_vehicles && b.num_vehicles) {
        const d = 100 * (a.avg_wait_s - b.avg_wait_s) / a.avg_wait_s;
        $("ab-delta").innerHTML =
          `Vehicle wait <b>${a.avg_wait_s}s → ${b.avg_wait_s}s</b> ` +
          `<span class="delta ${d > 0 ? "good" : "bad"}">${d > 0 ? "−" : "+"}${Math.abs(d).toFixed(1)}%</span>` +
          ` · pedestrian delay ${a.avg_ped_delay_s}s → ${b.avg_ped_delay_s}s` +
          ` · peak queue ${a.peak_total_queue} → ${b.peak_total_queue}`;
        $("ab-delta").classList.remove("hidden");
      }
    }
  }

  /* ---------------- websocket runs ---------------- */
  function params(controllerOverride) {
    const S = window.AppState;
    return { controller: controllerOverride || S.controller, network: S.network, mix: S.mix,
      ew: +$("ew").value, ns: +$("ns").value, ped: +$("ped").value, duration: +$("dur").value };
  }

  function runBuffered(controller, onProgress) {
    return new Promise((resolve, reject) => {
      const buffer = [];
      let result = null, network = null;
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(`${proto}://${location.host}/api/ws/simulate`);
      activeWs = ws;
      ws.onopen = () => ws.send(JSON.stringify(params(controller)));
      ws.onmessage = (e) => {
        const m = JSON.parse(e.data);
        if (m.type === "frame") { buffer.push(m); if (onProgress) onProgress(m.t); }
        else if (m.type === "network") network = m;
        else if (m.type === "done") { result = m.result; ws.close(); }
        else if (m.type === "error") { reject(new Error(m.message)); ws.close(); }
      };
      ws.onclose = () => resolve({ buffer, result, network });
      ws.onerror = () => resolve({ buffer, result, network });
    });
  }

  function startPlayback() {
    playT = 0; lastNow = performance.now(); playing = true;
    requestAnimationFrame(loop);
  }

  async function startSingle() {
    $("result").classList.add("hidden"); $("run-hint").textContent = "";
    initChart([
      { label: "vehicles queued", data: [], borderColor: TPAL.sky, backgroundColor: fill(TPAL.sky, 0.34), fill: true, tension: 0.4, pointRadius: 0, borderWidth: 2.5 },
      { label: "avg wait (s)", data: [], borderColor: TPAL.warn, backgroundColor: fill(TPAL.warn, 0.1), fill: true, pointRadius: 0, tension: 0.4, borderWidth: 2.5 },
    ]);
    sides = [{ buffer: [], renderer: Renderer, captionEl: null, label: "" }];
    simDone = false; setRunning(true); setConn("live");
    startPlayback();
    try {
      const dur = +$("dur").value;
      // stream into the playing buffer
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(`${proto}://${location.host}/api/ws/simulate`);
      activeWs = ws;
      ws.onopen = () => ws.send(JSON.stringify(params()));
      ws.onmessage = (e) => {
        const m = JSON.parse(e.data);
        if (m.type === "frame") sides[0].buffer.push(m);
        else if (m.type === "network") Renderer.setNetwork(m);
        else if (m.type === "done") { sides[0].result = m.result; simDone = true; ws.close(); }
        else if (m.type === "error") { $("run-hint").textContent = "⚠ " + m.message; simDone = true; }
      };
      ws.onclose = () => { simDone = true; };
    } catch (err) { $("run-hint").textContent = "⚠ " + err.message; simDone = true; }
  }

  async function startAB() {
    $("ab-delta").classList.add("hidden"); $("run-hint").textContent = "";
    setRunning(true); setConn("busy");
    const dur = +$("dur").value;
    const prog = (label) => (t) => { $("run-hint").textContent = `Simulating ${label}… ${Math.min(100, Math.round(100 * t / dur))}%`; };
    try {
      if (!abRenderers.A) {
        abRenderers.A = makeRenderer($("junctionA"));
        abRenderers.B = makeRenderer($("junctionB"));
      }
      const a = await runBuffered("fixed_time", prog("today's fixed timer"));
      if (!a.buffer.length) throw new Error("the fixed-timer run produced no frames");
      const b = await runBuffered("max_pressure", prog("smart adaptive signals"));
      if (!b.buffer.length) throw new Error("the smart-signal run produced no frames");
      $("run-hint").textContent = "";
      if (a.network) { abRenderers.A.setNetwork(a.network); abRenderers.B.setNetwork(a.network); }
      sides = [
        { buffer: a.buffer, renderer: abRenderers.A, captionEl: $("cap-A"), label: "BEFORE · fixed timer", result: a.result },
        { buffer: b.buffer, renderer: abRenderers.B, captionEl: $("cap-B"), label: "AFTER · smart adaptive", result: b.result },
      ];
      initChart([
        { label: "queue — fixed timer (before)", data: [], borderColor: TPAL.bad, backgroundColor: fill(TPAL.bad, 0.16), fill: true, pointRadius: 0, tension: 0.4, borderWidth: 2.5 },
        { label: "queue — smart adaptive (after)", data: [], borderColor: TPAL.good, backgroundColor: fill(TPAL.good, 0.16), fill: true, pointRadius: 0, tension: 0.4, borderWidth: 2.5 },
      ]);
      simDone = true;              // both buffers complete; play them out
      setConn("live");
      startPlayback();
    } catch (err) {
      $("run-hint").textContent = "⚠ " + err.message;
      setRunning(false); setConn("ready");
    }
  }

  function start() { mode === "ab" ? startAB() : startSingle(); }
  function stop() {
    if (activeWs) try { activeWs.close(); } catch (e) {}
    playing = false; simDone = true; setRunning(false); setConn("ready");
  }
  $("run").onclick = () => { running ? stop() : start(); };

  /* Jump-in from the Analysis page: preset demand + A/B mode + auto-run. */
  function compareWithPreset(preset) {
    if (running) stop();
    document.querySelector('.tab[data-view="live"]').click();
    // A/B compares signals on vs off — a signal-free roundabout would make the
    // before/after meaningless, so force a signalised layout first.
    const desc = (window.NETWORK_DESCRIPTORS || {})[window.AppState.network];
    if (!desc || desc.kind === "roundabout") {
      const cross = document.querySelector('#network button[data-val="cross"]');
      if (cross) cross.click();
    }
    document.querySelectorAll("#simmode button").forEach((x) =>
      x.classList.toggle("on", x.dataset.val === "ab"));
    setMode("ab");
    if (preset) {
      for (const [id, v] of Object.entries(preset)) {
        const el = $(id); if (el) { el.value = v; el.dispatchEvent(new Event("input")); }
      }
    }
    start();
  }

  window.Live = { start, stop, isRunning: () => running, compareWithPreset };
})();
