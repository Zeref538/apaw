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
from dams import DAMS, canonical, catchment_points  # noqa: E402

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

# Rainfall is averaged over a cross of points around each dam rather than read
# at the wall — see dams.catchment_points. Open-Meteo takes many coordinates in
# one request, so the spatial mean costs no extra calls.


class RateLimited(RuntimeError):
    """Open-Meteo's free tier is capped per hour, not per request burst."""


def _get(url: str, params: dict) -> dict:
    """Open-Meteo drops long connections and rate-limits the free tier.

    Catches RequestException, not just ConnectionError: a read timeout is a
    Timeout, which is a sibling rather than a subclass, and slipped straight
    past a narrower handler in CI.
    """
    for attempt in range(4):
        try:
            r = requests.get(url, params=params, timeout=60)
        except requests.exceptions.RequestException:
            time.sleep(3 * (attempt + 1))
            continue
        if r.status_code == 429:
            # The cap is hourly; short retries just burn the remaining budget.
            raise RateLimited(
                "Open-Meteo hourly request limit hit. Existing data is left "
                "untouched; re-run in an hour to continue.")
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"Open-Meteo unreachable after retries: {url}")


def _frame(payload, dam: str, source: str) -> pd.DataFrame:
    """Mean the sampled points into one daily series per dam.

    A multi-coordinate request returns a list, one entry per point; a single
    coordinate returns a bare object.
    """
    parts = payload if isinstance(payload, list) else [payload]
    frames = [pd.DataFrame(p["daily"]).rename(columns={"time": "date"}) for p in parts]
    stacked = pd.concat(frames, ignore_index=True)
    df = stacked.groupby("date", as_index=False).mean(numeric_only=True)
    df.insert(0, "dam", canonical(dam))
    df["source"] = source
    df["n_points"] = len(parts)
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
    for dam in DAMS:
        pts = catchment_points(dam)
        lats = ",".join(str(a) for a, _ in pts)
        lons = ",".join(str(b) for _, b in pts)
        for chunk_start, chunk_end in _year_chunks(start, end):
            payload = _get(ARCHIVE, {
                "latitude": lats, "longitude": lons,
                "start_date": chunk_start.isoformat(),
                "end_date": chunk_end.isoformat(),
                "daily": ",".join(DAILY), "timezone": TZ,
            })
            out.append(_frame(payload, dam, "archive"))
        print(f"  archive {dam}", flush=True)
    return pd.concat(out, ignore_index=True)


def fetch_forecast(past_days: int = 14, forecast_days: int = 7) -> pd.DataFrame:
    out = []
    for dam in DAMS:
        pts = catchment_points(dam)
        payload = _get(FORECAST, {
            "latitude": ",".join(str(a) for a, _ in pts),
            "longitude": ",".join(str(b) for _, b in pts),
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
    # Write via a temp file and swap. A half-finished or rate-limited rebuild
    # must never leave the collected record truncated or missing.
    tmp = out.with_suffix(".csv.tmp")
    combined.to_csv(tmp, index=False)
    tmp.replace(out)
    return combined


def main() -> int:
    # Dam observations only start in 2021 (the Wayback seed), so pulling rain
    # back to 2015 was 6 years of requests nothing could ever join to.
    backfill_from = date(2021, 1, 1) if not OUT.exists() else None

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
