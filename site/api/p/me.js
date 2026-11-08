import { CHARACTERS, K, hubOnline, parse, pipe, route } from "../../lib/kv.js";

export default route(["GET"], async (req, res) => {
  const t = String(req.query.t || "");
  const [c] = t ? await pipe([["GET", `${K}tok:${t}`]]) : [null];
  if (!c) return res.status(401).json({ error: "not registered" });
  const [cards, hubAt] = await pipe([["GET", `${K}cards`], ["GET", `${K}hub_at`], ["SET", `${K}seen:${c}`, String(Date.now() / 1000), "EX", 600]]);
  const card = parse(cards)?.[c] || {
    who: { id: c, ...CHARACTERS[c] }, tone: "calm", kicker: null, title: "Hold on, the story is about to start.",
    body: "Keep this page open. Your phone will buzz when something happens.", why: null, buttons: [], glow: null, buzz: 0,
  };
  res.json({ ...card, hub_online: hubOnline(hubAt) });
});
