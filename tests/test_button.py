"""The physical "I'm fine" button: light state from the hub, presses back to the hub."""
import asyncio
import threading
import time

from kettle.edge.button import Button, light_for, parse_spec
from kettle.edge.hub import Hub


class FakeBoard:
    """Stands in for the UNO R4 serial port: records what the hub writes, plays back lines."""

    def __init__(self):
        self.written: list[str] = []
        self.incoming: list[bytes] = []
        self.lock = threading.Lock()
        self.closed = False

    def readline(self) -> bytes:
        time.sleep(0.01)
        with self.lock:
            return self.incoming.pop(0) if self.incoming else b""

    def write(self, data: bytes) -> int:
        self.written.append(data.decode().strip())
        return len(data)

    def close(self) -> None:
        self.closed = True

    def say(self, line: str) -> None:
        with self.lock:
            self.incoming.append((line + "\r\n").encode())


def test_light_follows_hub_state():
    now = 1000.0
    assert light_for({"checkin": None, "glow": None}, now) == "off"
    assert light_for({"checkin": "Good morning Margaret…"}, now) == "pulse"
    assert light_for({"checkin": None, "glow": {"from": "Priya", "until": now + 30}}, now) == "glow"
    assert light_for({"checkin": None, "glow": {"from": "Priya", "until": now - 1}}, now) == "off"
    # a check-in outranks a glow; a (simulated) power cut darkens everything
    assert light_for({"checkin": "…", "glow": {"until": now + 30}}, now) == "pulse"
    assert light_for({"checkin": "…"}, now, outage=True) == "off"


def test_parse_spec():
    assert parse_spec("auto") == (True, None)
    assert parse_spec("none") == (False, None)
    assert parse_spec("serial:/dev/ttyACM0") == (True, "/dev/ttyACM0")
    assert parse_spec("/dev/ttyUSB1") == (True, "/dev/ttyUSB1")


def test_press_and_light_over_serial():
    async def go():
        board = FakeBoard()
        state = {"light": "off"}
        presses = []

        async def on_press():
            presses.append(time.time())
            state["light"] = "off"          # the hub clears the check-in on "I'm fine"

        b = Button("serial:/dev/fake", on_press=on_press, get_light=lambda: state["light"], opener=lambda port: board)
        task = asyncio.create_task(b.run())
        await asyncio.sleep(0.15)
        assert b.connected and b.port == "/dev/fake"
        assert board.written[-1] == "off"

        state["light"] = "pulse"            # cloud asked Margaret to check in
        await asyncio.sleep(0.15)
        assert board.written[-1] == "pulse" and b.light == "pulse"

        board.say("fine")                   # she presses the big button
        await asyncio.sleep(0.15)
        assert len(presses) == 1 and b.presses == 1
        assert board.written[-1] == "off"

        n = len(board.written)
        board.say("ready")                  # board rebooted: the hub re-sends the light
        await asyncio.sleep(0.15)
        assert len(board.written) > n and board.written[-1] == "off"

        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert board.closed and board.written[-1] == "off"
    asyncio.run(go())


def test_disabled_button_does_nothing():
    async def go():
        b = Button("none", on_press=None, get_light=lambda: "off")
        await asyncio.wait_for(b.run(), 1)
        assert b.status()["enabled"] is False and not b.connected
    asyncio.run(go())


def test_hub_press_clears_checkin_and_light():
    async def go():
        hub = Hub("margaret", "sim", "ws://127.0.0.1:1", "k", 75.0, button="none")
        hub.ui["checkin"] = "Good morning Margaret. Press the button if you're okay."
        assert light_for(hub.ui, time.time()) == "pulse"
        await hub.button.on_press()
        assert hub.ui["checkin"] is None
        assert hub.button.get_light() == "off"
        assert hub.status()["button"]["enabled"] is False
    asyncio.run(go())
