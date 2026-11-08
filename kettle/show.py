"""Presenter mode: drive the demo story one keypress at a time.

    .venv/bin/python -m kettle show                                  # in-app notifications only
    .venv/bin/python -m kettle show --phone margaret=+1403… --phone priya=+1587… --phone daniel=+1780…

Starts the cloud + the kitchen hub (simulated kettle plug, the big button if it
is plugged in), puts Margaret's learned morning at 8:30 (--usual), switches
the escalation timers off, then waits for you:

    SPACE / ENTER   next step:
                      1  8:31  Kettle asks Margaret        (her text, the big button pulses)
                      2  8:34  no answer: ask a neighbour  (Priya's phone)
                      3  8:54  still nothing: ask family   (Daniel's phone)
                      4  9:01  she makes her tea           (everyone: "Margaret's kettle just came on")
    R               start over        Q   quit

Pressing the big button at any point is Margaret saying "I'm fine": it ends the
alert the same way. With --phone numbers the messages also go out as real SMS
through Twilio (KETTLE_TWILIO_PROFILE / TWILIO_FROM; only the numbers you list
are ever texted). Server logs go to a file so this terminal stays clean.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import select
import subprocess
import sys
import tempfile
import time

import httpx

STEPS = [
    ("ask_self", "Kettle asks Margaret", "It's past her usual time. She gets a text and the big button pulses.",
     "“Margaret usually makes her tea around {usual}. Look, it's {t1}. Nobody has to do anything…”"),
    ("ask_neighbour", "Ask a neighbour", "Priya, next door, gets “Can you knock?”",
     "“But Margaret doesn't answer, so Kettle asks her neighbour.”"),
    ("ask_family", "Ask the family", "Daniel, her son, gets “Can you call Margaret?”",
     "“If the neighbour doesn't answer within 20 minutes, Kettle asks her family.”"),
    ("tea", "She makes her tea", "The kettle comes on; everyone gets “Margaret's kettle just came on”.",
     "“But maybe she was just asleep, and now she puts the kettle on.”"),
]
CLR, DIM, BOLD, GRN, YEL, RED, RST = "\033[2J\033[H", "\033[2m", "\033[1m", "\033[32m", "\033[33m", "\033[31m", "\033[0m"
TWILIO_FROM_DEFAULT = "+18257829153"      # the team's Twilio number (docs/team-handoff.md)


def fmt(m: float) -> str:
    m = int(round(m))
    return f"{m // 60}:{m % 60:02d}"


def load_site(url: str | None) -> dict | None:
    """The public phone site + the hub's secret for it (written when the site was deployed)."""
    p = pathlib.Path.home() / ".config/kettle/site.json"
    try:
        d = json.loads(p.read_text())
    except Exception:
        return None
    d["url"] = (url or d.get("url") or "").rstrip("/")
    return d if d["url"] and d.get("secret") else None


def twilio_env(env: dict) -> list[str]:
    """Fill in Twilio settings from the Twilio CLI login when they aren't set. Returns warnings."""
    warn = []
    has_creds = env.get("TWILIO_AUTH_TOKEN") or env.get("TWILIO_API_SECRET") or env.get("KETTLE_TWILIO_PROFILE")
    if not has_creds:
        try:
            cfg = json.loads((pathlib.Path.home() / ".twilio-cli/config.json").read_text())
            env["KETTLE_TWILIO_PROFILE"] = next(iter(cfg["profiles"]))
        except Exception:
            warn.append("no Twilio credentials found: texts stay simulated (in-app only)")
    env.setdefault("TWILIO_FROM", TWILIO_FROM_DEFAULT)
    return warn


class Show:
    def __init__(self, base: str, hub: str):
        self.base, self.hub = base.rstrip("/"), hub.rstrip("/")
        self.http = httpx.Client(timeout=10)
        self.state: dict = {}
        self.button: dict = {}
        self.urls: dict = {}
        self.msg = ""

    def post(self, path: str, **kw) -> dict:
        r = self.http.post(self.base + path, **kw)
        r.raise_for_status()
        return r.json()

    def refresh(self) -> None:
        try:
            self.state = self.http.get(self.base + "/api/demo/show").json()
        except Exception as e:
            self.state = {"error": str(e)}
        try:
            self.button = self.http.get(self.hub + "/api/status", timeout=2).json().get("button", {})
        except Exception:
            self.button = {}

    def wait_up(self, seconds: float = 20) -> bool:
        t0 = time.time()
        while time.time() - t0 < seconds:
            try:
                st = self.http.get(self.base + "/api/state", timeout=2).json()
                if next((h for h in st["homes"] if h["id"] == "margaret"), {}).get("device", {}).get("online"):
                    return True
            except Exception:
                pass
            time.sleep(0.5)
        return False

    def draw(self) -> None:
        s = self.state.get("show") or {}
        step = s.get("step", 0)
        usual = s.get("usual_min", 510)
        b = self.button
        btn = (f"{GRN}big button ✓{RST}" if b.get("connected") else
               f"{YEL}big button not connected{RST}" if b.get("enabled") else f"{DIM}no big button{RST}")
        texts = self.state.get("twilio") == "twilio"
        out = [CLR, f"{BOLD}Kettle · presenter{RST}   clock {BOLD}{self.state.get('clock', '–')}{RST}"
               f" · usual {self.state.get('usual') or fmt(usual)} · {btn} · "
               + (f"{GRN}real SMS on{RST}" if texts else f"{DIM}SMS simulated{RST}"), ""]
        esc = self.state.get("step")
        for i, (_, title, what, say) in enumerate(STEPS):
            t = fmt(usual + [1, 4, 24, 31][i])
            if i < step:
                out.append(f"  {GRN}✓ {i + 1}  {t}  {title}{RST}")
            elif i == step:
                out.append(f"  {BOLD}▸ {i + 1}  {t}  {title}{RST}   {DIM}{what}{RST}")
                out.append(f"       {YEL}say: {say.format(usual=fmt(usual), t1=fmt(usual + 1))}{RST}")
            else:
                out.append(f"  {DIM}  {i + 1}  {t}  {title}{RST}")
        if esc == "resolved" or step >= len(STEPS):
            out.append(f"\n  {GRN}{BOLD}Margaret is fine. End of the story.{RST}  {DIM}R to run it again{RST}")
        out.append("")
        for o in (self.state.get("outbox") or [])[:6]:
            via = o.get("via")
            col = GRN if via == "twilio" else DIM
            out.append(f"  {DIM}{o.get('hhmm')}{RST} {o.get('channel'):5} → {o.get('to'):9} {col}{via:9}{RST} {o.get('text', '')[:70]}")
        if self.urls.get("site"):
            out.append(f"\n  {DIM}phones: {self.urls['site']}   ·   host page: {self.urls['host']}{RST}")
            out.append(f"  {DIM}no internet? phones on the same Wi-Fi: {self.urls.get('priya')} (and ?c=daniel, ?c=margaret){RST}")
        elif self.urls:
            out.append(f"\n  {DIM}phones: Margaret {self.urls.get('hub')}  ·  Priya {self.urls.get('priya')}  ·  "
                       f"Daniel {self.urls.get('daniel')}{RST}")
        out.append(f"\n  {DIM}SPACE next · R restart · Q quit{RST}  {self.msg}")
        sys.stdout.write("\n".join(out) + "\n")
        sys.stdout.flush()


def keys(timeout: float):
    """One keypress (or None after `timeout` seconds). stdin must be in cbreak mode."""
    r, _, _ = select.select([sys.stdin], [], [], timeout)
    return sys.stdin.read(1) if r else None


def run_loop(show: Show) -> None:
    import termios
    import tty
    tty_ok = sys.stdin.isatty()
    old = termios.tcgetattr(sys.stdin) if tty_ok else None
    if tty_ok:
        tty.setcbreak(sys.stdin)
    try:
        while True:
            show.refresh()
            show.draw()
            k = keys(1.0) if tty_ok else (sys.stdin.readline()[:1] or "q")
            if k is None:
                continue
            k = k.lower()
            try:
                if k in (" ", "\n", "\r", "n"):
                    show.post("/api/demo/show/next")
                    show.msg = ""
                elif k == "r":
                    show.post("/api/demo/show/reset")
                    show.msg = f"{DIM}restarted{RST}"
                elif k == "q":
                    return
            except Exception as e:
                show.msg = f"{RED}{e}{RST}"
    finally:
        if old:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old)


def main(argv: list[str]) -> None:
    ap = argparse.ArgumentParser(prog="kettle show", description=__doc__.split("\n\n")[0])
    ap.add_argument("--usual", default="8:30", help="Margaret's usual first kettle (default 8:30)")
    ap.add_argument("--phone", action="append", default=[], metavar="WHO=+1…",
                    help="real phone for margaret, priya, tom or daniel (repeatable)")
    ap.add_argument("--call", action="store_true", help="also ring Margaret's phone (needs --phone margaret=…)")
    ap.add_argument("--no-launch", action="store_true", help="drive an already running `kettle demo`")
    ap.add_argument("--site", default=None, help="public phone site (default: ~/.config/kettle/site.json)")
    ap.add_argument("--offline", action="store_true", help="don't connect to the public phone site")
    ap.add_argument("--port", type=int, default=8700)
    a, edge_args = ap.parse_known_args(argv)
    if not re.fullmatch(r"\d{1,2}:\d{2}", a.usual):
        ap.error("--usual looks like 8:30")
    phones = {}
    for p in a.phone:
        who, _, num = p.partition("=")
        num = num.replace(" ", "").replace("-", "")
        if not re.fullmatch(r"\+\d{8,15}", num):
            ap.error(f"--phone {p}: use WHO=+14035551234")
        phones[who.strip().lower()] = num

    site = None if a.offline else load_site(a.site)
    procs: list[subprocess.Popen] = []
    log_path = pathlib.Path(tempfile.gettempdir()) / "kettle-show.log"
    if not a.no_launch:
        env = dict(os.environ)
        for w in (twilio_env(env) if phones or site else []):
            print(f"  ! {w}")
        if site:
            env["KETTLE_SITE"], env["KETTLE_SITE_SECRET"] = site["url"], site["secret"]
        log = open(log_path, "w")
        py = sys.executable
        procs.append(subprocess.Popen([py, "-m", "kettle", "cloud", "--port", str(a.port)], env=env,
                                      stdout=log, stderr=subprocess.STDOUT))
        time.sleep(1.5)
        edge = edge_args if any(x.startswith("--plug") for x in edge_args) else ["--plug", "sim", *edge_args]
        procs.append(subprocess.Popen([py, "-m", "kettle", "edge", "--cloud", f"ws://127.0.0.1:{a.port}", *edge],
                                      env=env, stdout=log, stderr=subprocess.STDOUT))
        print(f"  starting Kettle (logs: {log_path}) …")

    show = Show(f"http://127.0.0.1:{a.port}", "http://127.0.0.1:8701")
    try:
        if not show.wait_up():
            print(f"  ! the kitchen hub didn't connect; the kettle step will be simulated in the cloud. Logs: {log_path}")
            if any(p.poll() is not None for p in procs):
                print("  ! a server exited; see the log above")
                return
        show.post("/api/demo/show/setup", json={"usual": a.usual, "phones": phones, "call": a.call})
        try:
            u = show.http.get(show.base + "/api/urls").json()
            base = u.get("tailscale") or u.get("best")
            host = base.rsplit(":", 1)[0]
            show.urls = {"priya": f"{base}/phone/?c=priya", "daniel": f"{base}/phone/?c=daniel",
                         "hub": f"{base}/phone/?c=margaret"}
            if site:
                show.urls["site"] = site["url"]
                show.urls["host"] = f"{site['url']}/host/?pin={site.get('pin', '')}"
        except Exception:
            pass
        run_loop(show)
    except KeyboardInterrupt:
        pass
    finally:
        print(RST)
        for p in procs:
            p.send_signal(2)
        for p in procs:
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()
