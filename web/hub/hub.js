// Kitchen display, served by the edge hub. It talks only to the hub on the local network.
import { socket, wsBase, h } from "../shared/kettle.js";

const $ = (s) => document.querySelector(s);
const body = document.body;
let clock = null, glowTimer = null, paused = false, points = [], recog = null;

const ws = socket(`${wsBase()}/ws/local`, { onmessage, onstatus: (ok) => { if (!ok) setChip("#cloud", "hub offline", true); } });

function onmessage(m) {
  switch (m.type) {
    case "status":
      setChip("#plug", m.plug_ok ? `${m.plug_real ? "plug" : "simulated plug"} ✓` : "plug not responding", !m.plug_ok);
      setChip("#cloud", m.outage ? "power cut" : m.cloud_ok ? `online · ${m.sent} events sent` : `offline · ${m.queued} queued`, !m.cloud_ok);
      $("#simk").hidden = m.plug_real;
      body.classList.toggle("outage", !!m.outage);
      if (m.ui?.clock) clock = m.ui.clock;
      if (m.ui?.checkin) startCheckin(m.ui.checkin);
      break;
    case "history": points = m.points; break;
    case "sample":
      points.push([m.t, m.w]); if (points.length > 900) points.splice(0, points.length - 900);
      $("#watts").textContent = `${Math.round(m.w)} W`;
      break;
    case "event": {
      const e = m.event;
      if (e.human && e.kind === "on") note("☕ Kettle on. Your circle will see your morning has started.");
      if (e.human && e.kind === "cycle") note("☕ Enjoy your tea.");
      break;
    }
    case "clock": clock = m; break;
    case "checkin": case "checkin_keep": startCheckin(m.text); break;
    case "checkin_end": endCheckin(m.text); break;
    case "glow": glow(m.from); break;
    case "outage": body.classList.add("outage"); setTimeout(() => body.classList.remove("outage"), (m.seconds || 30) * 1000); break;
    case "toast": toast(m.text); break;
  }
}

function setChip(sel, text, bad) { const c = $(sel); c.textContent = text; c.classList.toggle("bad", !!bad); }
function note(text) { $("#note").textContent = text; clearTimeout(note.t); note.t = setTimeout(() => ($("#note").textContent = ""), 12000); }
function toast(text) { const t = h("div", { class: "toast", role: "status" }, text); body.append(t); setTimeout(() => t.remove(), 4000); }

// ---------------------------------------------------------------- check-in
function startCheckin(text) {
  if (body.classList.contains("checkin")) return;
  body.classList.add("checkin");
  $("#askText").textContent = text || "Good morning. Press the button if you're fine.";
  listen();
}
function endCheckin(text) {
  body.classList.remove("checkin");
  stopListening();
  if (text) note(text);
}
$("#fine").addEventListener("click", imFine);
function imFine() {
  ws.send({ type: "im_fine" });
  endCheckin("Thank you. Your circle knows you're fine. 💛");
}

// Voice: "I'm fine", where the browser supports speech recognition.
function listen() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR || recog) return;
  try {
    recog = new SR(); recog.lang = "en-CA"; recog.continuous = true; recog.interimResults = true;
    recog.onresult = (ev) => {
      const said = Array.from(ev.results).map((r) => r[0].transcript).join(" ").toLowerCase();
      $("#heard").textContent = `Heard: “${said.slice(-60)}”`;
      if (/\b(i'?m|i am) (fine|ok|okay|alright|good)\b|\bfine\b|\bokay\b/.test(said)) imFine();
    };
    recog.onend = () => { if (body.classList.contains("checkin")) { try { recog.start(); } catch {} } else recog = null; };
    recog.start();
  } catch { recog = null; }
}
function stopListening() { try { recog && recog.stop(); } catch {} recog = null; $("#heard").textContent = ""; }

// ---------------------------------------------------------------- warmth
function glow(from) {
  body.classList.add("glow");
  note(`💛 ${from} is thinking of you`);
  clearTimeout(glowTimer);
  glowTimer = setTimeout(() => body.classList.remove("glow"), 60000);
}

// ---------------------------------------------------------------- controls
$("#away").addEventListener("click", () => {
  paused = !paused;
  ws.send({ type: "pause", hours: paused ? 24 : null });
  $("#away").textContent = paused ? "I'm back" : "I'm away today";
  note(paused ? "Kettle is paused for 24 hours. Your circle has been told." : "Welcome back. Kettle is on again.");
});
$("#simk").addEventListener("click", () => ws.send({ type: "sim", appliance: "kettle" }));
document.addEventListener("keydown", (e) => { if (e.key === "k") ws.send({ type: "sim", appliance: "kettle" }); if (e.key === " " && body.classList.contains("checkin")) imFine(); });

// ---------------------------------------------------------------- clock + trace
function tick() {
  let d;
  if (clock && clock.demo) {
    const t = clock.t + (Date.now() / 1000 - (clock._recv ||= Date.now() / 1000)) * clock.speed;
    d = new Date(t * 1000);
    $("#demo").hidden = false;
    $("#demo").textContent = clock.speed !== 1 ? `demo time · ×${clock.speed}` : "demo time";
  } else { d = new Date(); $("#demo").hidden = true; }
  const tz = clock?.tz || "America/Edmonton";
  const parts = new Intl.DateTimeFormat("en-CA", { hour: "numeric", minute: "2-digit", hour12: false, timeZone: tz }).formatToParts(d);
  const hh = +parts.find((p) => p.type === "hour").value % 24, mm = parts.find((p) => p.type === "minute").value;
  $("#clock").textContent = `${hh}:${mm}`;
  $("#hello").textContent = hh < 12 && hh >= 4 ? "Good morning, Margaret." : hh < 18 && hh >= 12 ? "Good afternoon, Margaret." : "Good evening, Margaret.";
  draw();
  requestAnimationFrame(tick);
}
requestAnimationFrame(tick);

const cv = $("#trace"), ctx = cv.getContext("2d");
function draw() {
  const dpr = devicePixelRatio || 1, W = cv.clientWidth, H = cv.clientHeight;
  if (cv.width !== W * dpr) { cv.width = W * dpr; cv.height = H * dpr; }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, H);
  const now = Date.now() / 1000, span = 180, max = 1700;
  ctx.lineWidth = 2; ctx.lineJoin = "round"; ctx.strokeStyle = "rgba(246,239,228,.75)";
  ctx.shadowColor = "rgba(255,180,87,.6)"; ctx.shadowBlur = 8;
  ctx.beginPath();
  let first = true;
  for (const [t, w] of points) {
    if (t < now - span) continue;
    const x = ((t - (now - span)) / span) * W, y = H - 4 - (Math.min(w, max) / max) * (H - 10);
    first ? ctx.moveTo(x, y) : ctx.lineTo(x, y); first = false;
  }
  ctx.stroke();
}
