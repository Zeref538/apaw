# APAW — Build Plan & Status

> Self-improving dam level and flood-watch nowcaster. Free tier only.
> Spec: [PRD.md](PRD.md) · working contract: [CLAUDE.md](CLAUDE.md)

## Repo layout

```
data/      scrapers, the committed observation record, feature build
             fetch_dams.py          dam levels + basin flood watch
             fetch_weather.py       Open-Meteo, catchment-mean rainfall
             fetch_rain_forecast.py archived forecasts at real lead times
             backfill_wayback.py    one-shot history seed
             build_table.py         join into the modelling table
             dams.py                registry, aliases, catchment points
model/     River models per (dam, horizon), pickled state
eval/      baselines, prequential backtest, risk rules, basin forecaster,
           prediction ledger, error log, metrics
pipeline/  run.py — the loop
web/       static dashboard (GitHub Pages)
.github/workflows/daily.yml
```

## Phase 0 — Collection ✅

- [x] `fetch_dams.py` — 9 dams from the PAGASA table, idempotent
- [x] Basin flood watch (18 river basins + 4 sub-basins) from the same page
- [x] `fetch_weather.py` — Open-Meteo archive + forecast, catchment mean
- [x] `backfill_wayback.py` — 166 dates recovered, 2021–2026
- [x] `build_table.py` — features and ΔRWL targets
- [x] Twice-daily Action, committing the record

**Gate met:** the Action runs green and the CSV grows on its own.

## Phase 1 — Baselines + incremental model ✅

- [x] Persistence and drift baselines
- [x] River regressor per (dam, horizon), 1–7 days, target ΔRWL
- [x] Prequential backtest, no leakage
- [x] State persisted and committed; the backtest warm-starts the live loop

**Gate met:** metrics published, losing horizons reported as losses.

## Phase 2 — The self-improving loop ✅

- [x] `pipeline/run.py` — fetch → score due → learn → issue → publish
- [x] Prediction ledger with the features captured at issue time
- [x] ADWIN drift detection wired into both backtest and loop
- [x] Fail-safe ordering: scrape first, commit even on failure

**Gate met:** unattended runs, state persists, error log grows.

## Phase 3 — Dashboard ✅

- [x] Animated dam cross-section with named elevation zones
- [x] Nine-dam overview, forecast chart, learning curve, skill scoreboard
- [x] Basin flood-watch board
- [x] Plain/technical registers, light/dark themes
- [x] Staleness banner, extrapolation flags, disclaimer

## Phase 4 — Honesty hardening ✅

- [x] Real archived forecast rain at true lead times where the archive reaches
      (2025→), ERA5 proxy elsewhere, **scored separately** so the optimism is
      visible rather than assumed away
- [x] Catchment-mean rainfall instead of a single point at the wall
- [x] Horizons under 200 scored forecasts published but not ranked
- [x] Second target: basin flood watch, with its own persistence baseline

## What's next

Ordered by value, not effort:

1. **Accrue history.** Most of what remains weak is thin data. Longer horizons
   and the basin classifier both unlock themselves as the collector runs.
2. **Real catchment polygons.** The sampled cross is a stand-in; HydroSHEDS
   basin boundaries are free and would make the rainfall input physically
   correct.
3. **Non-linear model** — but only once the linear one is measured and found
   wanting. `tree.HoeffdingTreeRegressor` is the obvious next rung.
4. **Inflow/outflow features.** PAGASA publishes both; they are collected and
   currently unused.
5. **Portfolio card** in the house format, once a horizon clears MIN_SCORED
   with a real win.

## Standing rules

- Reuse [Hangin'](https://github.com/Zeref538/hangin)'s refresh-and-publish
  pattern; only the fetcher, the online model, the drift detector and the
  dashboard visuals are genuinely new.
- Repo-committed state is the free, versioned default.
- One small model per (dam, horizon); no ensembles until the simple version is
  proven insufficient.
