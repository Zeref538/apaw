"""Chronological prequential backtest: predict, then learn. Never the reverse.

Every labeled row is predicted by a model that has only ever seen strictly
earlier rows, so there is no leakage and no train/test split to get wrong.
This is also exactly how the live loop behaves, which means the backtest error
and the production error are measuring the same thing.

Writes eval/metrics.json and eval/learning_curve.csv.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1]))
from eval.baselines import BASELINES  # noqa: E402
from model.online import Nowcaster, new_detector, save  # noqa: E402

TABLE = Path(__file__).parents[1] / "data" / "modeling_table.csv"

# Below this many scored forecasts a horizon's error is noise, not a result.
# It is reported with enough_data=false and the dashboard refuses to rank it.
MIN_SCORED = 200
OUT_METRICS = Path(__file__).parent / "metrics.json"
OUT_CURVE = Path(__file__).parent / "learning_curve.csv"


def run(table: pd.DataFrame) -> pd.DataFrame:
    """Returns one row per prediction, with the model and baseline errors."""
    labeled = table[table["target_delta"].notna()].copy()
    labeled = labeled.sort_values(["date", "dam", "horizon"])

    # One pooled model for every dam and horizon; see model/online.py.
    model = Nowcaster()
    detectors: dict = {}
    drift_events = []
    records = []

    for row in labeled.to_dict("records"):
        dam, horizon = row["dam"], int(row["horizon"])
        key = (dam, horizon)
        if key not in detectors:
            detectors[key] = new_detector()

        feats = model.raw_features(row, horizon)
        actual = float(row["target_delta"])

        # Predict with a model that has seen only earlier rows.
        pred = model.predict(feats, dam)

        rec = {
            "date": row["date"],
            "dam": row["dam"],
            "horizon": int(row["horizon"]),
            "fcst_source": row.get("fcst_source", "era5_proxy"),
            "actual": actual,
            "model": pred,
            "abs_err_model": abs(pred - actual),
        }
        for name, fn in BASELINES.items():
            base = fn(row)
            rec[name] = base
            rec[f"abs_err_{name}"] = abs(base - actual)
        records.append(rec)

        # Then learn from it.
        model.learn(feats, dam, actual)

        detectors[key].update(rec["abs_err_model"])
        if detectors[key].drift_detected:
            drift_events.append({"date": str(row["date"]), "dam": row["dam"],
                                 "horizon": int(row["horizon"])})

    results = pd.DataFrame(records)
    results.attrs["drift_events"] = drift_events
    results.attrs["model"] = model
    return results


def summarize(results: pd.DataFrame) -> dict:
    cols = ["abs_err_model"] + [f"abs_err_{n}" for n in BASELINES]
    per_h = results.groupby("horizon")[cols].mean().round(4)
    per_h["n"] = results.groupby("horizon").size()

    beats = {}
    for h, r in per_h.iterrows():
        best_baseline = min(BASELINES, key=lambda n: r[f"abs_err_{n}"])
        enough = int(r["n"]) >= MIN_SCORED
        beats[int(h)] = {
            "n": int(r["n"]),
            "enough_data": enough,
            "min_scored": MIN_SCORED,
            "mae_model": float(r["abs_err_model"]),
            "mae_persistence": float(r["abs_err_persistence"]),
            "best_baseline": best_baseline,
            "mae_best_baseline": float(r[f"abs_err_{best_baseline}"]),
            # A verdict on a handful of points is not a verdict.
            "beats_baseline": bool(
                enough and r["abs_err_model"] < r[f"abs_err_{best_baseline}"]),
        }

    # How much of the score comes from rows that were handed observed rain for
    # days that had not happened yet. Quantifies the remaining optimism.
    by_src = {}
    if "fcst_source" in results:
        g = results.groupby("fcst_source")["abs_err_model"].agg(["mean", "size"])
        by_src = {k: {"mae_model": float(v["mean"]), "n": int(v["size"])}
                  for k, v in g.iterrows()}

    return {"per_horizon": beats, "per_horizon_table": per_h.to_string(),
            "by_rain_source": by_src}


def main() -> int:
    table = pd.read_csv(TABLE)
    results = run(table)
    if results.empty:
        print("no labeled rows to score", file=sys.stderr)
        return 1

    summary = summarize(results)
    summary["n_predictions"] = len(results)
    summary["drift_events"] = results.attrs["drift_events"]

    OUT_METRICS.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    # Learning curve: rolling error over calendar time, model vs baseline.
    curve = (results.sort_values("date")
             .groupby("date")[["abs_err_model", "abs_err_persistence"]]
             .mean().reset_index())
    for col in ("abs_err_model", "abs_err_persistence"):
        curve[f"roll_{col}"] = curve[col].rolling(20, min_periods=5).mean()
    curve.to_csv(OUT_CURVE, index=False)

    # Warm-start the live loop. The backtest walked the history in order and
    # learned from it exactly as the loop would have, so the resulting state is
    # the legitimate starting point — otherwise the recovered Wayback history
    # is scored and then thrown away.
    save(results.attrs["model"])

    print(summary["per_horizon_table"])
    print(f"\n{len(results)} predictions, "
          f"{len(summary['drift_events'])} drift events")
    print("\nhorizons where the model beats every baseline:",
          [h for h, v in summary["per_horizon"].items() if v["beats_baseline"]]
          or "none")
    thin = [h for h, v in summary["per_horizon"].items() if not v["enough_data"]]
    if thin:
        print(f"horizons under {MIN_SCORED} scored forecasts "
              f"(published, but not ranked): {thin}")
    if summary["by_rain_source"]:
        print("\nerror by forward-rain source:")
        for k, v in summary["by_rain_source"].items():
            print(f"  {k:<12} MAE {v['mae_model']:.3f}  n={v['n']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
