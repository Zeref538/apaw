# Next attempt: the +1 day forecast

Written 2026-09-29, **before** anything below was run.

## The one target number

**+1 day MAE against persistence.**

- Published scoreboard: APAW 0.323 m vs persistence 0.362 m (n=853). That is 11% better.
- On the search's dev dates it is worse: ratio **0.964** (0.3031 vs 0.3145, n=646), just 3.6% better.
- Every other horizon beats persistence by 40-50%. So +1 day is the number a skeptic points at first.

## What has already been tried (not repeated)

`eval/experiment.py` searched 3,776 configurations: 25 River estimators, 4 feature sets, 4 pooling schemes, target scaling, shrinkage toward zero (0.8), blending with the baselines (4 rates) and stacking the baseline as a feature.

**Two gaps remain:**

1. **Every model used one fixed random seed (`seed=7`).** The winner's score is one draw of the forest's randomness. Nobody knows how much of 0.615 is luck.
2. **The only "trend" feature is the last 1-day change (`dev_24h_m`).** Nothing says how the level has moved over the last several days.

## Ideas

**A. More trees with aggregation off: `amf100_noagg`.**
The search tried 100 trees only with aggregation on, and aggregation off was what won at 50 trees. So 100 trees with it off was never run.

- Why it should help: averaging more randomised trees lowers variance without adding bias (Breiman 2001, *Random Forests*, Machine Learning 45). The +1 day error is small and noisy, which is where variance matters most.
- Cost: the saved forest roughly doubles, from ~88 MB to ~176 MB. That still fits the Actions cache (10 GB limit), but the rebuild after a cache miss takes twice as long.

**B. Level trend features: change over the last 3 and 7 days.**
`rwl_m` now minus `rwl_m` 3 and 7 calendar days earlier. The earlier value is looked up by date, not by row, because the history has gaps. If the earlier value is missing, the feature is left out (NaN is omitted, the same as other features).

- Why it should help: past values of the series are the standard predictors for short-range forecasts (Hyndman & Athanasopoulos, *Forecasting: Principles and Practice*, 3rd ed., ch. 7 and 9). A reservoir that has risen for a week tends to keep rising tomorrow, and one day of change alone does not show that.
- Backward-only: both look at t-3 and t-7, never t+1. A test checks this.

**C. A + B together.** This runs only as a third candidate. It is not a fallback to try if A and B lose.

## Rules, fixed now

- **The holdout stays exactly as it is:** dates on or after `SPLIT = 2025-11-01`, untouched. Same labeled rows, same baselines, same `score()` function.
- **5 seeds each (1, 2, 3, 4, 5)** for the incumbent (`amf50_noagg`, base, dam+h pooled, scaled) and for A, B and C. The incumbent is re-run on the same 5 seeds, so the comparison is fair and seed 7 is not favoured.
- **Choosing is done on dev only.** A candidate is chosen only if, on dev +1 day MAE:
  - its 5-seed mean is at least **3% lower** than the incumbent's 5-seed mean, and
  - it is lower than the incumbent on **at least 4 of the 5 seeds** (seed for seed).
  If more than one qualifies, the one with the lowest dev mean wins. If none qualifies, the attempt stops there and the holdout is not opened.
- **Holdout, read once, for the chosen candidate only.** It ships only if:
  - its 5-seed mean holdout +1 day MAE is lower than the incumbent's, and
  - no other horizon's 5-seed mean holdout ratio is worse than the incumbent's by more than **0.02** (2 points), and
  - the overall holdout mean ratio is not worse by more than 0.02.
- **Results are reported as mean and range (min to max) over the 5 seeds**, for every candidate, including losers.
- If it ships, `model/online.py` changes, and `eval/backtest.py` is re-run so the published scoreboard reflects it.

## Caveat, written in advance

Holdout +1 day has n=198, below the project's own 200 bar. Even a win there is **unranked**, and the README will say so.

## Budget, measured

- One prequential pass of the incumbent: **8.0 s** (measured 2026-09-29 on this laptop). It reproduced the published dev mean ratio of 0.615 exactly.
- Plan: 4 configs × 5 seeds = 20 passes. A with 100 trees takes about twice as long. Estimate: **about 4 minutes**. Then one `backtest.py` run if something ships.
- Hard stop: this runs once. No extra ideas get added after the results are in.

## Results

Run once on 2026-09-29 with `uv run python eval/attempt_next.py`: 20 passes in 4 min 37 s. Raw output: `eval/attempt_next.json`.

**Nothing won. The shipped model stays. The holdout was never opened.**

Dev +1 day MAE in metres, mean and (min to max) over seeds 1-5:

| Config | +1d MAE | vs incumbent | Seeds better | Dev mean ratio, all horizons |
|---|---|---|---|---|
| Incumbent (50 trees) | 0.3051 (0.3009 to 0.3094) | | | 0.623 (0.618 to 0.628) |
| A: 100 trees | 0.3014 (0.2978 to 0.3045) | -1.2% | 5 of 5 | 0.617 (0.614 to 0.620) |
| B: trend features | 0.3022 (0.2986 to 0.3068) | -1.0% | 4 of 5 | 0.621 (0.617 to 0.629) |
| C: both | 0.2980 (0.2944 to 0.3007) | -2.3% | 5 of 5 | 0.615 (0.611 to 0.621) |

What it found:

- **All three help a little, and consistently**, but none reaches the 3% bar set in advance. C beats the incumbent on every seed, by 2.3% on average. By the rule, that is not a win, and the bar is not moved after seeing it.
- **The seed matters about as much as the ideas.** The published dev score of 0.615 came from seed 7. Across seeds 1-5 the same model scores 0.618 to 0.628. The published number was at the lucky end of its own range, and the README now says so.
- **+1 day stays close to persistence.** On dev the incumbent's +1 day MAE is 0.3051 against persistence's 0.3145, so it is about 3% better. One day ahead, most of what moves a reservoir is gate operations, which no input here sees.

Not tried, and why: 150+ trees or more trend windows would be tuning after seeing results. The next honest step is data rather than knobs: dam release schedules, if a public source exists.
