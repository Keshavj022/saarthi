"use strict";
/* Experiments view: run a controllers × layouts comparison matrix and render
   comparative analytics (bar charts, queue timelines, findings, table). */
(function () {
  const $ = (id) => document.getElementById(id);
  const COL = { fixed_time: "#f87171", max_pressure: "#38bdf8", rl: "#34d399" };
  const LBL = { fixed_time: "Fixed timer", max_pressure: "Smart adaptive", rl: "Self-learning AI" };
  const NETLBL = { cross: "4-way", tee: "T-junction", asym: "Main road × side", highway: "Highway", boulevard: "Boulevard × cross-street" };

  let ws = null, waitChart = null, pedChart = null, tlCharts = [], running = false;
  const CT = window.ChartTheme;
  const barBg = (c) => (CT ? CT.barFill(c) : c);
  const lineFill = (c) => (CT ? CT.fadeFill(c, 0.14) : "transparent");
  const ax = (o) => (CT ? CT.axes(o) : { x: {}, y: {} });
  const BAR_ANIM = { duration: 850, easing: "easeOutQuart", delay: (c) => (c.type === "data" && c.mode === "default" ? c.dataIndex * 80 : 0) };

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
    const gcv = $(canvas); gcv.parentElement.classList.add("on");
    return new Chart(gcv, {
      type: "bar",
      data: { labels: networks.map((n) => NETLBL[n]),
        datasets: ctrls.map((c) => ({ label: LBL[c], backgroundColor: barBg(COL[c]), hoverBackgroundColor: COL[c], maxBarThickness: 54,
          data: networks.map((n) => { const r = results.find((x) => x.network === n && x.controller === c); return r ? r.result[field] : null; }) })) },
      options: { responsive: true, maintainAspectRatio: false, animation: BAR_ANIM,
        scales: ax({ x: { grid: { display: false }, ticks: { color: "#e6edf6", font: { weight: "600" } } },
          y: { title: { display: true, text: title, color: "#8b98ad" } } }) },
    });
  }

  // one queue-over-time chart per layout — keeps each plot to ≤3 lines instead of
  // cramming every controller × layout combo (and a 9-entry legend) into one panel.
  function timelines(results) {
    tlCharts.forEach((c) => c.destroy());
    tlCharts = [];
    const host = $("ex-timelines");
    host.innerHTML = "";
    const networks = [...new Set(results.map((r) => r.network))];
    const single = networks.length === 1;
    $("tl-empty").style.display = "none";
    $("tl-hint").style.display = single ? "none" : "";

    for (const n of networks) {
      const rows = results.filter((r) => r.network === n);
      const card = document.createElement("div");
      card.className = "tl-card";
      const title = document.createElement("h3");
      title.className = "tl-title";
      title.textContent = NETLBL[n];
      const box = document.createElement("div");
      box.className = "chartbox on";
      box.style.setProperty("--ch", single ? "300px" : "240px");
      const cv = document.createElement("canvas");
      box.appendChild(cv);
      card.appendChild(title);
      card.appendChild(box);
      host.appendChild(card);

      tlCharts.push(new Chart(cv, {
        type: "line",
        data: { datasets: rows.map((r) => ({
          label: LBL[r.controller],
          data: r.timeline.map((p) => ({ x: p.t, y: p.q })),
          borderColor: COL[r.controller], backgroundColor: lineFill(COL[r.controller]), fill: true,
          pointRadius: 0, borderWidth: 2.5, tension: 0.38 })) },
        options: { responsive: true, maintainAspectRatio: false, animation: { duration: 800, easing: "easeOutQuart" }, parsing: true,
          scales: ax({ x: { type: "linear", ticks: { maxTicksLimit: 7 }, title: { display: true, text: "sim time (s)", color: "#8b98ad" } },
            y: { beginAtZero: true, title: { display: true, text: "total queue (veh)", color: "#8b98ad" } } }) },
      }));
    }
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
