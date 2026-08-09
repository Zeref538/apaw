"""Naive baselines. Every model claim is measured against these.

Both predict the CHANGE in reservoir level over the horizon, matching the
model's target. Persistence is the one to beat, and at short horizons it is
genuinely hard to beat — a reservoir tomorrow is very nearly a reservoir today.
"""

from __future__ import annotations


def persistence(row: dict) -> float:
    """The level doesn't move. Delta = 0."""
    return 0.0


def drift(row: dict) -> float:
    """Yesterday's 24h change, carried forward across the horizon.

    PAGASA publishes the 24-hour deviation directly, so this costs nothing.
    Falls back to persistence when the deviation is missing.
    """
    dev = row.get("dev_24h_m")
    if dev is None:
        return 0.0
    return float(dev) * float(row["horizon"])


BASELINES = {"persistence": persistence, "drift": drift}
