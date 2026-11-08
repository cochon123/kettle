import crypto from "node:crypto";
import { CHARACTERS, DAY, K, pipe, route } from "../../lib/kv.js";

export default route(["POST"], async (req, res) => {
  const { c, number } = req.body || {};
  if (!CHARACTERS[c]) return res.status(400).json({ error: "Unknown character." });
  let num = String(number || "").replace(/[\s().-]/g, "");
  if (/^\d{10}$/.test(num)) num = "+1" + num;            // North American number typed without +1
  if (/^1\d{10}$/.test(num)) num = "+" + num;
  if (num && !/^\+\d{8,15}$/.test(num)) return res.status(400).json({ error: "That phone number doesn't look right. Try +1 403 555 1234." });
  const token = crypto.randomBytes(18).toString("base64url");
  const reg = JSON.stringify({ token, number: num || null, name: CHARACTERS[c].name, at: Date.now() / 1000 });
  const [ok] = await pipe([["SET", `${K}reg:${c}`, reg, "NX", "EX", DAY]]);
  if (ok !== "OK") return res.status(409).json({ error: "taken" });
  await pipe([["SET", `${K}tok:${token}`, c, "EX", DAY]]);
  res.json({ token, c });
});
