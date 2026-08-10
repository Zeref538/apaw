"""Incremental model: ONE Mondrian forest for every dam and horizon.

Never retrained from scratch. `learn_one` is called once per observation as
its label arrives, and the state is pickled between runs so learning is
cumulative across GitHub Actions runs.

State lives in model/state/ and is committed — it is small, and versioning it
means the learning curve is reproducible from git history alone.

Why one model instead of 63
---------------------------
The first version kept a separate linear model per (dam, horizon). With the
history that actually exists that gave each model 13 to 94 rows to learn 15
coefficients from, and it lost to persistence at most horizons.

`eval/experiment.py` searched 3,776 configurations on dates before
2025-11-01 and scored the winner once on the untouched dates after. Pooling
every dam and horizon into a single model — with the dam as a one-hot feature
and the horizon as a numeric one — was worth far more than any change of
estimator, because it turns ~94 rows into ~1,750.

The chosen configuration beat both naive baselines at all seven horizons on
the held-out period, with dev 0.615 -> holdout 0.617 mean ratio: essentially
no slippage, which is what says the search found a real effect rather than
fitting itself to the evaluation set.

Read model/README.md before changing any of this.
"""

from __future__ import annotations

import math
import pickle
from pathlib import Path

from river import drift, forest

STATE = Path(__file__).parent / "state" / "models.pkl"

# Bumped whenever the pickled layout changes. A mismatch is discarded rather
# than unpickled into the wrong shape; eval/backtest.py rebuilds the state by
# walking the history in order, so nothing is actually lost.
STATE_VERSION = 2

FEATURES = [
    "rwl_m",
    "dev_24h_m",
    "dev_rule_curve_m",
    "dev_nhwl_m",
    "rain_1d", "rain_3d", "rain_7d", "rain_14d", "rain_30d",
    "rain_next_3d", "rain_next_7d",
    "temperature_2m_mean",
    "et0_fao_evapotranspiration",
    "doy_sin", "doy_cos",
]


def new_estimator():
    """Aggregated Mondrian Forest, 50 trees, aggregation off.

    Mondrian trees split on random thresholds and average over the ensemble,
    which behaves like Bayesian model averaging rather than committing hard to
    a split. On a few hundred samples that is exactly the right bias, and it
    is why this beat the linear model, the Hoeffding trees and the adaptive
    random forest in the search.

    `use_aggregation=False` won on the dev period: the per-node aggregation
    weighting needs more data than we have to pay for itself.

    ponytail: 50 trees is where the dev curve flattened; 100 was no better and
    twice the runtime. Revisit once the collector has a few thousand rows.
    """
    return forest.AMFRegressor(n_estimators=50, use_aggregation=False, seed=7)


def new_detector():
    """ADWIN over the model's own error stream.

    Flags the monsoon onset / typhoon regime changes the PRD wants documented.
    """
    return drift.ADWIN()


class _Running:
    """Welford mean/variance, updated only after a row has been used."""

    def __init__(self):
        self.n, self.mean, self.m2 = {}, {}, {}

    def std(self, key):
        n = self.n.get(key, 0)
        if n < 2:
            return None
        return math.sqrt(self.m2[key] / n)

    def update(self, key, x):
        n = self.n.get(key, 0) + 1
        mean = self.mean.get(key, 0.0)
        d = x - mean
        mean += d / n
        self.m2[key] = self.m2.get(key, 0.0) + d * (x - mean)
        self.n[key], self.mean[key] = n, mean


class Nowcaster:
    """The whole model: one forest, plus the scaling it needs to pool dams.

    Two pieces of causal bookkeeping travel with the estimator, and both are
    updated *after* a row has been predicted so that no prediction is ever
    informed by its own label:

    - feature standardisation, because the forest is fed rainfall in mm
      alongside a one-hot dam flag;
    - a per-dam target scale, because the dams differ in how much their level
      moves by a factor of twelve (La Mesa 0.16 m, San Roque 1.91 m). Pooled
      raw, San Roque would write the model and La Mesa would be noise.
    """

    version = STATE_VERSION

    def __init__(self):
        self.est = new_estimator()
        self.feat = _Running()
        self.target = _Running()

    # -- features ---------------------------------------------------------

    @staticmethod
    def raw_features(row: dict, horizon: int) -> dict:
        """Row + horizon -> plain feature dict, unscaled.

        The ledger stores exactly this, so a forecast is always re-learnable
        from what it actually saw. Missing values are omitted rather than
        imputed — the forest simply doesn't use an absent feature, which is
        right for the dams that have no rule curve at all.
        """
        out = {}
        for name in FEATURES:
            val = row.get(name)
            try:
                val = float(val)
            except (TypeError, ValueError):
                continue
            if val != val:  # NaN
                continue
            out[name] = val
        dam = row.get("dam")
        if dam:
            out[f"dam={dam}"] = 1.0
        out["horizon"] = float(horizon)
        return out

    def _scaled(self, raw: dict) -> dict:
        out = {}
        for k, v in raw.items():
            sd = self.feat.std(k)
            if sd is None:
                # No spread known yet. Emit 0 rather than the raw value: an
                # unscaled rwl_m of ~200 in the first steps is enough to wreck
                # a model that has seen nothing else.
                out[k] = 0.0
            elif sd < 1e-6:
                out[k] = v          # constant, e.g. a one-hot dam flag
            else:
                out[k] = max(-5.0, min(5.0, (v - self.feat.mean[k]) / sd))
        return out

    # -- use --------------------------------------------------------------

    def predict(self, raw: dict, dam: str) -> float:
        pred = self.est.predict_one(self._scaled(raw))
        if pred is None or not math.isfinite(pred):
            return 0.0
        sd = self.target.std(dam)
        pred = float(pred) * sd if sd is not None else float(pred)
        return pred if math.isfinite(pred) else 0.0

    def learn(self, raw: dict, dam: str, actual: float) -> None:
        sd = self.target.std(dam)
        y = actual / sd if sd and sd > 1e-6 else actual
        self.est.learn_one(self._scaled(raw), y)
        for k, v in raw.items():
            self.feat.update(k, v)
        self.target.update(dam, actual)


def load(path: Path = STATE) -> Nowcaster:
    """Returns saved state, or a fresh model if there is none or it is stale."""
    if path.exists():
        try:
            with path.open("rb") as fh:
                obj = pickle.load(fh)
            if isinstance(obj, Nowcaster) and \
                    getattr(obj, "version", 0) == STATE_VERSION:
                return obj
        except Exception:
            # A corrupt or older pickle is not worth failing the run over.
            # backtest.py rebuilds equivalent state from the committed history.
            pass
    return Nowcaster()


def save(model: Nowcaster, path: Path = STATE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("wb") as fh:
        pickle.dump(model, fh)
    tmp.replace(path)
