"""Catchment sampling, lead-time forecast rain, and the basin forecaster."""

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data"))

from dams import CATCHMENT_RADIUS_KM, DAMS, catchment_points  # noqa: E402


def test_catchment_points_surround_the_dam():
    for dam, meta in DAMS.items():
        pts = catchment_points(dam)
        assert len(pts) == 5
        assert pts[0] == (meta["lat"], meta["lon"])          # centre first
        lats = [p[0] for p in pts]
        lons = [p[1] for p in pts]
        # Offsets straddle the dam in both axes rather than all sitting on one side.
        assert max(lats) > meta["lat"] and min(lats) < meta["lat"]
        assert max(lons) > meta["lon"] and min(lons) < meta["lon"]


def test_catchment_offsets_are_roughly_the_requested_radius():
    import math
    lat, lon = DAMS["Angat"]["lat"], DAMS["Angat"]["lon"]
    for plat, plon in catchment_points("Angat")[1:]:
        dy = (plat - lat) * 111.32
        dx = (plon - lon) * 111.32 * math.cos(math.radians(lat))
        assert math.hypot(dx, dy) == pytest.approx(CATCHMENT_RADIUS_KM, rel=0.02)


def test_forecast_rain_sums_the_right_lead_times(tmp_path, monkeypatch):
    """rain_next_3d issued on day t must be the forecasts for t+1..t+3 that
    were made 1, 2 and 3 days ahead respectively — not any other combination."""
    import build_table

    rows = []
    for lead in range(1, 8):
        for day in range(1, 8):
            # forecast for 2026-01-01 + day, issued `lead` days earlier
            rows.append({
                "dam": "Angat",
                "date": (pd.Timestamp("2026-01-01") + pd.to_timedelta(day, unit="D")
                         ).strftime("%Y-%m-%d"),
                "lead": lead,
                "rain_mm": lead * 10 + day,
            })
    f = tmp_path / "rain_forecast.csv"
    pd.DataFrame(rows).to_csv(f, index=False)
    monkeypatch.setattr(build_table, "RAIN_FCST", f)

    out = build_table.forecast_rain()
    issue = out[(out["dam"] == "Angat")
                & (out["date"] == pd.Timestamp("2026-01-01"))]
    assert len(issue) == 1
    # day t+1 at lead 1 (11), t+2 at lead 2 (22), t+3 at lead 3 (33)
    assert issue.iloc[0]["fc_rain_next_3d"] == pytest.approx(11 + 22 + 33)


def test_forecast_rain_skips_incomplete_windows(tmp_path, monkeypatch):
    """A window missing a lead would silently under-count the rain."""
    import build_table
    rows = [{"dam": "Angat", "date": "2026-01-02", "lead": 1, "rain_mm": 5.0}]
    f = tmp_path / "rain_forecast.csv"
    pd.DataFrame(rows).to_csv(f, index=False)
    monkeypatch.setattr(build_table, "RAIN_FCST", f)

    out = build_table.forecast_rain()
    # Only lead 1 present, so neither the 3-day nor the 7-day window qualifies.
    assert out.empty or out["fc_rain_next_3d"].isna().all()


def test_basin_forecaster_refuses_thin_history(tmp_path, monkeypatch):
    """With a few days collected it must say so, not publish a score."""
    from eval import basin_forecast

    rows = [{"basin": "Agno", "status": "Flood Watch", "on_watch": True,
             "kind": "river_basin", "date": "2026-08-0%d" % d,
             "scraped_at": ""} for d in range(1, 5)]
    f = tmp_path / "basin_status.csv"
    pd.DataFrame(rows).to_csv(f, index=False)
    monkeypatch.setattr(basin_forecast, "BASINS", f)

    res = basin_forecast.run()
    assert res["status"] == "not enough history yet"
    assert "per_horizon" not in res
