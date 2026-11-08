"""Render film.html to video frames with headless Chrome, one deterministic frame at a time.

    python video/render.py --stills 3,12.5,30 --out /tmp/stills         # PNG stills to look at
    python video/render.py --out /tmp/kettle-film.mp4 [--workers 2]     # the whole film (silent)

Needs google-chrome, ffmpeg, and `pip install websockets`.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import functools
import http.server
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

import websockets

HERE = Path(__file__).resolve().parent


def serve() -> int:
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a, **k) -> None:
            pass

    handler = functools.partial(Quiet, directory=str(HERE))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv.server_address[1]


class Chrome:
    def __init__(self, port: int):
        self.port, self.n, self.pending = port, 0, {}

    async def start(self, url: str) -> None:
        self.prof = tempfile.mkdtemp(prefix="film-prof-")
        self.proc = subprocess.Popen(["google-chrome", "--headless=new", "--disable-gpu", "--enable-unsafe-swiftshader", "--hide-scrollbars", "--no-first-run", "--mute-audio",
                                      "--force-color-profile=srgb", f"--remote-debugging-port={self.port}", f"--user-data-dir={self.prof}",
                                      "--window-size=1920,1080", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(600):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json"))
                page = next(t for t in tabs if t["type"] == "page")
                break
            except Exception:
                await asyncio.sleep(0.1)
        self.ws = await websockets.connect(page["webSocketDebuggerUrl"], max_size=500_000_000)
        self.reader = asyncio.create_task(self._read())
        await self.call("Runtime.enable")
        await self.call("Page.enable")
        await self.call("Emulation.setDeviceMetricsOverride", {"width": 1920, "height": 1080, "deviceScaleFactor": 1, "mobile": False})
        await self.call("Page.navigate", {"url": url})
        for _ in range(600):
            r = await self.call("Runtime.evaluate", {"expression": "window.READY === true", "returnByValue": True})
            if r.get("result", {}).get("value"):
                return
            await asyncio.sleep(0.1)
        raise RuntimeError("film never became ready")

    async def _read(self) -> None:
        async for raw in self.ws:
            msg = json.loads(raw)
            if "id" in msg and msg["id"] in self.pending:
                self.pending.pop(msg["id"]).set_result(msg)
            elif msg.get("method") == "Runtime.exceptionThrown":
                print("page exception:", msg["params"]["exceptionDetails"].get("exception", {}).get("description", "")[:400])

    async def call(self, method: str, params: dict | None = None) -> dict:
        self.n += 1
        fut = asyncio.get_running_loop().create_future()
        self.pending[self.n] = fut
        await self.ws.send(json.dumps({"id": self.n, "method": method, "params": params or {}}))
        msg = await asyncio.wait_for(fut, 120)
        if "error" in msg:
            raise RuntimeError(f"{method}: {msg['error']}")
        return msg.get("result", {})

    async def frame(self, t: float, fmt: str = "jpeg") -> bytes:
        r = await self.call("Runtime.evaluate", {"expression": f"window.seek({t:.5f})", "awaitPromise": True})
        if "exceptionDetails" in r:
            raise RuntimeError(r["exceptionDetails"])
        params = {"format": fmt}
        if fmt == "jpeg":
            params["quality"] = 94
        shot = await self.call("Page.captureScreenshot", params)
        return base64.b64decode(shot["data"])

    def close(self) -> None:
        self.reader.cancel()
        self.proc.terminate()
        shutil.rmtree(self.prof, ignore_errors=True)


async def stills(url: str, times: list[float], out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    c = Chrome(9600 + os.getpid() % 200)
    try:
        await c.start(url)
        for t in times:
            (out / f"t{t:07.2f}.png").write_bytes(await c.frame(t, "png"))
            print("still", t)
    finally:
        c.close()


async def segment(url: str, port: int, frames: range, fps: int, out: str) -> None:
    c = Chrome(port)
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(fps), "-c:v", "mjpeg", "-i", "-",
                           "-c:v", "libx264", "-preset", "medium", "-crf", "15", "-pix_fmt", "yuv420p", "-r", str(fps), out], stdin=subprocess.PIPE)
    try:
        await c.start(url)
        t0 = time.time()
        for i, f in enumerate(frames):
            ff.stdin.write(await c.frame(f / fps))
            if i % 150 == 0:
                el = time.time() - t0
                print(f"[{out[-12:]}] frame {f} ({i + 1}/{len(frames)}) {el / (i + 1):.3f}s/frame", flush=True)
    finally:
        ff.stdin.close()
        ff.wait()
        c.close()


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--stills")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--start", type=float, default=0)
    ap.add_argument("--end", type=float)
    a = ap.parse_args()
    url = f"http://127.0.0.1:{serve()}/film.html"
    if a.stills:
        await stills(url, [float(x) for x in a.stills.split(",")], Path(a.out))
        return
    tl = json.loads((HERE / "timeline.json").read_text())
    fps, dur = tl["fps"], a.end or tl["duration"]
    n0, n1 = int(a.start * fps), int(dur * fps)
    chunk = (n1 - n0 + a.workers - 1) // a.workers
    tmp = tempfile.mkdtemp(prefix="film-seg-")
    parts = [f"{tmp}/part{i}.mp4" for i in range(a.workers)]
    await asyncio.gather(*[segment(url, 9500 + i, range(n0 + i * chunk, min(n1, n0 + (i + 1) * chunk)), fps, parts[i]) for i in range(a.workers)])
    lst = f"{tmp}/list.txt"
    Path(lst).write_text("".join(f"file '{p}'\n" for p in parts))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", a.out], check=True)
    shutil.rmtree(tmp, ignore_errors=True)
    print("wrote", a.out)


if __name__ == "__main__":
    asyncio.run(main())
