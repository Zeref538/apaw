"""Translate a forecast reservoir level into a plain-language risk level.

Thresholds are PAGASA's own published elevations, not invented ones. Dams with
no published reference get "Not rated" rather than a guess — Caliraya has no
NHWL at all, and Ipo, La Mesa and Caliraya have no rule curve.
"""

from __future__ import annotations

import math

NORMAL = "Normal"
WATCH = "Watch"
SPILL_WATCH = "Spill Watch"
NOT_RATED = "Not rated"

DESCRIPTIONS = {
    NORMAL: "Forecast level stays below the operating rule curve.",
    WATCH: "Forecast level crosses the rule curve within the next 7 days.",
    SPILL_WATCH: (
        "Forecast level reaches the normal high water level within 7 days; "
        "a gate release becomes likely."
    ),
    NOT_RATED: "PAGASA publishes no reference elevation for this dam.",
}


def _valid(x) -> bool:
    return x is not None and not (isinstance(x, float) and math.isnan(x))


def classify(forecast_levels, nhwl, rule_curve) -> str:
    """forecast_levels: the predicted RWL at each horizon, in metres."""
    levels = [float(x) for x in forecast_levels if _valid(x)]
    if not levels:
        return NOT_RATED
    peak = max(levels)

    if _valid(nhwl) and peak >= float(nhwl):
        return SPILL_WATCH
    if _valid(rule_curve) and peak >= float(rule_curve):
        return WATCH
    if not _valid(nhwl) and not _valid(rule_curve):
        return NOT_RATED
    return NORMAL


def demo() -> None:
    # Angat-like: NHWL 210, rule curve 180.79
    assert classify([158.0, 159.0], 210.0, 180.79) == NORMAL
    assert classify([181.0, 182.0], 210.0, 180.79) == WATCH
    assert classify([209.0, 211.0], 210.0, 180.79) == SPILL_WATCH
    # Caliraya: no references at all.
    assert classify([286.8], float("nan"), float("nan")) == NOT_RATED
    # La Mesa: NHWL but no rule curve — still ratable for spill.
    assert classify([79.4], 80.15, float("nan")) == NORMAL
    assert classify([80.2], 80.15, float("nan")) == SPILL_WATCH
    # No usable forecast.
    assert classify([], 80.15, 70.0) == NOT_RATED
    print("risk classification ok")


if __name__ == "__main__":
    demo()
