"""Guards on the feature/target construction.

The leakage checks matter more than they look: a backward rain window that
quietly includes tomorrow's rain would make the backtest sing and the live
model flop, and nothing else in the pipeline would notice.
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "data"))
from build_table import RAIN_WINDOWS, build, weather_features  # noqa: E402
from dams import canonical  # noqa: E402


@pytest.fixture(scope="module")
def table():
    return build()


def test_magat_alias_collapses():
    """PAGASA has used both labels for the same reservoir."""
    assert canonical("Magat Dam") == canonical("Magat") == "Magat"
    assert canonical("  la  mesa  ") == "La Mesa" or canonical("La Mesa") == "La Mesa"


def test_one_row_per_dam_date_horizon(table):
    assert not table.duplicated(subset=["dam", "date", "horizon"]).any()


def test_backward_rain_excludes_the_future():
    """rain_Nd at day t must cover t-N+1..t, never t+1."""
    w = weather_features()
    one = w[w["dam"] == "Angat"].sort_values("date").reset_index(drop=True)
    i = 400  # arbitrary interior day, clear of the warm-up edge
    for win in RAIN_WINDOWS:
        expected = one["precipitation_sum"].iloc[i - win + 1: i + 1].sum()
        assert one[f"rain_{win}d"].iloc[i] == pytest.approx(expected), win


def test_forward_rain_is_strictly_future():
    """rain_next_Nd at day t must cover t+1..t+N, and must exclude t itself."""
    w = weather_features()
    one = w[w["dam"] == "Angat"].sort_values("date").reset_index(drop=True)
    i = 400
    for win in (3, 7):
        expected = one["precipitation_sum"].iloc[i + 1: i + 1 + win].sum()
        assert one[f"rain_next_{win}d"].iloc[i] == pytest.approx(expected), win


def test_target_is_the_level_change_over_the_horizon(table):
    labeled = table[table["target_delta"].notna()]
    assert len(labeled) > 0
    row = labeled.iloc[0]
    assert row["target_delta"] == pytest.approx(row["rwl_future"] - row["rwl_m"])


def test_target_lands_exactly_h_days_out(table):
    """A target stitched to the wrong future date is silent and fatal."""
    levels = table[["dam", "date", "rwl_m"]].drop_duplicates()
    lookup = {(r.dam, r.date): r.rwl_m for r in levels.itertuples()}
    labeled = table[table["target_delta"].notna()]
    for r in labeled.head(200).itertuples():
        future_date = r.date + pd.to_timedelta(int(r.horizon), unit="D")
        assert lookup.get((r.dam, future_date)) == pytest.approx(r.rwl_future)


def test_dev_24h_never_looks_forward(table):
    """Regression: PAGASA prints one 24h deviation per snapshot and shows it on
    BOTH the today and yesterday rows, so on the yesterday row it is the t->t+1
    change. Taken at face value it hands the model the answer, and a drift
    baseline scored 0.05 m MAE at h=1 off it.

    The recomputed column must equal rwl(t) - rwl(t-1), never rwl(t+1) - rwl(t).
    """
    levels = (table[["dam", "date", "rwl_m", "dev_24h_m"]]
              .drop_duplicates(subset=["dam", "date"])
              .sort_values(["dam", "date"]))
    lookup = {(r.dam, r.date): r.rwl_m for r in levels.itertuples()}

    day = pd.to_timedelta(1, unit="D")
    checked = 0
    for r in levels.itertuples():
        if pd.isna(r.dev_24h_m):
            continue
        yesterday = lookup.get((r.dam, r.date - day))
        assert yesterday is not None, "deviation defined without a prior day"
        # Backward-looking by construction. Note this cannot be written as
        # "must differ from tomorrow's change" — a steady reservoir really can
        # move the same amount two days running.
        assert r.dev_24h_m == pytest.approx(r.rwl_m - yesterday, abs=1e-6)
        checked += 1
    assert checked > 50, f"only {checked} rows exercised the check"


def test_every_labeled_row_has_weather(table):
    labeled = table[table["target_delta"].notna()]
    assert labeled["precipitation_sum"].notna().all()
