"""Outbound channels: voice call to the person, SMS to circle members.

Credentials, first match wins:
  * TWILIO_ACCOUNT_SID + TWILIO_AUTH_TOKEN
  * TWILIO_ACCOUNT_SID + TWILIO_API_KEY + TWILIO_API_SECRET
  * KETTLE_TWILIO_PROFILE=<name>: read the API key from the Twilio CLI's ~/.twilio-cli/config.json
plus TWILIO_FROM (a Twilio number you own). With all of that, real calls and
texts go out through Twilio's REST API. Otherwise every message is recorded as
"simulated" so the demo (and the stage screen) shows exactly what would be sent.
Nothing here is required for the in-app circle notifications, which go over
WebSocket.
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
from xml.sax.saxutils import escape

import httpx

log = logging.getLogger("kettle.notify")


class Notifier:
    def __init__(self) -> None:
        self.sid = os.getenv("TWILIO_ACCOUNT_SID")
        user, pw = self.sid, os.getenv("TWILIO_AUTH_TOKEN")
        if not pw and os.getenv("TWILIO_API_KEY"):
            user, pw = os.getenv("TWILIO_API_KEY"), os.getenv("TWILIO_API_SECRET")
        profile = os.getenv("KETTLE_TWILIO_PROFILE")
        if not pw and profile:
            try:
                cfg = json.loads((pathlib.Path.home() / ".twilio-cli/config.json").read_text())
                prof = cfg["profiles"][profile]
                self.sid, user, pw = prof["accountSid"], prof["apiKey"], prof["apiSecret"]
            except Exception as e:
                log.warning("could not read Twilio CLI profile %s: %s", profile, e)
        self.auth = (user, pw) if (user and pw) else None
        self.from_ = os.getenv("TWILIO_FROM")
        self.public_url = os.getenv("KETTLE_PUBLIC_URL", "").rstrip("/")
        self.enabled = bool(self.sid and self.auth and self.from_)
        if self.auth and not self.from_:
            log.warning("Twilio credentials found but TWILIO_FROM is not set: calls/SMS stay simulated")

    @property
    def via(self) -> str:
        return "twilio" if self.enabled else "simulated"

    def _twiml_call(self, text: str, gather_url: str | None) -> str:
        say = f'<Say voice="Polly.Joanna">{escape(text)}</Say>'
        if gather_url:
            return (f'<Response><Gather numDigits="1" timeout="12" action="{escape(gather_url)}">{say}</Gather>'
                    f'<Say>Okay. Goodbye.</Say></Response>')
        return f"<Response>{say}<Pause length=\"2\"/>{say}</Response>"

    async def call(self, to: str | None, text: str, gather_path: str | None = None) -> dict:
        if not (self.enabled and to):
            return {"via": "simulated", "ok": True}
        gather = f"{self.public_url}{gather_path}" if (self.public_url and gather_path) else None
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.post(f"https://api.twilio.com/2010-04-01/Accounts/{self.sid}/Calls.json",
                                 auth=self.auth,
                                 data={"To": to, "From": self.from_, "Twiml": self._twiml_call(text, gather),
                                       "Timeout": "25"})
            ok = r.status_code < 300
            if not ok:
                log.warning("twilio call failed %s %s", r.status_code, r.text[:200])
            return {"via": "twilio", "ok": ok, "sid": r.json().get("sid") if ok else None}
        except Exception as e:  # never let a telecom error break the escalation
            log.warning("twilio call error: %s", e)
            return {"via": "twilio", "ok": False, "error": str(e)}

    async def sms(self, to: str | None, text: str) -> dict:
        if not (self.enabled and to):
            return {"via": "simulated", "ok": True}
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.post(f"https://api.twilio.com/2010-04-01/Accounts/{self.sid}/Messages.json",
                                 auth=self.auth, data={"To": to, "From": self.from_, "Body": text})
            return {"via": "twilio", "ok": r.status_code < 300}
        except Exception as e:
            log.warning("twilio sms error: %s", e)
            return {"via": "twilio", "ok": False, "error": str(e)}
