"""Incremental model: one River regressor per (dam, horizon).

Never retrained from scratch. `learn_one` is called once per observation as
its label arrives, and the whole set of models is pickled between runs so
learning is cumulative across GitHub Actions runs.

State lives in model/state/ and is committed — it is small, and versioning it
means the learning curve is reproducible from git history alone.
"""

from __future__ import annotations

import pickle
from pathlib import Path

from river import compose, drift, linear_model, optim, preprocessing

STATE = Path(__file__).parent / "state" / "models.pkl"

# Feature columns fed to the model. Anything NaN is omitted from the dict
# rather than imputed — River simply doesn't use an absent feature, which is
# the right behaviour for dams that have no rule curve at all.
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


def new_model():
    """Scaler + linear regression. Deliberately the simplest thing that learns.

    ponytail: a linear model on ~15 features. No trees, no ensemble. Reservoir
    inflow is genuinely non-linear (spill thresholds, saturated catchments), so
    if this plateaus above the baseline, the upgrade is
    `tree.HoeffdingTreeRegressor` or a bagged variant — but not before the
    linear version is measured.
    """
    return compose.Pipeline(
        preprocessing.StandardScaler(),
        linear_model.LinearRegression(optimizer=optim.SGD(0.01)),
    )


def new_detector():
    """ADWIN over the model's own error stream.

    Flags the monsoon onset / typhoon regime changes the PRD wants documented.
    """
    return drift.ADWIN()


def to_features(row: dict) -> dict:
    out = {}
    for name in FEATURES:
        val = row.get(name)
        if val is None:
            continue
        try:
            val = float(val)
        except (TypeError, ValueError):
            continue
        if val != val:  # NaN
            continue
        out[name] = val
    return out


def load(path: Path = STATE) -> dict:
    if path.exists():
        with path.open("rb") as fh:
            return pickle.load(fh)
    return {}


def save(models: dict, path: Path = STATE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        pickle.dump(models, fh)
