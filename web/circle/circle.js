// Kettle circle app: what a neighbour or family member sees on their phone.
// It only ever receives *events* ("kettle on at 7:48"), never power readings.
import { socket, wsBase, fmtMin, ICON, NICE, post, h } from "../shared/kettle.js";

const $ = (s) => document.querySelector(s);
const main = $("#main"), alertEl = $("#alert"), live = $("#live");
const params = new URLSearchParams(location.search);
const URGENT = new Set(["ask", "ask_family", "welfare", "need_help", "grid", "dark", "heat", "followup"]);
const SHOWN = new Set([...URGENT, "going_ack", "resolved"]);

let me = params.get("m") || localStorage.getItem("kettle.member");
if (params.get("m")) localStorage.setItem("kettle.member", params.get("m"));
let state = null, ws = null, lastSig = "", lastNoteId = Number(sessionStorage.getItem("kettle.lastNote") || 0);
let dismissed = new Set(JSON.parse(sessionStorage.getItem("kettle.dismissed") || "[]"));
let audio = null, alertNoteId = null;

if ("serviceWorker" in navigator && window.isSecureContext) navigator.serviceWorker.register("sw.js").catch(() => {});

// ------------------------------------------------------------------ boot
if (params.has("join") || !me) renderJoin();
else connect();

function connect() {
  ws = socket(`${wsBase()}/ws/circle?m=${encodeURIComponent(me)}`, {
    onmessage: onState,
    onstatus: (ok, code) => {
      const c = $("#conn");
      c.className = "conn " + (ok ? "on" : "off");
      $("#connText").textContent = ok ? "Connected" : "Reconnecting";
      if (code === 4404) { localStorage.removeItem("kettle.member"); me = null; renderJoin("We couldn't find your invite. Please join again."); }
    },
  });
}

// ------------------------------------------------------------------ state
function onState(s) {
  state = s;
  const home = s.homes[0];
  $("#sub").textContent = home ? `${home.person}'s circle` : "Circle";
  const newest = s.notes[0];
  if (newest && newest.id > lastNoteId) {
    const fresh = s.notes.filter((n) => n.id > lastNoteId);
    lastNoteId = newest.id;
    sessionStorage.setItem("kettle.lastNote", lastNoteId);
    if (fresh.some((n) => URGENT.has(n.kind))) buzz(true);
    else if (fresh.some((n) => n.kind === "resolved")) buzz(false);
    live.textContent = `${newest.title} ${newest.body || ""}`;
  }
  renderAlert();
  const sig = JSON.stringify([home && [home.status, home.status_text, home.events.length, home.baseline?.deadline, home.baseline?.usual, home.glow?.from, home.paused],
    s.cold.active, s.cold.temp_c, s.notes.slice(0, 8).map((n) => [n.id, n.answered]), s.clock.hhmm]);
  if (sig !== lastSig) { lastSig = sig; renderHome(); }
}

// ------------------------------------------------------------------ alert overlay
function activeNote() {
  if (!state) return null;
  for (const n of state.notes) {
    if (dismissed.has(n.id)) continue;
    if (n.buttons?.length && !n.answered && URGENT.has(n.kind)) return n;
    if (!SHOWN.has(n.kind)) continue;
    const ageS = Date.now() / 1000 - n.t_real;
    if (n.kind === "resolved" && ageS < 25) return n;
    if (n.kind === "going_ack" && !n.answered && ageS < 600) return n;
    if (URGENT.has(n.kind)) continue;
  }
  return null;
}

function renderAlert() {
  const n = activeNote();
  if (!n) { if (!alertEl.hidden) closeAlert(); return; }
  if (alertNoteId === n.id && !alertEl.hidden) return;
  alertNoteId = n.id;
  const home = state.homes.find((x) => x.id === n.home_id) || state.homes[0];
  const kicker = {
    ask: "Kettle needs you", ask_family: "Kettle needs you", welfare: "Still no answer", need_help: "Help needed",
    followup: "Quick question", going_ack: "On your way", resolved: "All good", grid: "Alberta grid emergency", dark: "Power may be out", heat: "Is the heat on?",
  }[n.kind] || "Kettle";
  const urgent = URGENT.has(n.kind);
  alertEl.className = `alert k-${n.kind}`;
  alertEl.replaceChildren(h("div", { class: "inner" },
    n.kind === "resolved" ? h("div", { class: "cup", "aria-hidden": "true" }, steam(), "☕") : null,
    h("div", { class: "kicker" }, urgent ? h("span", { "aria-hidden": "true" }, ["grid", "dark", "heat"].includes(n.kind) ? "❄️" : "🔔") : null, kicker),
    h("h1", { id: "alertTitle" }, n.title),
    n.body ? h("p", { class: "why", id: "alertBody" }, n.kind === "ask" ? [h("b", {}, "Why: "), n.body] : n.body) : h("p", { id: "alertBody", class: "sr-only" }, n.title),
    n.kind === "ask" && home ? h("p", { class: "map" }, `${home.person} · ${home.area}. Kettle asked ${home.person} first; there was no answer.`) : null,
    ...(n.buttons || []).map((b) => b.id.startsWith("tel:")
      ? h("a", { class: `btn ${b.style || "secondary"}`, href: b.id }, b.label)
      : h("button", { class: `btn ${b.style || "secondary"}`, onclick: (e) => answer(n, b.id, e.currentTarget) }, b.label)),
    !urgent || n.kind === "going_ack" ? h("button", { class: "btn quiet", onclick: () => { dismiss(n.id); } }, n.kind === "resolved" ? "Back to the circle" : "Close") : null,
  ));
  alertEl.hidden = false;
  document.body.style.overflow = "hidden";
  setTimeout(() => alertEl.querySelector("button, a")?.focus(), 30);
}

function closeAlert() {
  alertEl.hidden = true;
  alertNoteId = null;
  document.body.style.overflow = "";
  $("#main").focus({ preventScroll: true });
}

function dismiss(id) {
  dismissed.add(id);
  sessionStorage.setItem("kettle.dismissed", JSON.stringify([...dismissed].slice(-60)));
  closeAlert();
  renderAlert();
}

async function answer(n, response, btn) {
  unlockAudio();
  alertEl.querySelectorAll("button").forEach((b) => (b.disabled = true));
  btn.textContent = "Sending…";
  const ok = ws && ws.send({ type: "respond", escalation: n.escalation, response });
  if (!ok) await post("/api/respond", { member: me, escalation: n.escalation, response });
  n.answered = response;
  dismissed.add(n.id);
  sessionStorage.setItem("kettle.dismissed", JSON.stringify([...dismissed]));
  alertNoteId = null;
  setTimeout(renderAlert, 400);
}

// ------------------------------------------------------------------ home view
function renderHome() {
  const s = state, home = s.homes[0];
  if (!home) { main.replaceChildren(h("p", {}, "You're not in a circle yet.")); return; }
  const b = home.baseline || {};
  const events = [...home.events].filter((e) => e.human).reverse();
  const meName = s.me.name;

  main.replaceChildren(...[
    s.cold.active ? h("div", { class: "banner cold", role: "note" }, h("span", { "aria-hidden": "true" }, "❄️"),
      h("div", {}, `Cold mode is on${s.cold.temp_c != null ? ` · ${String(s.cold.temp_c).replace("-", "−")} °C` : ""}. `, h("span", { class: "small" }, "Kettle checks sooner and watches for homes that go dark."))) : null,
    home.paused ? h("div", { class: "banner paused" }, "⏸ ", home.status_text) : null,

    h("h1", {}, `Hi ${meName}.`),
    h("p", { class: "muted" }, `You're in ${home.person}'s circle${s.me.distance_min != null ? `, ${s.me.distance_min} min from ${home.pronoun === "she" ? "her" : home.pronoun === "he" ? "his" : "their"} door` : ""}.`),

    h("section", { class: "card person", "aria-labelledby": "pname" },
      h("div", { class: "who" },
        h("div", { class: "avatar", "aria-hidden": "true" }, home.person[0]),
        h("div", {}, h("div", { class: "name", id: "pname" }, home.person), h("div", { class: "area" }, `${home.area} · ${s.clock.demo ? "demo time " : ""}${s.clock.hhmm}`))),
      h("div", { class: `status st-${home.status}` }, h("span", { class: "pip", "aria-hidden": "true" }), h("span", {}, home.status_text)),
      ribbon(home),
      events.length ? h("ul", { class: "events", "aria-label": "Today" },
        events.slice(0, 6).map((e) => h("li", {}, h("span", { class: "t" }, e.hhmm), h("span", { class: "i", "aria-hidden": "true" }, ICON[e.label] || "•"),
          h("span", {}, NICE[e.label] || e.label, e.kind === "cycle" && e.duration_s ? h("span", { class: "muted small" }, ` · ${Math.round(e.duration_s / 60) || "<1"} min`) : null))))
        : h("p", { class: "muted", style: "margin-top:.8rem" }, "Nothing yet today."),
      h("p", { class: "privacy" }, h("span", { "aria-hidden": "true" }, "🔒"),
        h("span", {}, `Kettle only shares moments like “kettle on at 7:48”. ${home.person}'s power readings never leave ${home.pronoun === "she" ? "her" : home.pronoun === "he" ? "his" : "their"} home, and ${home.pronoun === "they" ? "they" : home.pronoun} can pause Kettle any time.`)),
    ),

    h("section", { class: "card" },
      h("button", { class: "btn warm", onclick: sendGlow, "aria-describedby": "glowHelp" }, h("span", { "aria-hidden": "true" }, "💛"), " Thinking of you"),
      h("p", { id: "glowHelp", class: "muted small", style: "margin-top:.6rem;text-align:center" }, `A warm light glows in ${home.person}'s kitchen. No reply needed.`)),

    h("h2", {}, "Recent"),
    h("section", { class: "card" }, s.notes.length
      ? h("ul", { class: "feed" }, s.notes.slice(0, 8).map((n) => h("li", { class: `k-${n.kind}` },
          h("div", { class: "t" }, n.hhmm), h("div", { class: "title" }, n.title),
          n.answered && n.answered !== "closed" ? h("div", { class: "muted small" }, `You answered: ${label(n, n.answered)}`) : null)))
      : h("p", { class: "muted" }, "Quiet. That's how it should be.")),

    h("h2", {}, "The circle"),
    h("div", { class: "circle-list" }, (home.circle || []).map((name) => h("span", { class: "chip" + (name === meName ? " me" : "") }, name === meName ? `${name} (you)` : name))),
    h("p", { class: "muted small", style: "margin-top:1.2rem" }, "Kettle is not a medical device or an emergency service. In an emergency, call 911."),
  ].filter(Boolean));
}

function label(n, id) { return (n.buttons || []).find((b) => b.id === id)?.label || id; }

function ribbon(home) {
  const b = home.baseline || {};
  const W = 320, H = 70, t0 = 240, t1 = 840, x = (m) => ((Math.min(Math.max(m, t0), t1) - t0) / (t1 - t0)) * W;
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", b.sentence || "Daily rhythm");
  const add = (tag, attrs) => { const el = document.createElementNS(ns, tag); for (const k in attrs) el.setAttribute(k, attrs[k]); svg.append(el); return el; };
  add("rect", { x: 0, y: 26, width: W, height: 14, rx: 7, fill: "#efe6d8" });
  const alert = ["alert", "grid", "dark"].includes(home.status);
  if (b.learned && b.usual_min != null) {
    add("rect", { x: x(b.usual_min - b.spread_min), y: 22, width: Math.max(4, x(b.usual_min + b.spread_min) - x(b.usual_min - b.spread_min)), height: 22, rx: 11,
      fill: alert ? "#f6c37e" : "#cfe6d6" });
    add("line", { x1: x(b.usual_min), x2: x(b.usual_min), y1: 20, y2: 46, stroke: "#2f7d4f", "stroke-width": 2 });
    for (const m of b.history || []) add("circle", { cx: x(m), cy: 56, r: 2.6, fill: "none", stroke: "#7a6352", "stroke-width": 1.2, opacity: .7 });
  }
  if (b.deadline_min != null) {
    add("line", { x1: x(b.deadline_min), x2: x(b.deadline_min), y1: 16, y2: 50, stroke: "#8a4b06", "stroke-width": 2, "stroke-dasharray": "3 3" });
  }
  for (const e of home.events.filter((e) => e.human)) add("circle", { cx: x(e.min), cy: 33, r: 5.5, fill: "#2b1d12" });
  const nx = x(home.now_min);
  add("line", { x1: nx, x2: nx, y1: 12, y2: 54, stroke: "#b3261e", "stroke-width": 2 });
  for (const [m, t] of [[240, "4:00"], [480, "8:00"], [720, "12:00"]]) {
    const tx = add("text", { x: x(m) + (m === 240 ? 0 : -14), y: 12, class: "" }); tx.textContent = t;
    tx.setAttribute("font-size", "11"); tx.setAttribute("fill", "#7a6352");
  }
  const legend = h("div", { class: "ribbon-legend" },
    b.learned ? h("span", {}, h("i", { style: `background:${alert ? "#f6c37e" : "#cfe6d6"}` }), `Usually ${b.usual} ± ${b.spread} min`) : h("span", {}, b.sentence || ""),
    b.deadline ? h("span", {}, h("i", { style: "background:#8a4b06;width:3px" }), `Asks at ${b.deadline}`) : null,
    h("span", {}, h("i", { style: "background:#b3261e;width:3px" }), "Now"));
  return h("div", { class: "ribbon" }, svg, legend);
}

function steam() {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("class", "steam"); svg.setAttribute("viewBox", "0 0 60 50");
  for (const d of ["M18 45c-6-8 6-12 0-22", "M30 45c-6-8 6-12 0-24", "M42 45c-6-8 6-12 0-22"]) {
    const p = document.createElementNS(ns, "path"); p.setAttribute("d", d); svg.append(p);
  }
  return svg;
}

async function sendGlow(e) {
  unlockAudio();
  const home = state.homes[0];
  const ok = ws && ws.send({ type: "glow", home: home.id });
  if (!ok) await post("/api/glow", { member: me, home: home.id });
  toast(`${home.person}'s kitchen is glowing warm 💛`);
  e.currentTarget.disabled = true;
  const btn = e.currentTarget;
  setTimeout(() => (btn.disabled = false), 10000);
}

// ------------------------------------------------------------------ join
function renderJoin(err) {
  main.replaceChildren(
    h("h1", {}, "Join a Kettle circle"),
    h("p", { class: "muted" }, "Someone you care about uses Kettle. If their morning doesn't start as usual, Kettle may ask you to knock on their door."),
    h("form", { class: "form card", onsubmit: async (e) => {
      e.preventDefault();
      const name = e.target.name.value.trim(), code = e.target.code.value.trim();
      const r = await fetch("/api/join", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name, code }) });
      if (!r.ok) { const d = await r.json().catch(() => ({})); e.target.querySelector(".err").textContent = d.detail || "That didn't work."; return; }
      const { member } = await r.json();
      me = member; localStorage.setItem("kettle.member", member);
      history.replaceState(null, "", `?m=${member}`);
      connect();
    } },
      h("label", { for: "name" }, "Your first name"),
      h("input", { id: "name", name: "name", autocomplete: "given-name", required: true, maxlength: 24 }),
      h("label", { for: "code" }, "Invite code"),
      h("input", { id: "code", name: "code", autocomplete: "off", autocapitalize: "none", required: true, value: params.get("code") || "" }),
      h("p", { class: "err", role: "alert" }, err || ""),
      h("button", { class: "btn primary", type: "submit", style: "margin-top:1rem" }, "Join the circle")),
    h("p", { class: "muted small", style: "margin-top:1rem" }, "You'll only ever see moments like “kettle on at 7:48”. Never power readings, never cameras."),
  );
}

// ------------------------------------------------------------------ feedback
function toast(text) {
  document.querySelector(".toast")?.remove();
  const t = h("div", { class: "toast", role: "status" }, text);
  document.body.append(t);
  setTimeout(() => t.remove(), 3500);
}

function unlockAudio() {
  if (audio) return;
  try { audio = new (window.AudioContext || window.webkitAudioContext)(); } catch { audio = null; }
}
document.addEventListener("pointerdown", unlockAudio, { once: true });

function buzz(urgent) {
  if (navigator.vibrate) navigator.vibrate(urgent ? [260, 120, 260, 120, 520] : [120]);
  if (!audio) return;
  const now = audio.currentTime;
  const tones = urgent ? [[660, 0], [880, .18], [660, .5], [880, .68]] : [[784, 0], [1046, .14]];
  for (const [f, at] of tones) {
    const o = audio.createOscillator(), g = audio.createGain();
    o.type = "sine"; o.frequency.value = f;
    g.gain.setValueAtTime(0, now + at); g.gain.linearRampToValueAtTime(.18, now + at + .02); g.gain.exponentialRampToValueAtTime(.001, now + at + .16);
    o.connect(g).connect(audio.destination); o.start(now + at); o.stop(now + at + .2);
  }
  if (document.hidden && "Notification" in window && Notification.permission === "granted") {
    const n = state?.notes?.[0]; if (n) new Notification(n.title, { body: n.body, icon: "icon-192.png", tag: `kettle-${n.id}` });
  }
}
