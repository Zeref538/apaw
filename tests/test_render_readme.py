"""The README defends itself.

The point of generating the scoreboard is that nobody has to remember to
update it. That only holds if the wording actually changes when the counts
cross the gate — otherwise the file rots exactly as a hand-typed one would,
but with more machinery.
"""

import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from eval.render_readme import END, START, patch, render  # noqa: E402


def metrics(certified: set[int], n_thin: int = 117):
    """Seven horizons, all ahead of the baseline; `certified` clear the gate."""
    return {"per_horizon": {
        str(h): {"n": 900 if h in certified else n_thin,
                 "enough_data": h in certified,
                 "min_scored": 200,
                 "mae_model": 0.4,
                 "mae_persistence": 0.8,
                 "best_baseline": "persistence",
                 "mae_best_baseline": 0.8,
                 "beats_baseline": h in certified}
        for h in range(1, 8)}}


def test_says_ahead_but_counting_while_horizons_are_thin():
    out = render(metrics({1, 2}), today=date(2026, 8, 10))
    assert "ahead of both naive baselines at all 7 horizons" in out
    assert "2 of 7 clear the 200-forecast bar" in out
    # The distance to the gate is stated so nobody has to work it out.
    assert "needs 83 more scored forecasts" in out
    assert "clears the 200-forecast bar" not in out


def test_flips_to_the_full_claim_once_every_horizon_is_certified():
    """This is the whole reason the file is generated: on the day the last
    horizon crosses 200, the README must start making the stronger claim
    without anyone editing it."""
    out = render(metrics(set(range(1, 8))), today=date(2026, 8, 21))
    assert "all 7 horizons, and every one of them clears" in out
    assert "still counting" not in out


def test_reports_a_loss_as_a_loss():
    m = metrics({1, 2})
    m["per_horizon"]["1"].update(mae_model=0.9, beats_baseline=False)  # worse
    out = render(m, today=date(2026, 8, 10))
    assert "ahead at 6 of 7 horizons" in out
    assert "+1d" in out.split("listed above as losses, not hidden:")[1]


def test_patch_replaces_only_the_marked_region_and_is_idempotent():
    doc = f"before\n{START}\nstale\n{END}\nafter\n"
    once = patch(doc, render(metrics({1, 2}), today=date(2026, 8, 10)))
    assert once.startswith("before\n") and once.endswith("after\n")
    assert "stale" not in once
    assert patch(once, render(metrics({1, 2}), today=date(2026, 8, 10))) == once


def test_refuses_to_guess_when_the_markers_are_gone():
    with pytest.raises(SystemExit):
        patch("a README with no markers", "block")


def test_the_real_readme_still_has_its_markers():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert text.count(START) == 1 and text.count(END) == 1
