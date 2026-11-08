"""The physical "I'm fine" button, with its light, on USB serial.

Board: an Arduino UNO R4 Minima running firmware/kettle-r4 (big button on D2,
light inside the button on D9). Wiring: docs/wiring.html.

Line protocol, 115200 baud:
    hub -> board   off | pulse | glow | on | ping
    board -> hub   ready | fine | mode <name> | pong

The hub owns the state and the board only shows it:
    a check-in is waiting       -> pulse   ("press me")
    someone sent a warm glow    -> glow    (steady, for 60 s)
    otherwise, or in a power cut -> off
A press sends "I'm fine", exactly like the button on the kitchen display.
The hub works the same without the board; it keeps looking for one.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Awaitable, Callable

log = logging.getLogger("kettle.button")

ARDUINO_VID = 0x2341
BAUD = 115200
RESEND_S = 5.0          # re-assert the light now and then, in case the board rebooted
RETRY_S = 3.0


def light_for(ui: dict, now: float, outage: bool = False) -> str:
    """What the button's light should show for the hub's current UI state."""
    if outage:
        return "off"
    if ui.get("checkin"):
        return "pulse"
    glow = ui.get("glow")
    if glow and glow.get("until", 0) > now:
        return "glow"
    return "off"


def find_port() -> str | None:
    """The first Arduino (USB vendor 0x2341) serial port, if any."""
    from serial.tools import list_ports
    for p in list_ports.comports():
        if p.vid == ARDUINO_VID:
            return p.device
    return None


def parse_spec(spec: str) -> tuple[bool, str | None]:
    """'auto' -> (True, None); 'none' -> (False, None); 'serial:/dev/x' or '/dev/x' -> (True, '/dev/x')."""
    spec = (spec or "auto").strip()
    if spec in ("none", "off", "no"):
        return False, None
    if spec == "auto":
        return True, None
    return True, spec.removeprefix("serial:")


class Button:
    def __init__(self, spec: str, on_press: Callable[[], Awaitable[None]], get_light: Callable[[], str],
                 on_change: Callable[[], Awaitable[None]] | None = None, opener=None):
        self.enabled, self.fixed_port = parse_spec(spec)
        self.on_press, self.get_light, self.on_change = on_press, get_light, on_change
        self.opener = opener                    # tests inject a fake serial port here
        self.connected = False
        self.port: str | None = None
        self.light: str | None = None
        self.presses = 0
        self.err: str | None = None if self.enabled else "disabled"

    def status(self) -> dict:
        return {"enabled": self.enabled, "connected": self.connected, "port": self.port,
                "light": self.light, "presses": self.presses, "err": self.err}

    async def _changed(self) -> None:
        if self.on_change:
            with contextlib.suppress(Exception):
                await self.on_change()

    def _open(self, port: str):
        if self.opener:
            return self.opener(port)
        import serial
        return serial.Serial(port, BAUD, timeout=0.2)

    async def run(self) -> None:
        if not self.enabled:
            return
        if not self.opener:
            try:
                import serial  # noqa: F401
            except ImportError:
                self.err = "pyserial not installed"
                log.warning("button: pyserial not installed; run: pip install pyserial")
                return
        warned = False
        while True:
            port = self.fixed_port or await asyncio.to_thread(find_port)
            if not port:
                self.err = "no board found"
                if not warned:
                    log.info("button: no Arduino found; will keep looking")
                    warned = True
                await asyncio.sleep(RETRY_S)
                continue
            try:
                ser = await asyncio.to_thread(self._open, port)
            except Exception as e:
                self.err = f"cannot open {port}: {e}"[:120]
                await asyncio.sleep(RETRY_S)
                continue
            self.connected, self.port, self.err, self.light = True, port, None, None
            warned = False
            log.info("button: connected on %s", port)
            await self._changed()
            try:
                await self._session(ser)
            except asyncio.CancelledError:
                with contextlib.suppress(Exception):
                    ser.write(b"off\n")             # leave the kitchen dark when the hub stops
                raise
            except Exception as e:
                self.err = f"lost: {e}"[:120]
                log.info("button: lost the board: %s", e)
            finally:
                with contextlib.suppress(Exception):
                    ser.close()
                self.connected, self.light = False, None
                await self._changed()
            await asyncio.sleep(1.0)

    async def _session(self, ser) -> None:
        last_sent = 0.0
        while True:
            raw = await asyncio.to_thread(ser.readline)
            text = raw.decode(errors="replace").strip() if raw else ""
            if text == "fine":
                self.presses += 1
                log.info("button: pressed (\"I'm fine\")")
                await self.on_press()
            elif text == "ready":
                self.light = None                   # the board restarted: send the light again
            want = self.get_light()
            now = time.monotonic()
            if want != self.light or now - last_sent > RESEND_S:
                await asyncio.to_thread(ser.write, f"{want}\n".encode())
                last_sent = now
                if want != self.light:
                    self.light = want
                    await self._changed()
