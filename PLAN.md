# Pulso — Phased Build Plan

> Self-improving dengue nowcaster. Free tier only. ~4 weeks part-time.
> Full spec: [PRD.md](PRD.md). Kickoff context: [HANDOFF.md](HANDOFF.md).

## Proposed repo layout

```
data/          fetchers (dengue, weather), cached snapshots (csv/parquet)
model/         incremental model, drift detector, persisted state
eval/          baseline, backtest, metrics logging, learning-curve builder
pipeline/      the daily orchestration entrypoint (fetch → update → log → publish)
web/           static dashboard (map, forecast chart, learning curve)
.github/workflows/daily.yml   the cron
CLAUDE.md      working contract
```

## Phase 0 — Data source (GATE, do this first)

- [ ] Confirm a free, refreshable PH regional dengue case source (OpenDengue /
      DOH-PIDSR). Document cadence, granularity, license, and how to fetch.
- [ ] Build `data/fetch_dengue.py` → clean regional weekly table.
- [ ] Build `data/fetch_weather.py` (Open-Meteo, no key) → daily weather per
      region, with engineered lags.
- [ ] Join into one modeling table; cache snapshots with timestamps.
- **EXIT GATE:** one command produces a clean, refreshable regional table with
  weather features. **No modeling before this passes.** If no free source
  works, invoke the HANDOFF fallback and re-scope.

## Phase 1 — Baseline + incremental model

- [ ] Naive baselines: last-week persistence + seasonal-naive.
- [ ] Incremental regressor per region (River or sklearn `partial_fit`),
      horizons 1–4 weeks.
- [ ] Chronological backtest (no leakage) vs baselines; log MAE per
      region/horizon.
- [ ] Persist model state to repo so learning is cumulative.
- **EXIT GATE:** model beats (or honestly ties) the baseline at 2–4wk horizons
  on the holdout; metrics written to `eval/`.

## Phase 2 — The self-improving loop

- [ ] `pipeline/run.py`: fetch new data → incremental update on newly labeled
      weeks → log prediction-vs-actual error → rebuild learning curve →
      publish dashboard data.
- [ ] Drift detection (River ADWIN or rolling-error threshold); on drift, adapt
      and flag in the log.
- [ ] `.github/workflows/daily.yml`: cron, commits updated state + metrics.
- **EXIT GATE:** the Action runs unattended for 3+ days, state persists across
  runs, and the learning curve gains points automatically.

## Phase 3 — Dashboard + ship

- [ ] Static dashboard: PH region risk map/heatmap, per-region forecast chart,
      the self-improvement learning curve, model-performance panel.
- [ ] Plain-language risk levels + educational disclaimer.
- [ ] README (honest baseline comparison, how the loop works), demo GIF,
      portfolio card, add to portfolio data.
- **EXIT GATE:** live dashboard + green daily Action + write-up; card metric in
  house format.

## Success tiers (from PRD)

- **Minimum:** incremental model + daily Action + baseline comparison + dashboard.
- **Good:** + learning curve trending down, drift detection live.
- **Headline:** beats baseline at 2–4wk, a documented drift-adapt event, multi-week
  hands-off Actions streak.

## Ponytail notes (keep it lazy)

- Reuse Hangin's Actions workflow and dashboard scaffolding — don't rebuild from
  scratch.
- Repo-committed model state is the free, versioned default; only reach for an
  external store if state gets large.
- One small online model per region; no ensemble/deep-learning until the simple
  version is measured and proven insufficient.
