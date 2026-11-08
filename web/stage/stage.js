// Kettle stage: the presenter screen projected behind the team (and recorded for the video).
// It animates the real product state: /ws/stage from the cloud, plus the edge hub's local-only
// power trace (?edge=ws://host:8701/ws/local). Every number shown comes from one of those two.

import { socket, wsBase, post, fmtMin } from "../shared/kettle.js";

// ============================================================== setup
const $ = (id) => document.getElementById(id);
const qs = new URLSearchParams(location.search);
const EDGE_URL = qs.get("edge") || `ws://${location.hostname || "localhost"}:8701/ws/local`;
const motionQ = matchMedia("(prefers-reduced-motion: reduce)");
let reduced = motionQ.matches || qs.has("still");
motionQ.addEventListener?.("change", (e) => (reduced = e.matches || qs.has("still")));

const rootCss = getComputedStyle(document.documentElement);
const cssv = (n, fb) => rootCss.getPropertyValue(n).trim() || fb;
const C = {
  steam: cssv("--steam", "#f6efe4"), steam2: cssv("--steam-2", "#cdbfae"), steam3: cssv("--steam-3", "#9b8b7a"),
  glow: cssv("--glow", "#ffb457"), night: cssv("--night", "#140e09"), ok: cssv("--ok-n", "#9fd8b0"),
  frost: cssv("--frost-n", "#a9d6f5"), dark: "#5a4a3d",
};
const FONT = getComputedStyle(document.body).fontFamily;
let REM = parseFloat(rootCss.fontSize) || 16;

const rgba = (hex, a) => {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`;
};
const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
const nf = new Intl.NumberFormat("en-CA");
const fmtInt = (x) => nf.format(Math.round(x));
const minus = (s) => String(s).replace(/(^|[\s(])-(?=\d)/g, "$1−");
const fmtTemp = (c) => (c == null ? "–" : `${minus(String(Math.round(c * 10) / 10))} °C`);
const fmtW = (w) => (w < 10 ? `${w.toFixed(1)} W` : `${fmtInt(w)} W`);
const NICE = { kettle: "kettle", microwave: "microwave", toaster: "toaster", tv: "TV", furnace_blower: "furnace", human_unknown: "appliance", cooking: "stove", activity: "activity" };
const PRON = { she: { obj: "her", poss: "her" }, he: { obj: "him", poss: "his" }, they: { obj: "them", poss: "their" } };
const pron = (m) => PRON[m?.pronoun] || PRON.they;

function el(tag, cls, ...kids) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  for (const k of kids.flat()) if (k != null && k !== false) e.append(k.nodeType ? k : document.createTextNode(String(k)));
  return e;
}
function svgIcon(path, vb = "0 0 24 24") {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  s.setAttribute("viewBox", vb);
  s.setAttribute("aria-hidden", "true");
  s.innerHTML = path;
  return s;
}
const ICONS = {
  phone: '<path d="M6.6 3.5h2.6l1.4 4.1-2 1.5a12 12 0 0 0 6.3 6.3l1.5-2 4.1 1.4v2.6a2 2 0 0 1-2.2 2A16.5 16.5 0 0 1 4.6 5.7a2 2 0 0 1 2-2.2Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>',
  sms: '<path d="M4 5.5h16v10H9.5L5 19v-3.5H4z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>',
  push: '<path d="M6 16.5V11a6 6 0 0 1 12 0v5.5l1.5 1.5h-15zM10 20.5h4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round"/>',
  device: '<circle cx="12" cy="12" r="3.2" fill="currentColor"/><circle cx="12" cy="12" r="7.5" fill="none" stroke="currentColor" stroke-width="1.6" opacity=".55"/>',
  flake: '<path d="M12 2v20M3.3 7l17.4 10M3.3 17 20.7 7M9.5 3.8 12 6l2.5-2.2M9.5 20.2 12 18l2.5 2.2" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>',
  mobile: '<rect x="7" y="2.5" width="10" height="19" rx="2.2" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M10.5 18.5h3" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>',
};

// ============================================================== state + clocks
let S = null;          // latest stage state from the cloud
let sAt = 0;           // performance.now() when it arrived
let sBaseMin = 0;      // kettle-day minutes (04:00 -> 28:00) of S.clock.local
let sMidnight = 0;     // epoch of local midnight for the demo date
let realSkew = 0;      // cloud real_time - browser time, seconds

const speedNow = () => (S?.clock?.demo ? S.clock.speed : 1);
const demoT = () => (S ? S.clock.t + ((performance.now() - sAt) / 1000) * speedNow() : Date.now() / 1000);
const nowMin = () => (S ? sBaseMin + ((performance.now() - sAt) / 60000) * speedNow() : 0);
const srvNow = () => Date.now() / 1000 + realSkew;
const isReplay = () => S?.grid?.mode === "replay";
const hero = () => S?.homes?.find((x) => x.id === "margaret") || S?.homes?.find((x) => x.kind === "live") || S?.homes?.[0];
const memberById = (id) => S?.members?.find((m) => m.id === id);

const fmtCache = new Map();
function dtf(opts) {
  const tz = S?.clock?.tz || "America/Edmonton";
  const k = tz + JSON.stringify(opts);
  if (!fmtCache.has(k)) fmtCache.set(k, new Intl.DateTimeFormat("en-CA", { timeZone: tz, ...opts }));
  return fmtCache.get(k);
}
function hhmmOf(t) {
  const p = dtf({ hour: "numeric", minute: "2-digit", hourCycle: "h23" }).formatToParts(new Date(t * 1000));
  return `${+(p.find((x) => x.type === "hour")?.value ?? 0)}:${p.find((x) => x.type === "minute")?.value ?? "00"}`;
}
function minOfDayIso(iso) {
  const hh = +iso.slice(11, 13), mm = +iso.slice(14, 16), ss = +iso.slice(17, 19) || 0;
  return hh * 60 + mm + ss / 60;
}

/** The day axis shared by the ribbon, the replay charts and the map's mini lines. */
function dayDomain() {
  const n = nowMin();
  if (isReplay()) return [12 * 60, Math.min(28 * 60, Math.max(24 * 60, Math.ceil((n + 30) / 60) * 60))];
  return [240, Math.min(28 * 60, Math.max(14 * 60, Math.ceil((n + 50) / 60) * 60))];
}

// ============================================================== cloud socket
let offlineTimer = 0;
socket(wsBase() + "/ws/stage", {
  onmessage: (m) => m && m.type === "state" && onState(m),
  onstatus: (ok) => {
    clearTimeout(offlineTimer);
    if (ok) $("offline").hidden = true;
    else offlineTimer = setTimeout(() => ($("offline").hidden = false), 2500);
  },
});

function onState(s) {
  const first = !S;
  S = s;
  sAt = performance.now();
  realSkew = (s.real_time ?? Date.now() / 1000) - Date.now() / 1000;
  const mod = minOfDayIso(s.clock.local);
  sBaseMin = mod < 240 ? mod + 1440 : mod;
  sMidnight = Math.floor(s.clock.t - sBaseMin * 60); // local midnight that starts this kettle day (whole seconds)
  document.body.classList.remove("booting");
  document.body.classList.toggle("replay", isReplay());
  document.body.classList.toggle("cold", !!s.cold?.active);
  if (s.cold?.active) frost.ensure();
  rememberDeadline();
  handleFlashes(s.flashes || []);
  handleOutbox(s.outbox || [], first);
  render();
}

// ============================================================== edge (local-only trace)
const edge = { ok: false, status: null, pts: [], events: [], skew: null, outageUntil: 0, checkin: null, glow: null };
const edgeSock = socket(EDGE_URL, {
  onmessage: onEdge,
  onstatus: (ok) => { edge.ok = ok; if (!ok) edge.status = null; renderChips(true); },
});
function onEdge(m) {
  const now = Date.now() / 1000;
  switch (m.type) {
    case "history":
      edge.pts = (m.points || []).map(([t, w]) => ({ t, w }));
      if (edge.pts.length) noteSkew(edge.pts[edge.pts.length - 1].t, now);
      break;
    case "sample":
      edge.pts.push({ t: m.t, w: m.w, off: now < edge.outageUntil });
      noteSkew(m.t, now);
      if (edge.pts.length > 1500) edge.pts.splice(0, edge.pts.length - 1300);
      break;
    case "status":
      edge.status = m;
      edge.checkin = m.ui?.checkin || edge.checkin;
      renderChips(true);
      break;
    case "event":
      edge.events.push(m.event);
      if (edge.events.length > 40) edge.events.shift();
      break;
    case "checkin": edge.checkin = m.text || "…"; break;
    case "checkin_end": edge.checkin = null; break;
    case "glow": edge.glow = { from: m.from, until: now + 60 }; break;
    case "outage": edge.outageUntil = now + (+m.seconds || 30); break;
    case "toast": toast({ text: m.text }); break;
  }
}
function noteSkew(t, now) {
  const s = t - now;
  edge.skew = edge.skew == null || Math.abs(s - edge.skew) > 5 ? s : edge.skew + (s - edge.skew) * 0.08;
}

// ============================================================== render (DOM)
const memo = new Map();
const changed = (name, key) => (memo.get(name) === key ? false : (memo.set(name, key), true));

function render() {
  if (!S) return;
  renderHeader();
  renderChips();
  const m = hero();
  if (m) {
    renderHero(m);
    renderLadder(m);
    renderDayCaption(m);
  }
  renderContext();
  renderOutbox();
  renderEvidence();
  map.update();
  syncDrawer();
}

// ---------------------------------------------------------------- header
function renderHeader() {
  const c = S.clock;
  const pill = $("demoPill");
  pill.hidden = !c.demo;
  const sp = Number(c.speed);
  const spTxt = sp === 1 ? "real speed" : `×${Number.isInteger(sp) ? sp : sp.toFixed(1)}`;
  const txt = isReplay() ? `Replay · ${spTxt}` : `Demo time · ${spTxt}`;
  if (pill.textContent !== txt) pill.textContent = txt;
  const date = dtf(isReplay() ? { weekday: "short", day: "numeric", month: "short", year: "numeric" } : { weekday: "long", day: "numeric", month: "long" }).format(new Date(c.t * 1000));
  if ($("clockDate").textContent !== date) $("clockDate").textContent = date;
}
function tickClock() {
  if (!S) return;
  const m = Math.floor(nowMin()) % 1440;
  const t = `${Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")}`;
  const e = $("clockTime");
  if (e.textContent !== t) e.textContent = t;
}

function chip(cls, k, v, title) {
  const c = el("span", `chip ${cls || ""}`, el("i"), `${k} `, v != null ? el("b", null, v) : null);
  if (title) c.title = title;
  return c;
}
function renderChips(force) {
  if (!S) return;
  const g = S.grid || {};
  const m = hero();
  const info = m?.device?.info || {};
  const es = edge.status;
  const key = JSON.stringify([g.mode, g.aeso?.fetched, g.weather?.fetched, g.errors, S.cold?.active, S.store, S.twilio, info, m?.device?.online, m?.device?.dark,
    es && [es.plug_real, es.plug_ok, es.plug, es.cloud_ok], edge.ok]);
  if (!changed("chips", key) && !force) return;
  const out = [];
  if (g.mode === "replay") {
    out.push(chip("ok", "AESO + ECCC", "archive replay", "Real archived data: AESO Actual/Forecast + SMP, ECCC CALGARY INTL A hourly"));
  } else {
    const a = g.aeso || {}, err = g.errors || {}, w = g.weather || {};
    out.push(chip(err.aeso ? "bad" : a.fetched ? "ok" : "", "AESO", err.aeso ? (a.fetched ? "stale" : "offline") : a.fetched ? "live" : "…", a.source));
    out.push(chip(err.weather ? "bad" : w.fetched ? "ok" : "", "ECCC", err.weather ? (w.fetched ? "stale" : "offline") : w.fetched ? "live" : "…", w.source));
  }
  if (S.cold?.active) out.push(chip("cold", "cold mode", "on"));
  const store = String(S.store || "memory");
  out.push(chip(store.startsWith("timescale") ? "ok" : store.includes("error") ? "bad" : "", "store", store.split(" ")[0], store));
  out.push(chip(S.twilio === "twilio" ? "ok" : "warn", "calls", S.twilio === "twilio" ? "Twilio" : "simulated"));
  const real = es ? es.plug_real : info.real;
  const plugName = es?.plug || info.plug || "";
  if (es && es.plug_ok === false) out.push(chip("bad", "plug", "not responding", es.plug_err || ""));
  else out.push(chip(real ? "ok" : "warn", "plug", real ? `real${plugName ? " · " + plugName.split(":")[0] : ""}` : "simulated", plugName));
  if (m && !m.device?.online) out.push(chip("bad", "Kettle", m.device?.dark ? "dark" : "offline"));
  $("chips").replaceChildren(...out);
}

// ---------------------------------------------------------------- hero text
function heroModel(m) {
  const e = m.escalation, b = m.baseline || {};
  if (e && e.step !== "resolved") {
    if (e.reason === "grid") {
      const t = S.cold?.temp_c;
      return { tone: "cold", big: t != null ? `Grid emergency at ${fmtTemp(t)}` : "Alberta grid emergency", sub: minus(`Rotating outages possible. ${e.explanation}`) };
    }
    const tone = e.reason === "morning" ? "alert" : e.reason === "dark" ? "dark" : "cold";
    return { tone, big: minus(e.headline), sub: minus(e.explanation) };
  }
  if (e && e.step === "resolved") {
    const when = e.resolved_at ? hhmmOf(e.resolved_at) : "";
    return { tone: "ok", big: m.first_today ? m.status_text : minus(e.resolution || "All good"), sub: el("span", "ok", `✓ Resolved ${when} · ${e.resolution || ""}`) };
  }
  if (m.device?.dark) return { tone: "dark", big: `${m.person}'s Kettle is dark`, sub: "No power at the plug." };
  if (m.status === "ok") return { tone: "ok", big: m.status_text, sub: b.sentence };
  if (m.status === "paused") return { tone: "wait", big: m.status_text, sub: "Kettle won't ask while paused." };
  if (!b.learned) return { tone: "wait", big: `Waiting for ${m.person}'s first kettle`, sub: b.sentence };
  return { tone: "wait", big: m.status_text, sub: b.sentence };
}

const phone = { wasRinging: false, endedAt: 0, resolvedSeen: new Map() };
function renderHero(m) {
  const hm = heroModel(m);
  const heroEl = $("hero");
  heroEl.className = `hero tone-${hm.tone}`;

  const area = [m.area, "lives alone"].filter(Boolean).join(" · ");
  const sensing = m.sensing === "v1" ? "whole-home meter" : "kettle plug";
  if (changed("who", m.person + area + sensing)) {
    $("who").replaceChildren(el("span", "dot"), el("span", "name", m.person), el("span", null, `· ${area} · ${sensing}`));
  }
  const subTxt = typeof hm.sub === "string" ? hm.sub : hm.sub?.textContent || "";
  if (changed("heroText", hm.big + "|" + subTxt)) {
    const big = $("statusBig");
    big.textContent = hm.big;
    big.classList.toggle("long", hm.big.length > 46);
    big.classList.remove("fade-swap"); void big.offsetWidth; big.classList.add("fade-swap");
    $("statusSub").replaceChildren(hm.sub || "");
  }
  renderCallout(m);
}

function renderCallout(m) {
  const e = m.escalation;
  const now = srvNow();
  if (m.ringing) phone.wasRinging = true;
  else if (phone.wasRinging) { phone.wasRinging = false; phone.endedAt = now; }
  const rows = [];
  const p = pron(m);
  if (m.ringing) {
    rows.push(["ringing", ICONS.phone, `Calling ${m.person}…`, S.twilio === "twilio" ? "Twilio voice call" : "phone call (simulated)"]);
  } else if (e && e.step !== "resolved" && now - phone.endedAt < 9 && e.log?.some((l) => /^No answer/.test(l.text))) {
    rows.push(["noanswer", ICONS.phone, "No answer", `${m.person} didn't pick up`]);
  }
  if (e && e.step === "resolved" && /pressed|answered/.test(e.resolution || "")) {
    if (!phone.resolvedSeen.has(e.id)) phone.resolvedSeen.set(e.id, now);
    if (now - phone.resolvedSeen.get(e.id) < 10) rows.push(["fine", ICONS.device, `${m.person} is fine`, e.resolution]);
  }
  const lightOn = (e && e.step !== "resolved" && (e.step === "check_self" || (edge.checkin && e.reason !== "morning"))) || (!e && edge.checkin);
  if (lightOn || (e && e.step === "check_self")) rows.push(["light", null, `Light pulsing on ${p.poss} Kettle`, `“${edge.checkin && edge.checkin !== "…" ? edge.checkin : "Press here if you're fine."}”`]);

  const key = rows.map((r) => r[0] + r[2]).join("|");
  const box = $("callout");
  if (!changed("callout", key)) return;
  box.hidden = rows.length === 0;
  document.querySelector(".hero-head").style.paddingRight = rows.length ? "22rem" : "";
  box.replaceChildren(...rows.map(([cls, icon, t1, t2]) => {
    const ico = el("span", "ico");
    if (icon) ico.append(svgIcon(icon)); else ico.append(el("i"));
    return el("div", `row ${cls}`, ico, el("div", null, el("div", "t1", t1), el("div", "t2", t2)));
  }));
}

// ---------------------------------------------------------------- escalation ladder
const STEP_IDX = { check_self: 0, ask_neighbour: 1, neighbour_going: 1, ask_family: 2, welfare: 3, needs_help: 3 };
let lastLogLen = 0;
function renderLadder(m) {
  const e = m.escalation, b = m.baseline || {};
  const circle = Array.isArray(m.circle) ? m.circle.filter((c) => typeof c === "object") : [];
  const nbrs = circle.filter((c) => c.role === "neighbour").sort((a, z) => (a.distance_min ?? 99) - (z.distance_min ?? 99));
  const fam = circle.filter((c) => c.role === "family");
  const p = pron(m);
  const key = JSON.stringify([e && [e.id, e.step, e.log.length, e.responder, e.asked], circle.map((c) => c.id), b.deadline, m.ringing]);
  if (!changed("ladder", key)) return;

  let state = "idle", cur = -1;
  const reachedSet = new Set();
  if (e) {
    for (const l of e.log || []) if (STEP_IDX[l.step] != null) reachedSet.add(STEP_IDX[l.step]);
    if (e.step === "resolved") state = "resolved";
    else { state = "active"; cur = STEP_IDX[e.step] ?? 0; reachedSet.add(cur); }
  }
  const reached = reachedSet.size ? Math.max(...reachedSet) : -1;
  const asked = (e?.asked || []).map((id) => circle.find((c) => c.id === id)).filter(Boolean);
  const lastAskedN = [...asked].reverse().find((c) => c.role === "neighbour");
  const responder = e?.responder && circle.find((c) => c.id === e.responder);
  const dist = (c) => (c.distance_min != null ? `${c.distance_min} min away` : "nearby");

  const subs = [
    "Call + kitchen light",
    nbrs[0] ? `${nbrs[0].name}, ${dist(nbrs[0])}` : "None listed",
    fam.map((f) => `${f.name}, ${(f.relation || "family").split(",")[0]}`).join(" · ") || "None listed",
    "non-emergency line",
  ];
  if (state === "active") {
    if (cur === 0) subs[0] = m.ringing ? `Calling ${m.person}…` : "Waiting for “I'm fine”";
    if (cur === 1) {
      if (e.step === "neighbour_going" && responder) subs[1] = `${responder.name} is on the way`;
      else if (e.reason !== "morning") subs[1] = `Asking ${asked.map((c) => c.name).join(", ")}`;
      else if (lastAskedN) subs[1] = `Asking ${lastAskedN.name}, ${dist(lastAskedN)}`;
    }
    if (cur === 2) subs[2] = `Asking ${fam.map((f) => f.name).join(", ") || "family"}`;
    if (cur === 3) subs[3] = e.step === "needs_help" ? "911 shown · family alerted" : "Suggested to family";
  }
  const titles = [`Ask ${m.person}`, "Neighbour", "Family", "Welfare check"];
  const steps = titles.map((t, i) => {
    let cls = "step";
    if (state === "active") cls += i < cur ? (reachedSet.has(i) ? " done" : " skip") : i === cur ? " now" : "";
    if (state === "resolved" && reachedSet.has(i)) cls += " done";
    return el("div", cls, el("div", "node", String(i + 1)), el("div", "st", t), el("div", "ss", subs[i]));
  });
  const bar = el("div", "bar");
  const upto = state === "active" ? cur : state === "resolved" ? reached : -1;
  bar.style.width = upto > 0 ? `calc(${upto * 25}% - 0px)` : "0";

  const reasonTxt = !e ? `If there's no kettle by ${b.deadline || "the deadline"}, Kettle asks, in this order`
    : e.reason === "morning" ? (state === "resolved" ? "Missed morning · resolved" : `Missed morning · since ${hhmmOf(e.started_at)}`)
    : e.reason === "grid" ? "Grid emergency check-in" : e.reason === "dark" ? "Kettle went dark in the cold" : e.reason;
  const head = el("div", "lhead", el("h2", "label", "Escalation"), el("span", "reason", reasonTxt));

  const log = el("ul", "log");
  if (e) {
    const items = (e.log || []).slice(-3);
    const fresh = (e.log || []).length > lastLogLen;
    items.forEach((l, i) => {
      const li = el("li", `k-${l.kind}${fresh && i === items.length - 1 ? " new" : ""}`, el("span", "lt", hhmmOf(l.t)), el("span", null, minus(l.text)));
      log.append(li);
    });
    lastLogLen = (e.log || []).length;
  } else {
    lastLogLen = 0;
    const note = el("li", null, el("span", "idle-note", el("b", null, "Quiet by design."), ` Nobody is disturbed while ${m.person}'s mornings look normal. Kettle asks ${m.person} first; ${p.poss} circle only hears if ${m.pronoun === "she" ? "she doesn't" : m.pronoun === "he" ? "he doesn't" : "they don't"} answer.`));
    note.style.display = "block";
    log.append(note);
  }
  const lad = $("ladder");
  lad.className = `ladder ${state}${e && e.reason !== "morning" ? " cold" : ""}`;
  lad.replaceChildren(el("div", null, head, el("div", "steps", bar, ...steps)), log);
}

function renderDayCaption(m) {
  const b = m.baseline || {};
  let txt;
  if (isReplay()) {
    const spd = speedNow();
    txt = [el("span", null, el("b", null, "January 13 2024, real data"), " · price & load: AESO Actual/Forecast, hourly · temperature: ECCC CALGARY INTL A, hourly"),
      el("span", "caption-r", `replayed ×${spd}`)];
  } else {
    const house = seedHouse(m.seed);
    const dayKind = { weekday: "weekdays", weekend: "weekends", all: "days" }[b.kind] || "days";
    const left = b.learned
      ? el("span", null, el("b", null, "Her rhythm"), ` · band: usual start ± spread · dots: first activity on ${b.n} previous ${dayKind}`)
      : el("span", null, el("b", null, "Her rhythm"), ` · still learning: ${b.n || 0} of ${(b.n || 0) + (b.days_needed || 0)} days`);
    txt = [left, el("span", "caption-r", house ? `learned from REFIT House ${house}, a real UK home` : "4:00 → now")];
  }
  const key = txt.map((x) => x.textContent).join("|");
  if (changed("dayCap", key)) $("dayCap").replaceChildren(...txt);
  $("replayBlock").hidden = !isReplay();
}
function seedHouse(seed) {
  if (!seed) return null;
  if (seed.house) return seed.house;
  const f = (seed.files || []).join(" ").match(/House(\d+)/);
  return f ? f[1] : null;
}

// ---------------------------------------------------------------- context (weather, cold, AESO / replay timeline)
let standardDeadline = null;
function rememberDeadline() {
  const b = hero()?.baseline;
  if (b && b.policy === "standard" && b.learned) standardDeadline = b.deadline;
}
function ring(frac, big, small) {
  const NS = "http://www.w3.org/2000/svg";
  const s = document.createElementNS(NS, "svg");
  s.setAttribute("viewBox", "-70 -70 140 140");
  const circ = 2 * Math.PI * 56;
  const f = clamp(frac || 0, 0, 1);
  s.innerHTML = `<circle class="ring-track" r="56"/><circle class="ring-fill" r="56" transform="rotate(-90)" stroke-dasharray="${circ}" stroke-dashoffset="${circ * (1 - f)}"/>` +
    `<text class="ring-v" y="6"></text><text class="ring-u" y="28"></text>`;
  s.querySelector(".ring-v").textContent = big;
  s.querySelector(".ring-u").textContent = small;
  return s;
}
function renderContext() {
  const g = S.grid || {}, cold = S.cold || {};
  const b = hero()?.baseline || {};
  const key = JSON.stringify([g.mode, g.mode === "replay" ? [g.weather, g.hour, g.fired] : [g.aeso, g.weather, g.alerts], cold, b.deadline, b.policy, standardDeadline]);
  if (!changed("context", key)) return;
  const box = $("context");
  const coldBlock = () => {
    const t = el("div", "t", svgIcon(ICONS.flake), cold.active ? "Cold mode on" : cold.mode === "off" ? "Cold mode off (presenter)" : "Cold mode off");
    const lines = [];
    if (cold.active) {
      lines.push(el("div", null, minus(cold.reason || "")));
      if (b.learned && b.policy === "cold") {
        lines.push(el("div", null, "Kettle asks sooner: ", el("b", null, `by ${b.deadline}`), standardDeadline && standardDeadline !== b.deadline ? ` instead of ${standardDeadline}` : "", ". A Kettle that goes dark is a reason to check."));
      } else lines.push(el("div", null, "Thresholds tighten. A Kettle that goes dark is a reason to check."));
    } else {
      lines.push(el("div", null, `Switches on at ${minus(String(cold.threshold_c ?? -25))} °C or below, or an Environment Canada extreme-cold warning.`));
    }
    return el("div", "cold-state", t, ...lines);
  };

  if (g.mode === "replay") {
    const w = g.weather || {};
    const fired = g.fired || [];
    const upto = Math.min((g.timeline || []).length - 1, (fired.length ? Math.max(...fired) : -1) + 1);
    const tl = (g.timeline || []).map((x, i) => {
      const f = fired.includes(i);
      return el("li", f ? "fired" : "", el("span", "tt", x.t.slice(11, 16)), el("span", null, x.text, el("span", "src", `Source: ${x.source}`)));
    }).slice(0, upto + 1).slice(-3);
    const temp = el("div", "temp", el("span", "v", fmtTemp(w.temp_c)), el("span", "u", w.wind_chill != null ? `wind chill ${minus(String(w.wind_chill))}` : ""));
    box.replaceChildren(
      el("div", "ctx-left",
        el("h2", "label", "Calgary · January 13 2024"),
        el("div", null, temp, el("div", "ctx-src", `ECCC archive, CALGARY INTL A · observed ${w.t ? w.t.slice(11, 16) : "–"}`)),
        el("ul", "tl", tl)));
    return;
  }

  const w = g.weather || {}, a = g.aeso || {};
  const obs = w.observed ? hhmmOf(Date.parse(w.observed) / 1000) : null;
  const temp = el("div", "temp", el("span", "v", fmtTemp(w.temp_c)),
    el("span", "u", [w.condition, w.temp_c != null && w.temp_c <= 0 && w.wind_chill != null ? `wind chill ${minus(String(w.wind_chill))}` : null].filter(Boolean).join(" · ")));
  const left = el("div", "ctx-left",
    el("h2", "label", "Calgary now"),
    el("div", null, temp, el("div", "ctx-src", w.temp_c != null ? `ECCC live · ${w.station || "Calgary"}${obs ? ` · observed ${obs}` : ""}` : "ECCC: waiting for data")),
    coldBlock());
  let right;
  if (a.reserve_required_mw && a.reserve_dispatched_mw != null) {
    const frac = a.reserve_dispatched_mw / a.reserve_required_mw;
    const upd = (a.updated || "").match(/(\d{1,2}:\d{2})\s*$/)?.[1];
    right = el("div", "ring-box",
      ring(frac, `${fmtInt(a.reserve_dispatched_mw)}`, `of ${fmtInt(a.reserve_required_mw)} MW`),
      el("div", "rk", el("b", null, "Contingency reserve"), el("br"), "dispatched vs required"),
      el("div", "rk", "Alberta load ", el("b", null, a.ail_mw != null ? `${fmtInt(a.ail_mw)} MW` : "–")),
      el("div", "rk", `AESO live${upd ? ` · ${upd}` : ""}`));
  } else {
    right = el("div", "ring-box", ring(0, "–", "MW"), el("div", "rk", el("b", null, "Contingency reserve"), el("br"), (S.grid.errors || {}).aeso ? "AESO unreachable" : "waiting for AESO"));
  }
  box.replaceChildren(el("div", "ctx-grid", left, right));
}

// ---------------------------------------------------------------- outbox
const outSeen = new Set();
let outNew = new Set();
const okey = (o) => `${o.t}|${o.channel}|${o.to}|${o.text.slice(0, 20)}`;
function handleOutbox(list, first) {
  outNew = new Set();
  for (const o of list) {
    const k = okey(o);
    if (outSeen.has(k)) continue;
    outSeen.add(k);
    if (!first) {
      outNew.add(k);
      if (o.channel === "sms") sound.buzz("sms");
    }
  }
  if (moment.open) moment.updateAsked(list);
}
function renderOutbox() {
  const list = (S.outbox || []).slice(0, 3);
  if (!changed("outbox", JSON.stringify(list.map(okey)))) return;
  const row = $("outbox");
  if (!list.length) {
    row.replaceChildren(el("div", "ob-empty", el("b", null, "Nothing sent yet."), " Kettle stays quiet while mornings look normal."));
    return;
  }
  const CH = { voice: ["phone", "Call"], sms: ["sms", "SMS"], push: ["push", "App"], device: ["device", "Kitchen light"] };
  const VIA = { simulated: "simulated", twilio: "Twilio", ws: "live", offline: "offline" };
  row.replaceChildren(...list.map((o) => {
    const [ic, name] = CH[o.channel] || ["push", o.channel];
    const via = el("span", `via${o.via === "twilio" || o.via === "ws" ? " real" : ""}`, VIA[o.via] || o.via);
    return el("div", `ob${outNew.has(okey(o)) ? " new" : ""}`,
      el("div", "oh", svgIcon(ICONS[ic]), el("b", null, o.to), `${name} · ${o.hhmm}`, via),
      el("div", "ot", minus(o.text)));
  }));
}

// ---------------------------------------------------------------- evidence (REFIT)
function pick(obj, path) {
  return path.split(".").reduce((o, k) => (o && typeof o === "object" ? o[k] : undefined), obj);
}
function refitFacts(r) {
  const out = [];
  const ci = pick(r, "checkins_per_home_month.v0_kettle_plug.standard");
  const ciCold = pick(r, "checkins_per_home_month.v0_kettle_plug.cold");
  if (typeof ci === "number") out.push({ v: ci.toFixed(1), k: "check-ins per home per month", s: `kettle plug${typeof ciCold === "number" ? ` · ${ciCold.toFixed(1)} in cold mode` : ""}` });
  const f1p = pick(r, "kettle_f1_plug"), f1 = pick(r, "kettle_f1");
  if (typeof f1p === "number") out.push({ v: f1p.toFixed(2), k: "kettle detection F1 (plug)", s: typeof f1 === "number" ? `whole-home meter (v1): ${f1.toFixed(2)}` : "" });
  else if (typeof f1 === "number") out.push({ v: f1.toFixed(2), k: "kettle detection F1", s: "whole-home meter" });
  const mins = pick(r, "minutes_after_usual_before_asking.v0_kettle_plug.standard");
  const minsC = pick(r, "minutes_after_usual_before_asking.v0_kettle_plug.cold");
  if (typeof mins === "number") out.push({ v: `${Math.round(mins)} min`, k: "after the usual time, Kettle asks", s: typeof minsC === "number" ? `cold mode ${Math.round(minsC)} min` : "" });
  if (!out.length) {
    // Unknown summary shape: show its own top-level numbers, named by their keys.
    for (const [k, v] of Object.entries(r)) if (typeof v === "number" && out.length < 3 && !/runtime|generated/.test(k)) out.push({ v: String(v), k: k.replace(/_/g, " "), s: "" });
  }
  return out;
}
function renderEvidence() {
  const r = S.refit;
  if (!changed("evidence", JSON.stringify(r))) return;
  const row = $("evidence");
  const homes = r?.houses ?? 20;
  $("evSrc").replaceChildren(el("b", null, `REFIT: ${homes} UK homes`), ", CC BY 4.0", r?.home_days ? ` · ${fmtInt(r.home_days)} real home-days, same code` : "");
  if (!r) {
    row.replaceChildren(el("div", "ev pending", el("div", "ev-v", "REFIT evaluation running"), el("div", "ev-s", "real measured electricity from 20 UK homes; results appear here when ready")));
    return;
  }
  const facts = refitFacts(r).slice(0, 2);
  row.replaceChildren(...facts.map((f) => el("div", "ev", el("div", "ev-v", f.v), el("div", "ev-k", f.k), el("div", "ev-s", f.s || ""))));
}

// ============================================================== canvases
const canv = {};
function setupCanvas(name, id) {
  const cv = $(id);
  const o = { cv, ctx: cv.getContext("2d"), w: 0, h: 0 };
  const fit = () => {
    const r = cv.getBoundingClientRect();
    const dpr = Math.min(2, devicePixelRatio || 1);
    o.w = r.width; o.h = r.height;
    const W = Math.max(1, Math.round(r.width * dpr)), H = Math.max(1, Math.round(r.height * dpr));
    if (cv.width !== W || cv.height !== H) { cv.width = W; cv.height = H; }
    o.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  };
  new ResizeObserver(fit).observe(cv);
  fit();
  canv[name] = o;
}
setupCanvas("trace", "trace");
setupCanvas("ribbon", "ribbon");
setupCanvas("replay", "replayChart");
addEventListener("resize", () => { REM = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16; frost.reset(); });

const LANE_L = 1.2, LANE_R = 1.2; // rem; the ribbon and the replay charts share this x-axis

// ---------------------------------------------------------------- live trace (edge, real time)
const TRACE_WIN = 120, TRACE_DELAY = 0.8, W_MAX = 2400;
const steam = [];
let lastFrame = performance.now(), traceHot = null, steamAcc = 0;
function lowerBound(arr, t) {
  let lo = 0, hi = arr.length;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (arr[mid].t < t) lo = mid + 1; else hi = mid; }
  return lo;
}
function drawTrace(ts, dt) {
  const { ctx, w: W, h: H } = canv.trace;
  if (!W || !H) return;
  ctx.clearRect(0, 0, W, H);
  const r = REM;
  const padT = 2.2 * r, padB = 0.4 * r, padL = 0, padR = 10 * r;
  const pw = W - padL - padR, ph = H - padT - padB;
  const LOGMAX = Math.log10(1 + W_MAX / 4);
  const Y = (w) => padT + ph * (1 - Math.log10(1 + Math.max(0, w) / 4) / LOGMAX);
  const nowE = Date.now() / 1000 + (edge.skew ?? 0) - TRACE_DELAY;
  const t0 = nowE - TRACE_WIN;
  const X = (t) => padL + ((t - t0) / TRACE_WIN) * pw;

  // recessive grid: a log scale, so the 0.6 W standby hum and a 1500 W boil both read
  ctx.lineWidth = 1;
  ctx.font = `500 ${0.95 * r}px ${FONT}`;
  ctx.textBaseline = "bottom";
  ctx.textAlign = "left";
  for (const [w, lab] of [[0, ""], [10, "10 W"], [100, "100 W"], [1000, "1 kW"]]) {
    const y = Math.round(Y(w)) + 0.5;
    ctx.strokeStyle = rgba(C.steam, w ? 0.055 : 0.11);
    ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(padL + pw, y); ctx.stroke();
  }

  // segments (gaps where the plug went quiet or the house "lost power")
  const pts = edge.pts;
  const segs = [];
  let seg = null, headW = null, headX = null, headY = null;
  const i0 = Math.max(0, lowerBound(pts, t0 - 2) - 1);
  for (let i = i0; i < pts.length; i++) {
    const p = pts[i];
    if (p.t > nowE) {
      const pr = pts[i - 1];
      if (seg && pr && !p.off && !pr.off && p.t - pr.t < 4) {
        const f = (nowE - pr.t) / (p.t - pr.t);
        const wv = pr.w + (p.w - pr.w) * f;
        seg.push([X(nowE), Y(wv)]);
        headW = wv; headX = X(nowE); headY = Y(wv);
      }
      break;
    }
    const prev = pts[i - 1];
    if (p.off || !seg || (prev && p.t - prev.t > 4)) { seg = p.off ? null : []; if (seg) segs.push(seg); }
    if (!seg) continue;
    const x = X(p.t), y = Y(p.w);
    seg.push([x, y]);
    headW = p.w; headX = x; headY = y;
  }
  const stale = pts.length && nowE - pts[pts.length - 1].t > 6;
  const powerCut = Date.now() / 1000 < edge.outageUntil;
  if (stale || powerCut) headW = null;

  const hotY = Y(250);
  const fill = ctx.createLinearGradient(0, padT, 0, hotY + 4);
  fill.addColorStop(0, rgba(C.glow, 0.34));
  fill.addColorStop(1, rgba(C.glow, 0));
  const stroke = ctx.createLinearGradient(0, padT, 0, padT + ph);
  const fh = clamp((hotY - padT) / ph, 0, 1);
  stroke.addColorStop(0, C.glow); stroke.addColorStop(fh, C.glow);
  stroke.addColorStop(Math.min(1, fh + 0.06), C.steam); stroke.addColorStop(1, C.steam);
  const base = Y(0);
  for (const s of segs) {
    if (s.length < 2) continue;
    ctx.beginPath();
    ctx.moveTo(s[0][0], base);
    for (const [x, y] of s) ctx.lineTo(x, y);
    ctx.lineTo(s[s.length - 1][0], base);
    ctx.closePath();
    ctx.fillStyle = fill;
    ctx.fill();
  }
  const breathe = reduced ? 0.5 : 0.5 + 0.5 * Math.sin((ts / 1000) * ((2 * Math.PI) / 4.2));
  for (const pass of [0, 1]) {
    for (const s of segs) {
      if (s.length < 2) continue;
      ctx.beginPath();
      ctx.moveTo(s[0][0], s[0][1]);
      for (let i = 1; i < s.length; i++) ctx.lineTo(s[i][0], s[i][1]);
      ctx.lineJoin = "round"; ctx.lineCap = "round";
      if (pass === 0) { ctx.strokeStyle = stroke; ctx.globalAlpha = 0.05 + 0.07 * breathe; ctx.lineWidth = 7; }
      else { ctx.strokeStyle = stroke; ctx.globalAlpha = 1; ctx.lineWidth = 2.6; }
      ctx.stroke();
    }
  }
  ctx.globalAlpha = 1;
  ctx.save();
  ctx.globalCompositeOperation = "destination-out";
  const fade = ctx.createLinearGradient(padL, 0, padL + pw * 0.14, 0);
  fade.addColorStop(0, "rgba(0,0,0,1)"); fade.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = fade;
  ctx.fillRect(padL, padT - 2, pw * 0.14, ph + 4);
  ctx.restore();
  ctx.font = `500 ${1 * r}px ${FONT}`;
  ctx.textBaseline = "bottom";
  ctx.fillStyle = rgba(C.steam3, 0.85);
  for (const [w, lab] of [[10, "10 W"], [100, "100 W"], [1000, "1 kW"]]) ctx.fillText(lab, padL + 2, Math.round(Y(w)) - 3);

  // appliance tags from the edge detector (same timebase as the trace)
  ctx.font = `600 ${1 * r}px ${FONT}`;
  ctx.textBaseline = "alphabetic";
  let lastTagX = -1e9;
  for (const ev of edge.events) {
    const isOn = ev.kind === "on";
    const t = isOn ? (ev.t_on ?? ev.t) : ev.t;
    if (t < t0 || t > nowE) continue;
    const x = X(t);
    const name = NICE[ev.label] || ev.label;
    const txt = isOn ? `${name} on` : ev.label === "kettle" ? `boiled · ${Math.round(ev.duration_s || 0)} s` : `${name} off · ${Math.round(ev.duration_s || 0)} s`;
    if (x - lastTagX < 7 * r) continue;
    lastTagX = x;
    ctx.strokeStyle = rgba(C.glow, 0.45);
    ctx.beginPath(); ctx.moveTo(Math.round(x) + 0.5, padT - 0.55 * r); ctx.lineTo(Math.round(x) + 0.5, Y(1300)); ctx.stroke();
    ctx.fillStyle = isOn ? C.glow : C.steam2;
    ctx.textAlign = isOn ? "left" : "right";
    ctx.fillText(txt, x + (isOn ? 6 : -6), padT - 0.75 * r);
  }
  ctx.textAlign = "left";

  // steam rising off the boil
  const hot = headW != null && headW > 250;
  if (hot !== traceHot) { traceHot = hot; $("traceWrap").classList.toggle("hot", hot); }
  if (!reduced && headW != null && headW > 800 && headX != null) {
    steamAcc += dt * 16;
    while (steamAcc > 1) {
      steamAcc -= 1;
      steam.push({ x: headX - Math.random() * 3.5 * r, y: headY - 4, vx: (Math.random() - 0.5) * 10, vy: -(18 + Math.random() * 22), r: 0.35 * r + Math.random() * 0.4 * r, age: 0, life: 2.4 + Math.random() * 1.6, ph: Math.random() * 6.28 });
    }
  }
  for (let i = steam.length - 1; i >= 0; i--) {
    const s = steam[i];
    s.age += dt;
    if (s.age > s.life) { steam.splice(i, 1); continue; }
    s.x += (s.vx + Math.sin(s.age * 2.2 + s.ph) * 9) * dt;
    s.y += s.vy * dt;
    s.r += 0.75 * r * dt;
    const a = 0.13 * Math.min(1, s.age / 0.35) * (1 - s.age / s.life);
    const g = ctx.createRadialGradient(s.x, s.y, 0, s.x, s.y, s.r);
    g.addColorStop(0, `rgba(255,248,238,${a})`);
    g.addColorStop(1, "rgba(255,248,238,0)");
    ctx.fillStyle = g;
    ctx.beginPath(); ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2); ctx.fill();
  }

  // the living head + reading
  if (headW != null && headX != null) {
    const col = hot ? C.glow : C.steam;
    if (!reduced) {
      const phs = ((ts / 1000) % 1.7) / 1.7;
      ctx.beginPath(); ctx.arc(headX, headY, 5 + phs * 15, 0, Math.PI * 2);
      ctx.fillStyle = rgba(col, 0.3 * (1 - phs)); ctx.fill();
    }
    ctx.beginPath(); ctx.arc(headX, headY, 5, 0, Math.PI * 2);
    ctx.shadowColor = col; ctx.shadowBlur = 16; ctx.fillStyle = col; ctx.fill(); ctx.shadowBlur = 0;
    const lx = padL + pw + 1.4 * r;
    const big = clamp(ph * 0.42, 1.3 * r, 2.2 * r);
    const ly = clamp(headY, padT + big * 0.55, Math.max(padT + big * 0.55, padT + ph - big * 0.95));
    ctx.textBaseline = "middle";
    ctx.fillStyle = col;
    ctx.font = `650 ${big}px ${FONT}`;
    ctx.fillText(fmtW(headW), lx, ly);
    ctx.font = `500 ${1.05 * r}px ${FONT}`;
    ctx.fillStyle = C.steam3;
    const lastEv = edge.events[edge.events.length - 1];
    const label = headW < 20 ? "idle · standby" : lastEv && lastEv.kind === "on" ? `${NICE[lastEv.label] || lastEv.label} on` : "in use";
    ctx.fillText(label, lx, ly + 1.8 * r);
  }

  if (powerCut) {
    ctx.textBaseline = "middle";
    ctx.fillStyle = C.frost;
    ctx.font = `650 ${clamp(ph * 0.42, 1.3 * r, 2.2 * r)}px ${FONT}`;
    ctx.fillText("no power", padL + pw + 1.4 * r, clamp(Y(1), padT + r, padT + ph - r));
  }

  // honest notes
  const note = $("traceNote");
  let msg = null, cls = "";
  if (Date.now() / 1000 < edge.outageUntil) { msg = `Simulated power cut · ${hero()?.person || "Margaret"}'s Kettle is dark for ${Math.ceil(edge.outageUntil - Date.now() / 1000)} s`; cls = "cold"; }
  else if (!edge.ok) msg = "Kitchen link offline · waiting for the hub";
  else if (stale || !pts.length) msg = "Waiting for readings from the plug…";
  if (note.dataset.msg !== (msg || "")) {
    note.dataset.msg = msg || "";
    note.hidden = !msg;
    note.textContent = msg || "";
    note.className = `trace-note ${cls}`;
  }
}

// ---------------------------------------------------------------- day ribbon (demo time)
function dedupeEvents(evs) {
  const out = [];
  for (const ev of evs) {
    if (ev.min == null || ev.human === false || ev.label === "furnace_blower") continue;
    const prev = out.findLast?.((x) => x.label === ev.label) ?? [...out].reverse().find((x) => x.label === ev.label);
    if (prev && Math.abs(ev.min - prev.min) < 4) continue;
    out.push(ev);
  }
  return out;
}
const AMP = { kettle: 1, microwave: 0.8, toaster: 0.75, cooking: 0.75, tv: 0.55, activity: 0.6 };
function laneX(W, d0, d1) {
  const a = LANE_L * REM, b = W - LANE_R * REM;
  return (mm) => a + ((mm - d0) / (d1 - d0)) * (b - a);
}
function timelineMins() {
  return (S?.grid?.timeline || []).map((x, i) => ({ ...x, min: minOfDayIso(x.t + ":00"), fired: (S.grid.fired || []).includes(i) }));
}
function drawRibbon(ts) {
  const { ctx, w: W, h: H } = canv.ribbon;
  if (!W || !H) return;
  ctx.clearRect(0, 0, W, H);
  const m = hero();
  if (!m) return;
  const r = REM;
  const [d0, d1] = dayDomain();
  const X = laneX(W, d0, d1);
  const xL = LANE_L * r, xR = W - LANE_R * r;
  const top = 1.9 * r, bot = H - 1.75 * r;
  const b = m.baseline || {};
  const now = nowMin();
  const e = m.escalation;
  const missed = !!(e && e.step !== "resolved" && e.reason === "morning");
  const breathe = reduced ? 0.6 : 0.5 + 0.5 * Math.sin((ts / 1000) * ((2 * Math.PI) / 4.5));

  // hour grid + labels
  const span = d1 - d0;
  const stepH = span <= 12 * 60 ? 120 : 180;
  ctx.font = `500 ${1 * r}px ${FONT}`;
  ctx.textBaseline = "alphabetic";
  ctx.textAlign = "center";
  for (let mm = Math.ceil(d0 / stepH) * stepH; mm <= d1; mm += stepH) {
    const x = Math.round(X(mm)) + 0.5;
    ctx.strokeStyle = rgba(C.steam, 0.05); ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, bot); ctx.stroke();
    ctx.fillStyle = C.steam3;
    ctx.fillText(fmtMin(mm), clamp(x, xL + 1.2 * r, xR - 1.2 * r), H - 0.2 * r);
  }

  // rhythm band: usual ± spread, feathered, clamped to the axis
  ctx.textBaseline = "alphabetic";
  if (b.learned && b.usual_min != null) {
    const u = b.usual_min, s = Math.max(10, b.spread_min || 0);
    const xa = X(u - 2 * s), xb = X(u + 2 * s);
    const ca = Math.max(xL, xa), cb = Math.min(xR, xb);
    if (cb > ca) {
      const col = missed ? C.glow : C.steam;
      const a = missed ? 0.2 + 0.18 * breathe : 0.09;
      const g = ctx.createLinearGradient(xa, 0, xb, 0);
      g.addColorStop(0, rgba(col, 0)); g.addColorStop(0.25, rgba(col, a * 0.8)); g.addColorStop(0.5, rgba(col, a));
      g.addColorStop(0.75, rgba(col, a * 0.8)); g.addColorStop(1, rgba(col, 0));
      if (missed) { ctx.shadowColor = rgba(C.glow, 0.5 * breathe); ctx.shadowBlur = 24; }
      ctx.fillStyle = g;
      ctx.beginPath(); ctx.roundRect(ca, top, cb - ca, bot - top, 12); ctx.fill();
      ctx.shadowBlur = 0;
      const ux = X(u);
      if (ux > xL && ux < xR) {
        ctx.strokeStyle = rgba(col, missed ? 0.5 : 0.22); ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(Math.round(ux) + 0.5, top + 4); ctx.lineTo(Math.round(ux) + 0.5, bot - 4); ctx.stroke();
        ctx.font = `600 ${1.02 * r}px ${FONT}`;
        ctx.fillStyle = missed ? C.glow : C.steam2;
        ctx.textAlign = "center";
        const lab = `usually ${b.usual} ± ${b.spread} min`;
        const tw = ctx.measureText(lab).width;
        ctx.fillText(lab, clamp(ux, xL + tw / 2, xR - tw / 2), top - 0.55 * r);
      }
    }
  }

  // previous mornings: first activity on each learned day
  const hy = bot - 0.55 * r;
  for (const hm of b.history || []) {
    if (hm < d0 || hm > d1) continue;
    ctx.beginPath(); ctx.arc(X(hm), hy, 4, 0, Math.PI * 2);
    ctx.fillStyle = rgba(C.steam2, 0.5); ctx.fill();
  }

  // deadline
  if (b.deadline_min != null && b.deadline_min >= d0 && b.deadline_min <= d1) {
    const dx = Math.round(X(b.deadline_min)) + 0.5;
    const passed = now >= b.deadline_min;
    const col = missed ? C.glow : passed ? C.steam2 : C.steam3;
    ctx.strokeStyle = rgba(col, missed ? 0.95 : 0.7); ctx.lineWidth = missed ? 2 : 1.5;
    ctx.beginPath(); ctx.moveTo(dx, top - 0.2 * r); ctx.lineTo(dx, bot); ctx.stroke();
    ctx.font = `600 ${1.02 * r}px ${FONT}`;
    ctx.fillStyle = col;
    const lab = `Kettle asks · ${b.deadline}${b.policy === "cold" ? " (cold mode)" : !b.learned ? " (learning)" : ""}`;
    const tw = ctx.measureText(lab).width;
    const right = dx + 6 + tw < xR;
    ctx.textAlign = right ? "left" : "right";
    ctx.fillText(lab, right ? dx + 6 : dx - 6, top - 0.55 * r);
  }

  // replay timeline markers
  if (isReplay()) {
    for (const it of timelineMins()) {
      if (it.min < d0 || it.min > d1) continue;
      const x = Math.round(X(it.min)) + 0.5;
      ctx.strokeStyle = rgba(C.glow, it.fired ? 0.4 : 0.14); ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, H); ctx.stroke();
    }
  }

  // the living line: flat when nothing happens, a soft rise for each appliance event
  const evs = dedupeEvents(m.events || []);
  const y0 = top + (bot - top) * 0.64;
  const amp = (bot - top) * 0.46;
  const sig = Math.max(3.5, span / 150);
  const lift = (mm) => {
    let s = 0;
    for (const ev of evs) {
      if (ev.min > now + 0.01) continue;
      const d = (mm - ev.min) / sig;
      if (d > -4 && d < 4) s += (AMP[ev.label] ?? 0.6) * Math.exp(-0.5 * d * d);
    }
    return Math.min(s, 1.15) * amp;
  };
  const xNow = clamp(X(now), xL, xR);
  // future: a faint guide
  ctx.strokeStyle = rgba(C.steam, 0.1); ctx.lineWidth = 1.5;
  ctx.beginPath(); ctx.moveTo(xNow, y0); ctx.lineTo(xR, y0); ctx.stroke();
  // past
  const path = new Path2D();
  const toMin = (x) => d0 + ((x - xL) / (xR - xL)) * span;
  path.moveTo(xL, y0 - lift(d0));
  for (let x = xL + 2; x < xNow; x += 2) path.lineTo(x, y0 - lift(toMin(x)));
  path.lineTo(xNow, y0 - lift(now));
  ctx.lineJoin = "round"; ctx.lineCap = "round";
  ctx.strokeStyle = rgba(C.steam, 0.1 + 0.1 * breathe); ctx.lineWidth = 8; ctx.stroke(path);
  ctx.strokeStyle = C.steam; ctx.lineWidth = 2.4; ctx.stroke(path);
  if (missed && b.usual_min != null) {
    // the flat stretch since she'd usually be up glows amber
    const xa = clamp(X(b.usual_min), xL, xNow);
    ctx.save();
    ctx.beginPath(); ctx.rect(xa, 0, xNow - xa + 4, H); ctx.clip();
    ctx.shadowColor = C.glow; ctx.shadowBlur = 10 + 8 * breathe;
    ctx.strokeStyle = C.glow; ctx.lineWidth = 2.6; ctx.stroke(path);
    ctx.restore();
  }
  // event labels
  ctx.font = `600 ${1 * r}px ${FONT}`;
  ctx.textAlign = "left";
  ctx.textBaseline = "middle";
  let lastEnd = -1e9;
  const firstMin = m.first_today?.min;
  for (const ev of evs) {
    if (ev.min < d0 || ev.min > Math.min(d1, now)) continue;
    const x = X(ev.min);
    const lab = `${NICE[ev.label] || ev.label} ${ev.hhmm}`;
    const tw = ctx.measureText(lab).width;
    const lx = x + 0.7 * r;
    if (lx < lastEnd + 0.6 * r || lx + tw > xR) continue;
    lastEnd = lx + tw;
    const isFirst = firstMin != null && Math.abs(ev.min - firstMin) < 0.5;
    ctx.fillStyle = isFirst ? C.steam : C.steam3;
    ctx.fillText(lab, lx, y0 - lift(ev.min) + 0.1 * r);
  }
  ctx.textBaseline = "alphabetic";
  // now cursor
  if (now >= d0 && now <= d1) {
    const xc = Math.round(xNow) + 0.5;
    ctx.strokeStyle = rgba(C.steam, 0.35); ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(xc, top - 0.2 * r); ctx.lineTo(xc, bot); ctx.stroke();
    const yc = y0 - lift(now);
    const col = missed ? C.glow : C.steam;
    if (!reduced) {
      const phs = ((ts / 1000) % 2.2) / 2.2;
      ctx.beginPath(); ctx.arc(xNow, yc, 5 + phs * 13, 0, Math.PI * 2);
      ctx.fillStyle = rgba(col, 0.28 * (1 - phs)); ctx.fill();
    }
    ctx.beginPath(); ctx.arc(xNow, yc, 5, 0, Math.PI * 2);
    ctx.shadowColor = col; ctx.shadowBlur = 12; ctx.fillStyle = col; ctx.fill(); ctx.shadowBlur = 0;
  }
  ctx.textAlign = "left";
}

// ---------------------------------------------------------------- Jan 13 2024 replay charts (small multiples, one axis each)
function shortLabel(text) {
  if (/EEA3/.test(text)) return "Grid Alert (EEA3)";
  if (/emergency text alert/i.test(text)) return "Emergency alert";
  if (/drops/i.test(text)) { const mw = text.match(/~?\d[\d,]*\s?MW/g); return mw ? `${mw[mw.length - 1]} drop` : "Demand drops"; }
  if (/ended/i.test(text)) return "Grid Alert ended";
  return text.split(/[.:]/)[0].slice(0, 34);
}
function drawReplay() {
  if (!isReplay()) return;
  const { ctx, w: W, h: H } = canv.replay;
  if (!W || !H) return;
  ctx.clearRect(0, 0, W, H);
  const g = S.grid, r = REM;
  const [d0, d1] = dayDomain();
  const X = laneX(W, d0, d1);
  const xL = LANE_L * r, xR = W - LANE_R * r;
  const now = nowMin();
  const toMin = (t) => (t - sMidnight) / 60;
  const hourly = g.series?.hourly || [], temps = g.series?.temp || [];
  const rows = [
    { title: "Pool price", unit: "$/MWh · AESO", col: C.glow, step: true, data: hourly.map((p) => [toMin(p.t), p.price]),
      dom: [0, 1100], grid: [0, 1000], gfmt: (v) => `$${fmtInt(v)}`, fmt: (v) => `$${v.toFixed(2)}`,
      ref: g.facts?.price_cap != null ? { v: g.facts.price_cap, lab: `price cap $${g.facts.price_cap}` } : null },
    { title: "Alberta Internal Load", unit: "MW · AESO", col: C.steam, step: true, data: hourly.map((p) => [toMin(p.t), p.ail]),
      dom: null, gfmt: (v) => fmtInt(v), fmt: (v) => `${fmtInt(v)} MW` },
    { title: "Calgary temperature", unit: "°C · ECCC", col: C.frost, step: false, data: temps.map((p) => [toMin(p.t), p.c]),
      dom: null, gfmt: (v) => minus(String(v)), fmt: fmtTemp,
      ref: S.cold?.threshold_c != null ? { v: S.cold.threshold_c, lab: `cold mode at ${minus(String(S.cold.threshold_c))} °C` } : null },
  ];
  // y domains from the data on screen
  for (const row of rows) {
    if (row.dom) continue;
    const vs = row.data.filter(([mm]) => mm >= d0 - 60 && mm <= d1).map((d) => d[1]).filter((v) => v != null);
    if (row.ref) vs.push(row.ref.v);
    if (!vs.length) { row.dom = [0, 1]; row.grid = []; continue; }
    const lo = Math.min(...vs), hi = Math.max(...vs);
    const stepv = row.title.startsWith("Alberta") ? 500 : 5;
    row.dom = [Math.floor(lo / stepv) * stepv, Math.ceil(hi / stepv) * stepv];
    if (row.dom[1] - row.dom[0] < stepv) row.dom[1] += stepv;
    row.grid = [row.dom[0], row.dom[1]];
  }

  const markH = 2.6 * r;
  const rowGap = 0.5 * r;
  const rowH = (H - markH - rowGap * 2) / 3;
  const tl = timelineMins();

  // timeline labels (two levels so 18:44 and 18:46 don't collide)
  ctx.font = `600 ${1 * r}px ${FONT}`;
  ctx.textBaseline = "alphabetic";
  const levelsEnd = [-1e9, -1e9];
  const groups = [];
  for (const it of tl) {
    if (it.min < d0 || it.min > d1) continue;
    const g = groups[groups.length - 1];
    if (g && it.min - g[g.length - 1].min < 10) g.push(it); else groups.push([it]);
  }
  for (const g of groups) {
    const x = X(g[0].min);
    const lab = g.map((it) => `${it.t.slice(11, 16)} ${shortLabel(it.text)}`).join("  ·  ");
    const tw = ctx.measureText(lab).width;
    const anchorRight = x + 6 + tw > xR;
    const lx = anchorRight ? x - tw - 6 : x + 6;
    const lvl = levelsEnd[0] < lx - 8 ? 0 : levelsEnd[1] < lx - 8 ? 1 : (levelsEnd[0] < levelsEnd[1] ? 0 : 1);
    levelsEnd[lvl] = lx + tw;
    ctx.fillStyle = g.some((it) => it.fired) ? C.glow : rgba(C.steam3, 0.75);
    ctx.textAlign = "left";
    ctx.fillText(lab, lx, (lvl === 0 ? 1.05 : 2.25) * r);
  }

  rows.forEach((row, i) => {
    const y0 = markH + i * (rowH + rowGap);
    const pt = y0 + 1.5 * r, pb = y0 + rowH - 0.2 * r;
    const Y = (v) => pb - ((v - row.dom[0]) / (row.dom[1] - row.dom[0])) * (pb - pt);
    // title + unit
    ctx.textAlign = "left";
    ctx.font = `600 ${1.02 * r}px ${FONT}`;
    ctx.fillStyle = C.steam2;
    ctx.fillText(row.title, xL, y0 + 1 * r);
    const tw = ctx.measureText(row.title).width;
    ctx.font = `500 ${1 * r}px ${FONT}`;
    ctx.fillStyle = C.steam3;
    ctx.fillText(` ${row.unit}`, xL + tw, y0 + 1 * r);
    // grid
    ctx.lineWidth = 1;
    for (const gv of row.grid || []) {
      const y = Math.round(Y(gv)) + 0.5;
      ctx.strokeStyle = rgba(C.steam, 0.06);
      ctx.beginPath(); ctx.moveTo(xL, y); ctx.lineTo(xR, y); ctx.stroke();
      ctx.font = `500 ${1 * r}px ${FONT}`;
      ctx.textAlign = "right";
      const gl = row.gfmt(gv), gw = ctx.measureText(gl).width;
      ctx.fillStyle = rgba(C.night, 0.85);
      ctx.fillRect(xR - gw - 6, y - 1.05 * r, gw + 6, 1.05 * r);
      ctx.fillStyle = rgba(C.steam3, 0.9);
      ctx.fillText(gl, xR - 2, y - 3);
    }
    if (row.ref) {
      const y = Math.round(Y(row.ref.v)) + 0.5;
      ctx.strokeStyle = rgba(row.col, 0.35);
      ctx.beginPath(); ctx.moveTo(xL, y); ctx.lineTo(xR, y); ctx.stroke();
    }
    // series: whole day faint, revealed up to the clock
    const pts = [];
    for (let k = 0; k < row.data.length; k++) {
      const [mm, v] = row.data[k];
      if (v == null) continue;
      pts.push([mm, v]);
      if (row.step) pts.push([mm + 60, v]);
    }
    const draw = (upto, alpha, width, area) => {
      const p = new Path2D();
      let started = false, lastX = 0, firstX = 0;
      for (const [mm, v] of pts) {
        if (mm < d0 - 60) continue;
        const cm = Math.min(mm, upto);
        if (cm < d0 - 0.5) continue;
        const x = X(clamp(cm, d0, d1)), y = Y(v);
        if (!started) { p.moveTo(x, y); started = true; firstX = x; } else p.lineTo(x, y);
        lastX = x;
        if (mm >= upto || mm >= d1) break;
      }
      if (!started) return;
      if (area) {
        const a = new Path2D(p);
        a.lineTo(lastX, pb); a.lineTo(firstX, pb); a.closePath();
        ctx.fillStyle = rgba(row.col, 0.1);
        ctx.fill(a);
      }
      ctx.strokeStyle = rgba(row.col, alpha); ctx.lineWidth = width; ctx.lineJoin = "round";
      ctx.stroke(p);
    };
    draw(d1, 0.22, 1.5, false);
    draw(now, 1, 2.2, true);
    // current value, direct-labelled at the cursor
    let cur = null;
    for (const [mm, v] of row.data) if (mm <= now && v != null) cur = v;
    if (cur != null && now >= d0 && now <= d1) {
      const x = X(now), y = Y(cur);
      ctx.beginPath(); ctx.arc(x, y, 4.5, 0, Math.PI * 2);
      ctx.fillStyle = row.col; ctx.fill();
      ctx.lineWidth = 2; ctx.strokeStyle = C.night; ctx.stroke();
      ctx.font = `650 ${1.25 * r}px ${FONT}`;
      ctx.fillStyle = C.steam;
      const lab = row.fmt(cur) + (row.ref && row.title === "Pool price" && Math.abs(cur - row.ref.v) < 0.01 ? " · at the cap" : "");
      const w = ctx.measureText(lab).width;
      const right = x + 10 + w < xR - 4 * r;
      ctx.textAlign = right ? "left" : "right";
      ctx.textBaseline = "middle";
      ctx.fillText(lab, right ? x + 10 : x - 10, clamp(y - 0.9 * r, pt + 0.4 * r, pb - 0.4 * r));
      ctx.textBaseline = "alphabetic";
    }
  });

  // timeline verticals + the clock cursor through all rows
  for (const it of tl) {
    if (it.min < d0 || it.min > d1) continue;
    const x = Math.round(X(it.min)) + 0.5;
    ctx.strokeStyle = rgba(C.glow, it.fired ? 0.5 : 0.16); ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke();
  }
  if (now >= d0 && now <= d1) {
    const x = Math.round(X(now)) + 0.5;
    ctx.strokeStyle = rgba(C.steam, 0.45); ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(x, markH - 0.2 * r); ctx.lineTo(x, H); ctx.stroke();
  }
  ctx.textAlign = "left";
}

// ============================================================== map (inline SVG, stylised Calgary)
const map = (() => {
  const svg = $("map");
  const NS = "http://www.w3.org/2000/svg";
  const mk = (tag, attrs = {}, parent) => {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  };
  // Rough Calgary geography in the backend's ~1000x600 space (north up).
  const GEO = {
    bow: [[-30, 164], [60, 176], [130, 190], [200, 206], [255, 226], [300, 240], [345, 262], [385, 292], [420, 322], [455, 344], [500, 356], [548, 362], [600, 368], [645, 384], [690, 394], [722, 414], [740, 452], [750, 500], [762, 552], [786, 630]],
    elbow: [[110, 630], [200, 594], [262, 576], [318, 568], [372, 552], [418, 524], [452, 502], [486, 486], [524, 474], [562, 463], [596, 443], [618, 419], [636, 399], [647, 386]],
    park: [[352, 96], [410, 64], [480, 72], [516, 112], [498, 158], [430, 172], [370, 154]],
    roads: [
      [[706, -10], [700, 120], [688, 250], [668, 338], [664, 388], [714, 432], [746, 520], [772, 620]],
      [[1010, 262], [820, 262], [620, 266], [470, 268], [390, 244], [300, 196], [190, 156], [70, 132], [-10, 122]],
      [[240, -10], [300, 120], [362, 240], [404, 330], [416, 420], [392, 520], [356, 620]],
      [[-10, 524], [180, 528], [290, 546], [440, 540], [620, 546], [820, 540], [1010, 536]],
    ],
    downtown: [462, 380, 598, 430],
  };
  const FISHEYE = 2.9;
  let lens = (x, y) => [x, y];
  let focusKey = "";
  let L = {};
  const homeEls = new Map(), memberEls = new Map();
  const threads = [];
  let lastMini = 0;

  function makeLens(cx, cy) {
    return (x, y) => {
      const dx = x - cx, dy = y - cy, rr = Math.hypot(dx, dy);
      if (rr < 1e-6) return [x, y];
      const ux = dx / rr, uy = dy / rr;
      const tx = ux > 0 ? (1000 - cx) / ux : ux < 0 ? -cx / ux : Infinity;
      const ty = uy > 0 ? (600 - cy) / uy : uy < 0 ? -cy / uy : Infinity;
      const R = Math.max(1, Math.min(tx, ty));
      const q = rr / R;
      const f = (R * (FISHEYE + 1) * q) / (FISHEYE * q + 1);
      return [cx + ux * f, cy + uy * f];
    };
  }
  /** Lens + keep a glyph fully inside the frame (labels need room). */
  function place(x, y) {
    const [a, b] = lens(x, y);
    return [clamp(a, 40, 960), clamp(b, 46, 528)];
  }
  function catmull(pts, n = 8) {
    const out = [];
    for (let i = 0; i < pts.length - 1; i++) {
      const p0 = pts[Math.max(0, i - 1)], p1 = pts[i], p2 = pts[i + 1], p3 = pts[Math.min(pts.length - 1, i + 2)];
      for (let k = 0; k < n; k++) {
        const t = k / n, t2 = t * t, t3 = t2 * t;
        out.push([0, 1].map((j) => 0.5 * (2 * p1[j] + (-p0[j] + p2[j]) * t + (2 * p0[j] - 5 * p1[j] + 4 * p2[j] - p3[j]) * t2 + (-p0[j] + 3 * p1[j] - 3 * p2[j] + p3[j]) * t3)));
      }
    }
    out.push(pts[pts.length - 1]);
    return out;
  }
  const dPath = (pts, close) => pts.map(([x, y], i) => `${i ? "L" : "M"}${(+x).toFixed(1)} ${(+y).toFixed(1)}`).join("") + (close ? "Z" : "");
  const lensPts = (pts) => pts.map(([x, y]) => lens(x, y));

  function buildBase(focus) {
    svg.replaceChildren();
    lens = makeLens(focus.x, focus.y);
    const defs = mk("defs", {}, svg);
    defs.innerHTML = `
      <filter id="blur6" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="6"/></filter>
      <filter id="blur3" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="3"/></filter>
      <radialGradient id="homeGlow"><stop offset="0" stop-color="${C.glow}" stop-opacity=".55"/><stop offset=".45" stop-color="${C.glow}" stop-opacity=".16"/><stop offset="1" stop-color="${C.glow}" stop-opacity="0"/></radialGradient>
      <radialGradient id="okGlow"><stop offset="0" stop-color="${C.ok}" stop-opacity=".3"/><stop offset="1" stop-color="${C.ok}" stop-opacity="0"/></radialGradient>
      <radialGradient id="coldGlow"><stop offset="0" stop-color="${C.frost}" stop-opacity=".4"/><stop offset="1" stop-color="${C.frost}" stop-opacity="0"/></radialGradient>`;
    L = {};
    for (const k of ["ground", "water", "labels", "ties", "threads", "homes", "members", "fx"]) L[k] = mk("g", { class: `layer-${k}` }, svg);
    // ground: park + roads + downtown
    mk("path", { d: dPath(lensPts(catmull([...GEO.park, GEO.park[0]], 6)), true), class: "land-park" }, L.ground);
    for (const rd of GEO.roads) mk("path", { d: dPath(lensPts(catmull(rd, 10))), class: "road" }, L.ground);
    let seed = 11;
    const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
    const [dx0, dy0, dx1, dy1] = GEO.downtown;
    for (let i = 0; i < 26; i++) {
      const cx = dx0 + ((i % 9) + 0.5 + (rnd() - 0.5) * 0.5) * ((dx1 - dx0) / 9), cy = dy0 + (Math.floor(i / 9) + 0.5 + (rnd() - 0.5) * 0.4) * ((dy1 - dy0) / 3);
      const s = 2.2 + rnd() * 3.2, s2 = 2.2 + rnd() * 3.2;
      const corners = [[cx - s, cy - s2], [cx + s, cy - s2], [cx + s, cy + s2], [cx - s, cy + s2]].map(([x, y]) => lens(x, y));
      mk("path", { d: dPath(corners, true), class: `tower${rnd() > 0.72 ? " lit" : ""}` }, L.ground);
    }
    // water
    const bow = lensPts(catmull(GEO.bow, 10)), elbow = lensPts(catmull(GEO.elbow, 10));
    mk("path", { d: dPath(bow), class: "river", "stroke-width": 11 }, L.water);
    mk("path", { d: dPath(elbow), class: "river", "stroke-width": 7.5 }, L.water);
    const res = [];
    for (let a = 0; a < Math.PI * 2; a += Math.PI / 18) res.push([306 + Math.cos(a) * 46 - Math.sin(a) * 6, 568 + Math.sin(a) * 17 + Math.cos(a) * 6]);
    mk("path", { d: dPath(lensPts(res), true), class: "lake" }, L.water);
    mk("path", { d: dPath(bow), class: "river-sheen" }, L.water);
    mk("path", { d: dPath(elbow), class: "river-sheen" }, L.water);
    // geography labels
    const geo = (txt, x, y, cls = "geo", anchor = "middle") => {
      const [lx, ly] = lens(x, y);
      const t = mk("text", { x: lx.toFixed(1), y: ly.toFixed(1), class: cls, "text-anchor": anchor }, L.labels);
      t.textContent = txt;
      return t;
    };
    const onPath = (pts, tx, dy, txt) => {
      let best = pts[0];
      for (const p of pts) if (Math.abs(p[0] - tx) < Math.abs(best[0] - tx)) best = p;
      const t = mk("text", { x: best[0].toFixed(1), y: (best[1] + dy).toFixed(1), class: "geo water", "text-anchor": "middle" }, L.labels);
      t.textContent = txt;
    };
    onPath(bow, 70, 30, "Bow River");
    onPath(elbow, 120, -14, "Elbow River");
    geo("Downtown", 530, 448);
    // neighbourhoods (the spots the cloud places homes at), labelled just above each spot
    const AREAS = [["Bowness", 300, 210], ["Inglewood", 690, 420], ["Killarney", 420, 470], ["Renfrew", 760, 200], ["Wildwood", 230, 380], ["Ramsay", 620, 520]];
    const taken = new Set();
    for (const hm of S.homes || []) {
      if (hm.id === focusHome()?.id || !hm.area) continue;
      taken.add(hm.area);
      AREAS.push([hm.area, hm.pos.x, hm.pos.y]);
    }
    const seenArea = new Set();
    for (const [name, ax, ay] of AREAS.reverse()) {
      if (seenArea.has(name) || name === focusHome()?.area) continue;
      seenArea.add(name);
      const [hx, hy] = place(ax, ay);
      const t = mk("text", { x: hx.toFixed(1), y: (hy - 32).toFixed(1), class: "geo", "text-anchor": "middle" }, L.labels);
      t.textContent = name;
    }
  }
  const focusHome = () => hero();

  function memberPos(m) {
    // invite-joined members all start at the same spot: fan them out around it, deterministically
    const same = (S.members || []).filter((o) => o.pos.x === m.pos.x && o.pos.y === m.pos.y);
    const i = same.findIndex((o) => o.id === m.id);
    if (i <= 0) return place(m.pos.x, m.pos.y);
    const a = -Math.PI / 2 - i * 0.9;
    return place(m.pos.x + Math.cos(a) * 16, m.pos.y + Math.sin(a) * 16);
  }
  function homeTone(hm) {
    const e = hm.escalation;
    if (hm.device?.dark) return "dark";
    if (e && e.step !== "resolved") return e.reason === "morning" ? "alert" : "cold";
    if (hm.status === "ok") return "ok";
    return "wait";
  }
  const TONE = { ok: C.ok, alert: C.glow, cold: C.frost, dark: C.dark, wait: C.steam3 };

  function ensureHome(hm) {
    let o = homeEls.get(hm.id);
    if (o) return o;
    const big = hm.kind === "live";
    const s = big ? 1.75 : 1.05;
    const g = mk("g", { class: `home ${hm.kind}` }, L.homes);
    const halo = mk("circle", { r: big ? 46 : 26, fill: "url(#homeGlow)", class: "status-halo" }, g);
    const body = mk("path", { d: `M${-11 * s} ${9 * s}V${-3 * s}L0 ${-13 * s}L${11 * s} ${-3 * s}V${9 * s}Z`, class: "house-body", fill: "#2c2017" }, g);
    const win = mk("rect", { x: -3.6 * s, y: -1 * s, width: 7.2 * s, height: 6.2 * s, rx: 1.2, class: "house-window" }, g);
    const label = mk("text", { class: "home-label" }, g);
    const sub = mk("text", { class: "home-sub" }, g);
    const miniRest = mk("path", { class: "mini-rest" }, g);
    const mini = mk("path", { class: "mini" }, g);
    o = { g, halo, body, win, label, sub, mini, miniRest, big, s };
    homeEls.set(hm.id, o);
    return o;
  }
  function updateHomes() {
    const seen = new Set();
    for (const hm of S.homes || []) {
      seen.add(hm.id);
      const o = ensureHome(hm);
      const [x, y] = place(hm.pos.x, hm.pos.y);
      o.x = x; o.y = y;
      o.g.setAttribute("transform", `translate(${x.toFixed(1)} ${y.toFixed(1)})`);
      const tone = homeTone(hm);
      const col = TONE[tone];
      const lit = hm.kind === "replay" || (hm.device?.online && !hm.device?.dark);
      const glow = !!hm.glow;
      o.body.setAttribute("stroke", col);
      o.body.setAttribute("fill", tone === "dark" ? "#0e0a07" : "#2c2017");
      o.win.setAttribute("fill", lit ? (glow ? "#ffd59a" : C.glow) : "#3a2e25");
      o.win.setAttribute("opacity", lit ? (tone === "wait" && hm.kind === "replay" ? 0.55 : 1) : 1);
      o.halo.setAttribute("fill", tone === "cold" || tone === "dark" ? "url(#coldGlow)" : tone === "ok" && !glow && hm.kind === "replay" ? "url(#okGlow)" : "url(#homeGlow)");
      o.halo.setAttribute("opacity", tone === "dark" ? 0 : glow ? 1 : hm.kind === "live" ? (tone === "alert" ? 0.9 : 0.6) : tone === "ok" ? 0.7 : 0.25);
      o.halo.setAttribute("r", (o.big ? 46 : 26) * (glow ? 1.8 : 1));
      o.halo.classList.toggle("alert", tone === "alert" || tone === "cold");
      if (o.big) {
        o.label.setAttribute("x", 0); o.label.setAttribute("y", 50); o.label.setAttribute("text-anchor", "middle");
        o.sub.setAttribute("x", 0); o.sub.setAttribute("y", 73); o.sub.setAttribute("text-anchor", "middle");
        o.label.textContent = hm.person;
        o.sub.textContent = hm.device?.dark ? `${hm.area} · Kettle dark` : !hm.device?.online ? `${hm.area} · offline` : hm.area;
      } else {
        o.label.setAttribute("x", 0); o.label.setAttribute("y", 36); o.label.setAttribute("text-anchor", "middle");
        o.label.textContent = hm.kind === "replay" ? `REFIT House ${String(hm.id).replace(/\D/g, "") || ""}` : hm.person;
        o.sub.textContent = "";
      }
      o.mini.setAttribute("stroke", col === C.steam3 ? C.steam2 : col);
      o.hm = hm;
    }
    for (const [id, o] of homeEls) if (!seen.has(id)) { o.g.remove(); homeEls.delete(id); }
  }
  function updateMinis() {
    const [d0, d1] = dayDomain();
    const now = nowMin();
    for (const o of homeEls.values()) {
      const hm = o.hm;
      if (!hm) continue;
      const w = o.big ? 112 : 74, hgt = o.big ? 16 : 11;
      const x0 = -w / 2, yb = o.big ? 96 : 54;
      const evs = dedupeEvents(hm.events || []);
      const sig = (d1 - d0) / 90;
      const pts = [];
      const xNow = x0 + clamp((now - d0) / (d1 - d0), 0, 1) * w;
      for (let x = x0; x <= xNow + 0.01; x += 1.5) {
        const mm = d0 + ((x - x0) / w) * (d1 - d0);
        let s = 0;
        for (const ev of evs) { if (ev.min > now) continue; const d = (mm - ev.min) / sig; if (d > -4 && d < 4) s += (AMP[ev.label] ?? 0.6) * Math.exp(-0.5 * d * d); }
        pts.push([x, yb - Math.min(s, 1.1) * hgt]);
      }
      if (pts.length > 1) o.mini.setAttribute("d", dPath(pts)); else o.mini.removeAttribute("d");
      o.miniRest.setAttribute("d", `M${xNow.toFixed(1)} ${yb}H${x0 + w}`);
    }
  }
  function updateMembers() {
    const fh = focusHome();
    if (!fh) return;
    const [hx, hy] = place(fh.pos.x, fh.pos.y);
    const e = fh.escalation;
    const activeAsk = e && e.step !== "resolved" ? new Set(e.asked || []) : new Set();
    const going = e && e.step === "neighbour_going" ? e.responder : null;
    const seen = new Set();
    for (const m of S.members || []) {
      seen.add(m.id);
      let o = memberEls.get(m.id);
      if (!o) {
        const tie = mk("path", { class: "tie" }, L.ties);
        const g = mk("g", { class: "member" }, L.members);
        const ring = mk("circle", { r: 15, class: "ask-ring" }, g);
        const disc = mk("circle", { r: 15, class: "member-disc" }, g);
        const letter = mk("text", { class: "member-letter" }, g);
        const name = mk("text", { class: "member-name", x: 22, y: 1, "text-anchor": "start", "dominant-baseline": "central" }, g);
        const online = mk("circle", { r: 4.5, cx: 11, cy: -11, fill: C.ok, stroke: "#18110b", "stroke-width": 2 }, g);
        o = { tie, g, ring, disc, letter, name, online };
        memberEls.set(m.id, o);
      }
      const [x, y] = memberPos(m);
      o.x = x; o.y = y;
      o.g.setAttribute("transform", `translate(${x.toFixed(1)} ${y.toFixed(1)})`);
      o.letter.textContent = m.avatar || m.name[0];
      const far = m.role === "family" && m.relation && /in\s/i.test(m.relation) ? ` · ${m.relation.split(",").pop().trim()}` : "";
      o.name.textContent = m.name + far;
      const leftSide = m.pos.x < fh.pos.x && x > 160;
      o.name.setAttribute("x", leftSide ? -22 : 22);
      o.name.setAttribute("text-anchor", leftSide ? "end" : "start");
      o.disc.setAttribute("stroke", m.role === "family" ? C.glow : C.steam2);
      o.online.setAttribute("opacity", m.online ? 1 : 0);
      const asked = activeAsk.has(m.id);
      o.ring.style.display = asked && going !== m.id ? "" : "none";
      o.ring.setAttribute("stroke", e && e.reason !== "morning" ? C.frost : C.glow);
      // a soft tie from each circle member to the home they look after
      const mx = (x + hx) / 2, my = (y + hy) / 2, ddx = hx - x, ddy = hy - y, len = Math.hypot(ddx, ddy) || 1;
      const bend = Math.min(40, len * 0.18);
      o.tie.setAttribute("d", `M${x.toFixed(1)} ${y.toFixed(1)}Q${(mx - (ddy / len) * bend).toFixed(1)} ${(my + (ddx / len) * bend).toFixed(1)} ${hx.toFixed(1)} ${hy.toFixed(1)}`);
      o.tie.classList.toggle("asked", asked);
    }
    for (const [id, o] of memberEls) if (!seen.has(id)) { o.g.remove(); o.tie.remove(); memberEls.delete(id); }
  }

  function update() {
    const fh = focusHome();
    if (!fh) return;
    const fk = `${fh.pos.x},${fh.pos.y}|${(S.homes || []).map((h) => h.id + h.area).join(",")}`;
    if (fk !== focusKey) {
      focusKey = fk;
      homeEls.clear(); memberEls.clear();
      buildBase(fh.pos);
    }
    updateHomes();
    updateMembers();
    const repl = (S.homes || []).filter((h) => h.kind === "replay").length;
    if (changed("mapCap", String(repl))) {
      $("mapCap").replaceChildren(el("h2", "label", `Calgary · ${fh.person}'s circle`));
      $("mapLegend").replaceChildren(
        repl ? el("span", null, el("b", null, "REFIT House N"), " = a real UK household, replayed at its real times of day") : el("span"),
        el("span", null, "map stylised"));
    }
  }

  function thread(fromId, toId, kind) {
    const m = memberById(fromId);
    const th = S?.homes?.find((x) => x.id === toId);
    if (!m || !th) return;
    const [x1, y1] = memberPos(m);
    const [x2, y2] = place(th.pos.x, th.pos.y);
    const mx = (x1 + x2) / 2, my = (y1 + y2) / 2, dx = x2 - x1, dy = y2 - y1, len = Math.hypot(dx, dy) || 1;
    let nx = -dy / len, ny = dx / len;
    if (ny > 0) { nx = -nx; ny = -ny; } // bow upwards
    const bend = clamp(len * 0.7, 60, 170);
    const d = `M${x1} ${y1}Q${mx + nx * bend} ${my + ny * bend} ${x2} ${y2}`;
    const col = kind === "glow" ? C.glow : "#e9fff0";
    const g = mk("g", {}, L.threads);
    const soft = mk("path", { d, fill: "none", stroke: col, "stroke-width": 9, "stroke-linecap": "round", opacity: 0.35, filter: "url(#blur3)" }, g);
    const core = mk("path", { d, fill: "none", stroke: col, "stroke-width": 2.6, "stroke-linecap": "round" }, g);
    const head = mk("circle", { r: 7, fill: col, filter: "url(#blur3)" }, g);
    const head2 = mk("circle", { r: 3.5, fill: "#fff" }, g);
    const total = core.getTotalLength();
    for (const p of [soft, core]) { p.setAttribute("stroke-dasharray", `${total} ${total}`); p.setAttribute("stroke-dashoffset", total); }
    threads.push({ g, soft, core, head, head2, total, t0: performance.now(), toId, col, done: false });
  }
  function pulse(homeId, color) {
    const o = homeEls.get(homeId);
    if (!o || reduced) return;
    const c = mk("circle", { cx: o.x, cy: o.y, r: o.big ? 26 : 16, class: "pulse", stroke: color || C.steam }, L.fx);
    setTimeout(() => c.remove(), 2000);
  }
  function tick(ts) {
    for (let i = threads.length - 1; i >= 0; i--) {
      const t = threads[i];
      const age = (ts - t.t0) / 1000;
      const travel = reduced ? 0.01 : 2.4;
      const p = clamp(age / travel, 0, 1);
      const e = 1 - Math.pow(1 - p, 3);
      const off = t.total * (1 - e);
      t.soft.setAttribute("stroke-dashoffset", off);
      t.core.setAttribute("stroke-dashoffset", off);
      const pt = t.core.getPointAtLength(t.total * e);
      for (const hd of [t.head, t.head2]) { hd.setAttribute("cx", pt.x); hd.setAttribute("cy", pt.y); }
      if (p >= 1 && !t.done) { t.done = true; pulse(t.toId, t.col); }
      const fade = age > travel + 4 ? 1 - (age - travel - 4) / 4 : 1;
      t.g.setAttribute("opacity", clamp(fade, 0, 1));
      for (const hd of [t.head, t.head2]) hd.setAttribute("opacity", p >= 1 ? clamp(1 - (age - travel) * 1.5, 0, 1) : 1);
      if (fade <= 0) { t.g.remove(); threads.splice(i, 1); }
    }
    if (ts - lastMini > 400 && S) { lastMini = ts; updateMinis(); }
  }
  return { update, thread, pulse, tick };
})();

// ============================================================== frost (cold mode)
const frost = (() => {
  const cv = $("frost");
  let built = "";
  function build() {
    const w = innerWidth, h = innerHeight;
    const key = `${w}x${h}`;
    if (built === key) return;
    built = key;
    const dpr = Math.min(2, devicePixelRatio || 1);
    cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
    const ctx = cv.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    let seed = 4242;
    const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
    const md = Math.min(w, h);
    // icy haze at the edges and corners
    const edgeG = (x0, y0, x1, y1) => {
      const g = ctx.createLinearGradient(x0, y0, x1, y1);
      g.addColorStop(0, "rgba(200,228,250,.20)"); g.addColorStop(1, "rgba(200,228,250,0)");
      return g;
    };
    const ew = md * 0.16;
    ctx.fillStyle = edgeG(0, 0, ew, 0); ctx.fillRect(0, 0, ew, h);
    ctx.fillStyle = edgeG(w, 0, w - ew, 0); ctx.fillRect(w - ew, 0, ew, h);
    ctx.fillStyle = edgeG(0, 0, 0, ew); ctx.fillRect(0, 0, w, ew);
    ctx.fillStyle = edgeG(0, h, 0, h - ew); ctx.fillRect(0, h - ew, w, ew);
    for (const [cx, cy] of [[0, 0], [w, 0], [0, h], [w, h]]) {
      const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, md * 0.42);
      g.addColorStop(0, "rgba(225,242,255,.30)"); g.addColorStop(0.5, "rgba(210,236,255,.08)"); g.addColorStop(1, "rgba(210,236,255,0)");
      ctx.fillStyle = g; ctx.fillRect(0, 0, w, h);
    }
    // ice crystals growing in from the edges (hexagonal branching)
    ctx.lineCap = "round";
    const branch = (x, y, ang, len, depth, lw, a) => {
      const x2 = x + Math.cos(ang) * len, y2 = y + Math.sin(ang) * len;
      ctx.strokeStyle = `rgba(226,243,255,${a})`;
      ctx.lineWidth = lw;
      ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x2, y2); ctx.stroke();
      if (depth <= 0 || len < 5) return;
      const n = 2 + Math.floor(rnd() * 3);
      for (let i = 1; i <= n; i++) {
        const f = i / (n + 1) + (rnd() - 0.5) * 0.12;
        const bx = x + (x2 - x) * f, by = y + (y2 - y) * f;
        const bl = len * (0.22 + rnd() * 0.28) * (1 - f * 0.55);
        branch(bx, by, ang + Math.PI / 3 + (rnd() - 0.5) * 0.1, bl, depth - 1, lw * 0.7, a * 0.86);
        branch(bx, by, ang - Math.PI / 3 + (rnd() - 0.5) * 0.1, bl, depth - 1, lw * 0.7, a * 0.86);
      }
    };
    const corner = (x, y) => {
      const dx = Math.min(x, w - x) / (w / 2), dy = Math.min(y, h - y) / (h / 2);
      return Math.max(0, 1 - Math.min(dx, dy) * 3.2) * (1 - Math.max(dx, dy));
    };
    const seedEdge = (x, y, inward) => {
      const c = corner(x, y);
      const len = (22 + rnd() * 60) * (1 + 3.2 * c) * (md / 1080);
      branch(x, y, inward + (rnd() - 0.5) * 1.1, len, c > 0.25 ? 3 : 2, 1 + c * 0.8, 0.2 + c * 0.24);
    };
    const step = 30 * (md / 1080);
    for (let x = 0; x <= w; x += step * (0.6 + rnd() * 0.8)) { seedEdge(x, -2, Math.PI / 2); seedEdge(x, h + 2, -Math.PI / 2); }
    for (let y = 0; y <= h; y += step * (0.6 + rnd() * 0.8)) { seedEdge(-2, y, 0); seedEdge(w + 2, y, Math.PI); }
    // glints
    for (let i = 0; i < 260; i++) {
      const side = Math.floor(rnd() * 4), t = rnd(), d = Math.pow(rnd(), 2) * md * 0.14;
      const x = side === 0 ? t * w : side === 1 ? t * w : side === 2 ? d : w - d;
      const y = side === 0 ? d : side === 1 ? h - d : t * h;
      ctx.fillStyle = `rgba(240,250,255,${0.25 + rnd() * 0.5})`;
      ctx.beginPath(); ctx.arc(x, y, 0.6 + rnd() * 1.2, 0, Math.PI * 2); ctx.fill();
    }
  }
  return { ensure: build, reset() { built = ""; if (document.body.classList.contains("cold")) build(); } };
})();

// ============================================================== moments (Jan 13 timeline)
const moment = (() => {
  const box = $("moment");
  let timers = [], startT = 0, homeName = "Margaret";
  const api = {
    open: false,
    show(item) {
      timers.forEach(clearTimeout); timers = [];
      api.open = true;
      startT = item.ts || 0;
      homeName = hero()?.person || "Margaret";
      box.hidden = false;
      box.className = "moment";
      const phones = el("div", "phones");
      for (let i = 0; i < 5; i++) phones.append(svgIcon(ICONS.mobile));
      const when = dtf({ weekday: "long", month: "long", day: "numeric", year: "numeric" }).format(new Date((item.ts || demoT()) * 1000));
      const kl = el("div", "kettle-line", `Kettle makes that alert also say: check on ${homeName}.`);
      box.replaceChildren(el("div", "inner",
        el("div", "when", `${item.t.slice(11, 16)} · ${when}`),
        phones,
        el("h2", null, "Every phone in Alberta buzzed."),
        el("p", "real", item.text),
        el("div", "src", `Source: ${item.source}`),
        kl,
        el("div", "who-asked", "")));
      sound.buzz("sms");
      timers.push(setTimeout(() => { kl.classList.add("on"); box.classList.add("calm"); api.updateAsked(S?.outbox || []); }, 3400));
      timers.push(setTimeout(api.hide, 11500));
    },
    updateAsked(list) {
      if (!api.open) return;
      const who = [...new Set(list.filter((o) => o.channel === "sms" && o.t >= startT - 1).map((o) => o.to))];
      const dev = list.some((o) => o.channel === "device" && o.t >= startT - 1);
      const w = box.querySelector(".who-asked");
      if (!w) return;
      const names = who.length > 1 ? `${who.slice(0, -1).join(", ")} and ${who[who.length - 1]}` : who[0];
      w.textContent = names ? `${names} ${who.length > 1 ? "were" : "was"} asked to check on her${dev ? ", and the light on her Kettle asks if she's warm" : ""}.` : "";
    },
    hide() {
      timers.forEach(clearTimeout); timers = [];
      if (!api.open) return;
      box.classList.add("out");
      setTimeout(() => { box.hidden = true; api.open = false; flushToasts(); }, 900);
    },
  };
  box.addEventListener("click", () => api.hide());
  return api;
})();

const toastQueue = [];
function toast(t) {
  if (moment.open) { toastQueue.push({ ...t, at: Date.now() }); return; }
  const box = el("div", "toast", t.when ? el("span", "tt", t.when) : null, t.text, t.source ? el("span", "src", `Source: ${t.source}`) : null);
  $("toasts").append(box);
  setTimeout(() => { box.classList.add("out"); setTimeout(() => box.remove(), 800); }, t.ms || 7000);
}
function flushToasts() {
  // items that fired during the moment are already listed (with sources) in the context panel
  const now = Date.now();
  while (toastQueue.length) { const t = toastQueue.shift(); if (now - t.at < 4000) toast(t); }
}
function onTimeline(item) {
  if (/emergency text alert/i.test(item.text)) moment.show(item);
  else toast({ when: item.t.slice(11, 16), text: item.text, source: item.source });
}

// ============================================================== flashes from the cloud
const seenFlash = new Map();
function handleFlashes(list) {
  const now = srvNow();
  for (const f of list) {
    const key = [f.type, f.t, f.home, f.from, f.to, f.item?.t].join("|");
    if (seenFlash.has(key)) continue;
    seenFlash.set(key, now);
    if (now - f.t > 6) continue;
    if (f.type === "thread") map.thread(f.from, f.to, f.kind);
    else if (f.type === "ring") sound.buzz("ring");
    else if (f.type === "activity") map.pulse(f.home, C.ok);
    else if (f.type === "timeline" && f.item) onTimeline(f.item);
  }
  for (const [k, t] of seenFlash) if (now - t > 90) seenFlash.delete(k);
}

// ============================================================== sound (muted by default; a soft phone vibration, nothing like Alert Ready)
const sound = (() => {
  let ctx = null, muted = true;
  const ind = $("soundInd");
  const paint = () => { ind.textContent = muted ? "sound off · M" : "sound on · M"; ind.classList.toggle("on", !muted); };
  paint();
  function hum(t0, dur) {
    const o1 = ctx.createOscillator(), o2 = ctx.createOscillator(), lp = ctx.createBiquadFilter(), g = ctx.createGain();
    const am = ctx.createOscillator(), amg = ctx.createGain();
    o1.type = "sawtooth"; o1.frequency.value = 146;
    o2.type = "triangle"; o2.frequency.value = 149;
    lp.type = "lowpass"; lp.frequency.value = 340; lp.Q.value = 0.6;
    am.frequency.value = 24; amg.gain.value = 0.025;
    g.gain.setValueAtTime(0, t0);
    g.gain.linearRampToValueAtTime(0.07, t0 + 0.04);
    g.gain.setValueAtTime(0.07, t0 + dur - 0.06);
    g.gain.linearRampToValueAtTime(0, t0 + dur);
    am.connect(amg).connect(g.gain);
    o1.connect(lp); o2.connect(lp); lp.connect(g).connect(ctx.destination);
    for (const o of [o1, o2, am]) { o.start(t0); o.stop(t0 + dur + 0.05); }
  }
  return {
    toggle() {
      muted = !muted;
      if (!muted) { ctx ||= new (window.AudioContext || window.webkitAudioContext)(); ctx.resume?.(); }
      paint();
    },
    buzz(kind) {
      if (muted || !ctx) return;
      const t = ctx.currentTime + 0.02;
      const n = kind === "ring" ? 3 : 2;
      for (let i = 0; i < n; i++) hum(t + i * 0.55, 0.36);
    },
  };
})();
// a ringing phone keeps buzzing softly while it rings
setInterval(() => { if (hero()?.ringing) sound.buzz("ring"); }, 3200);

// ============================================================== presenter drawer + keys
const drawer = $("drawer"), drawerBtn = $("drawerBtn");
function toggleDrawer(force) {
  const open = force ?? drawer.hidden;
  drawer.hidden = !open;
  drawerBtn.setAttribute("aria-expanded", String(open));
}
const curSpeed = () => {
  const s = Number(S?.clock?.speed || 60);
  return [10, 60, 300].includes(s) ? s : 60;
};
let jumpNote = null; // { text, until } shown on the J button after a jump
async function respond(response) {
  const e = hero()?.escalation;
  if (!e || e.step === "resolved") { toast({ text: "No open alert to answer.", ms: 2500 }); return; }
  const r = await post("/api/respond", { member: "priya", escalation: e.id, response });
  if (r && r.ok === false) toast({ text: r.error || "Priya isn't part of this alert.", ms: 3000 });
}
const ACTIONS = {
  drawer: () => toggleDrawer(),
  reset: () => post("/api/demo/reset", { hhmm: "6:30", speed: curSpeed() }),
  jump: async () => {
    const r = await post("/api/demo/jump?home=margaret&after=4&speed=1");
    if (r?.hhmm) { jumpNote = { text: `Jumped to ${r.hhmm} · 1×`, until: Date.now() + 5000 }; syncDrawer(); }
  },
  kettle: async () => {
    const r = await post("/api/demo/kettle");
    if (r && r.ok === false) toast({ text: "No Kettle hub connected for Margaret's home.", ms: 3000 });
  },
  outage: () => post("/api/demo/outage?seconds=30"),
  replay: () => post("/api/demo/replay?speed=240"),
  grid: () => post("/api/demo/grid-alert"),
  coldToggle: () => post(`/api/demo/cold/${S?.cold?.active ? "off" : "on"}`),
  going: () => respond("going"),
  seen: () => respond("ok"),
  glow: () => post("/api/glow", { member: "priya", home: "margaret" }),
  fine: () => { if (!edgeSock.send({ type: "im_fine" })) toast({ text: "Kitchen hub not connected.", ms: 2500 }); },
};
function flashBtn(btn) { if (!btn) return; btn.classList.add("flash"); setTimeout(() => btn.classList.remove("flash"), 500); }
drawer.addEventListener("click", (ev) => {
  const b = ev.target.closest("button");
  if (!b) return;
  if (b.dataset.act) { ACTIONS[b.dataset.act]?.(); flashBtn(b); }
  if (b.dataset.speed) { post("/api/demo/clock", { speed: +b.dataset.speed }); flashBtn(b); }
  if (b.dataset.cold) { post(`/api/demo/cold/${b.dataset.cold}`); flashBtn(b); }
});
drawerBtn.addEventListener("click", () => toggleDrawer());
const scrub = $("scrub"), scrubOut = $("scrubOut");
let scrubbing = false;
scrub.addEventListener("input", () => { scrubbing = true; scrubOut.textContent = fmtMin(+scrub.value); });
scrub.addEventListener("change", async () => { await post("/api/demo/clock", { hhmm: fmtMin(+scrub.value) }); scrubbing = false; });
// The QR must be reachable from a judge's phone: ?public= wins, then the cloud's best LAN/Tailscale URL.
async function setupQr() {
  let base = qs.get("public");
  if (!base) {
    try { const u = await (await fetch("/api/urls")).json(); base = u.best || u.public || u.tailscale || u.lan; } catch { /* older cloud */ }
  }
  const joinUrl = `${(base || location.origin).replace(/\/+$/, "")}/circle/?join=1`;
  $("qr").src = `/api/qr.svg?data=${encodeURIComponent(joinUrl)}`;
  $("qrUrl").textContent = joinUrl;
}
setupQr();

function syncDrawer() {
  if (drawer.hidden || !S) return;
  const sp = Number(S.clock.speed);
  for (const b of drawer.querySelectorAll("[data-speed]")) b.classList.toggle("on", +b.dataset.speed === sp);
  for (const b of drawer.querySelectorAll("[data-cold]")) b.classList.toggle("on", b.dataset.cold === S.cold?.mode);
  $("coldMode").textContent = S.cold?.active ? "· active" : "";
  const b = hero()?.baseline;
  const jb = drawer.querySelector('[data-act="jump"]');
  const lab = jumpNote && Date.now() < jumpNote.until ? jumpNote.text : `Past her deadline${b?.deadline ? ` (${b.deadline})` : ""} · 1×`;
  if (jb && !jb.textContent.endsWith(lab)) { jb.replaceChildren(el("kbd", null, "J"), lab); }
  if (!scrubbing) {
    const n = Math.round(nowMin());
    scrub.value = clamp(n, 240, 840);
    scrubOut.textContent = fmtMin(n);
  }
}

addEventListener("keydown", (ev) => {
  if (ev.metaKey || ev.ctrlKey || ev.altKey) return;
  if (ev.target.matches?.("input[type=text], textarea")) return;
  const k = ev.key.toLowerCase();
  const map = { d: "drawer", r: "reset", j: "jump", k: "kettle", c: "coldToggle", p: "replay", g: "grid", o: "outage" };
  if (k === "escape") { if (moment.open) moment.hide(); else toggleDrawer(false); return; }
  if (k === "m") { sound.toggle(); return; }
  if (map[k]) {
    ev.preventDefault();
    ACTIONS[map[k]]();
    flashBtn(drawer.querySelector(`[data-act="${map[k]}"]`));
  }
});

// ============================================================== frame loop
function frame(ts) {
  const dt = Math.min(0.1, (ts - lastFrame) / 1000);
  lastFrame = ts;
  tickClock();
  drawTrace(ts, dt);
  drawRibbon(ts);
  drawReplay(ts);
  map.tick(ts);
  // kitchen glow ("thinking of you"): from the cloud's view of the home, or the hub's own message
  const m = hero();
  const glowFrom = (m?.glow && m.glow.from) || (edge.glow && Date.now() / 1000 < edge.glow.until ? edge.glow.from : null);
  const gKey = glowFrom || "";
  if (memo.get("glow") !== gKey) {
    memo.set("glow", gKey);
    $("traceWrap").classList.toggle("glowing", !!glowFrom);
    const gm = $("glowMsg");
    gm.hidden = !glowFrom;
    if (glowFrom) gm.replaceChildren(`${glowFrom} is thinking of you`, el("small", null, `a warm light glows in ${m?.person || "Margaret"}'s kitchen`));
  }
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);
