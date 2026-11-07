"""Fetch the real public energy + weather data the demo uses, with provenance.

    .venv/bin/python scripts/fetch_real_data.py

Writes (raw files are kept byte-for-byte, parsed JSON next to them):
  data/aeso/actual_forecast_2024-01-10_2024-01-16.csv   AESO hourly pool price + Alberta Internal Load
  data/aeso/smp_2024-01-13.csv                           AESO System Marginal Price changes, Jan 13 2024
  data/eccc/calgary_intl_hourly_2024-01.csv              Environment and Climate Change Canada, CALGARY INTL A hourly
  data/jan13_2024.json                                   everything above for the replay, + sourced timeline facts

No API keys are needed. AESO ETS reports are public; ECCC climate data is under the
Open Government Licence – Canada.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import pathlib
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

AESO_AF = ("http://ets.aeso.ca/ets_web/ip/Market/Reports/ActualForecastWMRQHReportServlet"
           "?beginDate=01102024&endDate=01162024&contentType=csv")
AESO_SMP = ("http://ets.aeso.ca/ets_web/ip/Market/Reports/HistoricalSystemMarginalPriceReportServlet"
            "?beginDate=01132024&endDate=01142024&contentType=csv")
ECCC = ("https://climate.weather.gc.ca/climate_data/bulk_data_e.html?format=csv&stationID=50430"
        "&Year=2024&Month=1&Day=13&timeframe=1&submit=Download+Data")

TIMELINE = [
    {"t": "2024-01-13T15:30", "text": "AESO declares a Grid Alert (EEA3), step 16 of 22 in its supply-shortfall procedure.",
     "source": "AESO newsroom, Jan 13 2024; Power Advisory, 'January 2024 Supply Shortfall in Alberta'",
     "url": "https://aeso.ca/aeso/newsroom/aeso-thanks-albertans-for-quick-response-to-call-for-power-conservation/"},
    {"t": "2024-01-13T18:44", "text": "Emergency text alert to every phone in Alberta: high risk of rotating outages, cut use to essentials.",
     "source": "Power Advisory (Global News reports ~6:36 pm)",
     "url": "https://www.poweradvisoryllc.com/reports/january-2024-supply-shortfall-in-alberta"},
    {"t": "2024-01-13T18:46", "text": "Demand drops 100 MW immediately, ~200 MW within minutes.",
     "source": "AESO newsroom, Jan 13 2024",
     "url": "https://aeso.ca/aeso/newsroom/aeso-thanks-albertans-for-quick-response-to-call-for-power-conservation/"},
    {"t": "2024-01-13T20:40", "text": "Grid Alert declared ended.",
     "source": "AESO newsroom, Jan 13 2024",
     "url": "https://aeso.ca/aeso/newsroom/aeso-thanks-albertans-for-quick-response-to-call-for-power-conservation/"},
]


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "kettle-hackathon/0.1 (+github)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def num(s: str) -> float | None:
    s = s.replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def parse_actual_forecast(text: str) -> list[dict]:
    rows = []
    for rec in csv.reader(io.StringIO(text)):
        if len(rec) < 5 or "/" not in rec[0]:
            continue
        date, he = rec[0].rsplit(" ", 1)
        d = dt.datetime.strptime(date, "%m/%d/%Y").date()
        # "HE 19" = hour ending 19:00, i.e. 18:00-19:00 local (MST)
        start = dt.datetime.combine(d, dt.time()) + dt.timedelta(hours=int(he) - 1)
        rows.append({"hour_start": start.isoformat(timespec="minutes"), "he": int(he),
                     "pool_price_forecast": num(rec[1]), "pool_price": num(rec[2]),
                     "ail_forecast_mw": num(rec[3]), "ail_mw": num(rec[4])})
    return rows


def parse_smp(text: str) -> list[dict]:
    rows = []
    for rec in csv.reader(io.StringIO(text)):
        if len(rec) < 3 or "/" not in rec[0]:
            continue
        date = rec[0].rsplit(" ", 1)[0]
        d = dt.datetime.strptime(date, "%m/%d/%Y").date()
        hh, mm = rec[1].split(":")
        t = dt.datetime.combine(d, dt.time()) + dt.timedelta(hours=int(hh), minutes=int(mm))
        rows.append({"t": t.isoformat(timespec="minutes"),
                     "smp": num(rec[2])})
    return sorted(rows, key=lambda r: r["t"])


def parse_eccc(text: str) -> list[dict]:
    rows = []
    for rec in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
        temp = num(rec.get("Temp (°C)", ""))
        rows.append({"t": rec["Date/Time (LST)"].replace(" ", "T"), "temp_c": temp,
                     "wind_kmh": num(rec.get("Wind Spd (km/h)", "")),
                     "wind_chill": num(rec.get("Wind Chill", "")),
                     "weather": rec.get("Weather", "")})
    return rows


def main() -> None:
    (DATA / "aeso").mkdir(parents=True, exist_ok=True)
    (DATA / "eccc").mkdir(parents=True, exist_ok=True)
    fetched = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    af_raw = get(AESO_AF)
    (DATA / "aeso/actual_forecast_2024-01-10_2024-01-16.csv").write_bytes(af_raw)
    smp_raw = get(AESO_SMP)
    (DATA / "aeso/smp_2024-01-13.csv").write_bytes(smp_raw)
    ec_raw = get(ECCC)
    (DATA / "eccc/calgary_intl_hourly_2024-01.csv").write_bytes(ec_raw)

    hourly = parse_actual_forecast(af_raw.decode("latin-1"))
    smp = [r for r in parse_smp(smp_raw.decode("latin-1")) if r["t"].startswith("2024-01-13")]
    weather = [r for r in parse_eccc(ec_raw.decode("utf-8", "replace"))
               if "2024-01-10" <= r["t"][:10] <= "2024-01-16"]

    coldest = min((w for w in weather if w["temp_c"] is not None), key=lambda w: w["temp_c"])
    out = {
        "title": "Alberta grid emergency, January 13 2024",
        "timezone": "America/Edmonton (MST, UTC-7). AESO hours are 'hour ending'; hour_start is the start of that hour.",
        "fetched_at": fetched,
        "sources": {
            "aeso_hourly": {"url": AESO_AF, "what": "AESO Actual/Forecast report: hourly pool price ($/MWh) and Alberta Internal Load (MW)"},
            "aeso_smp": {"url": AESO_SMP, "what": "AESO Historical System Marginal Price report ($/MWh), every price change"},
            "eccc_hourly": {"url": ECCC, "what": "Environment and Climate Change Canada historical hourly data, CALGARY INTL A (station 50430), LST",
                            "licence": "Open Government Licence - Canada"},
        },
        "facts": {
            "price_cap": 999.99,
            "hours_at_cap_jan13": sum(1 for h in hourly if h["hour_start"].startswith("2024-01-13") and (h["pool_price"] or 0) >= 999.99),
            "peak_ail_mw_week": max(h["ail_mw"] for h in hourly if h["ail_mw"]),
            "peak_ail_hour": max(hourly, key=lambda h: h["ail_mw"] or 0)["hour_start"],
            "coldest_c": coldest["temp_c"], "coldest_t": coldest["t"],
        },
        "timeline": TIMELINE,
        "hourly": hourly,
        "smp": smp,
        "weather": weather,
    }
    (DATA / "jan13_2024.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out["facts"], indent=1))
    print(f"hourly={len(hourly)} smp={len(smp)} weather={len(weather)}")


if __name__ == "__main__":
    main()
