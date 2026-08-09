"""Guard the PAGASA parser against silent layout drift.

If PAGASA reshuffles the table, these fail loudly rather than letting the
collector append a column of NaNs for weeks before anyone notices.
"""

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
from data.fetch_dams import append, parse  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "flood_20260807.html"
SCRAPED_AT = datetime(2026, 8, 7, 13, 40)

# Canonical names — the fixture page says "Magat Dam", older pages say "Magat".
EXPECTED_DAMS = {
    "Angat", "Ipo", "La Mesa", "Ambuklao", "Binga",
    "San Roque", "Pantabangan", "Magat", "Caliraya",
}


@pytest.fixture(scope="module")
def df():
    return parse(FIXTURE.read_text(encoding="utf-8"), SCRAPED_AT)


def test_all_dams_present(df):
    assert set(df["dam"]) == EXPECTED_DAMS


def test_two_observations_per_dam(df):
    assert df.groupby("dam").size().eq(2).all()


def test_known_values(df):
    """Spot-check against the numbers visible on the page on 2026-08-07."""
    angat = df[df["dam"] == "Angat"].set_index("obs_datetime")
    assert angat.loc["2026-08-07T08:00", "rwl_m"] == pytest.approx(158.13)
    assert angat.loc["2026-08-06T08:00", "rwl_m"] == pytest.approx(157.49)
    assert angat.loc["2026-08-07T08:00", "nhwl_m"] == pytest.approx(210.00)
    assert angat.loc["2026-08-07T08:00", "rule_curve_m"] == pytest.approx(180.79)


def test_rwl_is_never_null(df):
    """The target variable. A null here means the scrape silently degraded."""
    assert df["rwl_m"].notna().all()


def test_absent_reference_elevations_are_null_not_zero(df):
    """Caliraya has no NHWL and Ipo/La Mesa/Caliraya no rule curve.

    Left as 0.00 these read as 'reservoir is 286 m over its limit' and every
    spill-risk rule fires.
    """
    caliraya = df[df["dam"] == "Caliraya"]
    assert caliraya["nhwl_m"].isna().all()
    assert caliraya["dev_nhwl_m"].isna().all()
    assert df[df["dam"] == "La Mesa"]["rule_curve_m"].isna().all()
    # ...but dams that do have one keep it.
    assert df[df["dam"] == "Angat"]["rule_curve_m"].notna().all()


def test_year_rollover():
    """A December page scraped on 1 January must not be stamped next year."""
    html = FIXTURE.read_text(encoding="utf-8").replace("Aug-07", "Dec-31")
    out = parse(html, datetime(2027, 1, 1, 8, 0))
    stamps = set(out[out["dam"] == "Angat"]["obs_datetime"])
    assert "2026-12-31T08:00" in stamps
    assert not any(s.startswith("2027") for s in stamps)


def test_append_is_idempotent(df, tmp_path):
    out = tmp_path / "dam_levels.csv"
    assert append(df, out) == len(df)
    assert append(df, out) == 0
    assert len(pd.read_csv(out)) == len(df)


BASIN_FIXTURE = Path(__file__).parent / "fixtures" / "basins_20260809.html"


def test_basin_flood_watch():
    """The flood table on the same page: 18 river basins + dam sub-basins."""
    from data.fetch_dams import parse_basins
    b = parse_basins(BASIN_FIXTURE.read_text(encoding="utf-8"), SCRAPED_AT)
    assert len(b) == 22
    assert set(b["kind"]) == {"river_basin", "dam_sub_basin"}
    assert (b["kind"] == "river_basin").sum() == 18


def test_non_flood_watch_is_not_a_watch():
    """"Non-Flood Watch" contains "Flood Watch" — a substring test inverts
    every quiet basin into an alarm."""
    from data.fetch_dams import parse_basins
    b = parse_basins(BASIN_FIXTURE.read_text(encoding="utf-8"), SCRAPED_AT)
    quiet = b[b["status"].str.lower().str.startswith("non")]
    assert len(quiet) > 0
    assert not quiet["on_watch"].any()
    assert b[~b["status"].str.lower().str.startswith("non")]["on_watch"].all()
