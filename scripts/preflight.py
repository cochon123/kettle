"""Pre-show check: run this 10 minutes before presenting.

    .venv/bin/python scripts/preflight.py [--cloud http://localhost:8700] [--edge http://localhost:8701]

Checks the cloud, the edge hub, the plug, the device link, the circle WebSocket,
the data files and the live AESO/ECCC feeds, and prints the URLs for the phones.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import socket

import httpx
import websockets

OK, BAD, WARN = "\033[32m✔\033[0m", "\033[31m✘\033[0m", "\033[33m!\033[0m"


def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cloud", default="http://localhost:8700")
    ap.add_argument("--edge", default="http://localhost:8701")
    a = ap.parse_args()
    fails = 0

    def line(ok, text, warn=False):
        nonlocal fails
        print(f"  {OK if ok else (WARN if warn else BAD)} {text}")
        if not ok and not warn:
            fails += 1

    async with httpx.AsyncClient(timeout=5) as c:
        try:
            st = (await c.get(f"{a.cloud}/api/state")).json()
            line(True, f"cloud up · demo clock {st['clock']['hhmm']} ({'demo' if st['clock']['demo'] else 'real'}) · store: {st['store']} · calls: {st['twilio']}")
        except Exception as e:
            line(False, f"cloud not reachable at {a.cloud}: {e}")
            return 1
        try:
            es = (await c.get(f"{a.edge}/api/status")).json()
            line(es["plug_ok"], f"plug: {es['plug']} ({'REAL' if es['plug_real'] else 'simulated'}){'' if es['plug_ok'] else ' · ' + str(es['plug_err'])}")
            line(es["cloud_ok"], f"edge hub ↔ cloud link {'up' if es['cloud_ok'] else 'DOWN'} · {es['sent']} events sent, {es['queued']} queued")
        except Exception as e:
            line(False, f"edge hub not reachable at {a.edge}: {e}")
        m = next((h for h in st["homes"] if h["id"] == "margaret"), None)
        if m:
            b = m["baseline"]
            line(b.get("learned", False), f"Margaret's baseline: {b.get('sentence')}", warn=not b.get("learned"))
            line(m["device"]["online"], "Margaret's Kettle is online in the cloud")
        replay = [h for h in st["homes"] if h["kind"] == "replay"]
        line(bool(replay), f"{len(replay)} REFIT replay homes on the map", warn=True)
        line(bool(st.get("refit")), "REFIT evaluation summary loaded" if st.get("refit") else "REFIT summary missing (data/refit/summary.json)", warn=True)
        g = st["grid"]
        aeso = g.get("aeso") or {}
        line(bool(aeso.get("ail_mw")), f"AESO live: AIL {aeso.get('ail_mw')} MW (updated {aeso.get('updated')})", warn=True)
        wx = g.get("weather") or {}
        line(wx.get("temp_c") is not None, f"ECCC live: Calgary {wx.get('temp_c')} °C", warn=True)
        for name in ("jan13", "refit", "margaret"):
            r = await c.get(f"{a.cloud}/api/data/{name}")
            line(r.status_code == 200, f"data file '{name}' served", warn=name != "jan13")

    ws_url = a.cloud.replace("http", "ws", 1) + "/ws/circle?m=priya"
    try:
        async with websockets.connect(ws_url, open_timeout=5) as ws:
            s = json.loads(await asyncio.wait_for(ws.recv(), 5))
            line(s.get("me", {}).get("id") == "priya", "circle WebSocket works (Priya)")
    except Exception as e:
        line(False, f"circle WebSocket failed: {e}")

    ip = lan_ip()
    port = a.cloud.rsplit(":", 1)[-1]
    print("\n  Phones on the same network:")
    print(f"    judge's phone (Priya)  http://{ip}:{port}/circle/?m=priya")
    print(f"    join by QR / invite    http://{ip}:{port}/circle/?join=1   code: margaret")
    print(f"    stage                  http://{ip}:{port}/stage/      deck: /deck/")
    print(f"    kitchen display        http://{ip}:8701/hub/\n")
    print("  READY" if not fails else f"  {fails} problem(s) above")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
