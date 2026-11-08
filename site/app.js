// Kettle phone app. One calm card: what's happening with Margaret, and the one thing you can do.
// Same file on the Vercel site (phones register as a character) and on the laptop (/phone/?c=priya).

const $ = (s) => document.querySelector(s);
const main = $("#main"), foot = $("#foot"), meEl = $("#me");
const params = new URLSearchParams(location.search);
const still = params.has("still");            // screenshots for the film: no hints, no motion
let cfg = null, who = null, token = null, card = null, lastSig = "", lastBuzz = null, timer = null, busy = false;
let audio = null, soundOn = false;

const h = (tag, attrs = {}, ...kids) => {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v === true) el.setAttribute(k, "");
    else if (v !== false && v != null) el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid.nodeType ? kid : document.createTextNode(kid));
  return el;
};
const api = async (path, body) => {
  const r = await fetch(path, body ? { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) } : { cache: "no-store" });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error(data.error || data.detail || r.statusText), { status: r.status });
  return data;
};

// ------------------------------------------------------------------ boot
boot();
async function boot() {
  try { cfg = await api("/api/p/config"); }
  catch { cfg = { mode: "local", characters: {} }; }
  if (cfg.mode === "site") {
    token = localStorage.getItem("kettle.t");
    who = localStorage.getItem("kettle.c");
  } else {
    who = params.get("c") || localStorage.getItem("kettle.c");
    if (params.get("c")) localStorage.setItem("kettle.c", who);
  }
  if (who && (token || cfg.mode !== "site")) start(); else renderPick();
}

function start() {
  clearTimeout(timer);
  poll();
}

async function poll() {
  clearTimeout(timer);
  try {
    const c = await api(`/api/p/me?c=${encodeURIComponent(who)}${token ? `&t=${encodeURIComponent(token)}` : ""}`);
    render(c);
  } catch (e) {
    if (e.status === 401 || e.status === 404) { leave(true); return; }
    renderFoot(false);
  }
  timer = setTimeout(poll, document.hidden ? 4000 : 1200);
}
document.addEventListener("visibilitychange", () => { if (!document.hidden && card) poll(); });

// ------------------------------------------------------------------ the card
function render(c) {
  const sig = JSON.stringify([c.tone, c.kicker, c.title, c.body, c.why, c.buttons, c.glow, c.ref]);
  renderFoot(c.hub_online !== false, c.clock);
  if (c.buzz !== lastBuzz) {
    if (lastBuzz !== null && ["alert", "good", "warm"].includes(c.tone)) buzz(c.tone === "alert");
    lastBuzz = c.buzz;
  }
  card = c;
  if (sig === lastSig || busy) return;
  lastSig = sig;
  document.body.className = `t-${c.tone}`;
  meEl.replaceChildren(h("b", {}, c.who.name), c.who.line);
  const buttons = (c.buttons || []).map((b) => b.id.startsWith("tel:")
    ? h("a", { class: `btn ${b.style || "secondary"}`, href: b.id }, b.label)
    : h("button", { class: `btn ${b.style || "secondary"}`, onclick: (e) => tap(b.id, e.currentTarget) }, b.label));
  const glow = c.glow ? [
    h("button", { class: `btn warm${c.glow.sent ? " sent" : ""}`, disabled: c.glow.sent, onclick: (e) => tap("glow", e.currentTarget) },
      c.glow.sent ? "Sent" : c.glow.label),
    h("p", { class: "hint" }, c.glow.hint)] : [];
  main.replaceChildren(...[h("section", { class: "card", "aria-labelledby": "title" },
    c.kicker ? h("p", { class: "kicker" }, c.kicker) : null,
    h("h1", { id: "title" }, c.title),
    c.body ? h("p", { class: "body" }, c.body) : null,
    c.why ? h("p", { class: "why" }, c.why) : null),
    buttons.length || glow.length ? h("div", { class: "actions" }, ...buttons, ...glow) : null].filter(Boolean));
  if (still) {
    main.querySelectorAll(".card").forEach((x) => (x.style.animation = "none"));
    // film capture: report where the buttons are (fractions of the screen) in the page title
    const r = [...main.querySelectorAll(".btn")].map((b) => { const q = b.getBoundingClientRect();
      return [b.textContent, +((q.left + q.width / 2) / innerWidth).toFixed(3), +((q.top + q.height / 2) / innerHeight).toFixed(3)]; });
    document.title = JSON.stringify(r);
  }
}

async function tap(action, btn) {
  unlockAudio();
  if (busy) return;
  busy = true;
  main.querySelectorAll("button").forEach((b) => (b.disabled = true));
  const label = btn.textContent;
  btn.textContent = "Sending…";
  try {
    await api("/api/p/act", { c: who, t: token, action, ref: card?.ref || null });
  } catch (e) {
    btn.textContent = label;
    main.querySelectorAll("button").forEach((b) => (b.disabled = false));
    busy = false;
    return;
  }
  busy = false;
  lastSig = "";
  setTimeout(poll, 350);   // the hub answers within a second or two
  setTimeout(poll, 1500);
}

function renderFoot(online, clock) {
  foot.replaceChildren(...[
    h("span", { class: `dot${online ? "" : " off"}`, "aria-hidden": "true" }),
    online ? (clock ? `Demo time ${clock}` : "Connected") : "Waiting for the Kettle hub…",
    cfg?.mode === "site" && token ? h("button", { onclick: () => confirm("Leave this character?") && leave() }, "Leave") : null].filter(Boolean));
  if (!soundOn && !still && who && !$(".sound")) {
    document.body.append(h("button", { class: "sound", onclick: unlockAudio }, "🔔 Tap to turn on alerts"));
  }
}

// ------------------------------------------------------------------ choosing a character
async function renderPick(pre) {
  clearTimeout(timer);
  document.body.className = "";
  meEl.replaceChildren();
  foot.replaceChildren();
  $(".sound")?.remove();
  if (cfg.mode === "site") { try { cfg = await api("/api/p/config"); } catch {} }
  const chars = cfg.characters || {};
  main.replaceChildren(h("section", { class: "card pick" },
    h("p", { class: "kicker" }, "Kettle · live demo"),
    h("h1", {}, "Who are you in the story?"),
    h("p", { class: "body" }, "Pick a character. Your phone will get what they get."),
    h("div", { class: "chars" }, Object.entries(chars).map(([id, c]) => {
      const taken = cfg.taken?.[id];
      return h("button", { class: "char", disabled: !!taken, onclick: () => (cfg.mode === "site" ? renderJoin(id, c) : choose(id)) },
        h("span", { class: "av", "aria-hidden": "true" }, c.name[0]),
        h("span", {}, h("span", { class: "nm" }, c.name), h("span", { class: "ln" }, c.line)),
        taken ? h("span", { class: "tag" }, "taken") : null);
    })),
    pre ? h("p", { class: "err" }, pre) : null));
}

function choose(id) {
  who = id;
  localStorage.setItem("kettle.c", id);
  history.replaceState(null, "", `?c=${id}`);
  lastSig = ""; lastBuzz = null;
  start();
}

function renderJoin(id, c, err) {
  const input = h("input", { type: "tel", id: "num", inputmode: "tel", autocomplete: "tel", placeholder: "+1 403 555 1234" });
  const form = h("form", { class: "card pick", onsubmit: async (e) => {
    e.preventDefault();
    unlockAudio();
    const btn = form.querySelector(".primary");
    btn.disabled = true; btn.textContent = "Joining…";
    try {
      const r = await api("/api/p/register", { c: id, number: input.value.trim() });
      token = r.token; who = id;
      localStorage.setItem("kettle.t", token); localStorage.setItem("kettle.c", id);
      lastSig = ""; lastBuzz = null;
      start();
    } catch (ex) {
      if (ex.status === 409) renderPick(`${c.name} was just taken. Pick someone else.`);
      else renderJoin(id, c, ex.message);
    }
  } },
    h("p", { class: "kicker" }, "You'll play"),
    h("h1", {}, c.name),
    h("p", { class: "body" }, c.line),
    h("label", { for: "num" }, "Your phone number (optional)"),
    input,
    h("p", { class: "why" }, "Only for real text messages during this demo. Deleted within 24 hours."),
    err ? h("p", { class: "err" }, err) : null,
    h("div", { class: "actions" },
      h("button", { class: "btn primary", type: "submit" }, `Join as ${c.name}`),
      h("button", { class: "btn quiet", type: "button", onclick: () => renderPick() }, "Back")));
  main.replaceChildren(form);
}

async function leave(silent) {
  clearTimeout(timer);
  if (token && !silent) await api("/api/p/leave", { t: token }).catch(() => {});
  localStorage.removeItem("kettle.t"); localStorage.removeItem("kettle.c");
  token = null; who = null; card = null; lastSig = ""; lastBuzz = null;
  renderPick(silent ? "The host removed this phone. Pick a character to join again." : null);
}

// ------------------------------------------------------------------ sound + vibration
function unlockAudio() {
  soundOn = true;
  $(".sound")?.remove();
  if (audio) return;
  try { audio = new (window.AudioContext || window.webkitAudioContext)(); } catch { audio = null; }
}

function buzz(urgent) {
  if (navigator.vibrate) navigator.vibrate(urgent ? [260, 120, 260, 120, 520] : [120]);
  if (!audio) return;
  const now = audio.currentTime;
  const notes = urgent ? [[0, 880], [0.18, 1175], [0.5, 880], [0.68, 1175]] : [[0, 660], [0.16, 990]];
  for (const [at, f] of notes) {
    const o = audio.createOscillator(), g = audio.createGain();
    o.frequency.value = f; o.type = "sine";
    g.gain.setValueAtTime(0.0001, now + at); g.gain.exponentialRampToValueAtTime(0.25, now + at + 0.02); g.gain.exponentialRampToValueAtTime(0.0001, now + at + 0.3);
    o.connect(g).connect(audio.destination); o.start(now + at); o.stop(now + at + 0.32);
  }
}
