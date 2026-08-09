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
from model.online import (  # noqa: E402
    new_detector, new_model, save, to_features,
)

TABLE = Path(__file__).parents[1] / "data" / "modeling_table.csv"
OUT_METRICS = Path(__file__).parent / "metrics.json"
OUT_CURVE = Path(__file__).parent / "learning_curve.csv"


def run(table: pd.DataFrame) -> pd.DataFrame:
    """Returns one row per prediction, with the model and baseline errors."""
    labeled = table[table["target_delta"].notna()].copy()
    labeled = labeled.sort_values(["date", "dam", "horizon"])

    models: dict = {}
    detectors: dict = {}
    drift_events = []
    records = []

    for row in labeled.to_dict("records"):
        key = (row["dam"], int(row["horizon"]))
        if key not in models:
            models[key] = new_model()
            detectors[key] = new_detector()

        feats = to_features(row)
        actual = float(row["target_delta"])

        # Predict with a model that has seen only earlier rows.
        pred = models[key].predict_one(feats)
        pred = 0.0 if pred is None else float(pred)

        rec = {
            "date": row["date"],
            "dam": row["dam"],
            "horizon": int(row["horizon"]),
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
        models[key].learn_one(feats, actual)

        detectors[key].update(rec["abs_err_model"])
        if detectors[key].drift_detected:
            drift_events.append({"date": str(row["date"]), "dam": row["dam"],
                                 "horizon": int(row["horizon"])})

    results = pd.DataFrame(records)
    results.attrs["drift_events"] = drift_events
    results.attrs["models"] = models
    return results


def summarize(results: pd.DataFrame) -> dict:
    cols = ["abs_err_model"] + [f"abs_err_{n}" for n in BASELINES]
    per_h = results.groupby("horizon")[cols].mean().round(4)
    per_h["n"] = results.groupby("horizon").size()

    beats = {}
    for h, r in per_h.iterrows():
        best_baseline = min(BASELINES, key=lambda n: r[f"abs_err_{n}"])
        beats[int(h)] = {
            "n": int(r["n"]),
            "mae_model": float(r["abs_err_model"]),
            "mae_persistence": float(r["abs_err_persistence"]),
            "best_baseline": best_baseline,
            "mae_best_baseline": float(r[f"abs_err_{best_baseline}"]),
            "beats_baseline": bool(
                r["abs_err_model"] < r[f"abs_err_{best_baseline}"]),
        }
    return {"per_horizon": beats, "per_horizon_table": per_h.to_string()}


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
    save(results.attrs["models"])

    print(summary["per_horizon_table"])
    print(f"\n{len(results)} predictions, "
          f"{len(summary['drift_events'])} drift events")
    print("\nhorizons where the model beats every baseline:",
          [h for h, v in summary["per_horizon"].items() if v["beats_baseline"]]
          or "none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
