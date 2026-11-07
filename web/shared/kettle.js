// Small shared helpers: a self-reconnecting WebSocket and formatting.

export function socket(url, { onmessage, onstatus } = {}) {
  let ws, closed = false, delay = 500;
  const api = {
    send(obj) { if (ws && ws.readyState === 1) { ws.send(JSON.stringify(obj)); return true; } return false; },
    close() { closed = true; ws && ws.close(); },
    get open() { return ws && ws.readyState === 1; },
  };
  const connect = () => {
    ws = new WebSocket(url);
    ws.onopen = () => { delay = 500; onstatus && onstatus(true); };
    ws.onmessage = (e) => { try { onmessage && onmessage(JSON.parse(e.data)); } catch (err) { console.error(err); } };
    ws.onclose = (e) => {
      onstatus && onstatus(false, e.code);
      if (!closed && e.code !== 4404 && e.code !== 4403) setTimeout(connect, delay = Math.min(delay * 1.7, 8000));
    };
  };
  connect();
  return api;
}

export const wsBase = () => (location.protocol === "https:" ? "wss://" : "ws://") + location.host;

export function fmtMin(m) {
  if (m == null) return "–";
  m = Math.round(m) % 1440;
  return `${Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")}`;
}

export const ICON = { kettle: "☕", microwave: "🍲", toaster: "🍞", tv: "📺", furnace_blower: "🔥", human_unknown: "•", activity: "•" };
export const NICE = { kettle: "Kettle", microwave: "Microwave", toaster: "Toaster", tv: "TV", furnace_blower: "Furnace", human_unknown: "Appliance", activity: "Activity" };

export async function post(path, body) {
  const r = await fetch(path, { method: "POST", headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  return r.json().catch(() => ({}));
}

export function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v === true) el.setAttribute(k, "");
    else if (v !== false && v != null) el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid.nodeType ? kid : document.createTextNode(kid));
  return el;
}
