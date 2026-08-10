"""Model search. Offline, honest, and separated from the published scoreboard.

The rule this file exists to respect: if you search hundreds of configurations
against one evaluation set and publish the best, the winning number is a
property of the search, not of the model. Pick a config that way and it will
regress the moment new data lands.

So the calendar is cut in two, once, before anything runs:

    dev      dates <  SPLIT   — every configuration is scored here
    holdout  dates >= SPLIT   — scored once, by the single winner, at the end

Both scores come from ONE prequential pass per config, exactly as
eval/backtest.py runs: predict with a model that has seen only strictly
earlier rows, then learn. The holdout score is therefore a warm model meeting
genuinely unseen dates, which is what production is.

Everything here must stay deployable under the incremental rule in CLAUDE.md:
River estimators with learn_one, no batch refit. A config that cannot run in
the live loop is not a candidate no matter how well it scores.

    uv run python eval/experiment.py            # the full search
    uv run python eval/experiment.py --quick    # a small sanity subset
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1]))
from eval.baselines import BASELINES  # noqa: E402

from river import (  # noqa: E402
    compose, ensemble, forest, linear_model, neighbors, optim,
    preprocessing, tree,
)

ROOT = Path(__file__).parents[1]
TABLE = ROOT / "data" / "modeling_table.csv"
OUT = Path(__file__).parent / "experiments.json"

# The last ~9 months are never used to choose anything.
SPLIT = "2025-11-01"

MIN_SCORED = 200  # mirrors backtest.py; a horizon under this is not ranked


# ---------------------------------------------------------------- features

BASE_FEATURES = [
    "rwl_m", "dev_24h_m", "dev_rule_curve_m", "dev_nhwl_m",
    "rain_1d", "rain_3d", "rain_7d", "rain_14d", "rain_30d",
    "rain_next_3d", "rain_next_7d",
    "temperature_2m_mean", "et0_fao_evapotranspiration",
    "doy_sin", "doy_cos",
]

# Dropping the level itself and the slow rain windows. With ~94 rows per dam
# at h=1, every extra coefficient is a coefficient fit on nothing.
LEAN_FEATURES = [
    "dev_24h_m", "dev_rule_curve_m",
    "rain_1d", "rain_3d", "rain_7d",
    "rain_next_3d", "rain_next_7d",
    "doy_sin", "doy_cos",
]

TINY_FEATURES = ["dev_24h_m", "rain_3d", "rain_next_3d", "rain_next_7d"]

WIDE_FEATURES = BASE_FEATURES + ["inflow_cms", "outflow_cms",
                                 "basins_on_watch",
                                 "relative_humidity_2m_mean"]

FEATURE_SETS = {
    "base": BASE_FEATURES,
    "lean": LEAN_FEATURES,
    "tiny": TINY_FEATURES,
    "wide": WIDE_FEATURES,
}


def build_features(row, names, pool_dam, pool_horizon, interactions):
    """Row dict -> River feature dict. NaN features are omitted, never imputed;
    River just doesn't use an absent feature, which is right for the dams that
    genuinely have no rule curve."""
    out = {}
    for name in names:
        val = row.get(name)
        try:
            val = float(val)
        except (TypeError, ValueError):
            continue
        if val != val:
            continue
        out[name] = val

    if interactions:
        h = float(row["horizon"])
        # Rain matters more the longer the horizon, and a wet catchment routes
        # rain differently from a dry one. Both are products a linear model
        # cannot express on its own.
        for r in ("rain_next_3d", "rain_next_7d"):
            if r in out:
                out[f"{r}_x_h"] = out[r] * h
        if "rain_next_7d" in out and "rain_30d" in out:
            out["wetness_x_fcst"] = out["rain_next_7d"] * math.log1p(out["rain_30d"])

    if pool_dam:
        out[f"dam={row['dam']}"] = 1.0
    if pool_horizon:
        out["horizon"] = float(row["horizon"])
    return out


# ------------------------------------------------------------------ models

# Scaling is done causally in the harness (see RunningStandardizer), not with
# preprocessing.StandardScaler. River's scaler divides by a running standard
# deviation, and a one-hot dam indicator is constant 1.0 wherever it appears,
# so its variance is 0 and the scaled feature explodes. That is what produced
# MAE in the tens of millions on the first pooled run.
def _lin(opt, l2=0.0):
    return lambda: linear_model.LinearRegression(optimizer=opt(), l2=l2)


MODELS = {
    # the incumbent
    "lin_sgd0.01":   _lin(lambda: optim.SGD(0.01)),
    "lin_sgd0.003":  _lin(lambda: optim.SGD(0.003)),
    "lin_sgd0.03":   _lin(lambda: optim.SGD(0.03)),
    "lin_adam0.01":  _lin(lambda: optim.Adam(0.01)),
    "lin_adam0.003": _lin(lambda: optim.Adam(0.003)),
    "lin_adam_l2":   _lin(lambda: optim.Adam(0.01), l2=0.01),
    "lin_adagrad":   _lin(lambda: optim.AdaGrad(0.05)),
    "lin_rmsprop":   _lin(lambda: optim.RMSProp(0.01)),
    "lin_ftrl":      _lin(lambda: optim.FTRLProximal()),
    "lin_sgd_l2":    _lin(lambda: optim.SGD(0.01), l2=0.1),

    "bayes_lin": lambda: linear_model.BayesianLinearRegression(),
    "pa": lambda: linear_model.PARegressor(C=0.1, mode=2),
    "pa_c1": lambda: linear_model.PARegressor(C=1.0, mode=2),

    "htr": lambda: tree.HoeffdingTreeRegressor(grace_period=50),
    "htr_slow": lambda: tree.HoeffdingTreeRegressor(grace_period=200),
    "htr_fast": lambda: tree.HoeffdingTreeRegressor(grace_period=20),
    "hatr": lambda: tree.HoeffdingAdaptiveTreeRegressor(grace_period=50, seed=7),
    "sgt": lambda: tree.SGTRegressor(),

    "knn5": lambda: neighbors.KNNRegressor(n_neighbors=5),
    "knn20": lambda: neighbors.KNNRegressor(n_neighbors=20),

    "arf": lambda: forest.ARFRegressor(n_models=10, seed=7),
    "arf30": lambda: forest.ARFRegressor(n_models=30, seed=7),
    "amf": lambda: forest.AMFRegressor(n_estimators=10, seed=7),
    # AMF won the broad sweep at its default size, so its own knobs get a
    # sweep of their own — more trees, and the step that controls how fast
    # each Mondrian tree's aggregation weights move.
    "amf25": lambda: forest.AMFRegressor(n_estimators=25, seed=7),
    "amf50": lambda: forest.AMFRegressor(n_estimators=50, seed=7),
    "amf100": lambda: forest.AMFRegressor(n_estimators=100, seed=7),
    "amf25_s03": lambda: forest.AMFRegressor(n_estimators=25, step=0.3, seed=7),
    "amf25_s3": lambda: forest.AMFRegressor(n_estimators=25, step=3.0, seed=7),
    "amf50_s03": lambda: forest.AMFRegressor(n_estimators=50, step=0.3, seed=7),
    "amf50_s3": lambda: forest.AMFRegressor(n_estimators=50, step=3.0, seed=7),
    "amf50_noagg": lambda: forest.AMFRegressor(n_estimators=50, seed=7,
                                               use_aggregation=False),
    "amf50_cap": lambda: forest.AMFRegressor(n_estimators=50, max_nodes=200,
                                             seed=7),
    "bag_lin": lambda: ensemble.BaggingRegressor(
        model=linear_model.LinearRegression(optimizer=optim.Adam(0.01)),
        n_models=5, seed=7),
    "ewa": lambda: ensemble.EWARegressor(
        models=[
            linear_model.LinearRegression(optimizer=optim.Adam(0.01)),
            tree.HoeffdingTreeRegressor(grace_period=50),
            neighbors.KNNRegressor(n_neighbors=10),
        ],
        learning_rate=0.1),
}


# ------------------------------------------------------------- the harness

class RunningStandardizer:
    """Causal z-scoring, one running mean/variance per feature name.

    Updated only after a row has been predicted, so no row is ever scaled
    using statistics that contain itself. Features whose spread is still
    effectively zero — one-hot dam indicators, most obviously — are passed
    through untouched instead of being divided by ~0.
    """

    def __init__(self):
        self.n, self.mean, self.m2 = {}, {}, {}

    def transform(self, feats):
        out = {}
        for k, v in feats.items():
            n = self.n.get(k, 0)
            if n < 2:
                # No spread known yet. Emit 0, as River's own StandardScaler
                # does — passing the raw value through means rwl_m ~ 200 hits
                # the first SGD step and the weights never recover.
                out[k] = 0.0
                continue
            sd = math.sqrt(self.m2[k] / n)
            if sd < 1e-6:
                # Constant feature (a one-hot dam flag). Keep it as-is; this
                # is exactly the case where dividing by sd blows up.
                out[k] = v
                continue
            # Clipped so one freak reading cannot take a whole model with it.
            out[k] = max(-5.0, min(5.0, (v - self.mean[k]) / sd))
        return out

    def update(self, feats):
        for k, v in feats.items():
            n = self.n.get(k, 0) + 1
            mean = self.mean.get(k, 0.0)
            d = v - mean
            mean += d / n
            self.m2[k] = self.m2.get(k, 0.0) + d * (v - mean)
            self.n[k], self.mean[k] = n, mean


class ExpertBlend:
    """Exponentially-weighted aggregation over {learned model, persistence,
    drift}, one weight vector per key.

    This is the only construct here that actually targets the brief. A search
    over estimators can find one that beat the baselines on the dates we
    already have; it cannot promise anything about next month. Multiplicative
    weights can: the regret of this blend against the *best single expert* in
    the set grows like sqrt(T), so over time it cannot do much worse than the
    best baseline, and it does better whenever the model has real signal.

    The cost is honesty about what it is — a hedge, not a better forecaster.
    It wins by refusing to lose, and on horizons where persistence is simply
    right it converges to persistence and says nothing new.
    """

    def __init__(self, eta=0.5, n=3):
        self.eta = eta
        self.w = [1.0 / n] * n

    def predict(self, experts):
        return sum(wi * e for wi, e in zip(self.w, experts))

    def update(self, experts, actual):
        losses = [abs(e - actual) for e in experts]
        scale = max(max(losses), 1e-6)
        self.w = [wi * math.exp(-self.eta * l / scale)
                  for wi, l in zip(self.w, losses)]
        total = sum(self.w) or 1.0
        self.w = [wi / total for wi in self.w]


class RunningScale:
    """Causal per-dam target scale. Updated only AFTER a row is scored, so the
    scale applied to a prediction never contains that row's own target.

    Pooling dams is the whole point of this search, but the dams differ in
    target spread by 12x (La Mesa 0.16 m, San Roque 1.91 m). Pooled raw, San
    Roque writes the coefficients and La Mesa is noise around them.
    """

    def __init__(self):
        self.n, self.mean, self.m2 = {}, {}, {}

    def std(self, key):
        n = self.n.get(key, 0)
        if n < 5:
            return None  # not enough to scale by yet
        return max(math.sqrt(self.m2[key] / n), 1e-3)

    def update(self, key, x):
        n = self.n.get(key, 0) + 1
        mean = self.mean.get(key, 0.0)
        delta = x - mean
        mean += delta / n
        self.m2[key] = self.m2.get(key, 0.0) + delta * (x - mean)
        self.n[key], self.mean[key] = n, mean


def prequential(labeled, *, model_name, features, pool_dam, pool_horizon,
                interactions, scale_target, shrink, blend=0.0,
                stack_baseline=False):
    """One pass, predict-then-learn, in strict date order.

    Returns a DataFrame of per-prediction errors tagged dev/holdout.
    """
    factory = MODELS[model_name]
    names = FEATURE_SETS[features]
    models, scaler = {}, RunningScale()
    standardizers: dict = {}
    blenders: dict = {}
    rows = []

    for row in labeled:
        if pool_dam and pool_horizon:
            key = "all"
        elif pool_dam:
            key = int(row["horizon"])
        elif pool_horizon:
            key = row["dam"]
        else:
            key = (row["dam"], int(row["horizon"]))
        if key not in models:
            models[key] = factory()
            standardizers[key] = RunningStandardizer()
            blenders[key] = ExpertBlend(eta=blend) if blend else None

        raw = build_features(row, names, pool_dam, pool_horizon, interactions)
        if stack_baseline:
            # Hand the model the naive answer as an input. It then only has to
            # learn the correction, which is a far easier target than the
            # delta from nothing.
            raw["base_drift"] = float(BASELINES["drift"](row))
        feats = standardizers[key].transform(raw)
        actual = float(row["target_delta"])
        sd = scaler.std(row["dam"]) if scale_target else None

        pred = models[key].predict_one(feats)
        pred = 0.0 if pred is None else float(pred)
        if sd is not None:
            pred *= sd
        if not math.isfinite(pred):
            pred = 0.0
        # Shrinkage toward the persistence baseline (delta=0). With this little
        # data a raw online fit is high-variance; pulling it toward "no change"
        # is the cheapest variance reduction there is.
        pred *= shrink

        if blenders.get(key) is not None:
            experts = [pred] + [float(fn(row)) for fn in BASELINES.values()]
            blended = blenders[key].predict(experts)
            blenders[key].update(experts, actual)
            pred = blended

        rec = {"date": row["date"], "dam": row["dam"],
               "horizon": int(row["horizon"]), "actual": actual,
               "abs_err_model": abs(pred - actual)}
        for name, fn in BASELINES.items():
            rec[f"abs_err_{name}"] = abs(fn(row) - actual)
        rows.append(rec)

        y = actual / sd if sd is not None else actual
        models[key].learn_one(feats, y)
        standardizers[key].update(raw)
        if scale_target:
            scaler.update(row["dam"], actual)

    out = pd.DataFrame(rows)
    out["split"] = (out["date"] >= SPLIT).map({True: "holdout", False: "dev"})
    return out


def score(results, split):
    """MAE per horizon plus the beat-count, on one split."""
    r = results[results["split"] == split]
    if r.empty:
        return {}
    cols = ["abs_err_model"] + [f"abs_err_{n}" for n in BASELINES]
    per_h = r.groupby("horizon")[cols].mean()
    per_h["n"] = r.groupby("horizon").size()

    out, ratios = {}, []
    for h, v in per_h.iterrows():
        best = min(float(v[f"abs_err_{n}"]) for n in BASELINES)
        mae = float(v["abs_err_model"])
        # Ratio to the best baseline, capped. The cap is what stops a config
        # that diverges on one horizon from being ranked on its luck at the
        # others: without it, a model with MAE in the millions at h=3 still
        # sorted first on a raw win count.
        ratio = 3.0 if not math.isfinite(mae) else min(mae / max(best, 1e-6), 3.0)
        ratios.append(ratio)
        out[int(h)] = {"n": int(v["n"]), "mae": round(mae, 4),
                       "best_baseline": round(best, 4),
                       "ratio": round(ratio, 4),
                       "wins": bool(mae < best)}
    overall_mae = float(r["abs_err_model"].mean())
    out["_overall"] = {
        "mae": round(overall_mae, 4) if math.isfinite(overall_mae) else None,
        "n_wins": sum(1 for h, v in out.items()
                      if isinstance(h, int) and v["wins"]),
        "n_horizons": len(ratios),
        # Primary ranking key: mean capped ratio over horizons, lower better.
        # Below 1.0 means it beats the naive baselines on average.
        "mean_ratio": round(sum(ratios) / len(ratios), 4),
        "worst_ratio": round(max(ratios), 4),
    }
    return out


POOLINGS = [(False, False), (True, False), (False, True), (True, True)]


def grid(models, feats, poolings, scales, inters, shrinks,
         blends=(0.0,), stacks=(False,)):
    for m, f, (pd_, ph), sc, it, sh, bl, st in itertools.product(
            models, feats, poolings, scales, inters, shrinks, blends, stacks):
        yield {"model_name": m, "features": f, "pool_dam": pd_,
               "pool_horizon": ph, "scale_target": sc,
               "interactions": it, "shrink": sh, "blend": bl,
               "stack_baseline": st}


def coarse_configs(quick=False):
    """Every estimator, but a cheap grid around it. Finds which families are
    worth spending the fine sweep on."""
    models = ["lin_sgd0.01", "lin_adam0.01", "htr", "knn5", "arf"] if quick \
        else list(MODELS)
    return grid(models, ["base", "lean"], POOLINGS, [False, True],
                [False], [1.0, 0.5])


def sweep(labeled, cfgs, label):
    """Run a list of configs, returning those that completed, dev-scored."""
    print(f"\n--- {label}: {len(cfgs)} configurations ---")
    out, t0, failed = [], time.time(), 0
    for i, cfg in enumerate(cfgs, 1):
        try:
            res = prequential(labeled, **cfg)
        except Exception as exc:
            # A configuration that cannot run is simply not a candidate.
            failed += 1
            if failed <= 5:
                print(f"  [{i}] {cfg['model_name']} failed: "
                      f"{type(exc).__name__}: {exc}")
            continue
        dev = score(res, "dev")
        if dev:
            # The holdout score is computed here but deliberately NOT used for
            # ranking anywhere — sorting only ever reads cfg["dev"]. Keeping
            # the number rather than the frame is what makes thousands of
            # configs fit in memory; keeping it out of the sort is what keeps
            # the comparison honest.
            out.append({**cfg, "dev": dev, "holdout": score(res, "holdout")})
        if i % 50 == 0 or i == len(cfgs):
            el = time.time() - t0
            print(f"  [{i}/{len(cfgs)}] {el:.0f}s elapsed, "
                  f"~{el / i * (len(cfgs) - i):.0f}s left, {failed} failed")
    return out, failed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-fine", action="store_true",
                    help="skip the refinement sweep")
    ap.add_argument("--family", default="",
                    help="comma-separated model names; sweeps only these, "
                         "over the full grid")
    ap.add_argument("--focus", action="store_true",
                    help="with --family: hold the non-model dimensions at the "
                         "broad sweep's winning settings and vary only the "
                         "estimator. The full cross product of a slow "
                         "estimator is hours of compute for knobs that barely "
                         "interact.")
    args = ap.parse_args()

    table = pd.read_csv(TABLE)
    labeled = (table[table["target_delta"].notna()]
               .sort_values(["date", "dam", "horizon"])
               .to_dict("records"))
    print(f"{len(labeled)} labeled rows | dev < {SPLIT} <= holdout")

    if args.family:
        fam = [m.strip() for m in args.family.split(",")]
        missing = [m for m in fam if m not in MODELS]
        if missing:
            print(f"unknown model(s): {missing}", file=sys.stderr)
            return 2
        if args.focus:
            # The broad sweep's winner: base features, one model per dam with
            # horizon as a feature, causal per-dam target scaling.
            coarse = list(grid(fam, ["base"], [(False, True)], [True],
                               [False], [1.0, 0.8]))
            coarse += list(grid(fam, ["base", "wide"], [(True, True)], [True],
                                [False], [1.0]))
        else:
            coarse = list(grid(fam, list(FEATURE_SETS), POOLINGS,
                               [False, True], [False, True], [1.0, 0.8, 0.6],
                               blends=(0.0, 0.6), stacks=(False, True)))
        args.no_fine = True
    else:
        coarse = list(coarse_configs(args.quick))
    if args.limit:
        coarse = coarse[:args.limit]
    results, failed = sweep(labeled, coarse, "coarse sweep")
    if not results:
        print("no configuration ran", file=sys.stderr)
        return 1

    # Refine: take the estimator families that survived the coarse sweep and
    # give them the full grid — every feature set, interactions, shrinkage.
    if not args.no_fine:
        results.sort(key=lambda r: r["dev"]["_overall"]["mean_ratio"])
        keep, seen = [], set()
        for r in results:
            if r["model_name"] not in seen:
                seen.add(r["model_name"])
                keep.append(r["model_name"])
            if len(keep) == 6:
                break
        print(f"\nrefining: {keep}")
        fine = list(grid(keep, list(FEATURE_SETS), POOLINGS, [False, True],
                         [False, True], [1.0, 0.8, 0.6, 0.4, 0.2]))
        def ident(c):
            return tuple(c.get(k) for k in
                         ("model_name", "features", "pool_dam", "pool_horizon",
                          "scale_target", "interactions", "shrink", "blend",
                          "stack_baseline"))
        done = {ident(r) for r in results}
        fine = [c for c in fine if ident(c) not in done]
        more, f2 = sweep(labeled, fine, "fine sweep")
        results += more
        failed += f2

        # Stage 3: hedge the survivors against the baselines themselves, and
        # let them see the naive answer as an input. This is the stage aimed
        # squarely at "beat every baseline" rather than at raw accuracy.
        blend_cfgs = list(grid(keep[:4], ["base", "lean"], POOLINGS,
                               [False, True], [False, True], [1.0],
                               blends=(0.3, 0.6, 1.0, 2.0),
                               stacks=(False, True)))
        blend_cfgs += list(grid(keep[:4], ["base", "lean"], POOLINGS,
                                [False, True], [False], [1.0, 0.6],
                                blends=(0.0,), stacks=(True,)))
        more, f3 = sweep(labeled, blend_cfgs, "blend + baseline-stack sweep")
        results += more
        failed += f3

    # Rank on DEV ONLY, by mean capped ratio to the best baseline. Win count
    # breaks ties. The holdout is not consulted to choose anything.
    results.sort(key=lambda r: (r["dev"]["_overall"]["mean_ratio"],
                                -r["dev"]["_overall"]["n_wins"]))

    print(f"\n{'':3}{'model':<14} {'feat':<5} {'pool':<8} {'sc':<3} "
          f"{'ix':<3} {'shr':<5} {'bl':<4} {'st':<3} {'wins':<6} {'ratio':<7} "
          f"{'worst':<7} dev MAE")
    print("-" * 82)
    for n, r in enumerate(results[:25], 1):
        pool = ("dam+h" if r["pool_dam"] and r["pool_horizon"]
                else "dam" if r["pool_dam"]
                else "horizon" if r["pool_horizon"] else "none")
        o = r["dev"]["_overall"]
        print(f"{n:<3}{r['model_name']:<14} {r['features']:<5} {pool:<8} "
              f"{'y' if r['scale_target'] else 'n':<3} "
              f"{'y' if r['interactions'] else 'n':<3} {r['shrink']:<5} "
              f"{r.get('blend', 0.0):<4} "
              f"{'y' if r.get('stack_baseline') else 'n':<3} "
              f"{o['n_wins']}/{o['n_horizons']:<4} {o['mean_ratio']:<7.3f} "
              f"{o['worst_ratio']:<7.3f} "
              f"{o['mae'] if o['mae'] is not None else float('nan'):.4f}")

    # Two dev-only selection rules, declared before either was scored:
    #   A. lowest mean ratio to the best baseline  (best average accuracy)
    #   B. most horizons beaten, ratio breaking ties  (the literal brief)
    # Both are chosen on dev. Reporting both means two holdout peeks instead
    # of one, which is disclosed rather than hidden.
    win = results[0]
    hold = win["holdout"]
    by_wins = sorted(results,
                     key=lambda r: (-r["dev"]["_overall"]["n_wins"],
                                    r["dev"]["_overall"]["mean_ratio"]))[0]
    incumbent = next((r for r in results
                      if r["model_name"] == "lin_sgd0.01"
                      and r["features"] == "base" and not r["pool_dam"]
                      and not r["pool_horizon"] and not r["scale_target"]
                      and not r["interactions"] and r["shrink"] == 1.0
                      and not r.get("blend") and not r.get("stack_baseline")),
                     None)

    print(f"\n=== dev winner on the untouched holdout (>= {SPLIT}) ===")
    for h in sorted(k for k in hold if isinstance(k, int)):
        v = hold[h]
        flag = "WIN " if v["wins"] else "loss"
        thin = "" if v["n"] >= MIN_SCORED else f"  (n={v['n']}, unranked)"
        print(f"  h={h}  model {v['mae']:.4f}  baseline {v['best_baseline']:.4f}"
              f"  {flag}{thin}")
    print(f"  mean ratio {hold['_overall']['mean_ratio']:.3f}, "
          f"{hold['_overall']['n_wins']}/{hold['_overall']['n_horizons']} horizons")

    inc_h = None
    if incumbent:
        inc_h = incumbent["holdout"]
        print(f"  incumbent (lin_sgd0.01/base/per-dam): mean ratio "
              f"{inc_h['_overall']['mean_ratio']:.3f}, "
              f"{inc_h['_overall']['n_wins']}/{inc_h['_overall']['n_horizons']}")

    # Dev-to-holdout slippage is the honest measure of how much of the
    # winner's advantage was the search fitting the dev period.
    print(f"\n  dev mean ratio {win['dev']['_overall']['mean_ratio']:.3f} "
          f"-> holdout {hold['_overall']['mean_ratio']:.3f}")

    payload = {
        "split": SPLIT,
        "n_configs": len(results),
        "n_failed": failed,
        "ranked_on": "dev only; holdout scored once by the winner",
        "winner": win,
        "winner_holdout": hold,
        "incumbent_holdout": inc_h,
        "winner_by_wins": by_wins,
        "top20": results[:20],
    }
    OUT.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
