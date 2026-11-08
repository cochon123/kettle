"""Persistence in TimescaleDB, optional.

Set KETTLE_DB (e.g. postgresql://kettle:kettle@localhost:5433/kettle) to persist
events, escalations and grid context into hypertables; the rhythm baselines
are then rebuilt on start-up from the `daily_activity` continuous aggregate.

Without KETTLE_DB (or if the database is unreachable) everything still works
in memory: a demo must never die because a database container did.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import pathlib

log = logging.getLogger("kettle.store")
SCHEMA = pathlib.Path(__file__).resolve().parents[2] / "db/schema.sql"


class Store:
    def __init__(self) -> None:
        self.dsn = os.getenv("KETTLE_DB")
        self.conn = None
        self.status = "memory"

    async def open(self) -> None:
        if not self.dsn:
            return
        try:
            import psycopg
            self.conn = await psycopg.AsyncConnection.connect(self.dsn, autocommit=True)
            # Apply schema statement by statement (continuous aggregates can't run in a transaction block).
            for stmt in _statements(SCHEMA.read_text()):
                try:
                    await self.conn.execute(stmt)
                except Exception as e:
                    if "already exists" not in str(e):
                        log.warning("schema: %s -> %s", stmt.splitlines()[0][:60], e)
            self.status = "timescaledb"
            log.info("TimescaleDB connected")
        except Exception as e:
            log.warning("TimescaleDB unavailable (%s); running in memory", e)
            self.conn, self.status = None, f"memory (db error: {str(e)[:60]})"

    async def _exec(self, sql: str, args: tuple) -> None:
        if not self.conn:
            return
        try:
            await self.conn.execute(sql, args)
        except Exception as e:
            log.warning("db write failed: %s", e)

    async def upsert_home(self, home_id: str, person: str, pronoun: str) -> None:
        await self._exec("INSERT INTO homes (id, person, pronoun) VALUES (%s,%s,%s) "
                         "ON CONFLICT (id) DO UPDATE SET person=EXCLUDED.person, pronoun=EXCLUDED.pronoun",
                         (home_id, person, pronoun))

    async def event(self, home_id: str, ev: dict) -> None:
        await self._exec(
            "INSERT INTO events (time, home_id, channel, kind, label, human, dp_w, duration_s, confidence, detail) "
            "VALUES (to_timestamp(%s),%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (ev["t"], home_id, ev.get("channel", "?"), ev.get("kind", "on"), ev.get("label", "unknown"),
             bool(ev.get("human")), ev.get("dp_w"), ev.get("duration_s"), ev.get("confidence"),
             json.dumps({k: v for k, v in ev.items() if k in ("alternatives", "flatness_cv", "t_device", "source")})))

    async def context(self, t: float, source: str, metrics: dict) -> None:
        for k, v in metrics.items():
            if isinstance(v, (int, float)):
                await self._exec("INSERT INTO context_readings (time, source, metric, value) VALUES (to_timestamp(%s),%s,%s,%s)",
                                 (t, source, k, float(v)))

    async def escalation(self, e: dict) -> None:
        await self._exec(
            "INSERT INTO escalations (id, home_id, started_at, reason, step, resolution, resolved_at, log) "
            "VALUES (%s,%s,to_timestamp(%s),%s,%s,%s,to_timestamp(%s),%s) "
            "ON CONFLICT (id) DO UPDATE SET step=EXCLUDED.step, resolution=EXCLUDED.resolution, "
            "resolved_at=EXCLUDED.resolved_at, log=EXCLUDED.log",
            (e["id"], e["home_id"], e["started_at"], e["reason"], e["step"], e["resolution"],
             e["resolved_at"], json.dumps(e["log"])))

    async def daily_first(self, home_id: str, days: int = 35) -> list[tuple[dt.date, float]]:
        """(day, minutes after midnight) from the continuous aggregate (real-time aggregation on)."""
        if not self.conn:
            return []
        try:
            cur = await self.conn.execute(
                "SELECT (day AT TIME ZONE 'America/Edmonton')::date, "
                "EXTRACT(EPOCH FROM (first_human AT TIME ZONE 'America/Edmonton')::time)/60 "
                "FROM daily_activity WHERE home_id=%s AND first_human IS NOT NULL "
                "AND day > now() - make_interval(days => %s) ORDER BY day", (home_id, days))
            # an after-midnight "first" activity belongs to the end of that Kettle day
            return [(r[0], float(r[1]) + (1440 if float(r[1]) < 240 else 0)) for r in await cur.fetchall()]
        except Exception as e:
            log.warning("daily_first failed: %s", e)
            return []


def _statements(sql: str) -> list[str]:
    lines = [ln for ln in sql.splitlines() if not ln.strip().startswith("--")]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]
