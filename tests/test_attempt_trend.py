import math

from eval.attempt_next import add_trend


def test_trend_reads_only_the_past_and_by_date():
    rows = [{"dam": "X", "date": d, "rwl_m": v} for d, v in
            [("2025-01-01", 10.0), ("2025-01-04", 13.0), ("2025-01-05", 99.0)]]
    add_trend(rows)
    # 01-04 minus 01-01; the future 01-05 value must never leak in
    assert rows[1]["trend_3d"] == 3.0
    # 7 days back does not exist: missing, not zero
    assert math.isnan(rows[1]["trend_7d"])
    # 01-05 minus 01-02 (a gap) is missing, not the row 3 positions back
    assert math.isnan(rows[2]["trend_3d"])
