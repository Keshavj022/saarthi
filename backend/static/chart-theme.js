"use strict";
/* Shared Chart.js theme — one source of truth for how every chart in Saarthi
   looks and behaves: typography, palette, smooth entrance animation, crosshair
   hover, and premium tooltips. Also exports gradient-fill helpers so line/bar
   charts get soft depth instead of flat fills. Loaded once, before any view's
   chart code, so `window.ChartTheme` is ready when charts are built. */
(function () {
  if (typeof Chart === "undefined") return;

  const css = getComputedStyle(document.documentElement);
  const v = (name, fb) => (css.getPropertyValue(name).trim() || fb);

  const PAL = {
    text:   v("--text", "#e8edf5"),
    muted:  v("--muted", "#94a2b8"),
    faint:  v("--faint", "#5d6b80"),
    grid:   "rgba(125,144,176,.12)",
    gridX:  "rgba(125,144,176,.05)",
    accent: v("--accent", "#2dd4bf"),
    sky:    v("--accent-2", "#38bdf8"),
    good:   v("--good", "#34d399"),
    warn:   v("--warn", "#fbbf24"),
    bad:    v("--bad", "#f87171"),
    info:   v("--info", "#c084fc"),
    surface:v("--surface", "#111722"),
  };

  // hex (#rgb / #rrggbb) -> rgba string with alpha
  function hexA(hex, a) {
    if (!hex) return `rgba(148,162,184,${a})`;
    if (hex.startsWith("rgb")) return hex;
    let h = hex.replace("#", "");
    if (h.length === 3) h = h.split("").map((c) => c + c).join("");
    const n = parseInt(h, 16);
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
  }

  // scriptable backgroundColor → vertical gradient that fades to transparent.
  function fadeFill(hex, top = 0.32, bot = 0.0) {
    return (c) => {
      const { ctx, chartArea } = c.chart;
      if (!chartArea) return hexA(hex, top);
      const g = ctx.createLinearGradient(0, chartArea.top, 0, chartArea.bottom);
      g.addColorStop(0, hexA(hex, top));
      g.addColorStop(1, hexA(hex, bot));
      return g;
    };
  }

  // gradient for bars (top brighter → bottom dim) for a bit of dimensionality.
  function barFill(hex) {
    return (c) => {
      const { ctx, chartArea } = c.chart;
      if (!chartArea) return hex;
      const g = ctx.createLinearGradient(0, chartArea.top, 0, chartArea.bottom);
      g.addColorStop(0, hexA(hex, 1));
      g.addColorStop(1, hexA(hex, 0.55));
      return g;
    };
  }

  const fontStack =
    '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, system-ui, sans-serif';

  // ---- global defaults: applies to every chart created afterwards ----
  Chart.defaults.font.family = fontStack;
  Chart.defaults.font.size = 12;
  Chart.defaults.font.weight = "500";
  Chart.defaults.color = PAL.muted;
  Chart.defaults.animation = { duration: 850, easing: "easeOutQuart" };
  Chart.defaults.animations = {
    colors: { duration: 400 },
    numbers: { duration: 850, easing: "easeOutQuart" },
  };
  Chart.defaults.interaction = { mode: "index", intersect: false };
  Chart.defaults.elements.bar.borderRadius = 7;
  Chart.defaults.elements.bar.borderSkipped = false;
  Chart.defaults.elements.line.tension = 0.38;
  Chart.defaults.elements.line.borderWidth = 2.5;
  Chart.defaults.elements.point.radius = 0;
  Chart.defaults.elements.point.hoverRadius = 5;
  Chart.defaults.elements.point.hoverBorderWidth = 2;

  Chart.defaults.plugins.legend.labels.color = PAL.text;
  Chart.defaults.plugins.legend.labels.usePointStyle = true;
  Chart.defaults.plugins.legend.labels.pointStyle = "circle";
  Chart.defaults.plugins.legend.labels.boxWidth = 8;
  Chart.defaults.plugins.legend.labels.boxHeight = 8;
  Chart.defaults.plugins.legend.labels.padding = 16;
  Chart.defaults.plugins.legend.labels.font = { size: 12, weight: "600" };

  Object.assign(Chart.defaults.plugins.tooltip, {
    enabled: true,
    backgroundColor: "rgba(9,13,22,.95)",
    borderColor: hexA(PAL.accent, 0.45),
    borderWidth: 1,
    titleColor: PAL.text,
    bodyColor: PAL.text,
    titleFont: { weight: "700", size: 12.5 },
    bodyFont: { weight: "500", size: 12.5 },
    padding: 11,
    cornerRadius: 11,
    boxPadding: 6,
    usePointStyle: true,
    caretSize: 6,
  });

  // axis styling helper so views don't repeat scale boilerplate
  function axes({ x = {}, y = {} } = {}) {
    return {
      x: Object.assign({
        ticks: { color: PAL.muted, font: { size: 11 } },
        grid: { color: PAL.gridX, drawTicks: false },
        border: { color: "transparent" },
      }, x),
      y: Object.assign({
        ticks: { color: PAL.muted, font: { size: 11 }, padding: 6 },
        grid: { color: PAL.grid, drawTicks: false },
        border: { color: "transparent" },
      }, y),
    };
  }

  window.ChartTheme = { PAL, hexA, fadeFill, barFill, axes };
})();
