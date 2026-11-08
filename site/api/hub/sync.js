// The laptop hub calls this every second: it pushes every character's card and collects the phones' taps.
import { IDS, K, parse, pipe, route, same } from "../../lib/kv.js";

export default route(["POST"], async (req, res) => {
  if (!same((req.headers.authorization || "").replace(/^Bearer /, ""), process.env.HUB_SECRET))
    return res.status(401).json({ error: "unauthorized" });
  const { cards, hub } = req.body || {};
  const out = await pipe([
    ["SET", `${K}cards`, JSON.stringify(cards || {}), "EX", 300],
    ["SET", `${K}hub`, JSON.stringify(hub || {}), "EX", 300],
    ["SET", `${K}hub_at`, String(Date.now() / 1000), "EX", 300],
    ["LPOP", `${K}actions`, 100],
    ["MGET", ...IDS.map((c) => `${K}reg:${c}`)],
  ]);
  const actions = (out[3] || []).map(parse).filter(Boolean);
  const registrations = {};
  IDS.forEach((c, i) => { const r = parse(out[4][i]); if (r) registrations[c] = { name: r.name, number: r.number }; });
  res.json({ actions, registrations });
});
