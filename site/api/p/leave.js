import { K, parse, pipe, route } from "../../lib/kv.js";

export default route(["POST"], async (req, res) => {
  const t = String((req.body || {}).t || "");
  const [c] = await pipe([["GET", `${K}tok:${t}`]]);
  if (c) {
    const [reg] = await pipe([["GET", `${K}reg:${c}`]]);
    const cmds = [["DEL", `${K}tok:${t}`]];
    if (parse(reg)?.token === t) cmds.push(["DEL", `${K}reg:${c}`]);
    await pipe(cmds);
  }
  res.json({ ok: true });
});
