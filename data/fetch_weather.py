"""Fetch daily rainfall/temperature per dam from Open-Meteo (free, no key).

Two endpoints, one table:
  archive  — ERA5 reanalysis, 1940-present, ~5 day lag. History and training.
  forecast — the next 7 days, plus recent past days to bridge the archive lag.

The forecast rows are what make a 1-7 day dam-level forecast operational
rather than merely autoregressive: tomorrow's rainfall is a known input.
"""

from __future__ import annotations

import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

# Importable both as `python data/fetch_weather.py` and `from data import ...`.
sys.path.insert(0, str(Path(__file__).parent))
from dams import DAMS, canonical  # noqa: E402

ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
FORECAST = "https://api.open-meteo.com/v1/forecast"
OUT = Path(__file__).parent / "weather.csv"

DAILY = [
    "precipitation_sum",
    "temperature_2m_mean",
    "temperature_2m_max",
    "relative_humidity_2m_mean",
    "et0_fao_evapotranspiration",
]
TZ = "Asia/Manila"
KEY = ["dam", "date"]

# ponytail: rainfall sampled at the dam wall, not averaged over the upstream
# catchment. Catchment-mean rainfall is the physically right input; upgrade to
# a polygon mean (or a few upstream points per dam) if the point value proves
# too weak a predictor of inflow.


def _get(url: str, params: dict) -> dict:
    """Open-Meteo drops long connections and rate-limits the free tier."""
    for attempt in range(4):
        try:
            r = requests.get(url, params=params, timeout=60)
        except requests.exceptions.ConnectionError:
            time.sleep(3 * (attempt + 1))
            continue
        if r.status_code == 429:
            time.sleep(10 * (attempt + 1))
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"Open-Meteo unreachable after retries: {url}")


def _frame(payload: dict, dam: str, source: str) -> pd.DataFrame:
    df = pd.DataFrame(payload["daily"]).rename(columns={"time": "date"})
    df.insert(0, "dam", canonical(dam))
    df["source"] = source
    return df


def _year_chunks(start: date, end: date):
    """A decade of 5 variables in one request gets the connection reset."""
    cur = start
    while cur <= end:
        stop = min(date(cur.year, 12, 31), end)
        yield cur, stop
        cur = stop + timedelta(days=1)


def fetch_archive(start: date, end: date) -> pd.DataFrame:
    out = []
    for dam, meta in DAMS.items():
        for chunk_start, chunk_end in _year_chunks(start, end):
            payload = _get(ARCHIVE, {
                "latitude": meta["lat"], "longitude": meta["lon"],
                "start_date": chunk_start.isoformat(),
                "end_date": chunk_end.isoformat(),
                "daily": ",".join(DAILY), "timezone": TZ,
            })
            out.append(_frame(payload, dam, "archive"))
        print(f"  archive {dam}", flush=True)
    return pd.concat(out, ignore_index=True)


def fetch_forecast(past_days: int = 14, forecast_days: int = 7) -> pd.DataFrame:
    out = []
    for dam, meta in DAMS.items():
        payload = _get(FORECAST, {
            "latitude": meta["lat"], "longitude": meta["lon"],
            "daily": ",".join(DAILY), "timezone": TZ,
            "past_days": past_days, "forecast_days": forecast_days,
        })
        out.append(_frame(payload, dam, "forecast"))
    return pd.concat(out, ignore_index=True)


def merge(new: pd.DataFrame, out: Path = OUT) -> pd.DataFrame:
    """Archive beats forecast for the same day — reanalysis is the better truth.

    Forecast rows are provisional and must be overwritten once the archive
    catches up, otherwise the model trains on predicted rain as if observed.
    """
    frames = [pd.read_csv(out)] if out.exists() else []
    combined = pd.concat(frames + [new], ignore_index=True)
    combined["_rank"] = (combined["source"] == "archive").astype(int)
    combined = (
        combined.sort_values(KEY + ["_rank"])
        .drop_duplicates(subset=KEY, keep="last")
        .drop(columns="_rank")
        .sort_values(KEY)
    )
    combined.to_csv(out, index=False)
    return combined


def main() -> int:
    backfill_from = date(2015, 1, 1) if not OUT.exists() else None

    if backfill_from:
        print(f"first run: pulling archive from {backfill_from}")
        archive = fetch_archive(backfill_from, date.today() - timedelta(days=6))
    else:
        # Refresh the trailing window so provisional forecast rows get replaced
        # by reanalysis as it lands.
        archive = fetch_archive(date.today() - timedelta(days=30),
                                date.today() - timedelta(days=6))

    combined = merge(pd.concat([archive, fetch_forecast()], ignore_index=True))
    print(f"weather: {len(combined)} rows, "
          f"{combined['date'].min()} to {combined['date'].max()} -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
