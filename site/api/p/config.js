import { CHARACTERS, IDS, K, hubOnline, pipe, route } from "../../lib/kv.js";

export default route(["GET"], async (req, res) => {
  const [regs, hubAt] = await pipe([["MGET", ...IDS.map((c) => `${K}reg:${c}`)], ["GET", `${K}hub_at`]]);
  res.json({ mode: "site", characters: CHARACTERS, taken: Object.fromEntries(IDS.map((c, i) => [c, !!regs[i]])),
             hub_online: hubOnline(hubAt) });
});
