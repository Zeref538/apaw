"""What the rain forecast actually said, at the lead time we would have had.

The backtest's biggest lie was using ERA5 observed rain for the days ahead —
training on rainfall nobody could have known. Open-Meteo's previous-runs API
archives each model run, so `precipitation_previous_dayN` on date D is the
rain predicted for D by the run issued N days earlier. That is exactly the
number a forecast issued on D-N had in hand.

Two limits worth knowing:
  * The archive only reaches back to 2025 (2024 and earlier return nulls), so
    rows before that keep the ERA5 proxy and are marked as such.
  * Only the hourly variables expose previous_dayN, so hours are summed here
    into daily totals.

Output: data/rain_forecast.csv, one row per (dam, date, lead), where `lead` is
how many days ahead the forecast was made.
"""

from __future__ import annotations

import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).parent))
from dams import DAMS  # noqa: E402

API = "https://previous-runs-api.open-meteo.com/v1/forecast"
OUT = Path(__file__).parent / "rain_forecast.csv"
ARCHIVE_STARTS = date(2025, 1, 1)   # earlier dates come back null
LEADS = range(1, 8)
TZ = "Asia/Manila"
KEY = ["dam", "date", "lead"]


def _get(params: dict) -> dict:
    for attempt in range(4):
        try:
            r = requests.get(API, params=params, timeout=180)
        except requests.exceptions.RequestException:
            time.sleep(4 * (attempt + 1))
            continue
        if r.status_code == 429:
            time.sleep(15 * (attempt + 1))
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("previous-runs API unreachable after retries")


def _chunks(start: date, end: date, days: int = 180):
    cur = start
    while cur <= end:
        stop = min(cur + timedelta(days=days - 1), end)
        yield cur, stop
        cur = stop + timedelta(days=1)


def fetch(start: date, end: date) -> pd.DataFrame:
    """Daily rainfall totals per lead time, per dam."""
    variables = [f"precipitation_previous_day{n}" for n in LEADS]
    rows = []
    for dam, meta in DAMS.items():
        for a, b in _chunks(start, end):
            payload = _get({
                "latitude": meta["lat"], "longitude": meta["lon"],
                "start_date": a.isoformat(), "end_date": b.isoformat(),
                "hourly": ",".join(variables), "timezone": TZ,
            })
            hourly = pd.DataFrame(payload["hourly"])
            hourly["date"] = pd.to_datetime(hourly["time"]).dt.date.astype(str)
            for n in LEADS:
                col = f"precipitation_previous_day{n}"
                if col not in hourly:
                    continue
                daily = hourly.groupby("date")[col].sum(min_count=1).reset_index()
                daily = daily[daily[col].notna()]
                daily["dam"] = dam
                daily["lead"] = n
                daily = daily.rename(columns={col: "rain_mm"})
                rows.append(daily[["dam", "date", "lead", "rain_mm"]])
        print(f"  {dam}", flush=True)
    if not rows:
        return pd.DataFrame(columns=KEY + ["rain_mm"])
    return pd.concat(rows, ignore_index=True)


def merge(new: pd.DataFrame, out: Path = OUT) -> pd.DataFrame:
    frames = [pd.read_csv(out)] if out.exists() else []
    combined = pd.concat(frames + [new], ignore_index=True)
    combined = (combined.drop_duplicates(subset=KEY, keep="last")
                .sort_values(KEY).reset_index(drop=True))
    combined.to_csv(out, index=False)
    return combined


def main() -> int:
    end = date.today() + timedelta(days=7)
    if OUT.exists():
        seen = pd.read_csv(OUT)
        start = max(ARCHIVE_STARTS,
                    pd.to_datetime(seen["date"]).max().date() - timedelta(days=10))
    else:
        start = ARCHIVE_STARTS
    print(f"lead-time rain forecasts {start} -> {end}")
    combined = merge(fetch(start, end))
    print(f"{len(combined)} rows, {combined['date'].min()} .. {combined['date'].max()}"
          f" -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
