/* Kettle — the film. Everything is a pure function of time t (seconds), so render.py can
   step frame by frame: window.seek(t). Open film.html?t=93 to look at one moment, or ?play. */
(() => {
  "use strict";
  const W = 1920, H = 1080;
  const D = window.KDATA, TL = window.KTIME;
  const $ = (id) => document.getElementById(id);

  // ------------------------------------------------------------------ math
  const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
  const lerp = (a, b, t) => a + (b - a) * t;
  const ramp = (t, a, b) => clamp((t - a) / (b - a));
  const ease = {
    out3: (x) => 1 - (1 - x) ** 3,
    out5: (x) => 1 - (1 - x) ** 5,
    outExpo: (x) => (x >= 1 ? 1 : 1 - 2 ** (-10 * x)),
    io3: (x) => (x < 0.5 ? 4 * x * x * x : 1 - (-2 * x + 2) ** 3 / 2),
    ioSine: (x) => -(Math.cos(Math.PI * x) - 1) / 2,
    in2: (x) => x * x,
  };
  const er = (t, a, b, fn = ease.out3) => fn(ramp(t, a, b));
  /** 0 → 1 between a and a+fi, 1 → 0 between b and b+fo. */
  const win = (t, a, b, fi = 0.8, fo = 0.8) => ease.ioSine(ramp(t, a, a + fi)) * (1 - ease.ioSine(ramp(t, b, b + fo)));
  const hash = (n) => { const x = Math.sin(n * 127.1 + 311.7) * 43758.5453; return x - Math.floor(x); };
  function rng(seed) { let s = seed >>> 0 || 1; return () => ((s = (s * 16807) % 2147483647) / 2147483647); }
  const vnoise = (x, seed = 0) => { const i = Math.floor(x), f = x - i, u = f * f * (3 - 2 * f); return lerp(hash(i + seed * 57), hash(i + 1 + seed * 57), u) * 2 - 1; };

  // ------------------------------------------------------------------ voice-over timing helpers
  const VO = {};
  for (const v of TL.vo) VO[v.id] = v;
  /** absolute time of the n-th word of a VO line (or of the first word matching a prefix). */
  function wt(id, which) {
    const v = VO[String(id)];
    if (typeof which === "number") return v.at + v.words[which][1];
    const w = v.words.find((x) => x[0].toLowerCase().replace(/[^a-z0-9']/g, "").startsWith(which));
    if (!w) throw new Error(`word ${which} not in ${id}`);
    return v.at + w[1];
  }

  // ------------------------------------------------------------------ DOM helpers
  function style(el, o, y = 0, s = 1, blur = 0, extra = "") {
    el.style.opacity = o.toFixed(4);
    el.style.visibility = o <= 0.001 ? "hidden" : "visible";
    el.style.transform = `translate3d(0, ${y.toFixed(2)}px, 0) scale(${s.toFixed(4)}) ${extra}`;
    el.style.filter = blur > 0.05 ? `blur(${blur.toFixed(2)}px)` : "none";
  }
  /** Rise-and-sharpen entrance at a, fade-up exit at b. */
  function rev(el, t, a, b = 1e9, { dur = 1.0, rise = 22, blur = 10, fo = 0.7, extra = "" } = {}) {
    const i = er(t, a, a + dur, ease.out5), o = er(t, b, b + fo, ease.io3);
    style(el, i * (1 - o), (1 - i) * rise - o * rise * 0.6, 1, (1 - i) * blur + o * blur * 0.6, extra);
  }
  function words(el, text) {
    el.textContent = "";
    return text.split(" ").map((w, i, a) => { const s = document.createElement("span"); s.textContent = w + (i < a.length - 1 ? " " : ""); el.appendChild(s); return s; });
  }
  function scene(id, t, a, b, fi = 0.6, fo = 0.6) {
    const el = $(id), o = win(t, a, b, fi, fo);
    el.style.opacity = o.toFixed(4);
    el.style.visibility = o > 0.001 ? "visible" : "hidden";
    return o;
  }
  const fmt = (min) => { const m = Math.floor(min) % 1440; return `${Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")}`; };

  // ------------------------------------------------------------------ canvas helpers
  const back = $("back").getContext("2d"), front = $("front").getContext("2d");
  function sprite(r, g, b) {
    const c = document.createElement("canvas"); c.width = c.height = 128;
    const x = c.getContext("2d"), gr = x.createRadialGradient(64, 64, 0, 64, 64, 64);
    gr.addColorStop(0, `rgba(${r},${g},${b},1)`); gr.addColorStop(0.35, `rgba(${r},${g},${b},.55)`);
    gr.addColorStop(0.7, `rgba(${r},${g},${b},.12)`); gr.addColorStop(1, `rgba(${r},${g},${b},0)`);
    x.fillStyle = gr; x.fillRect(0, 0, 128, 128); return c;
  }
  const SPR = { steam: sprite(246, 239, 228), amber: sprite(255, 180, 87), frost: sprite(200, 228, 250), white: sprite(255, 255, 255) };
  function blob(ctx, spr, x, y, r, a) { if (a <= 0.002 || r <= 0) return; ctx.globalAlpha = Math.min(1, a); ctx.drawImage(spr, x - r, y - r, r * 2, r * 2); ctx.globalAlpha = 1; }

  /** Deterministic steam: particles emitted on a fixed time grid, so any t renders the same. */
  function steam(ctx, t, { x, y, t0, t1 = 1e9, rate = 60, life = 4.6, scale = 1, alpha = 1, rise = 1, seed = 1, spread = 1 }) {
    if (t < t0) return;
    const k0 = Math.ceil(Math.max(t0, t - life) * rate), k1 = Math.floor(Math.min(t, t1) * rate);
    ctx.globalCompositeOperation = "lighter";
    for (let k = k0; k <= k1; k++) {
      const e = k / rate, age = t - e;
      if (age < 0 || age > life) continue;
      const r1 = hash(k * 1.3 + seed), r2 = hash(k * 2.7 + seed * 3), r3 = hash(k * 4.1 + seed * 7), r4 = hash(k * 5.9 + seed * 11);
      const u = age / life;
      const py = y - (70 + 50 * r1) * age * rise * scale - 10 * age * age * scale;
      const sway = Math.sin(age * (1.1 + r2 * 0.8) + r3 * 6.283 + vnoise(e * 0.7, seed) * 2) * (8 + 26 * age) * spread * scale;
      const px = x + sway + (r4 - 0.5) * 18 * age * scale + vnoise(e * 0.3 + age * 0.4, seed + 5) * 40 * u * scale;
      const r = (7 + 19 * age) * scale * (0.7 + 0.6 * r1);
      const a = alpha * 0.042 * Math.sin(Math.PI * Math.min(1, u)) ** 0.9 * clamp(age / 0.35);
      blob(ctx, SPR.steam, px, py, r, a);
    }
    ctx.globalCompositeOperation = "source-over";
  }
  /** A glowing polyline (drawn three times, wide to narrow). */
  function glowLine(ctx, pts, { color = "255,180,87", width = 3, glow = 1, alpha = 1 } = {}) {
    if (pts.length < 2 || alpha <= 0) return;
    ctx.lineJoin = ctx.lineCap = "round";
    for (const [w, a] of [[width * 7, 0.06], [width * 3, 0.16], [width, 1]]) {
      ctx.beginPath(); ctx.moveTo(pts[0][0], pts[0][1]);
      for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
      ctx.strokeStyle = `rgba(${color},${(a * alpha * (w === width ? 1 : glow)).toFixed(3)})`; ctx.lineWidth = w; ctx.stroke();
    }
  }


  // ================================================================== OPEN
  const openWords = words($("open-cap"), "Every morning, around ten, Margaret makes tea.");
  const LED = { x: 960, y: 700 };
  function renderOpen(t) {
    scene("s-open", t, 0, 8.6, 0.01, 0.9);
    openWords.forEach((s, i) => rev(s, t, VO["1"].at + VO["1"].words[i][1] - 0.05, 7.8, { dur: 0.9, rise: 14, blur: 8, fo: 1.0 }));
    // the kettle's switch light, then steam
    const on = ramp(t, 0.5, 0.55), flash = Math.exp(-Math.max(0, t - 0.5) * 6) * on;
    const toLine = er(t, 8.3, 10.2, ease.io3);
    const ledA = on * (1 - toLine) * (0.85 + 0.15 * Math.sin(t * 2.2));
    if (ledA > 0) {
      blob(back, SPR.amber, LED.x, LED.y, 90 + flash * 120, 0.55 * ledA + flash * 0.5);
      back.fillStyle = `rgba(255,196,120,${ledA})`;
      back.beginPath(); back.roundRect(LED.x - 14, LED.y - 4, 28, 8, 4); back.fill();
    }
    steam(back, t, { x: LED.x, y: LED.y - 30, t0: 0.9, t1: 7.4, rate: 70, life: 5.0, scale: 1.2, alpha: 1.0, seed: 3 });
    // the light becomes a line: Margaret's power trace
    if (toLine > 0 && t < 11.5) {
      const half = 800 * toLine;
      openLine(t, half, 1 - ramp(t, 10.5, 11.2));
    }
  }
  function flatLine(x0, x1, y, t, amp = 1.6, seed = 2) {
    const pts = [];
    for (let x = x0; x <= x1; x += 8) pts.push([x, y + vnoise(x * 0.05 + t * 3, seed) * amp]);
    return pts;
  }
  function openLine(t, half, a) {
    glowLine(back, flatLine(960 - half, 960 + half, 700, t), { color: "246,239,228", width: 2.2, alpha: 0.8 * a, glow: 0.6 });
  }

  // ================================================================== RHYTHM
  const RX0 = 200, RX1 = 1720;
  const rx = (min) => RX0 + ((min - 240) / 1440) * (RX1 - RX0);
  const day0 = D.days.find((d) => d.date === "2014-12-03");
  const rowsY = (i) => 236 + i * 27;
  const day0Index = D.days.indexOf(day0);
  const rhAxis = $("rh-axis");
  const ticks = [6, 9, 12, 15, 18, 21].map((h) => {
    const s = document.createElement("div"); s.className = "tk"; s.textContent = `${h % 24}:00`;
    s.style.left = `${rx(h * 60)}px`; rhAxis.appendChild(s); return s;
  });
  const callouts = [["kettle", "Kettle"], ["toaster", "Toaster"], ["microwave", "Microwave"]].map(([label, name]) => {
    const e = day0.events.find((x) => x.label === label);
    const el = document.createElement("div"); el.className = "ch"; el.innerHTML = `${name}<small>${fmt(e.min)}</small>`;
    $("rh-chips").appendChild(el);
    return { e, el, at: wt(2, label === "kettle" ? "kettle" : label) };
  });
  // the 22 days fold into one point of light, which becomes the 42%
  const FOLD = { a: 20.9, b: 22.05, x: 512, y: 488 };
  function renderRhythm(t) {
    scene("s-rhythm", t, 10.3, 20.7, 0.5, 0.6);
    if (t < 10.3 || t > 23.4) return;
    const zoom = 1 + 0.05 * ease.ioSine(ramp(t, VO["3"].at, 22.4));
    const f = er(t, FOLD.a, FOLD.b, ease.io3), fx = f ** 0.7, fy = f ** 1.35;
    $("s-rhythm").style.transform = `scale(${zoom})`; $("s-rhythm").style.transformOrigin = "960px 520px";
    if (t < FOLD.b + 0.05) {
      back.save();
      back.translate(lerp(960, FOLD.x, f), lerp(520, FOLD.y, f));
      back.scale(zoom * lerp(1, 0.015, fx), zoom * lerp(1, 0.02, fy));
      back.translate(-960, -520);
      try { drawRhythm(t); } finally { back.restore(); }
    }
    // the spark: gathers as the rows fold, flashes, and leaves a soft ring that opens into the number
    const gather = er(t, FOLD.a + 0.4, FOLD.b, ease.in2), spark = Math.exp(-Math.max(0, t - FOLD.b) * 3.2) * (t >= FOLD.b ? 1 : gather);
    back.globalCompositeOperation = "lighter";
    blob(back, SPR.amber, FOLD.x, FOLD.y, 40 + 260 * spark, 0.9 * spark);
    blob(back, SPR.white, FOLD.x, FOLD.y, 14 + 40 * spark, 0.8 * spark);
    back.globalCompositeOperation = "source-over";
    const ring = ramp(t, FOLD.b, FOLD.b + 1.1);
    if (ring > 0 && ring < 1) {
      back.strokeStyle = `rgba(255,190,110,${(0.5 * (1 - ring) ** 1.5).toFixed(3)})`; back.lineWidth = 2.5 * (1 - ring) + 0.5;
      back.beginPath(); back.arc(FOLD.x, FOLD.y, 30 + ease.out3(ring) * 420, 0, Math.PI * 2); back.stroke();
    }
  }
  function drawRhythm(t) {
    const toRows = er(t, VO["3"].at - 0.1, VO["3"].at + 1.6, ease.io3);
    const yMain = lerp(700, rowsY(day0Index), toRows);
    ticks.forEach((s, i) => { rev(s, t, 10.6 + i * 0.06, 20.5, { rise: 8, blur: 4, fo: 0.5 }); s.style.top = `${lerp(730, 830, toRows) + 0}px`; });
    const fade = 1 - ramp(t, FOLD.b - 0.25, FOLD.b);
    // main day: baseline + spikes that rise as the voice names them
    const pts = [[RX0, yMain]];
    const shown = day0.events.map((e) => {
      const c = callouts.find((c) => c.e === e);
      return { e, at: c ? c.at : VO["2"].at + 3.7 + (e.min % 7) * 0.08 };
    }).sort((a, b) => a.e.min - b.e.min);
    for (const { e, at } of shown) {
      const k = er(t, at, at + 0.5, ease.out3), x = rx(e.min), h = (e.w / 2200) * lerp(200, 20, toRows) * k;
      pts.push([x - 1, yMain], [x, yMain - h], [x + 5, yMain - h], [x + 6, yMain]);
    }
    pts.push([RX1, yMain]);
    glowLine(back, pts, { color: "246,239,228", width: 2.2, alpha: 0.85 * fade, glow: 0.5 });
    for (const { e, at } of shown) {
      const k = Math.exp(-Math.max(0, t - at) * 0.8) * ramp(t, at, at + 0.05);
      blob(back, SPR.amber, rx(e.min) + 3, yMain - (e.w / 2200) * lerp(200, 20, toRows), 70, 0.5 * k * fade);
    }
    callouts.forEach((c) => {
      rev(c.el, t, c.at, VO["3"].at - 0.2, { rise: 14, blur: 6, fo: 0.5 });
      c.el.style.left = `${rx(c.e.min) + 3}px`; c.el.style.top = `${yMain - (c.e.w / 2200) * 200 - 22}px`;
    });
    // all the real days, stacked
    if (toRows > 0) {
      D.days.forEach((d, i) => {
        if (i === day0Index) return;
        const a = er(t, VO["3"].at + 0.2 + i * 0.03, VO["3"].at + 1.0 + i * 0.03) * fade;
        if (a <= 0) return;
        const y = rowsY(i);
        back.strokeStyle = `rgba(246,239,228,${0.12 * a})`; back.lineWidth = 1.5;
        back.beginPath(); back.moveTo(RX0, y); back.lineTo(RX1, y); back.stroke();
        d.events.forEach((e, j) => {
          const first = j === 0, x = rx(e.min), h = 4 + (e.w / 2200) * 16;
          back.fillStyle = e.label === "kettle" ? `rgba(255,180,87,${(first ? 1 : 0.75) * a})` : `rgba(205,191,174,${0.6 * a})`;
          back.fillRect(x - 1.5, y - h, 3, h);
          if (first) blob(back, SPR.amber, x, y - 6, 22, 0.35 * a);
        });
      });
    }
    // her usual morning (weekday baseline from the same data)
    const bandA = er(t, wt(3, "and") - 0.2, wt(3, "and") + 1.4) * fade;
    if (bandA > 0) {
      const xa = rx(614 - 75), xb = rx(614 + 75), yt = rowsY(0) - 40, yb = rowsY(D.days.length - 1) + 16;
      const g = back.createLinearGradient(xa, 0, xb, 0);
      g.addColorStop(0, "rgba(255,180,87,0)"); g.addColorStop(0.5, `rgba(255,180,87,${0.16 * bandA})`); g.addColorStop(1, "rgba(255,180,87,0)");
      back.fillStyle = g; back.fillRect(xa, yt, xb - xa, yb - yt);
    }
    const bl = $("rh-band"); rev(bl, t, wt(3, "and") + 0.2, 20.4, { fo: 0.5 }); bl.style.left = `${rx(614)}px`; bl.style.top = `${rowsY(0) - 96}px`;
    rev($("rh-src"), t, wt(3, "already"), 20.4, { rise: 8, blur: 4, fo: 0.5 });
  }

  // ================================================================== PROBLEM
  const pbWords = words($("pb-42t"), "of Canadians aged 85 and over live alone.");
  const dotEls = [];
  for (let i = 0; i < 10; i++) { const d = document.createElement("i"); d.style.left = `${960 - 4.5 * 118 - 42 + i * 118}px`; $("pb-dots").appendChild(d); dotEls.push(d); }
  function renderProblem(t) {
    const o = scene("s-problem", t, 22.0, 41.2, 0.4, 0.7);
    if (o <= 0) return;
    // 42%
    const a0 = VO["4"].at;
    const n = Math.max(1, Math.round(42 * er(t, FOLD.b - 0.05, a0 + 1.7, ease.outExpo)));
    $("pb-42").textContent = `${n}%`;
    { const el = $("pb-42"), k = er(t, FOLD.b - 0.05, FOLD.b + 1.1, ease.out5), out = er(t, 27.7, 28.4, ease.io3);
      style(el, k * (1 - out), -out * 18, lerp(0.72, 1, k), (1 - k) * 22 + out * 8); el.style.transformOrigin = "282px 158px"; }
    pbWords.forEach((s, i) => rev(s, t, a0 + 0.9 + i * 0.07, 27.7, { rise: 14, blur: 6 }));
    rev($("pb-42s"), t, a0 + 1.6, 27.7, { rise: 6, blur: 3 });
    // 8 in 10
    const b0 = VO["5"].at;
    rev($("pb-b1"), t, b0 + 0.05, 36.5, { fo: 0.6 });
    const dotsAt = wt(5, "8");
    // the ten circles slide together and become the pendant: the eight who didn't press, the two who did
    const merge = er(t, 36.55, 37.4, ease.io3), gone = er(t, 37.32, 37.6);
    dotEls.forEach((d, i) => {
      const ap = er(t, dotsAt + i * 0.07, dotsAt + 0.5 + i * 0.07, ease.out5);
      const used = i === 3 || i === 7; // two of the ten
      const k = er(t, wt(5, "they") - 1.0 + i * 0.06, wt(5, "they") - 0.4 + i * 0.06);
      const cx = 960 - 4.5 * 118 + i * 118;
      d.style.opacity = (ap * (1 - gone)).toFixed(3);
      const sc = lerp(0.6, 1, ap) * lerp(1, used ? 60 / 84 : 140 / 84, merge);
      d.style.transform = `translate(${((960 - cx) * merge).toFixed(1)}px, ${((1 - ap) * 20 + 78 * merge).toFixed(1)}px) scale(${sc.toFixed(4)})`;
      d.style.zIndex = used ? 2 : 1;
      if (used) { d.style.background = `rgba(255,180,87,${lerp(lerp(0.25, 0.95, k), 0.6, merge)})`; d.style.boxShadow = `0 0 ${40 * k}px rgba(255,180,87,${0.6 * k})`; d.style.border = "0"; }
      else { d.style.background = `rgba(20,14,9,${0.6 * merge})`; d.style.border = `${lerp(2, 2.4, merge)}px solid rgba(246,239,228,${lerp(lerp(0.25, 0.35, k), 0.9, merge)})`; d.style.boxShadow = "none"; }
    });
    rev($("pb-b2"), t, wt(5, "they") - 0.1, 36.5, { fo: 0.6 });
    rev($("pb-bs"), t, wt(5, "they") + 0.4, 36.5, { rise: 6, blur: 3, fo: 0.6 });
    // the pendant: in place where the circles met; its cord draws up, then it swings
    const pa = er(t, 37.3, 37.6) * (1 - er(t, 41.0, 41.6, ease.io3));
    const pe = $("pb-pendant");
    pe.style.opacity = pa.toFixed(3); pe.style.visibility = pa > 0 ? "visible" : "hidden";
    const cord = $("pb-cord"), ck = er(t, 37.45, 38.3, ease.out3);
    cord.style.strokeDasharray = "520 520"; cord.style.strokeDashoffset = (520 * (1 - ck)).toFixed(1);
    const s0 = 38.1, P = wt(6, "press") + 0.22;
    let ang = (t > s0 ? 6 * Math.sin((t - s0) * 2.1) * Math.exp(-(t - s0) * 0.25) * ramp(t, s0, s0 + 0.8) : 0) + 1.2 * Math.sin(t * 1.3) * ramp(t, 37.6, 38.6);
    if (t > P) ang += 2.2 * Math.sin((t - P) * 7) * Math.exp(-(t - P) * 2.6);
    pe.style.transform = `rotate(${ang.toFixed(3)}deg)`;
    // the press: the button gives, the light answers (and a click on the soundtrack)
    const press = ramp(t, P - 0.07, P) * (1 - er(t, P + 0.06, P + 0.4));
    const lit = t >= P ? Math.exp(-(t - P) * 1.6) : 0;
    $("pb-disc").style.transform = `scale(${(1 - 0.09 * press).toFixed(4)})`;
    const core = $("pb-core");
    core.setAttribute("opacity", (0.6 + 0.4 * lit).toFixed(3));
    core.setAttribute("fill", lit > 0.02 ? `rgb(255,${Math.round(lerp(145, 205, lit))},${Math.round(lerp(45, 130, lit))})` : "#e8912d");
    const rad = (ang * Math.PI) / 180, dx = 960 - 590 * Math.sin(rad), dy = 590 * Math.cos(rad);
    if (lit > 0.01) {
      front.globalCompositeOperation = "lighter";
      blob(front, SPR.amber, dx, dy, 120 + 120 * lit, 0.55 * lit * pa);
      front.globalCompositeOperation = "source-over";
      for (const r0 of [P, P + 0.2]) {
        const u = ramp(t, r0, r0 + 1.0);
        if (u <= 0 || u >= 1) continue;
        front.strokeStyle = `rgba(255,196,120,${(0.55 * (1 - u) ** 1.6 * pa).toFixed(3)})`; front.lineWidth = 2;
        front.beginPath(); front.arc(dx, dy, 74 + ease.out3(u) * 150, 0, Math.PI * 2); front.stroke();
      }
    }
    rev($("pb-wear"), t, wt(6, "wear") - 0.05, 41.0, { rise: 16 });
    rev($("pb-press"), t, wt(6, "press") - 0.05, 41.0, { rise: 16 });
  }

  // ================================================================== BRAND
  const LOGO_PATHS = (svg) => [...svg.querySelectorAll("path")].map((p) => { const L = p.getTotalLength(); p.style.strokeDasharray = `${L} ${L}`; return { p, L }; });
  const brandLogo = LOGO_PATHS($("br-logo")), closeLogo = LOGO_PATHS($("cl-logo"));
  function drawLogo(paths, t, a) {
    paths.forEach(({ p, L }, i) => { const k = er(t, a + i * 0.55, a + i * 0.55 + 1.1, ease.io3); p.style.strokeDashoffset = (L * (1 - k)).toFixed(2); });
  }
  function renderBrand(t) {
    const o = scene("s-brand", t, 41.5, 51.6, 0.4, 0.9);
    if (o <= 0) return;
    rev($("br-nothing"), t, VO["7"].at + 0.05, 43.75, { fo: 0.5 });
    const b = $("br-brand");
    const push = 1 + 0.03 * ease.ioSine(ramp(t, 44, 52));
    b.style.transform = `scale(${push})`;
    drawLogo(brandLogo, t, 44.05);
    const lg = er(t, 44.0, 44.4);
    $("br-logo").style.opacity = lg;
    rev($("br-word"), t, 44.6, 1e9, { dur: 1.4, rise: 26, blur: 14 });
    const nos = [...$("br-nos").children];
    nos.forEach((s, i) => rev(s, t, wt(8, [0, 2, 4][i]) - 0.05, 1e9, { rise: 14, blur: 6 }));
    rev($("br-just"), t, wt(8, "just") - 0.05, 1e9, { dur: 1.3, rise: 16 });
    steam(back, t, { x: 960, y: 520, t0: 43.6, t1: 51.0, rate: 40, life: 5, scale: 1.5, alpha: 0.5 * o, seed: 9 });
  }

  // ================================================================== SENSE (3D: Margaret's kitchen, then her whole house)
  const waveCtx = $("se-wave").getContext("2d");
  const boil = D.boil.trace; // [[s, W]]
  function pin(el, xy, dx = 0, dy = 0) { if (!xy) return; el.style.left = `${(xy[0] + dx).toFixed(1)}px`; el.style.top = `${(xy[1] + dy).toFixed(1)}px`; }
  function renderSense(t) {
    const o = scene("s-sense", t, 52.0, 62.0, 0.5, 0.7);
    if (o <= 0) return;
    const a0 = VO["9"].at, A = WA || {};
    // labels hang under the plug and the hub as the camera pulls back
    const lp = $("se-l-plug"), lh = $("se-l-hub");
    rev(lp, t, wt(9, "plug"), 56.6, { rise: 10, blur: 4 });
    rev(lh, t, wt(9, "plug") + 0.5, 56.6, { rise: 10, blur: 4 });
    for (const [el, xy, lead] of [[lp, A.plug, 80], [lh, A.hub, 64]]) {
      if (!xy) continue;
      el.style.setProperty("--lead", `${lead}px`);
      pin(el, xy, 0, lead); el.style.transform += " translateX(-50%)";
    }
    // raw readings: the real REFIT boil, scrolling; world.js floats this canvas inside the house
    const wv = er(t, wt(9, "the") - 0.2, wt(9, "the") + 0.8);
    waveCtx.clearRect(0, 0, 560, 200);
    if (wv > 0) {
      const span = 760, off = ((t - a0) * 70) % (boil[boil.length - 1][0] + 520);
      const pts = [];
      for (let x = 0; x <= 560; x += 4) {
        const s = (x / 560) * span + off - 600;
        let w = 0;
        for (let i = 0; i < boil.length - 1; i++) if (boil[i][0] <= s && boil[i + 1][0] > s) { w = boil[i][1]; break; }
        pts.push([x, 170 - (w / 2200) * 130 + vnoise(x * 0.3 + t * 8, 4) * 1.5]);
      }
      glowLine(waveCtx, pts, { color: "255,180,87", width: 2.4, alpha: 1, glow: 0.8 });
      const g = waveCtx.createLinearGradient(0, 0, 560, 0);
      g.addColorStop(0, "rgba(0,0,0,1)"); g.addColorStop(0.12, "rgba(0,0,0,0)"); g.addColorStop(0.88, "rgba(0,0,0,0)"); g.addColorStop(1, "rgba(0,0,0,1)");
      waveCtx.globalCompositeOperation = "destination-out"; waveCtx.fillStyle = g; waveCtx.fillRect(0, 0, 560, 200); waveCtx.globalCompositeOperation = "source-over";
    }
    rev($("se-l-raw"), t, wt(9, "never") - 0.1, 61.4);
    // only moments leave: the chip rides a light up out of the roof
    const chip = $("se-chip");
    style(chip, er(t, wt(9, "only") - 0.2, wt(9, "only") + 0.3) * (1 - er(t, 61.4, 62.0)), 0, 1, 0, "");
    if (A.chip) { pin(chip, A.chip); chip.style.transform += " translate(-50%, -130%)"; }
    const lo = $("se-l-out");
    rev(lo, t, wt(9, "kettle") + 0.3, 61.4, { rise: 10, blur: 4 });
    if (A.chip) { pin(lo, A.chip, 0, 0); lo.style.transform += " translate(150px, -50%)"; }
  }

  // ================================================================== MAP (the street is 3D: world.js)
  const GEO = {
    bow: [[-30, 164], [60, 176], [130, 190], [200, 206], [255, 226], [300, 240], [345, 262], [385, 292], [420, 322], [455, 344], [500, 356], [548, 362], [600, 368], [645, 384], [690, 394], [722, 414], [740, 452], [750, 500], [762, 552], [786, 630]],
    elbow: [[110, 630], [200, 594], [262, 576], [318, 568], [372, 552], [418, 524], [452, 502], [486, 486], [524, 474], [562, 463], [596, 443], [618, 419], [636, 399], [647, 386]],
  };
  function catmull(pts, n = 8) {
    const out = [];
    for (let i = 0; i < pts.length - 1; i++) {
      const p0 = pts[Math.max(0, i - 1)], p1 = pts[i], p2 = pts[i + 1], p3 = pts[Math.min(pts.length - 1, i + 2)];
      for (let k = 0; k < n; k++) {
        const u = k / n, u2 = u * u, u3 = u2 * u;
        out.push([0, 1].map((j) => 0.5 * (2 * p1[j] + (-p0[j] + p2[j]) * u + (2 * p0[j] - 5 * p1[j] + 4 * p2[j] - p3[j]) * u2 + (-p0[j] + 3 * p1[j] - 3 * p2[j] + p3[j]) * u3)));
      }
    }
    out.push(pts[pts.length - 1]); return out;
  }
  let WA = null;   // this frame's 3D anchors (screen positions from world.js)
  function renderMap(t) {
    const o = scene("s-map", t, 76.4, 92.9, 1.2, 0.6);
    if (o <= 0 || !WA) return;
    const pm = $("pin-m"), pp = $("pin-p"), pt = $("pin-t");
    style(pm, er(t, 77.0, 78.0) * (1 - er(t, 92.2, 92.7)));
    pin(pm, WA.margaret); pm.style.transform += " translate(-50%, -100%)";
    [pp, pt].forEach((el, i) => style(el, er(t, wt(13, "it") + 0.5 + i * 0.3, wt(13, "it") + 1.3 + i * 0.3) * (1 - er(t, 92.2, 92.7)), 0, 1, 0));
    pin(pp, WA.priya); pp.style.transform += " translate(-17px, -50%)";
    pin(pt, WA.tom); pt.style.transform += " translate(-17px, -50%)";
  }

  // ================================================================== MISSED
  const MX0 = 340, MX1 = 1580, MY = 680;
  const mx = (min) => MX0 + ((min - 360) / (480)) * (MX1 - MX0); // 6:00 → 14:00
  const miAxis = $("mi-axis");
  const miTicks = [6, 8, 10, 12, 14].map((h) => { const s = document.createElement("div"); s.className = "tk"; s.textContent = `${h}:00`; s.style.left = `${mx(h * 60)}px`; s.style.top = `${MY + 34}px`; miAxis.appendChild(s); return s; });
  const USUAL = 621, SPREAD = 34, DEADLINE = 723, JUMP_TO = 727; // from the stage: usually 10:21 ± 34, asks at 12:03, jumped to 12:07
  const tablet = $("mi-tablet"), call = $("mi-call");
  function renderMissed(t) {
    const o = scene("s-missed", t, 62.4, 77.0, 0.8, 0.9);
    if (o <= 0) return;
    const clockOut = er(t, 66.6, 67.6, ease.io3);
    const now = lerp(580, JUMP_TO, ease.io3(ramp(t, 62.9, 66.3)));
    $("mi-time").textContent = fmt(now);
    const ck = $("mi-clock");
    rev(ck, t, 62.6, 1e9, { rise: 20, blur: 10 });
    ck.style.transform = `translateY(${-clockOut * 130}px) scale(${1 - 0.35 * clockOut})`;
    ck.style.opacity = (er(t, 62.6, 63.4) * (1 - clockOut)).toFixed(3);
    const lineOut = er(t, 66.6, 67.4, ease.io3);
    const la = er(t, 62.7, 63.6) * (1 - lineOut);
    miTicks.forEach((s) => { s.style.opacity = la; });
    if (la > 0) {
      const passed = now >= DEADLINE;
      const glowK = er(t, 66.0, 66.6);
      // usual band
      const xa = mx(USUAL - SPREAD), xb = mx(USUAL + SPREAD);
      const g = back.createLinearGradient(xa, 0, xb, 0);
      const col = glowK > 0 ? "255,180,87" : "246,239,228";
      g.addColorStop(0, `rgba(${col},0)`); g.addColorStop(0.5, `rgba(${col},${(0.14 + 0.14 * glowK) * la})`); g.addColorStop(1, `rgba(${col},0)`);
      back.fillStyle = g; back.fillRect(xa, MY - 90, xb - xa, 120);
      // deadline
      back.setLineDash([6, 8]); back.strokeStyle = `rgba(${glowK > 0 ? "255,180,87" : "155,139,122"},${0.8 * la})`; back.lineWidth = 2;
      back.beginPath(); back.moveTo(mx(DEADLINE), MY - 90); back.lineTo(mx(DEADLINE), MY + 20); back.stroke(); back.setLineDash([]);
      // the day so far: flat
      glowLine(back, flatLine(MX0, mx(now), MY, t, 1.4, 7), { color: "246,239,228", width: 2.2, alpha: 0.85 * la, glow: 0.5 });
      back.strokeStyle = `rgba(246,239,228,${0.12 * la})`; back.lineWidth = 1.5; back.beginPath(); back.moveTo(mx(now), MY); back.lineTo(MX1, MY); back.stroke();
      blob(back, passed ? SPR.amber : SPR.white, mx(now), MY, 34, 0.9 * la);
      if (passed) blob(back, SPR.amber, mx(USUAL), MY - 30, 260, 0.18 * glowK * la);
    }
    const ul = $("mi-usual"); ul.style.left = `${mx(USUAL)}px`; ul.style.top = `${MY - 130}px`; rev(ul, t, 63.0, 66.6, { rise: 8, blur: 4 });
    const dl = $("mi-dl"); dl.style.left = `${mx(DEADLINE)}px`; dl.style.top = `${MY - 130}px`; rev(dl, t, 63.3, 66.6, { rise: 8, blur: 4 });
    rev($("mi-why"), t, 66.2, 66.9, { rise: 14, fo: 0.6 });
    // ask Margaret first: the kitchen display + a call to her landline
    const tin = er(t, 66.9, 68.2, ease.out5), tout = er(t, 75.6, 76.6, ease.io3);
    const soft = er(t, wt(11, "soft") - 0.2, wt(11, "soft") + 1.2), noAns = er(t, VO["12"].at - 0.2, VO["12"].at + 0.6);
    tablet.style.left = "180px"; tablet.style.top = "176px";
    tablet.style.opacity = (tin * (1 - tout)).toFixed(3);
    tablet.style.visibility = tin * (1 - tout) > 0 ? "visible" : "hidden";
    tablet.style.transform = `translateY(${(1 - tin) * 120 + tout * -40}px) scale(${0.94 + 0.06 * tin})`;
    tablet.style.setProperty("--glow", (0.9 * soft * (1 - 0.6 * noAns)).toFixed(3));
    const pulse = 0.5 + 0.5 * Math.sin((t - 67) * 3.4);
    front.globalCompositeOperation = "lighter";
    blob(front, SPR.amber, 748, 590, 700 + 80 * pulse, 0.16 * soft * (1 - 0.7 * noAns) * tin * (1 - tout));
    front.globalCompositeOperation = "source-over";
    $("mi-pulse").style.opacity = ((0.35 + 0.65 * pulse) * (0.4 + 0.6 * soft) * (1 - 0.7 * noAns)).toFixed(3);
    $("mi-pulse").style.transform = `scale(${0.9 + 0.2 * pulse})`;
    // the call card
    const cin = er(t, 67.6, 68.6, ease.out5);
    call.style.left = "1380px"; call.style.top = "500px";
    style(call, cin * (1 - tout), (1 - cin) * 20);
    const rings = [...call.querySelectorAll("b")];
    rings.forEach((r, i) => { const ph = ((t - 68.2) * 0.9 + i / 3) % 1; const live = t > 68.2 && t < VO["12"].at - 0.2 ? 1 : 0; r.style.opacity = (live * (1 - ph) * 0.8).toFixed(3); r.style.transform = `scale(${1 + ph * 0.9})`; });
    $("mi-call-top").textContent = t < VO["12"].at - 0.1 ? "Calling Margaret…" : "No answer";
    $("mi-call-sub").textContent = t < VO["12"].at - 0.1 ? "her landline" : "Kettle asks her circle";
  }

  // ================================================================== PHONE (neighbour → kettle → glow → cold)
  const phone = $("phone"), screens = {};
  for (const img of phone.querySelectorAll("img")) screens[img.dataset.k] = img;
  /** Which UI screen shows when: [t, key], with a short crossfade. */
  const PH_SEQ = [[83.0, "idle"], [85.2, "ask"], [88.25, "going"], [94.0, "kettle"], [102.6, "morning"], [105.75, "sent"], [124.4, "grid"]];
  function phoneScreen(t) {
    let cur = null, prev = null, at = 0;
    for (const [s, k] of PH_SEQ) if (t >= s) { prev = cur; cur = k; at = s; }
    for (const k in screens) screens[k].style.opacity = 0;
    if (!cur) return;
    const x = er(t, at, at + 0.35, ease.io3);
    if (prev) screens[prev].style.opacity = 1;
    screens[cur].style.opacity = x;
  }
  function tapAt(t, at, xFrac, yFrac) {
    const tp = $("tap"), k = ramp(t, at - 0.15, at + 0.55);
    if (k <= 0 || k >= 1) return false;
    tp.style.left = `${xFrac * 404}px`; tp.style.top = `${yFrac * 897}px`;
    const press = k < 0.22 ? ramp(k, 0, 0.22) : 1, rel = ramp(k, 0.22, 1);
    tp.style.opacity = (press * (1 - rel)).toFixed(3);
    tp.style.transform = `scale(${lerp(0.6, 0.85, press) + rel * 0.9})`;
    return true;
  }
  function renderPhone(t) {
    // placement keyframes: [t, x, y, scale, opacity]
    const K = [
      [83.2, 1500, 1180, 1, 0], [84.4, 1260, 82, 1, 1],
      [92.2, 1260, 82, 1, 1], [93.0, 1260, 112, 0.97, 0], [95.1, 1260, 112, 0.97, 0], [95.9, 1260, 82, 1, 1],
      [101.6, 1260, 82, 1, 1], [102.6, 190, 82, 1, 1],
      [109.6, 190, 82, 1, 1], [110.5, 190, 112, 0.97, 0],
      [124.0, 1260, 1180, 1, 0], [125.0, 1260, 82, 1, 1], [131.6, 1260, 82, 1, 1], [132.4, 1260, 82, 0.98, 0],
    ];
    let x = 1500, y = 1180, s = 1, op = 0;
    if (t >= K[0][0] && t <= K[K.length - 1][0]) {
      for (let i = 0; i < K.length - 1; i++) {
        const [t0, x0, y0, s0, o0] = K[i], [t1, x1, y1, s1, o1] = K[i + 1];
        if (t >= t0 && t <= t1) {
          const u = ease.io3(ramp(t, t0, t1));
          if (o0 === 0 && o1 === 0) { op = 0; break; }
          x = lerp(x0, x1, u); y = lerp(y0, y1, u); s = lerp(s0, s1, u); op = lerp(o0, o1, u); break;
        }
      }
    }
    phone.style.opacity = op.toFixed(3); phone.style.visibility = op > 0.001 ? "visible" : "hidden";
    phone.style.transform = `translate(${x}px, ${y}px) scale(${s})`;
    if (op <= 0) return;
    phoneScreen(t);
    // the notification
    const bn = $("banner"), bi = er(t, 84.3, 84.8, ease.out5), bo = er(t, 85.0, 85.3);
    bn.style.opacity = (bi * (1 - bo)).toFixed(3); bn.style.transform = `translateY(${(1 - bi) * -110}px)`;
    // the haptic buzz: a tiny shake
    let shake = 0;
    for (const b of [84.35, 84.75]) shake += Math.exp(-Math.max(0, t - b) * 9) * (t >= b ? 1 : 0) * Math.sin((t - b) * 120);
    if (t > 124.9 && t < 125.9) for (const b of [125.0, 125.4]) shake += Math.exp(-Math.max(0, t - b) * 9) * (t >= b ? 1 : 0) * Math.sin((t - b) * 120);
    phone.style.transform += ` rotate(${(shake * 1.2).toFixed(3)}deg)`;
    // taps
    $("tap").style.opacity = 0;
    tapAt(t, 88.0, 0.5, 0.686) || tapAt(t, wt(17, "tap") - 0.05, 0.5, 0.819);   // "I'm going", "Thinking of you"
  }

  // ================================================================== KETTLE (3D kitchen from world.js; a small live power panel)
  function renderKettle(t) {
    const o = scene("s-kettle", t, 93.4, 101.6, 0.6, 1.0);
    if (o <= 0) return;
    const on = 94.42; // the click
    const up = er(t, on, on + 0.35, ease.out5);
    const fade = 1 - er(t, 100.8, 101.8);
    // the panel: last minutes of Margaret's power, flat until the click, then the kettle's real step (REFIT House 11)
    const x0 = 150, x1 = 640, y = 960, xs = 560, hMax = 92;
    const reveal = lerp(x0, x1, er(t, 93.5, 94.3, ease.io3));
    const h = (D.boil.step_w / 2200) * hMax;
    const pts = [];
    for (let x = x0; x <= Math.max(x0 + 8, reveal); x += 5) {
      let yy = y + vnoise(x * 0.05 + t * 3, 3) * 1.1;
      if (x > xs) yy = y - h * up + vnoise(x * 0.07 + t * 2, 6) * 1.3 * up;
      pts.push([x, yy]);
    }
    if (reveal > xs) pts.splice(pts.findIndex((p) => p[0] > xs), 0, [xs, y], [xs + 0.1, y - h * up]);
    { const g = front.createRadialGradient(390, 960, 20, 390, 960, 420); g.addColorStop(0, `rgba(10,7,5,${0.55 * o * fade})`); g.addColorStop(1, "rgba(10,7,5,0)"); front.fillStyle = g; front.fillRect(0, 600, 900, 480); }
    front.strokeStyle = `rgba(246,239,228,${0.12 * o * fade})`; front.lineWidth = 1; front.beginPath(); front.moveTo(x0, y + 0.5); front.lineTo(x1, y + 0.5); front.stroke();
    glowLine(front, pts, { color: up > 0 ? "255,190,110" : "246,239,228", width: 2.4, alpha: 0.95 * o * fade, glow: 0.8 });
    if (up > 0) blob(front, SPR.amber, xs, y - h * up, 70, 0.35 * up * o * fade);
    rev($("ke-l"), t, 93.6, 100.6, { rise: 8, blur: 4 });
    const kon = $("ke-on"); kon.style.left = `${xs + 16}px`; kon.style.top = `${y - h - 44}px`; rev(kon, t, on + 0.2, 100.6, { rise: 10, blur: 4 });
    // steam from the 3D kettle's spout, sized to the shot
    const A = WA;
    if (A && A.spout) {
      const k = clamp(A.pxPerM / 900, 0.4, 3);
      steam(front, t, { x: A.spout[0], y: A.spout[1], t0: on + 0.8, t1: 100.6, rate: 70, life: 4.6, scale: 1.2 * k, alpha: 0.9 * o * fade, seed: 17, spread: 1.0 });
    }
  }

  // ================================================================== GLOW
  function renderGlow(t) {
    const o = scene("s-glow", t, 103.4, 110.4, 0.6, 0.8);
    const tb = $("gl-tablet");
    const tin = er(t, 103.4, 104.8, ease.out5);
    tb.style.left = "740px"; tb.style.top = "176px"; tb.style.transformOrigin = "0 50%";
    tb.style.transform = `translateX(${(1 - tin) * 260}px) scale(0.95)`;
    if (o <= 0) return;
    const gk = er(t, wt(17, "warm") - 0.1, wt(17, "warm") + 1.4, ease.io3);
    $("gl-b").style.opacity = gk.toFixed(3);
    tb.style.setProperty("--glow", gk.toFixed(3));
    front.globalCompositeOperation = "lighter";
    blob(front, SPR.amber, 1280, 530, 900, 0.12 * gk * o);
    front.globalCompositeOperation = "source-over";
  }

  // ================================================================== COLD
  // frost: crystals grown once from the edges; t only reveals them
  const frost = (() => {
    const r = rng(77), segs = [];
    function branch(x, y, ang, len, depth, d0) {
      const x2 = x + Math.cos(ang) * len, y2 = y + Math.sin(ang) * len;
      segs.push([x, y, x2, y2, d0, depth]);
      if (depth > 0) {
        const n = 2 + Math.floor(r() * 2);
        for (let i = 0; i < n; i++) {
          const f = 0.25 + r() * 0.65, bx = x + (x2 - x) * f, by = y + (y2 - y) * f, side = i % 2 ? 1 : -1;
          branch(bx, by, ang + side * (Math.PI / 3 + (r() - 0.5) * 0.25), len * (0.3 + r() * 0.25), depth - 1, d0 + f);
        }
        branch(x2, y2, ang + (r() - 0.5) * 0.5, len * 0.7, depth - 1, d0 + 1);
      }
    }
    for (let i = 0; i < 120; i++) {
      const side = i % 4, u = r();
      const [x, y, a] = side === 0 ? [u * W, -4, Math.PI / 2] : side === 1 ? [u * W, H + 4, -Math.PI / 2] : side === 2 ? [-4, u * H, 0] : [W + 4, u * H, Math.PI];
      branch(x, y, a + (r() - 0.5) * 1.2, 30 + r() * 64, 4, 0);
    }
    return segs;
  })();
  const snow = Array.from({ length: 160 }, (_, i) => [hash(i * 3.1), hash(i * 7.7), 0.4 + hash(i * 1.9) * 1.2, hash(i * 5.3)]);
  function drawFrost(t, k) {
    if (k <= 0) return;
    front.lineCap = "round";
    for (let level = 0; level <= 4; level++) {
      front.beginPath();
      for (const [x1, y1, x2, y2, d0, depth] of frost) {
        if (depth !== level) continue;
        const g = clamp((k * 4.2 - d0) / 1);
        if (g <= 0) continue;
        front.moveTo(x1, y1); front.lineTo(x1 + (x2 - x1) * g, y1 + (y2 - y1) * g);
      }
      front.strokeStyle = `rgba(225,242,255,${(0.22 + 0.12 * level) * Math.min(1, k * 1.5)})`;
      front.lineWidth = 0.5 + level * 0.32;
      front.stroke();
    }
    // a frosted edge haze
    const g = front.createRadialGradient(960, 540, 560, 960, 540, 1120);
    g.addColorStop(0, "rgba(200,228,250,0)"); g.addColorStop(0.75, `rgba(200,228,250,${0.05 * k})`); g.addColorStop(1, `rgba(214,236,252,${0.3 * k})`);
    front.fillStyle = g; front.fillRect(0, 0, W, H);
  }
  // Alberta, roughly: the 49th, the 60th, 110°W and the Rockies
  const AB = [[-110, 49], [-114.06, 49], [-114.7, 49.6], [-115.2, 50.4], [-116.1, 50.9], [-116.9, 51.7], [-117.9, 52.4], [-118.7, 53.0], [-119.6, 53.5], [-120, 53.8], [-120, 60], [-110, 60]];
  const abXY = ([lon, lat]) => [1250 + ((lon + 120) / 10) * 470, 90 + ((60 - lat) / 11) * 880];
  const abPoly = AB.map(abXY);
  const inPoly = (x, y) => { let c = false; for (let i = 0, j = abPoly.length - 1; i < abPoly.length; j = i++) { const [xi, yi] = abPoly[i], [xj, yj] = abPoly[j]; if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) c = !c; } return c; };
  const phones = (() => {
    const r = rng(2024), out = [];
    const cities = [[-114.07, 51.05, 0.34], [-113.49, 53.55, 0.32], [-113.81, 52.27, 0.05], [-112.84, 49.69, 0.05], [-110.68, 50.04, 0.03], [-118.79, 55.17, 0.03], [-111.38, 56.73, 0.03], [-113.0, 50.5, 0.0]];
    while (out.length < 2400) {
      const pick = r();
      let x, y;
      if (pick < 0.78) {
        let acc = 0, c = cities[0];
        const q = r() * 0.85; for (const cc of cities) { acc += cc[2]; if (q <= acc) { c = cc; break; } }
        const [cx, cy] = abXY([c[0], c[1]]), rr = Math.sqrt(-2 * Math.log(r() + 1e-9)) * (c[2] > 0.2 ? 20 : 11), th = r() * 6.283;
        x = cx + Math.cos(th) * rr; y = cy + Math.sin(th) * rr;
      } else { x = 1250 + r() * 470; y = 90 + r() * 880; }
      if (inPoly(x, y)) out.push([x, y, r()]);
    }
    return out;
  })();
  const coChart = $("co-chart").getContext("2d");
  function renderCold(t) {
    const k = er(t, 110.6, 118.0, ease.out3) * (1 - er(t, 131.6, 133.6, ease.io3));
    $("tint").style.opacity = (0.9 * k).toFixed(3);
    drawFrost(t, k);
    // snow
    if (k > 0) for (const [sx, sy, sz, sp] of snow) {
      const y = ((sy * H + (t - 110) * (24 + 30 * sp)) % (H + 40)) - 20, x = sx * W + Math.sin(t * 0.6 + sp * 9) * 30;
      blob(front, SPR.white, x, y, 5 * sz, 0.35 * k);
    }
    const o = scene("s-cold", t, 110.8, 132.6, 0.6, 0.8);
    if (o <= 0) return;
    rev($("co-built"), t, VO["18"].at + 0.1, 114.2);
    const a0 = VO["19"].at;
    rev($("co-date"), t, a0 + 0.05, 124.2, { rise: 8, blur: 4 });
    rev($("co-temp"), t, a0 + 0.4, 124.2, { rise: 20, blur: 12, dur: 1.2 });
    const temp = lerp(-27.0, -30.9, er(t, wt(19, "minus") - 0.6, wt(19, "minus") + 0.9, ease.out3));
    $("co-temp").textContent = `−${Math.abs(temp).toFixed(1)} °C`;
    rev($("co-temp-l"), t, wt(19, "minus"), 124.2, { rise: 8, blur: 4 });
    // AESO pool price for the day
    const ch = er(t, wt(19, "the") - 0.4, wt(19, "the") + 2.2, ease.io3);
    const chOut = er(t, wt(19, "every") - 0.3, wt(19, "every") + 0.5);
    $("co-chart").style.opacity = (er(t, wt(19, "the") - 0.5, wt(19, "the")) * (1 - chOut)).toFixed(3);
    coChart.clearRect(0, 0, 820, 480);
    if (ch > 0) {
      const hx = (h) => 30 + (h / 23) * 760, py = (p) => 440 - (p / 1000) * 360;
      coChart.setLineDash([5, 8]); coChart.strokeStyle = "rgba(255,180,87,.55)"; coChart.lineWidth = 1.5;
      coChart.beginPath(); coChart.moveTo(30, py(999.99)); coChart.lineTo(790, py(999.99)); coChart.stroke(); coChart.setLineDash([]);
      coChart.strokeStyle = "rgba(143,179,207,.25)"; coChart.beginPath(); coChart.moveTo(30, 440); coChart.lineTo(790, 440); coChart.stroke();
      coChart.font = "500 16px Inter"; coChart.fillStyle = "rgba(143,179,207,.8)";
      for (const h of [0, 6, 12, 18]) coChart.fillText(`${h === 0 ? 12 : h > 12 ? h - 12 : h} ${h < 12 ? "AM" : "PM"}`, hx(h) - 14, 468);
      const pts = D.jan13.hourly.map((r) => [hx(r.h), py(r.price)]);
      const n = ch * (pts.length - 1), cut = Math.floor(n), f = n - cut;
      const vis = pts.slice(0, cut + 1); if (cut < pts.length - 1) vis.push([lerp(pts[cut][0], pts[cut + 1][0], f), lerp(pts[cut][1], pts[cut + 1][1], f)]);
      glowLine(coChart, vis, { color: "255,180,87", width: 3, alpha: 1, glow: 0.9 });
      // 6:44 PM
      const m = er(t, wt(19, "at") - 0.1, wt(19, "at") + 0.6);
      if (m > 0) {
        const x = hx(18 + 44 / 60);
        coChart.strokeStyle = `rgba(231,241,250,${0.8 * m})`; coChart.lineWidth = 2;
        coChart.beginPath(); coChart.moveTo(x, 40); coChart.lineTo(x, 440); coChart.stroke();
        coChart.fillStyle = `rgba(231,241,250,${m})`; coChart.font = "600 20px Inter"; coChart.fillText("6:44 PM", x - 96, 34);
      }
    }
    rev($("co-chart-l"), t, wt(19, "the") + 0.2, wt(19, "every") - 0.3, { rise: 8, blur: 4 });
    rev($("co-cap"), t, wt(19, "limit") - 0.1, wt(19, "every") - 0.3, { rise: 8, blur: 4 });
    // every phone in Alberta
    const bz = wt(19, "every");
    const ab = er(t, bz - 0.4, bz + 0.4) * (1 - 0.75 * er(t, 125.0, 126.0)) * (1 - er(t, 131.0, 132.4));
    if (ab > 0) {
      back.strokeStyle = `rgba(160,196,224,${0.5 * ab})`; back.lineWidth = 2;
      back.beginPath(); abPoly.forEach(([x, y], i) => (i ? back.lineTo(x, y) : back.moveTo(x, y))); back.closePath(); back.stroke();
      back.globalCompositeOperation = "lighter";
      for (const [x, y, r] of phones) {
        const lit = clamp((t - bz - 0.05 - ((y - 90) / 880) * -0.9 - 0.9 - r * 0.35) * 5);
        const tw = 0.6 + 0.4 * Math.sin(t * 9 + r * 40);
        back.fillStyle = `rgba(255,${Math.round(lerp(220, 196, lit))},${Math.round(lerp(220, 130, lit))},${(0.18 + 0.8 * lit * tw) * ab})`;
        back.fillRect(x - 1.6, y - 1.6, 3.2, 3.2);
      }
      back.globalCompositeOperation = "source-over";
      const [cx, cy] = abXY([-114.07, 51.05]);
      blob(back, SPR.amber, cx, cy, 120, 0.3 * ab * clamp((t - bz) * 2));
      const [ex, ey] = abXY([-113.49, 53.55]);
      blob(back, SPR.amber, ex, ey, 110, 0.25 * ab * clamp((t - bz) * 2));
    }
    rev($("co-buzz"), t, bz - 0.1, 124.6, { rise: 12 });
    $("co-buzz").style.left = "0px"; $("co-buzz").style.right = "760px"; $("co-buzz").style.top = "640px"; $("co-buzz").style.fontSize = "52px";
    rev($("co-check"), t, wt(20, "check") - 0.1, 131.6, { rise: 16, dur: 1.2 });
    rev($("co-src"), t, a0 + 1.0, 131.6, { rise: 6, blur: 3 });
  }

  // ================================================================== EVIDENCE
  const homesEl = $("ev-homes");
  for (let i = 0; i < D.refit.houses; i++) homesEl.insertAdjacentHTML("beforeend", '<svg viewBox="0 0 24 24"><path d="M3 11 12 3.5 21 11v9.5H3z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/></svg>');
  const homeIcons = [...homesEl.children];
  function renderEvidence(t) {
    const o = scene("s-evidence", t, 133.2, 146.6, 0.8, 0.8);
    if (o <= 0) return;
    rev($("ev-head"), t, wt(21, "through") - 0.1, 146, { rise: 8, blur: 4 });
    const n1 = Math.round(D.refit.home_days * er(t, wt(21, "9") - 0.3, wt(21, "9") + 1.6, ease.outExpo));
    $("ev-1n").textContent = n1.toLocaleString("en-CA");
    rev($("ev-1"), t, wt(21, "9") - 0.4, 146, { rise: 24, blur: 10, dur: 1.1 });
    homeIcons.forEach((h, i) => { const a = er(t, wt(21, "20") + i * 0.04, wt(21, "20") + 0.4 + i * 0.04); h.style.opacity = a; h.style.transform = `translateY(${(1 - a) * 8}px)`; });
    $("ev-2n").textContent = (D.refit.f1_plug * er(t, wt(21, "recognizes") - 0.1, wt(21, "recognizes") + 1.2, ease.outExpo)).toFixed(2);
    rev($("ev-2"), t, wt(21, "recognizes") - 0.3, 146, { rise: 24, blur: 10, dur: 1.1 });
    $("ev-3n").textContent = (D.refit.checkins * er(t, wt(21, "check") - 0.2, wt(21, "check") + 1.1, ease.outExpo)).toFixed(1);
    rev($("ev-3"), t, wt(21, "check") - 0.4, 146, { rise: 24, blur: 10, dur: 1.1 });
    rev($("ev-src"), t, wt(21, "homes"), 146, { rise: 6, blur: 3 });
    steam(back, t, { x: 960, y: 1120, t0: 132, t1: 146, rate: 10, life: 9, scale: 3.2, alpha: 0.35 * o, seed: 23, spread: 3 });
  }

  // ================================================================== CLOSE
  // every Calgary home: lights scattered through the city, away from the rivers
  const cityLights = (() => {
    const r = rng(403), out = [];
    const near = (x, y, path, d) => path.some(([a, b]) => Math.hypot(a - x, b - y) < d);
    const bow = catmull(GEO.bow, 6), elbow = catmull(GEO.elbow, 6);
    while (out.length < 2400) {
      const x = 40 + r() * 920, y = 30 + r() * 560;
      const dx = (x - 520) / 470, dy = (y - 320) / 300;
      if (dx * dx + dy * dy > 1 + (r() - 0.5) * 0.25) continue;
      if (near(x, y, bow, 12) || near(x, y, elbow, 9)) continue;
      out.push([x * 1.92, y * 1.92 - 36, r(), Math.hypot(x - 548, y - 300), x, y]);
    }
    return out;
  })();
  function renderClose(t) {
    const o = scene("s-close", t, 147.0, 1e9, 0.8, 1);
    if (o <= 0) return;
    const a0 = VO["22"].at, mAt = wt(22, "every");
    rev($("cl-since"), t, a0 + 0.1, mAt - 0.3, { rise: 20, blur: 10, dur: 1.2 });
    // city of meters
    const city = er(t, mAt - 0.6, mAt + 0.4) * (1 - 0.7 * er(t, VO["23"].at - 0.4, VO["23"].at + 1.0, ease.io3)) * (1 - er(t, 164.5, 167.0));
    if (city > 0) {
      const z = 1.12 - 0.08 * ease.ioSine(ramp(t, mAt - 0.6, 160));
      const cx = 960, cy = 540;
      back.save(); back.translate(cx, cy); back.scale(z, z); back.translate(-cx, -cy);
      back.globalCompositeOperation = "lighter";
      const sweep = (t - mAt + 0.5) * 380;
      for (const [x, y, r, d] of cityLights) {
        const lit = clamp((sweep - d) / 120);
        if (lit <= 0) continue;
        const tw = 0.7 + 0.3 * Math.sin(t * (1.5 + r * 2) + r * 50);
        back.fillStyle = `rgba(255,${Math.round(180 + 40 * r)},${Math.round(90 + 60 * r)},${(0.55 * lit * tw * city).toFixed(3)})`;
        back.fillRect(x - 1.3, y - 1.3, 2.6, 2.6);
      }
      for (const path of [GEO.bow, GEO.elbow]) {
        const pts = catmull(path, 8).map(([x, y]) => [x * 1.92, y * 1.92 - 36]);
        back.globalCompositeOperation = "source-over";
        back.strokeStyle = `rgba(40,70,100,${0.9 * city})`; back.lineWidth = path === GEO.bow ? 9 : 6; back.lineCap = "round";
        back.beginPath(); pts.forEach(([x, y], i) => (i ? back.lineTo(x, y) : back.moveTo(x, y))); back.stroke();
      }
      back.globalCompositeOperation = "lighter";
      blob(back, SPR.amber, 548 * 1.92, 300 * 1.92 - 36, 60, 0.9 * city);
      back.restore(); back.globalCompositeOperation = "source-over";
    }
    rev($("cl-meter"), t, mAt - 0.1, VO["23"].at - 0.6);
    // the end: the brand, then the people it is for
    const e0 = VO["23"].at, just = wt(23, "just");
    const ph0 = just + 0.1, brandOut = er(t, just + 0.3, just + 1.3, ease.io3);
    drawLogo(closeLogo, t, e0 - 0.6);
    $("cl-logo").style.opacity = er(t, e0 - 0.7, e0 - 0.3) * (1 - brandOut);
    rev($("cl-brand").querySelector(".wordmark"), t, e0 - 0.3, just + 0.3, { dur: 1.4, rise: 24, blur: 12, fo: 1.0 });
    const nos = [...$("cl-nos").children];
    nos.forEach((s, i) => rev(s, t, wt(23, [0, 2][i]) - 0.05, just + 0.3, { rise: 14, blur: 6, fo: 1.0 }));
    // "Just someone who notices." lands, then settles into the lower third over the photo
    const jl = $("cl-just"), drop = er(t, just + 0.9, just + 2.4, ease.io3), credits = er(t, 167.4, 168.4, ease.io3);
    rev(jl, t, just - 0.05, 1e9, { dur: 1.3, rise: 16 });
    jl.style.transform += ` translateY(${(drop * 168).toFixed(1)}px)`;
    jl.style.opacity = (parseFloat(jl.style.opacity) * (1 - credits)).toFixed(3);
    jl.style.textShadow = `0 2px 30px rgba(0,0,0,${(0.7 * drop).toFixed(2)})`;
    const ev = $("cl-event");
    rev(ev, t, just + 2.6, 167.4, { rise: 8, blur: 4, fo: 1.0 });
    ev.style.transform += " translateY(130px)";
    const ph = $("cl-photo"), pa = er(t, ph0, ph0 + 2.0, ease.ioSine) * (1 - credits * 0.9);
    ph.style.opacity = pa.toFixed(3); ph.style.visibility = pa > 0.001 ? "visible" : "hidden";
    ph.firstElementChild.style.transform = `scale(${(1.0 + 0.075 * ease.ioSine(ramp(t, ph0, 175))).toFixed(4)})`;
    ph.style.filter = `brightness(${(1 - 0.75 * credits).toFixed(3)})`;
    rev($("cl-fine"), t, 168.2, 1e9, { rise: 8, blur: 4, dur: 1.2 });
    steam(back, t, { x: 960, y: 420, t0: e0 - 0.5, t1: just + 1.5, rate: 36, life: 5, scale: 1.4, alpha: 0.45 * o * (1 - brandOut), seed: 31 });
  }

  // ================================================================== frame
  const scenes = [renderOpen, renderRhythm, renderProblem, renderBrand, renderSense, renderMissed, renderMap, renderKettle, renderGlow, renderPhone, renderCold, renderEvidence, renderClose];
  function seek(t) {
    back.clearRect(0, 0, W, H); front.clearRect(0, 0, W, H);
    WA = window.WORLD ? window.WORLD.setup(t) : null;
    for (const r of scenes) r(t);
    if (window.WORLD) window.WORLD.draw();
    // fade in/out from black (film grain is added by ffmpeg in render.py)
    const bk = $("black");
    bk.style.visibility = (t > 0.55 && t < TL.duration - 1.65) ? "hidden" : "visible";
    const tn = $("tint"); tn.style.visibility = parseFloat(tn.style.opacity || 0) > 0.001 ? "visible" : "hidden";
    bk.style.opacity = (1 - er(t, 0.0, 0.5) + er(t, TL.duration - 1.6, TL.duration - 0.2, ease.io3)).toFixed(3);
  }
  window.seek = (t) => { seek(t); return new Promise((r) => requestAnimationFrame(() => r(true))); };
  window.FILM = { duration: TL.duration, fps: TL.fps };

  const q = new URLSearchParams(location.search);
  const worldReady = new Promise((r) => (window.WORLD ? r() : window.addEventListener("world-ready", r, { once: true })));
  Promise.all([document.fonts.ready, worldReady, ...[...document.images].map((im) => im.decode().catch(() => 0))]).then(() => {
    window.READY = true;
    if (q.has("t")) seek(parseFloat(q.get("t")));
    else if (q.has("play")) { const t0 = performance.now() - (parseFloat(q.get("play")) || 0) * 1000; const loop = () => { seek((performance.now() - t0) / 1000); requestAnimationFrame(loop); }; loop(); }
    else seek(0);
  });
})();
