// Pitch deck. Every number is loaded from the repo's data files (via /api/data/*), never typed in.
const slides = [...document.querySelectorAll(".slide")];
let i = Math.max(0, Math.min(slides.length - 1, (parseInt(location.hash.slice(1)) || 1) - 1));

function show(n) {
  i = Math.max(0, Math.min(slides.length - 1, n));
  slides.forEach((s, k) => s.classList.toggle("on", k === i));
  document.getElementById("bar").style.width = `${((i + 1) / slides.length) * 100}%`;
  document.getElementById("count").textContent = `${i + 1} / ${slides.length}`;
  history.replaceState(null, "", `#${i + 1}`);
}
document.addEventListener("keydown", (e) => {
  if (["ArrowRight", "PageDown", " ", "Enter"].includes(e.key)) { e.preventDefault(); show(i + 1); }
  if (["ArrowLeft", "PageUp", "Backspace"].includes(e.key)) { e.preventDefault(); show(i - 1); }
  if (e.key === "Home") show(0);
  if (e.key === "End") show(slides.length - 1);
  if (e.key === "f") document.documentElement.requestFullscreen?.();
  if (e.key === "s") window.open("/stage/", "kettle-stage");
});
document.addEventListener("click", (e) => { if (!e.target.closest("a,button")) show(i + (e.clientX < innerWidth / 4 ? -1 : 1)); });
show(i);

const get = (p) => fetch(p).then((r) => (r.ok ? r.json() : null)).catch(() => null);
const fmt = (n, d = 0) => n == null ? "–" : Number(n).toLocaleString("en-CA", { maximumFractionDigits: d, minimumFractionDigits: d }).replace("-", "−");
const hhmm = (m) => `${Math.floor(m / 60)}:${String(Math.round(m % 60)).padStart(2, "0")}`;

// ------------------------------------------------------------------ rhythm line (Margaret = REFIT House 11)
get("/api/data/margaret").then((m) => {
  const b = m?.baselines?.v0_kettle_plug?.standard;
  if (b?.usual) document.getElementById("rhythm-line").textContent = `“First kettle usually ${b.usual} ± ${b.spread} min on weekdays.” (REFIT House 11, real)`;
});

// ------------------------------------------------------------------ Jan 13 2024
get("/api/data/jan13").then((d) => {
  if (!d) return;
  const day = d.hourly.filter((h) => h.hour_start.startsWith("2024-01-13"));
  const wx = d.weather.filter((w) => w.t.startsWith("2024-01-13"));
  const svg = document.getElementById("jan13chart");
  const W = 900, H = 300, L = 60, R = 20, T = 20, B = 40;
  const x = (hour) => L + (hour / 24) * (W - L - R);
  const ails = day.map((h) => h.ail_mw), lo = Math.floor(Math.min(...ails) / 250) * 250, hi = Math.ceil(Math.max(...ails) / 250) * 250;
  const y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  const ns = "http://www.w3.org/2000/svg";
  const add = (tag, attrs, text) => { const el = document.createElementNS(ns, tag); for (const k in attrs) el.setAttribute(k, attrs[k]); if (text) el.textContent = text; svg.append(el); return el; };
  // price at the $999.99 cap: shaded hours
  day.forEach((h, k) => { if (h.pool_price >= 999.99) add("rect", { x: x(k), y: T, width: x(1) - x(0), height: H - T - B, fill: "rgba(255,180,87,.12)" }); });
  for (let v = lo; v <= hi; v += 500) { add("line", { x1: L, x2: W - R, y1: y(v), y2: y(v), stroke: "#2c2017" }); add("text", { x: L - 8, y: y(v) + 5, "text-anchor": "end" }, `${fmt(v / 1000, 1)}k`); }
  [0, 6, 12, 18, 24].forEach((hr) => add("text", { x: x(hr), y: H - 12, "text-anchor": "middle" }, `${hr}:00`));
  add("polyline", { points: day.map((h, k) => `${x(k + .5)},${y(h.ail_mw)}`).join(" "), fill: "none", stroke: "#f6efe4", "stroke-width": 3, "stroke-linejoin": "round" });
  // 18:44 alert
  const ax = x(18 + 44 / 60);
  add("line", { x1: ax, x2: ax, y1: T - 6, y2: H - B, stroke: "#a9d6f5", "stroke-width": 2, "stroke-dasharray": "4 4" });
  add("text", { x: ax + 8, y: T + 10, fill: "#a9d6f5" }, "18:44 alert");
  add("text", { x: L, y: T - 4 }, "Alberta Internal Load (MW, hourly) · shaded: pool price at $999.99 cap");

  const h18 = day.find((h) => h.hour_start.endsWith("T18:00")), h19 = day.find((h) => h.hour_start.endsWith("T19:00"));
  const t18 = wx.find((w) => w.t.endsWith("T18:00"));
  const capHours = day.filter((h) => h.pool_price >= 999.99).length;
  document.getElementById("jan13facts").innerHTML = `
    <div class="row"><span class="v ice">${fmt(t18?.temp_c, 1)} °C</span><span class="l">Calgary at 18:00 · wind chill ${fmt(t18?.wind_chill)} (ECCC, CALGARY INTL A)</span></div>
    <div class="row"><span class="v">${capHours} h</span><span class="l">pool price pinned at the $999.99/MWh cap (AESO)</span></div>
    <div class="row"><span class="v">${fmt(h18?.ail_mw)} → ${fmt(h19?.ail_mw)} MW</span><span class="l">Alberta load, 18:00–19:00 vs 19:00–20:00 hour (AESO). AESO: ~200 MW cut within minutes of the alert</span></div>`;
  document.getElementById("jan13src").textContent = "Sources: AESO Actual/Forecast + newsroom (Jan 13 2024) · Power Advisory · Environment and Climate Change Canada. Times MST.";
});

// ------------------------------------------------------------------ REFIT evidence
get("/api/data/refit").then((s) => {
  const el = document.getElementById("evidence");
  if (!s) { el.innerHTML = `<p class="muted">The REFIT evaluation hasn't been generated yet.</p>`; return; }
  const c = s.checkins_per_home_month || {};
  const v0 = c.v0_kettle_plug?.standard, paused = s.checkins_per_home_month_away_paused?.v0_kettle_plug?.standard;
  const wait = s.minutes_after_usual_before_asking?.v0_kettle_plug?.standard;
  el.innerHTML = `
    <div class="fact"><span class="big">${fmt(s.kettle_f1_plug != null ? s.kettle_f1_plug * 100 : null)}%</span><span>kettle detection F1 with a plug on the kettle</span><small>whole-home meter: ${fmt((s.kettle_f1 ?? 0) * 100)}% on 3 kW UK kettles</small></div>
    <div class="fact"><span class="big">${fmt(v0, 1)}</span><span>check-in calls per home per month</span><small>${paused != null ? `${fmt(paused, 1)} if away days are paused · ` : ""}each one is a call to the person first, not a neighbour</small></div>
    <div class="fact"><span class="big">${fmt(wait)}<span style="font-size:.4em"> min</span></span><span>median wait after the usual time before asking</span><small>cold mode asks sooner: ${fmt(s.minutes_after_usual_before_asking?.v0_kettle_plug?.cold)} min</small></div>`;
  document.getElementById("evsrc").textContent = `REFIT: ${s.houses} UK homes, ${fmt(s.home_days)} home-days of real 8-second measurements, CC BY 4.0 (Murray et al., Sci. Data 2017). Same detector + rhythm code as the live demo. Pilot in Calgary homes: not yet run.`;
});
