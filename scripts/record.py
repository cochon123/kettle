"""Record the real demo (no mock-ups) to MP4, as raw material for the submission video.

    .venv/bin/python scripts/record.py --out /tmp/kettle-demo.mp4

Drives the running demo through its API (reset -> jump past Margaret's deadline ->
no answer -> Priya taps "I'm going" -> kettle -> Jan 13 2024 replay) while capturing
the stage (1920x1080) and Priya's phone (412x915) with Chrome's screencast, then
composites them side by side with ffmpeg. Needs `python -m kettle demo` running.
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

import httpx
import websockets


class Tab:
    def __init__(self, port: int, w: int, h: int, mobile: bool, frames_dir: str):
        self.port, self.w, self.h, self.mobile, self.dir = port, w, h, mobile, frames_dir
        self.n = 0
        self.frames: list[tuple[float, str]] = []
        self.ws = None
        self.pending: dict[int, asyncio.Future] = {}

    async def open(self, url: str) -> None:
        # one Chrome per view: headless Chrome doesn't paint background tabs
        self.prof = tempfile.mkdtemp(prefix="rec-prof-")
        self.proc = subprocess.Popen(["google-chrome", "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                                      "--mute-audio", f"--remote-debugging-port={self.port}", f"--user-data-dir={self.prof}",
                                      f"--window-size={self.w},{self.h}", "about:blank"],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(80):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json"))
                page = next(t for t in tabs if t["type"] == "page")
                break
            except Exception:
                await asyncio.sleep(0.1)
        self.ws = await websockets.connect(page["webSocketDebuggerUrl"], max_size=100_000_000)
        asyncio.create_task(self._reader())
        await self.call("Page.enable")
        await self.call("Emulation.setDeviceMetricsOverride", {"width": self.w, "height": self.h,
                                                                "deviceScaleFactor": 1, "mobile": self.mobile})
        await self.call("Page.navigate", {"url": url})

    async def _reader(self) -> None:
        async for raw in self.ws:
            msg = json.loads(raw)
            if "id" in msg and msg["id"] in self.pending:
                self.pending.pop(msg["id"]).set_result(msg.get("result", {}))
            elif msg.get("method") == "Page.screencastFrame":
                p = msg["params"]
                path = os.path.join(self.dir, f"{len(self.frames):06d}.jpg")
                with open(path, "wb") as f:
                    f.write(base64.b64decode(p["data"]))
                self.frames.append((time.time(), path))
                asyncio.create_task(self.call("Page.screencastFrameAck", {"sessionId": p["sessionId"]}))

    async def call(self, method: str, params: dict | None = None) -> dict:
        self.n += 1
        fut = asyncio.get_running_loop().create_future()
        self.pending[self.n] = fut
        await self.ws.send(json.dumps({"id": self.n, "method": method, "params": params or {}}))
        return await asyncio.wait_for(fut, 30)

    async def start(self) -> None:
        await self.call("Page.startScreencast", {"format": "jpeg", "quality": 85, "maxWidth": self.w, "maxHeight": self.h,
                                                 "everyNthFrame": 1})

    async def stop(self) -> None:
        await self.call("Page.stopScreencast")

    def close(self) -> None:
        self.proc.terminate()
        shutil.rmtree(self.prof, ignore_errors=True)


def to_video(frames: list[tuple[float, str]], t0: float, t1: float, fps: int, out: str) -> None:
    """Resample variable-rate screencast frames onto a constant frame rate."""
    tmp = tempfile.mkdtemp(prefix="rec-")
    k, n = 0, int((t1 - t0) * fps)
    for i in range(n):
        t = t0 + i / fps
        while k + 1 < len(frames) and frames[k + 1][0] <= t:
            k += 1
        os.link(frames[k][1], os.path.join(tmp, f"{i:06d}.jpg"))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps), "-i", f"{tmp}/%06d.jpg",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", out], check=True)
    shutil.rmtree(tmp, ignore_errors=True)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cloud", default="http://localhost:8700")
    ap.add_argument("--edge", default="ws://localhost:8701/ws/local")
    ap.add_argument("--out", default="/tmp/kettle-demo.mp4")
    ap.add_argument("--fps", type=int, default=25)
    ap.add_argument("--no-replay", action="store_true")
    a = ap.parse_args()

    port = 9400 + os.getpid() % 300
    work = tempfile.mkdtemp(prefix="rec-frames-")
    tabs: list[Tab] = []
    try:
        os.makedirs(f"{work}/stage"), os.makedirs(f"{work}/phone")
        api = httpx.AsyncClient(base_url=a.cloud, timeout=10)
        await api.post("/api/demo/reset", json={"hhmm": "6:30"})
        stage = Tab(port, 1920, 1080, False, f"{work}/stage")
        phone = Tab(port + 1, 412, 915, True, f"{work}/phone")
        tabs = [stage, phone]
        await stage.open(f"{a.cloud}/stage/?edge={a.edge}")
        await phone.open(f"{a.cloud}/circle/?m=priya")
        await asyncio.sleep(4)
        await stage.start(); await phone.start()
        t0 = time.time()

        async def beat(label: str, secs: float) -> None:
            print(f"[{time.time() - t0:6.1f}s] {label}")
            await asyncio.sleep(secs)

        await beat("idle morning", 5)
        r = await api.post("/api/demo/jump", params={"speed": 1})
        await beat(f"jump to {r.json().get('hhmm')}: no kettle, asking Margaret", 23)
        st = (await api.get("/api/member/priya")).json()
        ask = next((n for n in st["notes"] if n["kind"] == "ask"), None)
        await beat("Priya's phone buzzes", 5)
        if ask:
            await api.post("/api/respond", json={"member": "priya", "escalation": ask["escalation"], "response": "going"})
        await beat("Priya: I'm going", 5)
        await api.post("/api/demo/kettle")
        await beat("kettle on", 12)
        await api.post("/api/glow", json={"member": "tom", "home": "margaret"})
        await beat("Tom: thinking of you", 6)
        if not a.no_replay:
            await api.post("/api/demo/replay", params={"speed": 240, "start": "17:30"})
            await beat("Jan 13 2024 replay", 30)
        t1 = time.time()
        await stage.stop(); await phone.stop()
        await asyncio.sleep(0.5)
        print(f"captured {len(stage.frames)} stage + {len(phone.frames)} phone frames over {t1 - t0:.0f}s")
        if not stage.frames or not phone.frames:
            raise SystemExit("no frames captured")

        s_mp4, p_mp4 = f"{work}/stage.mp4", f"{work}/phone.mp4"
        to_video(stage.frames, t0, t1, a.fps, s_mp4)
        to_video(phone.frames, t0, t1, a.fps, p_mp4)
        shutil.copy(s_mp4, a.out.replace(".mp4", "-stage.mp4"))
        shutil.copy(p_mp4, a.out.replace(".mp4", "-phone.mp4"))
        # side by side: stage scaled to 1080p height, phone scaled to 1080 high on the right
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", s_mp4, "-i", p_mp4, "-filter_complex",
                        "[0:v]scale=-2:1080[s];[1:v]scale=-2:1080[p];[s][p]hstack=inputs=2,scale=trunc(iw/4)*2:trunc(ih/4)*2",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", a.out], check=True)
        print("wrote", a.out, "and the -stage / -phone versions")
        await api.post("/api/demo/reset", json={"hhmm": "6:30"})
    finally:
        for t in tabs:
            t.close()
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
