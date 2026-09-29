"""The pre-registered +1 day attempt in docs/ATTEMPT_NEXT.md, run once.

Reuses experiment.py's prequential() and score() so the harness is identical.
Phase 1 scores dev only. The holdout is opened only if the dev rule picks a
candidate, and then only for that candidate and the incumbent.

    uv run python eval/attempt_next.py        # writes eval/attempt_next.json
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from statistics import mean

import pandas as pd
from river import forest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from eval import experiment as E  # noqa: E402

OUT = Path(__file__).with_name("attempt_next.json")
SEEDS = [1, 2, 3, 4, 5]
TREND_DAYS = (3, 7)


def add_trend(records):
    """rwl_m now minus rwl_m exactly N calendar days earlier, per dam.

    Looked up by date, not by row offset, because the history has gaps. Only
    earlier dates are read, never t+1. Missing -> NaN -> omitted as a feature.
    """
    level = {(r["dam"], r["date"]): r["rwl_m"] for r in records}
    for r in records:
        d = date.fromisoformat(r["date"])
        for n in TREND_DAYS:
            past = level.get((r["dam"], (d - timedelta(days=n)).isoformat()))
            r[f"trend_{n}d"] = (r["rwl_m"] - past) if past is not None else float("nan")
    return records


E.FEATURE_SETS["trend"] = E.BASE_FEATURES + [f"trend_{n}d" for n in TREND_DAYS]

CANDIDATES = {
    "incumbent": ("amf50_noagg", "base", 50),
    "A_amf100_noagg": ("amf100_noagg", "base", 100),
    "B_trend": ("amf50_noagg", "trend", 50),
    "C_both": ("amf100_noagg", "trend", 100),
}


def run(name, seed):
    model, feats, trees = CANDIDATES[name]
    E.MODELS[model] = lambda: forest.AMFRegressor(
        n_estimators=trees, use_aggregation=False, seed=seed)
    # Settings of the published winner: dam and horizon pooled, target scaled.
    return E.prequential(LABELED, model_name=model, features=feats,
                         pool_dam=True, pool_horizon=True, interactions=False,
                         scale_target=True, shrink=1.0)


def summary(vals):
    return {"mean": round(mean(vals), 4), "min": round(min(vals), 4),
            "max": round(max(vals), 4), "per_seed": [round(v, 4) for v in vals]}


if __name__ == "__main__":
    table = pd.read_csv(E.TABLE)
    LABELED = add_trend(table[table["target_delta"].notna()]
                        .sort_values(["date", "dam", "horizon"])
                        .to_dict("records"))

    results = {n: [run(n, s) for s in SEEDS] for n in CANDIDATES}

    # ---- phase 1: dev only
    dev_h1 = {n: [E.score(r, "dev")[1]["mae"] for r in rs] for n, rs in results.items()}
    inc = dev_h1["incumbent"]
    report = {"seeds": SEEDS, "dev_h1_mae": {n: summary(v) for n, v in dev_h1.items()},
              "dev_mean_ratio": {n: summary([E.score(r, "dev")["_overall"]["mean_ratio"]
                                             for r in rs]) for n, rs in results.items()}}
    qualified = []
    for n, v in dev_h1.items():
        if n == "incumbent":
            continue
        better = sum(c < i for c, i in zip(v, inc))
        ok = mean(v) <= 0.97 * mean(inc) and better >= 4
        report.setdefault("dev_rule", {})[n] = {
            "pct_vs_incumbent": round(100 * (mean(v) / mean(inc) - 1), 2),
            "seeds_better": better, "qualifies": ok}
        if ok:
            qualified.append(n)
    chosen = min(qualified, key=lambda n: mean(dev_h1[n])) if qualified else None
    report["chosen"] = chosen

    # ---- phase 2: holdout, once, only if something qualified
    if chosen:
        def hold(n):
            s = [E.score(r, "holdout") for r in results[n]]
            return {"h": {h: summary([x[h]["ratio"] for x in s]) for h in range(1, 8)},
                    "h1_mae": summary([x[1]["mae"] for x in s]),
                    "mean_ratio": summary([x["_overall"]["mean_ratio"] for x in s]),
                    "n_h1": s[0][1]["n"]}
        hi, hc = hold("incumbent"), hold(chosen)
        worse = [h for h in range(1, 8)
                 if hc["h"][h]["mean"] > hi["h"][h]["mean"] + 0.02]
        ships = (hc["h1_mae"]["mean"] < hi["h1_mae"]["mean"] and not worse
                 and hc["mean_ratio"]["mean"] <= hi["mean_ratio"]["mean"] + 0.02)
        report["holdout"] = {"incumbent": hi, chosen: hc,
                             "horizons_worse_by_over_0.02": worse, "ships": ships}

    OUT.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
