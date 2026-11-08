import { K, pipe, route } from "../../lib/kv.js";

const ACTIONS = /^(im_fine|glow|going|all_good|cant|ok|need_help)$/;

export default route(["POST"], async (req, res) => {
  const { t, action, ref } = req.body || {};
  if (!ACTIONS.test(String(action))) return res.status(400).json({ error: "unknown action" });
  const [c] = await pipe([["GET", `${K}tok:${String(t || "")}`]]);
  if (!c) return res.status(401).json({ error: "not registered" });
  const r = ref && typeof ref === "object" ? { escalation: Number(ref.escalation) || null, note: Number(ref.note) || null } : null;
  await pipe([["RPUSH", `${K}actions`, JSON.stringify({ who: c, action, ref: r, at: Date.now() / 1000 })], ["EXPIRE", `${K}actions`, 600]]);
  res.json({ ok: true });
});
