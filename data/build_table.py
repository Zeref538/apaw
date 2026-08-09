"""Join dam levels with weather into the modelling table.

One row per (dam, issue date, horizon). Target is the CHANGE in reservoir
water level over the horizon, not the level itself: levels are so
autocorrelated that predicting them looks impressive while beating nothing,
and differencing forces an honest comparison against persistence.

Only rows whose t+h observation actually exists get a target. With the sparse
Wayback seed that is mostly h=1; longer horizons fill in as the collector
accrues its own daily history.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from dams import DAMS, canonical  # noqa: E402

HERE = Path(__file__).parent
LEVELS = HERE / "dam_levels.csv"
WEATHER = HERE / "weather.csv"
RAIN_FCST = HERE / "rain_forecast.csv"
BASINS = HERE / "basin_status.csv"
OUT = HERE / "modeling_table.csv"

HORIZONS = range(1, 8)
RAIN_WINDOWS = (1, 3, 7, 14, 30)

# Forward rainfall prefers the real archived forecast at the lead time we would
# have had (data/rain_forecast.csv). Open-Meteo's previous-runs archive only
# reaches back to 2025, so earlier rows fall back to ERA5 observed rain — a
# perfect-foresight proxy that flatters them. Every row records which it got in
# `fcst_source`, and the backtest reports the two separately so the optimism is
# measured rather than assumed away.


def daily_levels() -> pd.DataFrame:
    """Collapse to one observation per dam-day (PAGASA's 08:00 reading).

    The scraped `dev_24h_m` column is NOT usable as a feature: PAGASA prints a
    single 24-hour deviation per snapshot, and the page shows it against both
    the today row and the yesterday row. On the yesterday row that number is
    the change from t to t+1 — the future. Using it as-is let a naive drift
    baseline "predict" the next day to 0.05 m.

    So the deviation is recomputed here from our own series, and is defined
    only where the preceding calendar day was actually observed.
    """
    df = pd.read_csv(LEVELS)
    df["obs_datetime"] = pd.to_datetime(df["obs_datetime"])
    df["date"] = df["obs_datetime"].dt.normalize()
    df = (df.sort_values("obs_datetime")
            .drop_duplicates(subset=["dam", "date"], keep="first")
            .rename(columns={"dev_24h_m": "dev_24h_reported"})
            .sort_values(["dam", "date"]))

    g = df.groupby("dam", group_keys=False)
    prev_rwl = g["rwl_m"].shift(1)
    prev_date = g["date"].shift(1)
    consecutive = (df["date"] - prev_date) == pd.to_timedelta(1, unit="D")
    df["dev_24h_m"] = (df["rwl_m"] - prev_rwl).where(consecutive)

    return df[["dam", "date", "rwl_m", "dev_24h_m", "nhwl_m", "dev_nhwl_m",
               "rule_curve_m", "dev_rule_curve_m", "inflow_cms", "outflow_cms"]]


def weather_features() -> pd.DataFrame:
    w = pd.read_csv(WEATHER)
    w["dam"] = w["dam"].map(canonical)
    w["date"] = pd.to_datetime(w["date"])
    w = w.sort_values(["dam", "date"])

    g = w.groupby("dam", group_keys=False)
    for win in RAIN_WINDOWS:
        # Backward-looking: rain that has already fallen on the catchment.
        w[f"rain_{win}d"] = g["precipitation_sum"].transform(
            lambda s, win=win: s.rolling(win, min_periods=1).sum()
        )
    for win in (3, 7):
        # Forward-looking: rain still to come, shifted so that day t sees
        # days t+1..t+win. This is the operational input at forecast time.
        w[f"rain_next_{win}d"] = g["precipitation_sum"].transform(
            lambda s, win=win: s.shift(-win).rolling(win, min_periods=1).sum()
        )
    return w


def forecast_rain() -> pd.DataFrame:
    """Rain expected over the next 3 and 7 days, as known on the issue date.

    rain_next_Nd(t) = sum over k=1..N of the forecast for day t+k issued k days
    earlier — which is precisely `lead == k` on date t+k.
    """
    if not RAIN_FCST.exists():
        return pd.DataFrame(columns=["dam", "date", "fc_rain_next_3d",
                                     "fc_rain_next_7d"])
    f = pd.read_csv(RAIN_FCST)
    f["date"] = pd.to_datetime(f["date"])
    # Shift each row back to the issue date it was made on.
    f["issue"] = f["date"] - pd.to_timedelta(f["lead"], unit="D")

    out = []
    for win in (3, 7):
        w = f[f["lead"] <= win]
        g = (w.groupby(["dam", "issue"])
               .agg(total=("rain_mm", "sum"), n=("lead", "nunique"))
               .reset_index())
        # Only trust a window with every lead present, else it under-counts.
        g = g[g["n"] == win]
        out.append(g[["dam", "issue", "total"]]
                   .rename(columns={"total": f"fc_rain_next_{win}d"}))
    merged = out[0]
    for extra in out[1:]:
        merged = merged.merge(extra, on=["dam", "issue"], how="outer")
    return merged.rename(columns={"issue": "date"})


def basin_features() -> pd.DataFrame:
    """Was this dam's own sub-basin under flood watch on the day?"""
    if not BASINS.exists():
        return pd.DataFrame(columns=["date", "basin_on_watch", "basins_on_watch"])
    b = pd.read_csv(BASINS)
    b["date"] = pd.to_datetime(b["date"])
    rivers = b[b["kind"] == "river_basin"]
    daily = (rivers.groupby("date")["on_watch"].sum()
             .reset_index().rename(columns={"on_watch": "basins_on_watch"}))
    return daily


def build() -> pd.DataFrame:
    levels = daily_levels()
    weather = weather_features()

    feats = levels.merge(weather, on=["dam", "date"], how="left",
                         validate="one_to_one")

    # Real lead-time forecast rain where the archive has it; ERA5 elsewhere.
    fc = forecast_rain()
    feats = feats.merge(fc, on=["dam", "date"], how="left")
    feats["fcst_source"] = np.where(feats["fc_rain_next_7d"].notna(),
                                    "forecast", "era5_proxy")
    for win in (3, 7):
        col, fcol = f"rain_next_{win}d", f"fc_rain_next_{win}d"
        if fcol in feats:
            feats[f"era5_{col}"] = feats[col]
            feats[col] = feats[fcol].fillna(feats[col])

    feats = feats.merge(basin_features(), on="date", how="left")

    doy = feats["date"].dt.dayofyear
    feats["doy_sin"] = np.sin(2 * np.pi * doy / 365.25)
    feats["doy_cos"] = np.cos(2 * np.pi * doy / 365.25)

    # Target: level change from the issue date to the issue date + h.
    future = levels[["dam", "date", "rwl_m"]].rename(
        columns={"rwl_m": "rwl_future"})
    rows = []
    for h in HORIZONS:
        shifted = future.copy()
        shifted["date"] = shifted["date"] - pd.to_timedelta(h, unit="D")
        part = feats.merge(shifted, on=["dam", "date"], how="left")
        part["horizon"] = h
        part["target_delta"] = part["rwl_future"] - part["rwl_m"]
        rows.append(part)

    table = pd.concat(rows, ignore_index=True)
    table = table[table["dam"].isin(DAMS)]
    return table.sort_values(["date", "dam", "horizon"]).reset_index(drop=True)


def main() -> int:
    table = build()
    labeled = table["target_delta"].notna()
    table.to_csv(OUT, index=False)

    print(f"{len(table)} rows -> {OUT}")
    print(f"labeled (t+h observed): {labeled.sum()}")
    print("\nlabeled rows per horizon:")
    print(table[labeled].groupby("horizon").size().to_string())

    missing_weather = table["precipitation_sum"].isna().sum()
    if missing_weather:
        print(f"\nWARNING: {missing_weather} rows have no weather join",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
