"use strict";
/* Experiments view: run a controllers × layouts comparison matrix and render
   comparative analytics (bar charts, queue timelines, findings, table). */
(function () {
  const $ = (id) => document.getElementById(id);
  const COL = { fixed_time: "#f87171", max_pressure: "#38bdf8", rl: "#34d399" };
  const LBL = { fixed_time: "Fixed timer", max_pressure: "Smart adaptive", rl: "Self-learning AI" };
  const NETLBL = { cross: "4-way", tee: "T-junction", asym: "Main road × side" };
  const DASH = { cross: [], tee: [7, 5], asym: [2, 4] };

  let ws = null, waitChart = null, pedChart = null, tlChart = null, running = false;

  const picked = (boxId) => [...document.querySelectorAll(`#${boxId} button.on`)].map((b) => b.dataset.val);

  function setProgress(show, frac, text) {
    $("ex-progress").classList.toggle("hidden", !show);
    $("ex-progress-bar").style.width = Math.round(frac * 100) + "%";
    $("ex-progress-text").textContent = text || "";
  }

  $("ex-run").onclick = () => {
    if (running) { if (ws) ws.close(); return; }
    const networks = picked("ex-networks"), controllers = picked("ex-controllers");
    if (!networks.length || !controllers.length) { $("ex-note").textContent = "Pick at least one layout and one controller."; return; }
    $("ex-note").textContent = "";
    const mix = document.querySelector("#ex-mix button.on").dataset.val;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/api/ws/experiment`);
    ws.onopen = () => {
      running = true; $("ex-run").textContent = "■ Cancel"; $("ex-run").classList.add("stop");
      setProgress(true, 0, "starting…");
      ws.send(JSON.stringify({ networks, controllers, mix,
        ew: +$("ex-ew").value, ns: +$("ex-ns").value, ped: +$("ex-ped").value, duration: +$("ex-dur").value }));
    };
    ws.onmessage = (e) => {
      const m = JSON.parse(e.data);
      if (m.type === "progress") setProgress(true, m.i / m.n, `${m.i + 1}/${m.n} — ${NETLBL[m.network]} · ${LBL[m.controller]}`);
      else if (m.type === "note") $("ex-note").textContent = "ℹ " + m.message;
      else if (m.type === "results") { setProgress(false, 1, ""); render(m.results); }
      else if (m.type === "error") { $("ex-note").textContent = "⚠ " + m.message; setProgress(false, 0, ""); }
    };
    ws.onclose = () => { running = false; $("ex-run").textContent = "▶ Run experiment"; $("ex-run").classList.remove("stop"); setProgress(false, 0, ""); };
    ws.onerror = ws.onclose;
  };

  function grouped(results, field, canvas, existing, title) {
    const networks = [...new Set(results.map((r) => r.network))];
    const ctrls = [...new Set(results.map((r) => r.controller))];
    if (existing) existing.destroy();
    const gcv = $(canvas); gcv.style.display = "block";
    return new Chart(gcv, {
      type: "bar",
      data: { labels: networks.map((n) => NETLBL[n]),
        datasets: ctrls.map((c) => ({ label: LBL[c], backgroundColor: COL[c], borderRadius: 5,
          data: networks.map((n) => { const r = results.find((x) => x.network === n && x.controller === c); return r ? r.result[field] : null; }) })) },
      options: { responsive: true, aspectRatio: 4, scales: {
        x: { ticks: { color: "#e6edf6" }, grid: { display: false } },
        y: { ticks: { color: "#8b98ad" }, grid: { color: "#1b2536" }, title: { display: true, text: title, color: "#8b98ad" } } },
        plugins: { legend: { labels: { color: "#e6edf6" } } } },
    });
  }

  function timelines(results) {
    if (tlChart) tlChart.destroy();
    const xcv = $("exTimelineChart"); xcv.style.display = "block";
    tlChart = new Chart(xcv, {
      type: "line",
      data: { datasets: results.map((r) => ({
        label: `${LBL[r.controller]} · ${NETLBL[r.network]}`,
        data: r.timeline.map((p) => ({ x: p.t, y: p.q })),
        borderColor: COL[r.controller], borderDash: DASH[r.network] || [],
        pointRadius: 0, borderWidth: 2, tension: 0.3 })) },
      options: { responsive: true, animation: false, parsing: true, aspectRatio: 3.4, scales: {
        x: { type: "linear", ticks: { color: "#8b98ad" }, grid: { color: "#1b2536" }, title: { display: true, text: "sim time (s)", color: "#8b98ad" } },
        y: { ticks: { color: "#8b98ad" }, grid: { color: "#1b2536" }, title: { display: true, text: "total queue (veh)", color: "#8b98ad" } } },
        plugins: { legend: { labels: { color: "#e6edf6", boxWidth: 18 } } } },
    });
  }

  function fmtDelta(d) {
    if (d == null) return "—";
    const better = d > 0;
    return `<span style="color:${better ? "#34d399" : "#f87171"}">${better ? "−" : "+"}${Math.abs(d).toFixed(1)}%</span>`;
  }

  function render(results) {
    if (!results.length) { $("ex-note").textContent = "No results."; return; }
    const eh = $("ex-empty"); if (eh) eh.style.display = "none";
    waitChart = grouped(results, "avg_wait_s", "exWaitChart", waitChart, "avg vehicle wait (s)");
    pedChart = grouped(results, "avg_ped_delay_s", "exPedChart", pedChart, "avg pedestrian delay (s)");
    timelines(results);

    // table + deltas vs fixed-time on the same network
    const fixedOf = {};
    results.forEach((r) => { if (r.controller === "fixed_time") fixedOf[r.network] = r.result.avg_wait_s; });
    const rows = results.map((r) => {
      const f = fixedOf[r.network];
      const d = (f && r.controller !== "fixed_time") ? 100 * (f - r.result.avg_wait_s) / f : null;
      return `<tr><td>${NETLBL[r.network]}</td><td>${LBL[r.controller]}</td>
        <td>${r.result.avg_wait_s}s</td><td>${r.controller === "fixed_time" ? "baseline" : fmtDelta(d)}</td>
        <td>${r.result.avg_ped_delay_s}s</td><td>${r.result.peak_total_queue}</td><td>${r.result.num_vehicles}</td></tr>`;
    });
    const table = $("ex-table");
    table.classList.remove("hidden");
    table.querySelector("tbody").innerHTML = rows.join("");
    $("ex-insights").innerHTML = insights(results, fixedOf);
    $("ex-insights").classList.remove("muted");
  }

  function insights(results, fixedOf) {
    const lines = [];
    const networks = [...new Set(results.map((r) => r.network))];
    let adaptiveWins = 0, adaptiveTotal = 0;
    for (const n of networks) {
      const f = fixedOf[n];
      const parts = [];
      for (const c of ["max_pressure", "rl"]) {
        const r = results.find((x) => x.network === n && x.controller === c);
        if (!r || f == null) continue;
        const d = 100 * (f - r.result.avg_wait_s) / f;
        adaptiveTotal++; if (d > 0) adaptiveWins++;
        parts.push(`${LBL[c]} <b>${d > 0 ? "−" : "+"}${Math.abs(d).toFixed(0)}%</b>`);
      }
      if (f != null && parts.length)
        lines.push(`<b>${NETLBL[n]}</b>: fixed-time ${f}s → ${parts.join(" · ")}.`);
    }
    if (adaptiveTotal) {
      lines.push(adaptiveWins === adaptiveTotal
        ? `✅ Smart signal timing reduced vehicle waiting in <b>every</b> case tested (${adaptiveWins}/${adaptiveTotal}).`
        : `⚠ Smart signal timing helped in ${adaptiveWins}/${adaptiveTotal} cases — check the exceptions above.`);
    }
    if (results.some((r) => r.controller === "rl" && r.network !== "cross"))
      lines.push(`ℹ The self-learning method was trained on the 4-way junction — its results on other layouts show how well it <i>adapts to junctions it has never seen</i>.`);
    return lines.map((l) => `<p>${l}</p>`).join("");
  }
})();
