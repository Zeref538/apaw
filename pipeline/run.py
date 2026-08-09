"""The self-improving loop. One run per cron tick.

  fetch -> score predictions whose actual has now landed -> learn from them
        -> emit fresh forecasts -> publish dashboard data

Scoring is deferred and never retrofitted: a forecast is written to the ledger
at issue time with the exact features it saw, and is only scored once the
observation it predicted actually arrives. That is what makes the learning
curve honest — nothing is ever rescored with hindsight.

Fails safe: if the scrape breaks, the previous dashboard JSON stays up and the
gap is logged rather than written as nulls.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data"))

from build_table import build  # noqa: E402
from dams import DAMS  # noqa: E402
from eval.baselines import BASELINES  # noqa: E402
from eval.risk import DESCRIPTIONS, classify  # noqa: E402
from model.online import (  # noqa: E402
    load, new_detector, new_model, save, to_features,
)

LEDGER = ROOT / "eval" / "predictions.csv"
ERRORS = ROOT / "eval" / "error_log.csv"
DRIFT_LOG = ROOT / "eval" / "drift_events.csv"
WEB = ROOT / "web" / "data"
HORIZONS = range(1, 8)


def _clean(obj):
    """NaN -> null.

    Python's json writes a bare `NaN`, which is not valid JSON and makes
    JSON.parse throw — one missing reference elevation (Caliraya has no NHWL)
    is enough to blank the entire dashboard.
    """
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, float) and math.isnan(obj):
        return None
    if obj is pd.NaT or (obj is not None and obj is pd.NA):
        return None
    return obj


def _append(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    df = pd.DataFrame(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, mode="a" if path.exists() else "w",
              header=not path.exists(), index=False)


def refresh_sources() -> bool:
    """Scrape today's levels and refresh weather.

    Only the dam scrape is fatal. PAGASA publishes today and yesterday and
    nothing else, so a missed reading is gone forever — but weather has years
    of committed history and an archive we can re-pull any time, so a flaky
    Open-Meteo call degrades to slightly stale rainfall instead of costing us
    the run.
    """
    dams = subprocess.run([sys.executable, str(ROOT / "data/fetch_dams.py")],
                          capture_output=True, text=True)
    print(f"$ data/fetch_dams.py\n{dams.stdout.strip()}")
    if dams.returncode != 0:
        print(dams.stderr.strip(), file=sys.stderr)
        return False

    wx = subprocess.run([sys.executable, str(ROOT / "data/fetch_weather.py")],
                        capture_output=True, text=True)
    print(f"$ data/fetch_weather.py\n{wx.stdout.strip()}")
    if wx.returncode != 0:
        print(wx.stderr.strip(), file=sys.stderr)
        print("weather refresh failed; continuing on the committed history",
              file=sys.stderr)
    return True


def score_due(table: pd.DataFrame, models: dict, detectors: dict) -> tuple[int, list]:
    """Score every outstanding prediction whose target date now has an actual."""
    if not LEDGER.exists():
        return 0, []

    ledger = pd.read_csv(LEDGER)
    open_rows = ledger[~ledger["scored"].fillna(False).astype(bool)]
    if open_rows.empty:
        return 0, []

    actuals = (table[["dam", "date", "rwl_m"]]
               .drop_duplicates(subset=["dam", "date"]))
    actuals["date"] = pd.to_datetime(actuals["date"]).dt.strftime("%Y-%m-%d")
    lookup = {(r.dam, r.date): r.rwl_m for r in actuals.itertuples()}

    scored_idx, error_rows, drift_rows = [], [], []
    for idx, row in open_rows.iterrows():
        actual_rwl = lookup.get((row["dam"], row["target_date"]))
        if actual_rwl is None:
            continue  # the observation hasn't arrived yet; leave it open

        actual_delta = float(actual_rwl) - float(row["issue_rwl_m"])
        feats = json.loads(row["features"])
        key = (row["dam"], int(row["horizon"]))

        err = abs(float(row["pred_delta"]) - actual_delta)
        rec = {
            "issue_date": row["issue_date"],
            "target_date": row["target_date"],
            "dam": row["dam"],
            "horizon": int(row["horizon"]),
            "pred_delta": float(row["pred_delta"]),
            "actual_delta": actual_delta,
            "abs_err_model": err,
        }
        for name, fn in BASELINES.items():
            rec[f"abs_err_{name}"] = abs(fn(json.loads(row["baseline_inputs"]))
                                         - actual_delta)
        error_rows.append(rec)

        # Learn only now, from the label that just became available.
        if key not in models:
            models[key], detectors[key] = new_model(), new_detector()
        models[key].learn_one(feats, actual_delta)

        detectors[key].update(err)
        if detectors[key].drift_detected:
            drift_rows.append({"detected_at": datetime.now().isoformat(
                timespec="seconds"), "dam": row["dam"],
                "horizon": int(row["horizon"]), "abs_err": err})

        scored_idx.append(idx)

    if scored_idx:
        ledger.loc[scored_idx, "scored"] = True
        ledger.to_csv(LEDGER, index=False)
    _append(ERRORS, error_rows)
    _append(DRIFT_LOG, drift_rows)
    return len(scored_idx), drift_rows


def issue_forecasts(table: pd.DataFrame, models: dict) -> list[dict]:
    """Predict 1-7 days ahead from each dam's most recent observation."""
    latest_date = table["date"].max()
    current = table[(table["date"] == latest_date) & (table["horizon"] == 1)]

    # A linear model asked about conditions wetter than anything it has been
    # trained on is extrapolating, and says so rather than being silently
    # trusted or clipped. Clipping would suppress exactly the extreme events
    # this is meant to catch.
    history = table[table["date"] < latest_date]
    wettest = history.groupby("dam")["rain_7d"].max().to_dict()
    biggest_rise = (history[history["target_delta"].notna()]
                    .groupby(["dam", "horizon"])["target_delta"].max().to_dict())

    ledger_rows, dashboard = [], []
    for row in current.to_dict("records"):
        dam = row["dam"]
        if dam not in DAMS:
            continue
        feats = to_features(row)
        issue_rwl = float(row["rwl_m"])
        issue_date = pd.Timestamp(row["date"]).strftime("%Y-%m-%d")

        levels, per_h = [], []
        for h in HORIZONS:
            key = (dam, h)
            model = models.get(key)
            pred = 0.0
            if model is not None:
                raw = model.predict_one(feats)
                pred = 0.0 if raw is None else float(raw)
            level = issue_rwl + pred
            levels.append(level)
            target_date = (pd.Timestamp(row["date"])
                           + pd.to_timedelta(h, unit="D")).strftime("%Y-%m-%d")
            seen_max = biggest_rise.get((dam, h))
            per_h.append({"horizon": h, "target_date": target_date,
                          "pred_delta": round(pred, 3),
                          "pred_rwl_m": round(level, 3),
                          "beyond_observed_rise": bool(
                              seen_max is not None and pred > seen_max)})
            ledger_rows.append({
                "issue_date": issue_date, "target_date": target_date,
                "dam": dam, "horizon": h,
                "issue_rwl_m": issue_rwl, "pred_delta": pred,
                "features": json.dumps(feats),
                "baseline_inputs": json.dumps(
                    {"dev_24h_m": row.get("dev_24h_m"), "horizon": h},
                    default=lambda o: None),
                "scored": False,
            })

        # Recent observed levels, so the chart can show what actually happened
        # running into what we think happens next. Windowed by DATE, not by row
        # count: the history is sparse, so the last N rows can span years and
        # squash the 7-day forecast into an unreadable spike.
        window_start = pd.Timestamp(latest_date) - pd.to_timedelta(60, unit="D")
        hist = (table[(table["dam"] == dam)
                      & (table["horizon"] == 1)
                      & (table["date"] >= window_start)]
                .sort_values("date"))
        observed = [
            {"date": pd.Timestamp(r["date"]).strftime("%Y-%m-%d"),
             "rwl_m": round(float(r["rwl_m"]), 3)}
            for r in hist.to_dict("records") if pd.notna(r["rwl_m"])
        ]

        risk = classify(levels, row.get("nhwl_m"), row.get("rule_curve_m"))
        dashboard.append({
            "dam": dam, "lat": DAMS[dam]["lat"], "lon": DAMS[dam]["lon"],
            "issue_date": issue_date, "rwl_m": issue_rwl,
            "nhwl_m": row.get("nhwl_m"), "rule_curve_m": row.get("rule_curve_m"),
            "risk": risk, "risk_note": DESCRIPTIONS[risk],
            "extrapolating": bool(
                wettest.get(dam) is not None
                and float(row.get("rain_7d") or 0) > wettest[dam]),
            "rain_7d": (round(float(row["rain_7d"]), 1)
                        if pd.notna(row.get("rain_7d")) else None),
            "rain_next_7d": (round(float(row["rain_next_7d"]), 1)
                             if pd.notna(row.get("rain_next_7d")) else None),
            "observed": observed,
            "forecasts": per_h,
        })

    # Don't double-issue if the loop runs twice on the same observation.
    if LEDGER.exists():
        prior = pd.read_csv(LEDGER)
        existing = set(zip(prior["dam"], prior["issue_date"], prior["horizon"]))
        ledger_rows = [r for r in ledger_rows
                       if (r["dam"], r["issue_date"], r["horizon"])
                       not in existing]
    _append(LEDGER, ledger_rows)
    return dashboard


def publish(dashboard: list[dict], scored: int, drift_rows: list) -> None:
    WEB.mkdir(parents=True, exist_ok=True)

    curve = []
    if ERRORS.exists():
        err = pd.read_csv(ERRORS)
        by_day = (err.groupby("target_date")[["abs_err_model",
                                              "abs_err_persistence"]]
                  .mean().reset_index())
        for col in ("abs_err_model", "abs_err_persistence"):
            by_day[f"roll_{col}"] = by_day[col].rolling(20, min_periods=3).mean()
        curve = by_day.round(4).to_dict("records")

    # The backtest's honest per-horizon scoreboard, including the horizons we
    # lose on. Published as-is; a losing horizon is shown saying so.
    metrics = {}
    metrics_path = ROOT / "eval" / "metrics.json"
    if metrics_path.exists():
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))

    # Until enough live predictions have been scored, the learning curve shown
    # is the backtest's prequential curve over the recovered history.
    if not curve and (ROOT / "eval" / "learning_curve.csv").exists():
        curve = (pd.read_csv(ROOT / "eval" / "learning_curve.csv")
                 .rename(columns={"date": "target_date"})
                 .round(4).where(lambda d: d.notna(), None)
                 .to_dict("records"))

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "dams": dashboard,
        "metrics": metrics.get("per_horizon", {}),
        "learning_curve": curve,
        "scored_this_run": scored,
        "drift_events_this_run": drift_rows,
        "disclaimer": (
            "Educational forecast, not an official warning. PAGASA and your "
            "local disaster risk reduction office are the authorities."
        ),
    }
    (WEB / "forecasts.json").write_text(
        json.dumps(_clean(payload), indent=2, default=str,
                   allow_nan=False), encoding="utf-8")


def main() -> int:
    fetch_ok = refresh_sources()
    if not fetch_ok:
        # NFR-4: keep the last good dashboard rather than publishing nulls.
        print("source refresh failed; leaving previous dashboard in place",
              file=sys.stderr)
        return 1

    table = build()
    table.to_csv(ROOT / "data" / "modeling_table.csv", index=False)

    models = load()
    detectors = {key: new_detector() for key in models}

    scored, drift_rows = score_due(table, models, detectors)
    dashboard = issue_forecasts(table, models)
    save(models)
    publish(dashboard, scored, drift_rows)

    print(f"scored {scored} due predictions; "
          f"issued forecasts for {len(dashboard)} dams; "
          f"{len(drift_rows)} drift events")
    for d in dashboard:
        print(f"  {d['dam']:<12} {d['rwl_m']:>8.2f} m  {d['risk']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
