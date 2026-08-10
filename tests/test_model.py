"""The pooled Nowcaster.

Two things here are load-bearing and silent when broken: the horizon has to
reach the model as a feature (otherwise one pooled model answers the same
number for every horizon), and the running statistics have to stay causal
(otherwise a prediction is informed by its own label and every score is a lie).
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from model.online import Nowcaster, load, save  # noqa: E402


ROW = {"dam": "Angat", "rwl_m": 200.0, "rain_7d": 30.0, "dev_24h_m": 0.2,
       "rule_curve_m": float("nan")}


def test_horizon_reaches_the_model():
    """Pooling only works if the model can tell the horizons apart."""
    f1 = Nowcaster.raw_features(ROW, 1)
    f7 = Nowcaster.raw_features(ROW, 7)
    assert f1["horizon"] == 1.0 and f7["horizon"] == 7.0
    assert f1["dam=Angat"] == 1.0


def test_missing_features_are_omitted_not_zeroed():
    """A dam with no rule curve must not be told its rule curve is 0.0 —
    that is the difference between 'unknown' and 'at the limit'."""
    assert "rule_curve_m" not in Nowcaster.raw_features(ROW, 1)


def test_predictions_differ_by_horizon_after_learning():
    m = Nowcaster()
    for i in range(60):
        for h, delta in ((1, 0.1), (7, 2.0)):
            m.learn(Nowcaster.raw_features({**ROW, "rain_7d": 10.0 + i}, h),
                    "Angat", delta)
    p1 = m.predict(Nowcaster.raw_features(ROW, 1), "Angat")
    p7 = m.predict(Nowcaster.raw_features(ROW, 7), "Angat")
    assert p1 != pytest.approx(p7), "pooled model is ignoring the horizon"
    assert p7 > p1, "the 7-day rise should exceed the 1-day one"


def test_statistics_are_causal():
    """The scaler must not have seen a row before that row is predicted."""
    m = Nowcaster()
    feats = Nowcaster.raw_features(ROW, 1)
    m.predict(feats, "Angat")
    assert m.feat.n == {}, "predict() updated the feature statistics"
    assert m.target.n == {}, "predict() updated the target statistics"
    m.learn(feats, "Angat", 1.0)
    assert m.target.n["Angat"] == 1


def test_prediction_is_finite_from_cold():
    """Before anything is learned the answer must be a number, not None/NaN."""
    assert Nowcaster().predict(Nowcaster.raw_features(ROW, 3), "Angat") == 0.0


def test_state_roundtrips_and_rejects_a_stale_pickle(tmp_path):
    path = tmp_path / "models.pkl"
    m = Nowcaster()
    m.learn(Nowcaster.raw_features(ROW, 1), "Angat", 0.5)
    save(m, path)
    assert load(path).target.n["Angat"] == 1

    # An older layout must be discarded rather than half-restored; backtest.py
    # rebuilds equivalent state from the committed history.
    import pickle
    with path.open("wb") as fh:
        pickle.dump({("Angat", 1): "an old per-dam-per-horizon model"}, fh)
    assert isinstance(load(path), Nowcaster)
    assert load(path).target.n == {}
