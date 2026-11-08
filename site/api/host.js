// The host page (the presenter's laptop): who is registered, remove a phone, drive the story.
import { CHARACTERS, IDS, K, hubOnline, parse, pipe, route, same } from "../lib/kv.js";

const mask = (n) => (n ? `•••• ${n.slice(-4)}` : null);

export default route(["GET", "POST"], async (req, res) => {
  if (!same(req.headers["x-host-pin"], process.env.HOST_PIN)) return res.status(401).json({ error: "wrong PIN" });
  if (req.method === "POST") {
    const { cmd, c } = req.body || {};
    if (cmd === "remove" && CHARACTERS[c]) {
      const [reg] = await pipe([["GET", `${K}reg:${c}`]]);
      const t = parse(reg)?.token;
      await pipe([["DEL", `${K}reg:${c}`], ["DEL", `${K}seen:${c}`], ...(t ? [["DEL", `${K}tok:${t}`]] : [])]);
    } else if (cmd === "next" || cmd === "reset") {
      await pipe([["RPUSH", `${K}actions`, JSON.stringify({ who: "host", action: cmd, at: Date.now() / 1000 })], ["EXPIRE", `${K}actions`, 600]]);
    } else return res.status(400).json({ error: "unknown command" });
    return res.json({ ok: true });
  }
  const out = await pipe([
    ["MGET", ...IDS.map((c) => `${K}reg:${c}`)],
    ["MGET", ...IDS.map((c) => `${K}seen:${c}`)],
    ["GET", `${K}hub`], ["GET", `${K}hub_at`], ["GET", `${K}cards`],
  ]);
  const now = Date.now() / 1000, cards = parse(out[4]) || {};
  res.json({
    characters: IDS.map((c, i) => {
      const r = parse(out[0][i]);
      return { id: c, ...CHARACTERS[c], registered: !!r, number: mask(r?.number), joined: r?.at || null,
               online: !!out[1][i] && now - Number(out[1][i]) < 8, showing: cards[c]?.title || null };
    }),
    hub: parse(out[2]), hub_online: hubOnline(out[3]),
  });
});
