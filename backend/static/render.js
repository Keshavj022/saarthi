"use strict";
/* "Cinematic Ops Dusk" junction renderer. Draws any topology described by a
   descriptor {name,label,arms:{N,S,E,W: lanesPerDir},kind,ring_r,style} with the
   junction at world (0,0) and a PER-LAYOUT fit-to-frame zoom, so every layout is
   instantly distinct. makeRenderer(canvas) returns an independent instance (the
   A/B before-vs-after canvases use this); window.Renderer is the main Live canvas.

   Vehicles/pedestrians stream REAL SUMO world coordinates (metres). Only the
   scalars VIEW/MPP change per layout — the world→pixel map (px=CX+x*MPP) is
   unchanged — so a car always sits on its road. All decoration randomness is
   seeded from the layout name, so the two A/B canvases render byte-identically. */
function makeRenderer(cv) {
  const ctx = cv.getContext("2d");
  const W = +cv.getAttribute("width") || 720, H = +cv.getAttribute("height") || W;
  const DPR = Math.min(window.devicePixelRatio || 1, 2);
  cv.width = W * DPR; cv.height = H * DPR; ctx.scale(DPR, DPR);

  const CX = W / 2, CY = H / 2;
  const LANE = 3.2, SW = 2.8, PAD = 22, REACH = 36, REACH_RB = 30, MIN_VIEW = 30;
  let VIEW = 45, MPP = (W - PAD) / (2 * VIEW);     // mutable — set per layout in computeGeom
  const px = (x) => CX + x * MPP;
  const py = (y) => CY - y * MPP;
  const lw = (m, floor) => Math.max(floor || 1, m * MPP);   // metres→px, floored

  const PAL = {
    skyTop: "#1a1626", skyBot: "#2b2238",
    ground: "#1d2230",
    asphalt: "#23262e", junction: "#26282f",
    shoulder: "#3a3340", kerb: "#5a5660", sidewalk: "#33343d",
    median: "#243024", medianKerb: "#3e5a3e",
    laneMark: "rgba(236,240,248,.55)", centre: "#fbbf24",
    zebra: "rgba(244,248,255,.78)", stopLine: "rgba(244,248,255,.5)",
    busTint: "rgba(245,158,11,.10)",
    greenD: "#16261a", greenL: "#1f3a26",
    bldgA: "#2c2a36", bldgB: "#332e3a", bldgHi: "#403a48", win: "rgba(245,200,120,.40)",
    lamp: "rgba(255,196,120,.18)",
    accent: "#38bdf8",
    vignette: "rgba(0,0,0,.45)", ambient: "rgba(255,210,150,.06)",
  };
  const SIGCOL = { G: "#22c55e", y: "#facc15", r: "#ef4444" };
  const CARCOLORS = ["#e2e8f0", "#60a5fa", "#f472b6", "#fbbf24", "#34d399", "#a78bfa", "#fb923c", "#cbd5e1", "#22d3ee"];
  const TYPES = { c: { l: 4.8, w: 2.0 }, m: { l: 2.2, w: 0.95 }, b: { l: 11.0, w: 2.5 } };
  const carColor = (id) => { let h = 0; for (const c of id) h = (h * 31 + c.charCodeAt(0)) >>> 0; return CARCOLORS[h % CARCOLORS.length]; };

  //: per-layout identity kit (geometry differences live in computeGeom via arms).
  const STYLE = {
    cross:      { median: [],                ctx: "downtown" },
    tee:        { median: [],                ctx: "suburban", closeArm: "S" },
    asym:       { median: ["E", "W"],         ctx: "arterial", island: ["N", "S"], parking: ["N", "S"] },
    highway:    { median: ["N", "S", "E", "W"], ctx: "sparse",   buslane: ["E", "W"], shoulder: true },
    boulevard:  { median: ["E", "W"],         ctx: "leafy",    planted: true },
    roundabout: { median: [],                ctx: "civic" },
  };

  let NET = { name: "cross", label: "4-way", arms: { N: 2, S: 2, E: 2, W: 2 }, kind: "signal", ring_r: 22, style: null };
  let geom = null;
  const styleOf = () => (NET.style && Object.keys(NET.style).length ? NET.style : STYLE[NET.name]) || STYLE.cross;

  const bg = document.createElement("canvas");
  bg.width = W * DPR; bg.height = H * DPR;
  const bgx = bg.getContext("2d"); bgx.scale(DPR, DPR);

  // ---- seeded RNG (deterministic per layout → identical A/B canvases) ----
  function mulberry32(s) {
    return () => { s |= 0; s = (s + 0x6D2B79F5) | 0;
      let t = Math.imul(s ^ (s >>> 15), 1 | s);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  }
  function seedFromName(s) { let h = 2166136261 >>> 0; for (const c of s) { h ^= c.charCodeAt(0); h = Math.imul(h, 16777619); } return h >>> 0; }

  // ---- asphalt grain tile (built once) ----
  function buildNoise() {
    const n = 64, t = document.createElement("canvas"); t.width = t.height = n;
    const tx = t.getContext("2d"), img = tx.createImageData(n, n);
    for (let i = 0; i < n * n; i++) { const v = 118 + ((Math.random() * 30) | 0);
      img.data[i * 4] = v; img.data[i * 4 + 1] = v; img.data[i * 4 + 2] = v + 4; img.data[i * 4 + 3] = 14; }
    tx.putImageData(img, 0, 0); return t;
  }
  const NOISE = buildNoise();

  // ---- primitives (world-coord rect/line/circle; rr is pixel-space) ----
  function rectW(g, x1, y1, x2, y2, color) {
    g.fillStyle = color;
    g.fillRect(px(Math.min(x1, x2)), py(Math.max(y1, y2)),
               Math.abs(x2 - x1) * MPP, Math.abs(y2 - y1) * MPP);
  }
  function lineW(g, x1, y1, x2, y2, color, width, dash) {
    g.save(); g.strokeStyle = color; g.lineWidth = width;
    if (dash) g.setLineDash(dash);
    g.beginPath(); g.moveTo(px(x1), py(y1)); g.lineTo(px(x2), py(y2)); g.stroke();
    g.restore();
  }
  function circleW(g, cx, cy, rad, color) {
    g.fillStyle = color; g.beginPath(); g.arc(px(cx), py(cy), rad * MPP, 0, 6.3); g.fill();
  }
  function rr(g, x, y, w, h, r) {
    g.beginPath();
    g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r);
    g.arcTo(x + w, y + h, x, y + h, r); g.arcTo(x, y + h, x, y, r);
    g.arcTo(x, y, x + w, y, r); g.closePath();
  }

  // ---- per-arm geometry + per-layout scale ----
  function computeGeom() {
    const a = NET.arms;
    const wN = (a.N || 0) * LANE, wS = (a.S || 0) * LANE, wE = (a.E || 0) * LANE, wW = (a.W || 0) * LANE;
    const bx = Math.max(wN, wS, 0) + SW;       // N-S carriageway half-extent + verge
    const by = Math.max(wE, wW, 0) + SW;       // E-W carriageway half-extent + verge
    geom = { wN, wS, wE, wW, wv: Math.max(wN, wS), wh: Math.max(wE, wW), bx, by,
             lanesV: Math.max(a.N || 0, a.S || 0), lanesH: Math.max(a.E || 0, a.W || 0),
             lanesN: a.N || 0, lanesS: a.S || 0, lanesE: a.E || 0, lanesW: a.W || 0 };
    if (NET.kind === "roundabout")
      VIEW = Math.max((NET.ring_r || 22) + LANE * 1.4 + REACH_RB, MIN_VIEW);
    else
      VIEW = Math.max(Math.max(bx, by) + REACH, MIN_VIEW);
    MPP = (W - PAD) / (2 * VIEW);
  }

  // ---- roads (per-arm width) ----
  function drawArmRoads(g) {
    const { wN, wS, wE, wW, bx, by } = geom, A = NET.arms;
    if (A.N) { rectW(g, -(wN + SW), by, (wN + SW), VIEW, PAL.shoulder); rectW(g, -wN, by, wN, VIEW, PAL.asphalt); }
    if (A.S) { rectW(g, -(wS + SW), -VIEW, (wS + SW), -by, PAL.shoulder); rectW(g, -wS, -VIEW, wS, -by, PAL.asphalt); }
    if (A.E) { rectW(g, bx, -(wE + SW), VIEW, (wE + SW), PAL.shoulder); rectW(g, bx, -wE, VIEW, wE, PAL.asphalt); }
    if (A.W) { rectW(g, -VIEW, -(wW + SW), -bx, (wW + SW), PAL.shoulder); rectW(g, -VIEW, -wW, -bx, wW, PAL.asphalt); }
    rectW(g, -bx, -by, bx, by, PAL.junction);   // open junction box
  }

  function speckle(g) {
    const { wN, wS, wE, wW, bx, by } = geom, A = NET.arms;
    const path = new Path2D();
    const add = (x1, y1, x2, y2) => path.rect(px(Math.min(x1, x2)), py(Math.max(y1, y2)),
                                              Math.abs(x2 - x1) * MPP, Math.abs(y2 - y1) * MPP);
    if (A.N) add(-wN, by, wN, VIEW);
    if (A.S) add(-wS, -VIEW, wS, -by);
    if (A.E) add(bx, -wE, VIEW, wE);
    if (A.W) add(-VIEW, -wW, -bx, wW);
    add(-bx, -by, bx, by);
    g.save(); g.clip(path); g.globalCompositeOperation = "overlay";
    g.fillStyle = g.createPattern(NOISE, "repeat"); g.fillRect(0, 0, W, H); g.restore();
  }

  function kerbLines(g) {
    const { wN, wS, wE, wW, bx, by } = geom, A = NET.arms, C = PAL.kerb, wd = lw(0.12, 1);
    if (A.N) { lineW(g, -wN, by, -wN, VIEW, C, wd); lineW(g, wN, by, wN, VIEW, C, wd); }
    if (A.S) { lineW(g, -wS, -VIEW, -wS, -by, C, wd); lineW(g, wS, -VIEW, wS, -by, C, wd); }
    if (A.E) { lineW(g, bx, -wE, VIEW, -wE, C, wd); lineW(g, bx, wE, VIEW, wE, C, wd); }
    if (A.W) { lineW(g, -VIEW, -wW, -bx, -wW, C, wd); lineW(g, -VIEW, wW, -bx, wW, C, wd); }
  }

  function drawMedian(g) {
    const st = styleOf(), med = st.median || []; if (!med.length) return;
    const { bx, by } = geom, HW = st.planted ? 1.2 : 0.9;
    if (med.includes("N")) rectW(g, -HW, by, HW, VIEW, PAL.median);
    if (med.includes("S")) rectW(g, -HW, -VIEW, HW, -by, PAL.median);
    if (med.includes("E")) rectW(g, bx, -HW, VIEW, HW, PAL.median);
    if (med.includes("W")) rectW(g, -VIEW, -HW, -bx, HW, PAL.median);
    if (st.planted) {                              // boulevard: trees down the E/W median
      if (med.includes("E")) for (let x = bx + 4; x < VIEW; x += 8) circleW(g, x, 0, 0.95, PAL.greenL);
      if (med.includes("W")) for (let x = -bx - 4; x > -VIEW; x -= 8) circleW(g, x, 0, 0.95, PAL.greenL);
    }
  }

  function drawBusLane(g) {
    const st = styleOf(); if (!st.buslane) return;
    const { wE, wW, bx } = geom, C = "rgba(245,158,11,.5)", dash = [lw(1.2, 4), lw(1.2, 4)];
    if (st.buslane.includes("E")) { rectW(g, bx, wE - LANE, VIEW, wE, PAL.busTint); lineW(g, bx, wE - LANE, VIEW, wE - LANE, C, lw(0.16, 1), dash); }
    if (st.buslane.includes("W")) { rectW(g, -VIEW, wW - LANE, -bx, wW, PAL.busTint); lineW(g, -VIEW, wW - LANE, -bx, wW - LANE, C, lw(0.16, 1), dash); }
  }

  function drawShoulderHatch(g) {
    const st = styleOf(); if (!st.shoulder) return;
    const { wN, wS, wE, wW, bx, by } = geom, A = NET.arms;
    const C = "rgba(120,134,156,.18)", wd = lw(0.14, 1), dash = [lw(0.8, 3), lw(1.0, 4)], o = SW * 0.5;
    if (A.N) { lineW(g, -(wN + o), by, -(wN + o), VIEW, C, wd, dash); lineW(g, wN + o, by, wN + o, VIEW, C, wd, dash); }
    if (A.S) { lineW(g, -(wS + o), -VIEW, -(wS + o), -by, C, wd, dash); lineW(g, wS + o, -VIEW, wS + o, -by, C, wd, dash); }
    if (A.E) { lineW(g, bx, -(wE + o), VIEW, -(wE + o), C, wd, dash); lineW(g, bx, wE + o, VIEW, wE + o, C, wd, dash); }
    if (A.W) { lineW(g, -VIEW, -(wW + o), -bx, -(wW + o), C, wd, dash); lineW(g, -VIEW, wW + o, -bx, wW + o, C, wd, dash); }
  }

  function drawIslands(g) {                         // asym channelising triangles at the side-street mouths
    const st = styleOf(); if (!st.island) return;
    const { wN, wS, by } = geom;
    const tri = (cx, cy, dir) => { g.fillStyle = PAL.median; g.beginPath();
      g.moveTo(px(cx), py(cy)); g.lineTo(px(cx + 1.2), py(cy + dir * 3)); g.lineTo(px(cx - 1.2), py(cy + dir * 3));
      g.closePath(); g.fill(); };
    if (st.island.includes("N") && NET.arms.N) { tri(-wN - 1.7, by + 0.5, 1); tri(wN + 1.7, by + 0.5, 1); }
    if (st.island.includes("S") && NET.arms.S) { tri(-wS - 1.7, -by - 0.5, -1); tri(wS + 1.7, -by - 0.5, -1); }
  }

  function drawMarkings(g) {
    const { wv, wh, by, bx, lanesV, lanesH } = geom, st = styleOf();
    const DASH = [lw(1.2, 4), lw(1.6, 6)], LC = PAL.laneMark, CL = PAL.centre;
    const lwid = lw(0.15, 1.2), cwid = lw(0.22, 2);
    const med = st.median || [];
    const medNS = med.includes("N") || med.includes("S");
    const medEW = med.includes("E") || med.includes("W");
    const vSpans = [];
    if (NET.arms.N) vSpans.push([by, VIEW]);
    if (NET.arms.S) vSpans.push([-VIEW, -by]);
    for (const [y1, y2] of vSpans) {
      for (let i = 1; i < lanesV; i++) {
        lineW(g, i * LANE, y1, i * LANE, y2, LC, lwid, DASH);
        lineW(g, -i * LANE, y1, -i * LANE, y2, LC, lwid, DASH);
      }
      if (!medNS) lineW(g, 0, y1, 0, y2, CL, cwid);
    }
    const hSpans = [];
    if (NET.arms.E) hSpans.push([bx, VIEW]);
    if (NET.arms.W) hSpans.push([-VIEW, -bx]);
    for (const [x1, x2] of hSpans) {
      for (let i = 1; i < lanesH; i++) {
        lineW(g, x1, i * LANE, x2, i * LANE, LC, lwid, DASH);
        lineW(g, x1, -i * LANE, x2, -i * LANE, LC, lwid, DASH);
      }
      if (!medEW) lineW(g, x1, 0, x2, 0, CL, cwid);
    }
  }

  function zebra(g, arm) {
    const { wv, wh, bx, by } = geom;
    g.fillStyle = PAL.zebra;
    const len = 4.0, stripe = 1.1, gap = 1.0;
    if (arm === "N" || arm === "S") {
      const w = arm === "N" ? geom.wN : geom.wS;
      const y0 = arm === "N" ? by + 0.8 : -(by + 0.8 + len);
      for (let x = -w + 0.4; x + stripe <= w; x += stripe + gap)
        g.fillRect(px(x), py(y0 + len), stripe * MPP, len * MPP);
    } else {
      const w = arm === "E" ? geom.wE : geom.wW;
      const x0 = arm === "E" ? bx + 0.8 : -(bx + 0.8 + len);
      for (let y = -w + 0.4; y + stripe <= w; y += stripe + gap)
        g.fillRect(px(x0), py(y + stripe), len * MPP, stripe * MPP);
    }
  }

  // ---- seeded neighbourhood (cheap, baked into bg, identical per name) ----
  function drawParkedCars(g, rng) {
    const { wN, wS, by } = geom;
    for (const [arm, w, sgn] of [["N", wN, 1], ["S", wS, -1]]) {
      if (!NET.arms[arm]) continue;
      for (let yy = by + 6; yy < VIEW - 5; yy += 6.5 + rng() * 2) {
        // parked on the verge (x = w + SW/2, off the |x|<=w carriageway), length along y
        g.save(); g.translate(px(w + SW * 0.5), py(sgn * yy)); g.rotate((rng() - 0.5) * 0.12);
        g.fillStyle = "rgba(120,130,150,.5)"; rr(g, -1.0 * MPP, -2.4 * MPP, 2.0 * MPP, 4.8 * MPP, 2); g.fill(); g.restore();
      }
    }
  }

  function drawContext(g) {
    const rng = mulberry32(seedFromName(NET.name)), st = styleOf(), { bx, by } = geom;
    for (const [sx, sy] of [[1, 1], [-1, 1], [1, -1], [-1, -1]]) {
      if (st.closeArm === "S" && sy < 0) continue;            // tee: south handled as a solid block
      const x0 = sx * bx, y0 = sy * by;
      rectW(g, x0, y0, x0 + sx * 2.5, sy * VIEW, PAL.sidewalk); // sidewalk bands along each arm
      rectW(g, x0, y0, sx * VIEW, y0 + sy * 2.5, PAL.sidewalk);
      const n = st.ctx === "sparse" ? 2 : st.ctx === "leafy" ? 2 : 3;
      for (let i = 0; i < n; i++) {
        const bw = 8 + rng() * 14, bh = 8 + rng() * 16, mx = x0 + sx * (4 + rng() * 20), my = y0 + sy * (4 + rng() * 20);
        rectW(g, mx, my, mx + sx * bw, my + sy * bh, rng() > 0.5 ? PAL.bldgA : PAL.bldgB);
        lineW(g, mx, my + sy * bh, mx + sx * bw, my + sy * bh, PAL.bldgHi, lw(0.5, 1.5)); // faux extrusion edge
        for (let wq = 0; wq < 4; wq++) if (rng() > 0.5) circleW(g, mx + sx * (2 + rng() * (bw - 3)), my + sy * (2 + rng() * (bh - 3)), 0.5, PAL.win);
      }
      const trees = st.ctx === "leafy" ? 4 : st.ctx === "civic" ? 3 : 2;
      for (let i = 0; i < trees; i++) circleW(g, x0 + sx * (6 + rng() * 22), y0 + sy * (6 + rng() * 22), 1.3 + rng() * 1.3, rng() > 0.5 ? PAL.greenD : PAL.greenL);
      const lx = px(x0 + sx * 3), ly = py(y0 + sy * 3), pool = g.createRadialGradient(lx, ly, 0, lx, ly, 8 * MPP);
      pool.addColorStop(0, PAL.lamp); pool.addColorStop(1, "rgba(255,196,120,0)");
      g.fillStyle = pool; g.beginPath(); g.arc(lx, ly, 8 * MPP, 0, 6.3); g.fill();
    }
    if (st.closeArm === "S") rectW(g, -VIEW, -VIEW, VIEW, -by, PAL.bldgB); // tee: solid building wall across the missing south leg
  }

  function ambientVignette(g) {
    let amb = g.createRadialGradient(CX, CY, 0, CX, CY, VIEW * MPP * 0.6);
    amb.addColorStop(0, PAL.ambient); amb.addColorStop(1, "rgba(255,210,150,0)");
    g.save(); g.globalCompositeOperation = "lighter"; g.fillStyle = amb; g.fillRect(0, 0, W, H); g.restore();
    let vg = g.createRadialGradient(CX, CY, H * 0.34, CX, CY, H * 0.72);
    vg.addColorStop(0, "rgba(0,0,0,0)"); vg.addColorStop(1, PAL.vignette);
    g.fillStyle = vg; g.fillRect(0, 0, W, H);
  }

  function drawFrame(g) {
    const m = 8, len = 22;
    g.save();
    g.strokeStyle = "rgba(56,189,248,.30)"; g.lineWidth = 1.5; g.strokeRect(m, m, W - 2 * m, H - 2 * m);
    g.lineWidth = 2; g.strokeStyle = "rgba(56,189,248,.6)";
    const tick = (x, y, dx, dy) => { g.beginPath(); g.moveTo(x, y); g.lineTo(x + dx, y); g.moveTo(x, y); g.lineTo(x, y + dy); g.stroke(); };
    tick(m, m, len, len); tick(W - m, m, -len, len); tick(m, H - m, len, -len); tick(W - m, H - m, -len, -len);
    const A = NET.arms;
    const sig = NET.kind === "roundabout" ? "ring" : (["N", "S", "E", "W"].filter((k) => A[k]).map((k) => A[k]).join("·") || "ring");
    const label = (NET.label || NET.name).toUpperCase();
    g.font = "600 13px ui-monospace, Menlo, monospace";
    const tw = g.measureText(label).width, cw = tw + 52, ch = 24, cx = m + 8, cy = m + 8;
    g.fillStyle = "rgba(11,17,32,.82)"; rr(g, cx, cy, cw, ch, 7); g.fill();
    g.strokeStyle = "rgba(56,189,248,.4)"; g.lineWidth = 1; g.stroke();
    g.fillStyle = PAL.accent; g.beginPath(); g.arc(cx + 13, cy + ch / 2, 3.4, 0, 6.3); g.fill();
    g.fillStyle = "#e6edf6"; g.textBaseline = "middle"; g.fillText(label, cx + 24, cy + ch / 2 + 1);
    g.font = "600 11px ui-monospace, Menlo, monospace"; g.fillStyle = PAL.accent;
    g.fillText(sig, cx + 24 + tw + 8, cy + ch / 2 + 1);
    g.restore();
  }

  function drawRoundabout(g) {
    const r = NET.ring_r || 22, ringHalf = LANE * 1.4;
    const outer = r + ringHalf, inner = Math.max(r - ringHalf, 4);
    for (const a of Object.keys(NET.arms)) {
      const half = Math.max(NET.arms[a] || 1, 1) * LANE, bh = half + SW;
      if (a === "N") { rectW(g, -bh, r, bh, VIEW, PAL.shoulder); rectW(g, -half, r, half, VIEW, PAL.asphalt); }
      if (a === "S") { rectW(g, -bh, -VIEW, bh, -r, PAL.shoulder); rectW(g, -half, -VIEW, half, -r, PAL.asphalt); }
      if (a === "E") { rectW(g, r, -bh, VIEW, bh, PAL.shoulder); rectW(g, r, -half, VIEW, half, PAL.asphalt); }
      if (a === "W") { rectW(g, -VIEW, -bh, -r, bh, PAL.shoulder); rectW(g, -VIEW, -half, -r, half, PAL.asphalt); }
    }
    circleW(g, 0, 0, outer + 0.8, PAL.shoulder);
    circleW(g, 0, 0, outer, PAL.asphalt);
    circleW(g, 0, 0, inner, PAL.greenD);             // landscaped island
    for (let k = 0; k < 8; k++) { const ang = k / 8 * 6.283; circleW(g, Math.cos(ang) * inner * 0.5, Math.sin(ang) * inner * 0.5, inner * 0.16, PAL.greenL); }
    circleW(g, 0, 0, inner * 0.3, PAL.greenL);
    g.save(); g.strokeStyle = PAL.laneMark; g.lineWidth = lw(0.16, 1.2); g.setLineDash([lw(1.2, 5), lw(1.6, 7)]);
    g.beginPath(); g.arc(px(0), py(0), r * MPP, 0, 6.3); g.stroke(); g.restore();
  }

  function rebuildBackground() {
    computeGeom();
    bgx.clearRect(0, 0, W, H);
    const sky = bgx.createLinearGradient(0, 0, 0, H); sky.addColorStop(0, PAL.skyTop); sky.addColorStop(1, PAL.skyBot);
    bgx.fillStyle = sky; bgx.fillRect(0, 0, W, H);
    if (NET.kind === "roundabout") {
      try { drawContext(bgx); } catch (e) { /* decoration is non-critical */ }
      drawRoundabout(bgx);
      ambientVignette(bgx); drawFrame(bgx);
      return;
    }
    try { drawContext(bgx); } catch (e) { /* decoration is non-critical — roads still render */ }
    drawArmRoads(bgx);
    speckle(bgx);
    kerbLines(bgx);
    // parked-car encroachment is drawn AFTER the roads (so it sits on the verge, not
    // under the opaque road fill); name-seeded so both A/B canvases match.
    if (styleOf().parking) { try { drawParkedCars(bgx, mulberry32(seedFromName(NET.name))); } catch (e) { /* non-critical */ } }
    drawMedian(bgx); drawBusLane(bgx); drawShoulderHatch(bgx); drawIslands(bgx);
    drawMarkings(bgx);
    Object.keys(NET.arms).forEach((a) => zebra(bgx, a));
    ambientVignette(bgx);
    drawFrame(bgx);
  }

  // ---- per-frame overlays ----
  function stopBars(sig) {
    const { wv, wh, by, bx } = geom;
    const segs = { N: [-wv, by, wv, by], S: [-wv, -by, wv, -by], E: [bx, -wh, bx, wh], W: [-bx, -wh, -bx, wh] };
    for (const arm of Object.keys(NET.arms)) {
      const [x1, y1, x2, y2] = segs[arm];
      const c = SIGCOL[sig[arm] || "r"], on = (sig[arm] && sig[arm] !== "r");
      if (on) {                                       // soft ground-glow under a green/yellow approach
        const gx = px((x1 + x2) / 2), gy = py((y1 + y2) / 2);
        const gl = ctx.createRadialGradient(gx, gy, 0, gx, gy, 7 * MPP);
        const col = sig[arm] === "G" ? "34,197,94" : "250,204,21";
        gl.addColorStop(0, `rgba(${col},.16)`); gl.addColorStop(1, `rgba(${col},0)`);
        ctx.save(); ctx.globalCompositeOperation = "lighter"; ctx.fillStyle = gl;
        ctx.beginPath(); ctx.arc(gx, gy, 7 * MPP, 0, 6.3); ctx.fill(); ctx.restore();
      }
      ctx.save(); ctx.strokeStyle = c; ctx.lineWidth = lw(0.55, 4); ctx.lineCap = "round";
      ctx.shadowColor = c; ctx.shadowBlur = on ? 12 : 0;
      ctx.beginPath(); ctx.moveTo(px(x1), py(y1)); ctx.lineTo(px(x2), py(y2)); ctx.stroke();
      ctx.restore();
    }
  }

  function signalHead(wx, wy, state) {
    const x = px(wx), y = py(wy), w = Math.max(9, 1.4 * MPP), h = w * 2.4, br = w * 0.3;
    ctx.save();
    ctx.strokeStyle = "#0c1118"; ctx.lineWidth = Math.max(2, lw(0.25, 2)); // mast pole
    ctx.beginPath(); ctx.moveTo(x, y + h / 2); ctx.lineTo(x, y + h / 2 + 8); ctx.stroke();
    ctx.fillStyle = "#0c1118"; rr(ctx, x - w / 2, y - h / 2, w, h, 3); ctx.fill();
    [["r", "#ef4444"], ["y", "#facc15"], ["G", "#22c55e"]].forEach((L, i) => {
      const cy = y - h / 2 + h * 0.22 + i * h * 0.28, on = state === L[0];
      ctx.beginPath(); ctx.arc(x, cy, br, 0, 6.3);
      ctx.fillStyle = on ? L[1] : "#1b2230";
      ctx.shadowColor = L[1]; ctx.shadowBlur = on ? 12 : 0; ctx.fill();
    });
    ctx.restore();
  }

  function signalHeads(sig) {
    const { bx, by } = geom, o = 4.5;
    if (NET.arms.N) signalHead(bx + o, by + o, sig.N);
    if (NET.arms.S) signalHead(-bx - o, -by - o, sig.S);
    if (NET.arms.E) signalHead(bx + o, -by - o, sig.E);
    if (NET.arms.W) signalHead(-bx - o, by + o, sig.W);
  }

  function drawVehicle(v) {
    const d = TYPES[v.t] || TYPES.c;
    const th = v.a * Math.PI / 180;
    const a = Math.atan2(-Math.cos(th), Math.sin(th));
    const L = d.l * MPP, Wd = d.w * MPP, moving = v.s > 0.2, braking = v.s < 0.6 && !moving;
    ctx.save(); ctx.translate(px(v.x), py(v.y)); ctx.rotate(a);
    ctx.shadowColor = "rgba(0,0,0,.5)"; ctx.shadowBlur = 6; ctx.shadowOffsetY = 2;     // soft shadow
    ctx.fillStyle = v.t === "b" ? "#f59e0b" : v.t === "m" ? "#cbd5e1" : carColor(v.id);
    rr(ctx, -L / 2, -Wd / 2, L, Wd, v.t === "m" ? 1.5 : 3); ctx.fill();
    ctx.shadowBlur = 0; ctx.shadowOffsetY = 0;
    ctx.strokeStyle = "rgba(0,0,0,.45)"; ctx.lineWidth = 1; ctx.stroke();
    if (v.t === "b") {
      ctx.fillStyle = "rgba(8,16,28,.65)"; rr(ctx, -L * 0.32, -Wd * 0.32, L * 0.7, Wd * 0.3, 1.5); ctx.fill();
    } else if (v.t !== "m") {
      ctx.fillStyle = "rgba(8,16,28,.7)";
      rr(ctx, L * 0.06, -Wd * 0.36, L * 0.26, Wd * 0.72, 1.5); ctx.fill();
      rr(ctx, -L * 0.34, -Wd * 0.34, L * 0.16, Wd * 0.68, 1.5); ctx.fill();
    } else {
      ctx.fillStyle = "#475569"; ctx.beginPath(); ctx.arc(0, 0, Wd * 0.45, 0, 6.3); ctx.fill();
    }
    if (v.t !== "m") {                                  // headlights + (moving) beam cone
      ctx.fillStyle = "#fff7d6";
      ctx.beginPath(); ctx.arc(L / 2 - 1, -Wd * 0.3, 1.1, 0, 6.3); ctx.fill();
      ctx.beginPath(); ctx.arc(L / 2 - 1, Wd * 0.3, 1.1, 0, 6.3); ctx.fill();
      if (moving) {
        ctx.save(); ctx.globalCompositeOperation = "lighter";
        const cone = ctx.createRadialGradient(L / 2, 0, 0, L / 2, 0, L * 1.2);
        cone.addColorStop(0, "rgba(255,240,200,.18)"); cone.addColorStop(1, "rgba(255,240,200,0)");
        ctx.fillStyle = cone; ctx.beginPath();
        ctx.moveTo(L / 2, -Wd * 0.5); ctx.lineTo(L / 2 + L * 1.1, -Wd * 1.3);
        ctx.lineTo(L / 2 + L * 1.1, Wd * 1.3); ctx.lineTo(L / 2, Wd * 0.5); ctx.closePath(); ctx.fill(); ctx.restore();
      }
    }
    ctx.fillStyle = braking ? "#ff4d4d" : "rgba(150,40,40,.7)";   // taillights
    ctx.beginPath(); ctx.arc(-L / 2 + 1, -Wd * 0.3, 1.0, 0, 6.3); ctx.fill();
    ctx.beginPath(); ctx.arc(-L / 2 + 1, Wd * 0.3, 1.0, 0, 6.3); ctx.fill();
    ctx.restore();
    if (braking && v.t !== "m") {                       // brake road-glow → queues read red
      ctx.save(); ctx.globalCompositeOperation = "lighter";
      const X = px(v.x), Y = py(v.y), gl = ctx.createRadialGradient(X, Y, 0, X, Y, L * 0.8);
      gl.addColorStop(0, "rgba(255,60,60,.20)"); gl.addColorStop(1, "rgba(255,60,60,0)");
      ctx.fillStyle = gl; ctx.beginPath(); ctx.arc(X, Y, L * 0.8, 0, 6.3); ctx.fill(); ctx.restore();
    }
  }

  function drawPed(p) {
    const x = px(p.x), y = py(p.y);
    ctx.fillStyle = "rgba(192,132,252,.30)"; ctx.beginPath(); ctx.arc(x, y, 5, 0, 6.3); ctx.fill();
    ctx.fillStyle = "#c084fc"; ctx.beginPath(); ctx.arc(x, y, 2.7, 0, 6.3); ctx.fill();
    ctx.strokeStyle = "rgba(255,255,255,.5)"; ctx.lineWidth = 1; ctx.stroke();
  }

  function drawScene(state) {
    ctx.drawImage(bg, 0, 0, W, H);
    if (NET.kind === "roundabout") {
      for (const p of state.peds || []) drawPed(p);
      for (const v of state.vehicles || []) drawVehicle(v);
      return;
    }
    if (state.ped_phase) {
      const { bx, by } = geom;
      ctx.fillStyle = "rgba(192,132,252,.10)";
      ctx.fillRect(px(-bx), py(by), 2 * bx * MPP, 2 * by * MPP);
    }
    stopBars(state.signals || {});
    signalHeads(state.signals || {});
    for (const p of state.peds || []) drawPed(p);
    for (const v of state.vehicles || []) drawVehicle(v);
  }

  function setNetwork(desc) {
    NET = { name: desc.name, label: desc.label || desc.name, arms: desc.arms,
            kind: desc.kind || "signal", ring_r: desc.ring_r || 22, style: desc.style || null };
    rebuildBackground();
  }
  function idle() {
    drawScene({ signals: { N: "G", S: "G", E: "r", W: "r" }, ped_phase: false, vehicles: [], peds: [] });
  }

  rebuildBackground();
  idle();
  return { setNetwork, drawScene, idle };
}
window.Renderer = makeRenderer(document.getElementById("junction"));
