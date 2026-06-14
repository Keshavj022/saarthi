"use strict";
/* App shell: tabs, shared control state, health badges. Analysis view logic
   lives in analysis.js; live sim in live.js; experiments in experiments.js. */
const $id = (id) => document.getElementById(id);

/* shared state read by live.js */
window.AppState = { controller: "max_pressure", network: "cross", mix: "cars", playSpeed: 4 };

/* -------------------------------- tabs -------------------------------- */
let analysisLoaded = false;
document.querySelectorAll(".tab").forEach((t) => t.onclick = () => {
  document.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
  t.classList.add("active");
  document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
  $id("view-" + t.dataset.view).classList.add("active");
  if (t.dataset.view === "analysis" && !analysisLoaded) { window.loadAnalysis(); analysisLoaded = true; }
});

/* ------------------------- sliders + segmented ------------------------- */
[["ew", "ew-val"], ["ns", "ns-val"], ["ped", "ped-val"], ["dur", "dur-val"],
 ["ex-ew", "ex-ew-val"], ["ex-ns", "ex-ns-val"], ["ex-ped", "ex-ped-val"], ["ex-dur", "ex-dur-val"]]
  .forEach(([id, lab]) => $id(id).oninput = () => $id(lab).textContent = $id(id).value);

function segmented(boxId, multi, onPick) {
  document.querySelectorAll(`#${boxId} button`).forEach((b) => b.onclick = () => {
    if (b.disabled) return;
    if (multi) b.classList.toggle("on");
    else {
      document.querySelectorAll(`#${boxId} button`).forEach((x) => x.classList.remove("on"));
      b.classList.add("on");
    }
    if (onPick) onPick(b.dataset.val);
  });
}
segmented("controller", false, (v) => AppState.controller = v);
segmented("mix", false, (v) => AppState.mix = v);
segmented("speed", false, (v) => AppState.playSpeed = +v);
segmented("ex-networks", true);
segmented("ex-controllers", true);
segmented("ex-mix", false);
segmented("network", false, (v) => {
  AppState.network = v;
  const d = (window.NETWORK_DESCRIPTORS || {})[v];
  if (d) { Renderer.setNetwork(d); Renderer.idle(); $id("network-blurb").textContent = d.blurb || ""; }
  // A roundabout has no signals: hide the signal-method picker + before/after
  // toggle and force a single run; restore them for signalised layouts.
  const round = !!(d && d.kind === "roundabout");
  $id("simmode").classList.toggle("hidden", round);
  if (round) {
    const single = document.querySelector('#simmode button[data-val="single"]');
    if (single && !single.classList.contains("on")) single.click();
    $id("controller-row").classList.add("hidden");
  } else {
    const ab = document.querySelector('#simmode button[data-val="ab"]').classList.contains("on");
    $id("controller-row").classList.toggle("hidden", ab);
  }
});

/* --------------- network catalogue + RL availability --------------- */
(async () => {
  const getJSON = async (u) => { try { const r = await fetch(u); return r.ok ? await r.json() : null; } catch { return null; } };

  const info = await getJSON("/api/networks");
  if (!info) return;
  window.NETWORK_DESCRIPTORS = {};
  for (const d of info.networks) window.NETWORK_DESCRIPTORS[d.name] = d;
  const cur = window.NETWORK_DESCRIPTORS[AppState.network];
  if (cur) $id("network-blurb").textContent = cur.blurb || "";
  if (!info.rl_available) {
    document.querySelectorAll('#controller button[data-val="rl"], #ex-controllers button[data-val="rl"]')
      .forEach((b) => { b.disabled = true; b.classList.remove("on"); b.title = "Train it first: python scripts/train_rl.py"; });
  }
})();

/* --------------- Live params collapse — collapsing enlarges the canvas --------------- */
(function () {
  const shell = document.querySelector(".live-shell");
  const toggle = $id("params-toggle");
  if (!shell || !toggle) return;
  const controls = shell.querySelector(".controls");

  function setCollapsed(on) {
    shell.classList.toggle("params-collapsed", on);
    toggle.setAttribute("aria-expanded", String(!on));
    toggle.setAttribute("aria-label", on ? "Expand parameters" : "Collapse parameters");
    toggle.title = on ? "Expand parameters" : "Collapse parameters";
    // nudge Chart.js to refit after the grid transition settles (canvas reflows on its own)
    setTimeout(() => window.dispatchEvent(new Event("resize")), 460);
  }

  setCollapsed(false);                                  // initially OPEN
  toggle.onclick = (e) => { e.stopPropagation(); setCollapsed(!shell.classList.contains("params-collapsed")); };
  if (controls) controls.addEventListener("click", () => {   // click the collapsed rail to reopen
    if (shell.classList.contains("params-collapsed")) setCollapsed(false);
  });
})();
