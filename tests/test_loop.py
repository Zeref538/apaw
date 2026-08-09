"""The deferred-scoring path.

This is the heart of the self-improving claim and the easiest thing to get
silently wrong: a prediction must be scored against the observation it actually
named, only once that observation exists, and exactly once.
"""

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data"))

import pipeline.run as loop  # noqa: E402
from model.online import new_detector, new_model  # noqa: E402


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """Point the ledger and logs at a temp dir so the real ones stay put."""
    monkeypatch.setattr(loop, "LEDGER", tmp_path / "predictions.csv")
    monkeypatch.setattr(loop, "ERRORS", tmp_path / "error_log.csv")
    monkeypatch.setattr(loop, "DRIFT_LOG", tmp_path / "drift.csv")
    return tmp_path


@pytest.fixture
def table():
    """Two dam-days: the issue date and the day it predicted."""
    return pd.DataFrame([
        {"dam": "Angat", "date": "2026-01-01", "rwl_m": 100.0},
        {"dam": "Angat", "date": "2026-01-02", "rwl_m": 101.5},
    ])


def _ledger_row(**over):
    row = {
        "issue_date": "2026-01-01", "target_date": "2026-01-02",
        "dam": "Angat", "horizon": 1,
        "issue_rwl_m": 100.0, "pred_delta": 1.0,
        "features": json.dumps({"rwl_m": 100.0, "rain_7d": 20.0}),
        "baseline_inputs": json.dumps({"dev_24h_m": 0.5, "horizon": 1}),
        "scored": False,
    }
    row.update(over)
    return row


def test_scores_against_the_named_target_date(isolated, table):
    pd.DataFrame([_ledger_row()]).to_csv(loop.LEDGER, index=False)
    models = {("Angat", 1): new_model()}
    detectors = {("Angat", 1): new_detector()}

    scored, _ = loop.score_due(table, models, detectors)

    assert scored == 1
    errors = pd.read_csv(loop.ERRORS)
    # Actual rose 1.5; the model said 1.0.
    assert errors.loc[0, "actual_delta"] == pytest.approx(1.5)
    assert errors.loc[0, "abs_err_model"] == pytest.approx(0.5)
    # Persistence said 0.0, so its error is the full 1.5.
    assert errors.loc[0, "abs_err_persistence"] == pytest.approx(1.5)


def test_never_scores_twice(isolated, table):
    pd.DataFrame([_ledger_row()]).to_csv(loop.LEDGER, index=False)
    models = {("Angat", 1): new_model()}
    detectors = {("Angat", 1): new_detector()}

    assert loop.score_due(table, models, detectors)[0] == 1
    assert loop.score_due(table, models, detectors)[0] == 0
    assert len(pd.read_csv(loop.ERRORS)) == 1


def test_leaves_unlanded_predictions_open(isolated, table):
    """A forecast for a day PAGASA hasn't published yet must stay pending."""
    pd.DataFrame([_ledger_row(target_date="2026-01-09", horizon=8)]).to_csv(
        loop.LEDGER, index=False)
    models, detectors = {}, {}

    assert loop.score_due(table, models, detectors)[0] == 0
    assert not loop.ERRORS.exists()
    assert not pd.read_csv(loop.LEDGER).loc[0, "scored"]


def test_learning_actually_moves_the_model(isolated, table):
    """learn_one must be called on the newly-labeled row, not skipped."""
    pd.DataFrame([_ledger_row()]).to_csv(loop.LEDGER, index=False)
    model = new_model()
    feats = {"rwl_m": 100.0, "rain_7d": 20.0}
    before = model.predict_one(feats)

    loop.score_due(table, {("Angat", 1): model},
                   {("Angat", 1): new_detector()})

    assert model.predict_one(feats) != before
