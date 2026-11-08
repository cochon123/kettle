// Tiny Upstash Redis REST client (no dependencies) + shared bits for the API routes.
import crypto from "node:crypto";

const URL_ = process.env.KV_REST_API_URL || process.env.UPSTASH_REDIS_REST_URL;
const TOKEN = process.env.KV_REST_API_TOKEN || process.env.UPSTASH_REDIS_REST_TOKEN;

export const K = "kd:";                       // key prefix
export const DAY = 86400;
export const CHARACTERS = {
  margaret: { name: "Margaret", line: "lives alone in Bridgeland" },
  priya: { name: "Priya", line: "neighbour, next door" },
  daniel: { name: "Daniel", line: "her son, in Edmonton" },
};
export const IDS = Object.keys(CHARACTERS);

/** Run Redis commands in one round trip: pipe([["GET","a"],["SET","b","1"]]) -> [resultA, resultB]. */
export async function pipe(cmds) {
  if (!URL_ || !TOKEN) throw new Error("storage not configured");
  const r = await fetch(`${URL_}/pipeline`, {
    method: "POST", headers: { authorization: `Bearer ${TOKEN}` }, body: JSON.stringify(cmds),
  });
  if (!r.ok) throw new Error(`storage ${r.status}`);
  const out = await r.json();
  return out.map((x) => { if (x.error) throw new Error(x.error); return x.result; });
}

export const parse = (s) => { try { return s ? JSON.parse(s) : null; } catch { return null; } };

export function same(a, b) {
  const x = Buffer.from(String(a || "")), y = Buffer.from(String(b || ""));
  return x.length > 0 && x.length === y.length && crypto.timingSafeEqual(x, y);
}

/** Wrap a handler: method check, JSON errors, never cache. */
export function route(methods, fn) {
  return async (req, res) => {
    res.setHeader("cache-control", "no-store");
    if (!methods.includes(req.method)) return res.status(405).json({ error: "method not allowed" });
    try {
      await fn(req, res);
    } catch (e) {
      console.error(e);
      res.status(500).json({ error: e.message || "server error" });
    }
  };
}

export const hubOnline = (at) => !!at && Date.now() / 1000 - Number(at) < 6;
