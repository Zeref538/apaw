"""Second target: will a river basin be under flood watch in N days?

The dam models predict a number; this predicts a yes/no, and it covers the
whole country rather than Luzon's nine reservoirs. Same discipline as the dam
side — online learning, prequential scoring, and a naive baseline that simply
assumes today's status holds.

Flood watch is heavily persistent (basins stay quiet for weeks), so accuracy
is a vanity metric here: predicting "quiet" forever scores well and is
useless. The number that matters is recall on the days a watch is actually
raised, reported next to persistence.

This starts empty. PAGASA's basin table is only collected from the day the
collector went live, so until enough days accrue the honest output is
"not enough history yet" rather than a figure.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
from river import compose, linear_model, optim, preprocessing

ROOT = Path(__file__).parents[1]
BASINS = ROOT / "data" / "basin_status.csv"
OUT = Path(__file__).parent / "basin_metrics.json"

HORIZONS = (1, 2, 3)
MIN_DAYS = 30          # below this, any score is noise
MIN_EVENTS = 10        # and we need some actual watch days to learn from


def new_classifier():
    return compose.Pipeline(
        preprocessing.StandardScaler(),
        linear_model.LogisticRegression(optimizer=optim.SGD(0.05)),
    )


def frame() -> pd.DataFrame:
    """One row per basin per day, with the recent-history features."""
    b = pd.read_csv(BASINS)
    b = b[b["kind"] == "river_basin"].copy()
    b["date"] = pd.to_datetime(b["date"])
    b["on_watch"] = b["on_watch"].astype(bool)
    b = b.sort_values(["basin", "date"])

    national = (b.groupby("date")["on_watch"].mean()
                .rename("national_share").reset_index())
    b = b.merge(national, on="date", how="left")

    g = b.groupby("basin", group_keys=False)
    b["watch_today"] = b["on_watch"].astype(float)
    b["watch_3d"] = g["on_watch"].transform(
        lambda s: s.astype(float).rolling(3, min_periods=1).mean())
    b["watch_7d"] = g["on_watch"].transform(
        lambda s: s.astype(float).rolling(7, min_periods=1).mean())
    b["streak"] = g["on_watch"].transform(
        lambda s: s.astype(int).groupby((~s).cumsum()).cumcount())
    return b


def features(row: dict) -> dict:
    return {k: float(row[k]) for k in
            ("watch_today", "watch_3d", "watch_7d", "streak", "national_share")}


def run() -> dict:
    if not BASINS.exists():
        return {"status": "no data"}
    b = frame()
    days = b["date"].nunique()

    out = {"days_collected": int(days), "min_days": MIN_DAYS,
           "basins": int(b["basin"].nunique())}
    if days < MIN_DAYS:
        out["status"] = "not enough history yet"
        return out

    models, records = {}, []
    for h in HORIZONS:
        future = b[["basin", "date", "on_watch"]].copy()
        future["date"] = future["date"] - pd.to_timedelta(h, unit="D")
        future = future.rename(columns={"on_watch": "target"})
        joined = b.merge(future, on=["basin", "date"], how="inner")

        for row in joined.sort_values("date").to_dict("records"):
            key = (row["basin"], h)
            models.setdefault(key, new_classifier())
            f = features(row)
            p = models[key].predict_proba_one(f).get(True, 0.0)
            records.append({
                "horizon": h, "basin": row["basin"], "date": row["date"],
                "pred": int(p >= 0.5), "prob": p,
                "actual": int(bool(row["target"])),
                # Naive: tomorrow looks like today.
                "persistence": int(bool(row["on_watch"])),
            })
            models[key].learn_one(f, bool(row["target"]))

    if not records:
        out["status"] = "not enough history yet"
        return out

    r = pd.DataFrame(records)
    events = int(r["actual"].sum())
    out["watch_days_seen"] = events
    if events < MIN_EVENTS:
        out["status"] = "not enough flood-watch days to learn from"
        return out

    per_h = {}
    for h, grp in r.groupby("horizon"):
        def stats(col):
            tp = int(((grp[col] == 1) & (grp["actual"] == 1)).sum())
            fp = int(((grp[col] == 1) & (grp["actual"] == 0)).sum())
            fn = int(((grp[col] == 0) & (grp["actual"] == 1)).sum())
            return {
                "accuracy": float((grp[col] == grp["actual"]).mean()),
                "recall": float(tp / (tp + fn)) if tp + fn else None,
                "precision": float(tp / (tp + fp)) if tp + fp else None,
            }
        m, p = stats("pred"), stats("persistence")
        per_h[int(h)] = {
            "n": int(len(grp)),
            "model": m,
            "persistence": p,
            # Recall on watch days is the metric with public meaning.
            "beats_baseline": bool(
                m["recall"] is not None and p["recall"] is not None
                and m["recall"] > p["recall"]),
        }
    out["status"] = "scored"
    out["per_horizon"] = per_h
    return out


def main() -> int:
    res = run()
    OUT.write_text(json.dumps(res, indent=2), encoding="utf-8")
    print(json.dumps(res, indent=2)[:900])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
