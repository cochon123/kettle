"""Real-time headless Chrome screenshots via the DevTools protocol (for checking the UIs).

    .venv/bin/python scripts/snap.py URL OUT.png --size 412x915 --wait 3 [--eval "js"] [--mobile]

Prints console errors. Unlike --virtual-time-budget, this lets WebSockets actually run.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request

import websockets


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("out")
    ap.add_argument("--size", default="1280x800")
    ap.add_argument("--wait", type=float, default=3.0)
    ap.add_argument("--eval", action="append", default=[], help="JS to run after load (repeatable)")
    ap.add_argument("--after", type=float, default=1.0, help="seconds to wait after each --eval")
    ap.add_argument("--mobile", action="store_true")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--long", action="store_true", help="print eval results in full")
    ap.add_argument("--inject", action="append", default=[], help="JS file to run in the page before the --eval steps")
    a = ap.parse_args()
    w, h = (int(x) for x in a.size.split("x"))
    port = 9300 + os.getpid() % 500
    prof = tempfile.mkdtemp(prefix="snap-")
    chrome = subprocess.Popen(["google-chrome", "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                               "--mute-audio", f"--remote-debugging-port={port}", f"--user-data-dir={prof}",
                               f"--window-size={w},{h}", "about:blank"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
                page = next(t for t in tabs if t["type"] == "page")
                break
            except Exception:
                time.sleep(0.1)
        async with websockets.connect(page["webSocketDebuggerUrl"], max_size=50_000_000) as ws:
            n = 0
            logs: list[str] = []

            async def call(method: str, params: dict | None = None) -> dict:
                nonlocal n
                n += 1
                my = n
                await ws.send(json.dumps({"id": my, "method": method, "params": params or {}}))
                while True:
                    msg = json.loads(await ws.recv())
                    if msg.get("id") == my:
                        return msg.get("result", {})
                    m = msg.get("method")
                    if m == "Runtime.consoleAPICalled" and msg["params"]["type"] in ("error", "warning"):
                        logs.append("console." + msg["params"]["type"] + ": " + " ".join(str(x.get("value", x.get("description", ""))) for x in msg["params"]["args"]))
                    elif m == "Runtime.exceptionThrown":
                        d = msg["params"]["exceptionDetails"]
                        logs.append("exception: " + (d.get("exception", {}).get("description") or d.get("text", "")))

            await call("Runtime.enable")
            await call("Page.enable")
            await call("Emulation.setDeviceMetricsOverride", {"width": w, "height": h, "deviceScaleFactor": 2 if a.mobile else 1,
                                                               "mobile": a.mobile})
            await call("Page.navigate", {"url": a.url})
            end = time.time() + a.wait
            while time.time() < end:
                await call("Runtime.evaluate", {"expression": "1"})
                await asyncio.sleep(0.2)
            for path in a.inject:
                r = await call("Runtime.evaluate", {"expression": open(path).read()})
                if "exceptionDetails" in r:
                    logs.append("inject error: " + str(r["exceptionDetails"].get("text")))
            for js in a.eval:
                r = await call("Runtime.evaluate", {"expression": js, "awaitPromise": True, "returnByValue": True})
                if "exceptionDetails" in r:
                    logs.append("eval error: " + str(r["exceptionDetails"].get("exception", {}).get("description")))
                elif r.get("result", {}).get("value") is not None:
                    v = str(r["result"]["value"])
                    print("eval ->", v if a.long else v[:300])
                end = time.time() + a.after
                while time.time() < end:
                    await call("Runtime.evaluate", {"expression": "1"})
                    await asyncio.sleep(0.2)
            shot = await call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": a.full})
            open(a.out, "wb").write(base64.b64decode(shot["data"]))
            for line in logs:
                print(line)
            print("saved", a.out)
    finally:
        chrome.terminate()
        try:
            chrome.wait(3)
        except subprocess.TimeoutExpired:
            chrome.kill()
        shutil.rmtree(prof, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
