# Pulso

**A self-improving nowcaster for Luzon dam levels and spill risk.**
Forecasts reservoir water level 1–7 days ahead for the nine major dams PAGASA
publishes, learns from every new observation, and reports the horizons where a
naive baseline still beats it.

Runs entirely on free infrastructure: GitHub Actions, open data, Open-Meteo,
GitHub Pages. No API keys, no paid compute.

> **Not an official warning.** This is an educational portfolio project, not a
> flood advisory. PAGASA and your local disaster risk reduction office are the
> authorities on dam releases and flooding.

---

## Honest results

Mean absolute error in metres, measured **prequentially** — every observation
is predicted by a model that has only ever seen strictly earlier ones, then
learned from. No train/test split to get wrong, and the same procedure the live
loop runs.

| Horizon | Pulso | Persistence | Best baseline | n | Verdict |
|---|---|---|---|---|---|
| +1d | 0.393 | **0.330** | 0.330 persistence | 844 | baseline wins |
| +2d | **0.602** | 0.698 | 0.682 drift | 206 | **Pulso** |
| +3d | **0.701** | 0.794 | 0.707 drift | 178 | **Pulso** |
| +4d | 1.170 | **0.649** | 0.649 persistence | 152 | baseline wins |
| +5d | 0.920 | **0.807** | 0.807 persistence | 117 | baseline wins |
| +6d | 1.130 | **0.981** | 0.981 persistence | 117 | baseline wins |
| +7d | 2.854 | **0.902** | 0.902 persistence | 144 | baseline wins |

**The model wins at +2d and +3d only.** Persistence wins at +1d, which is
expected — a reservoir tomorrow is very nearly a reservoir today. The +7d
number is not a real result yet; it is an unstable fit on 144 sparse points,
and it is published rather than hidden.

Regenerate with `uv run python eval/backtest.py`.

## How the loop works

```
        ┌──── twice daily, GitHub Actions ────┐
        │                                     │
  scrape PAGASA  →  score the predictions whose
  /flood table       actual just landed  →  learn_one
        │                     │                  │
   Open-Meteo            error log +         model state
   rainfall            learning curve      (pickled, committed)
        │                     │                  │
        └──────→ issue 1–7 day forecasts ────────┘
                          │
                   web/data/*.json → dashboard
```

A forecast is written to `eval/predictions.csv` at issue time **with the exact
features it saw**, and is scored only once the day it predicted actually
arrives. Nothing is ever rescored with hindsight, so the learning curve cannot
flatter itself.

## Data

| Source | What | Cadence |
|---|---|---|
| [PAGASA `/flood`](https://www.pagasa.dost.gov.ph/flood) | Reservoir level, NHWL, rule curve, gate opening for 9 dams | Daily, 08:00 PHT |
| [Open-Meteo](https://open-meteo.com) | Rainfall, temperature, humidity, ET₀ per dam | Archive to 1940 + 7-day forecast |
| Wayback Machine | Historical seed of the PAGASA table | 166 dates, 2021–2026 |

**PAGASA keeps no archive** — the page shows today and yesterday only. A missed
collector run is a permanently lost observation. That is why the cron runs
twice daily and why `data/dam_levels.csv` is committed rather than ignored.

### Things that will bite you

- **Nine dams, not eight.** San Roque sits in the table with the seven usual ones.
- **Magat appears as both "Magat" and "Magat Dam"** across the history; names are
  canonicalised in `data/dams.py`.
- **`0.00` means "not defined", not zero.** Caliraya has no NHWL; Ipo, La Mesa and
  Caliraya have no rule curve. Left as zero, every spill rule fires.
- **The published 24-hour deviation leaks the future.** PAGASA prints one value
  per snapshot and shows it against both the today and yesterday rows, so on the
  yesterday row it is the *t → t+1* change. Taken at face value a naive baseline
  "predicts" the next day to 0.05 m. It is recomputed from our own series, and
  `tests/test_build_table.py` keeps it that way.
- Coordinates come from PAGASA's KML, where **Magat's placemark is mislabelled
  `<name>Layers</name>`**.

## Running it

```bash
uv sync --group dev
uv run pytest -q                        # always, before touching the collector

uv run python data/fetch_dams.py        # today's levels (idempotent)
uv run python data/fetch_weather.py     # Open-Meteo archive + forecast
uv run python data/backfill_wayback.py  # one-shot seed; re-run retries failures
uv run python data/build_table.py       # join into the modelling table

uv run python eval/backtest.py          # honest scoreboard + warm-start state
uv run python pipeline/run.py           # the full loop, one tick

cd web && python -m http.server         # dashboard at localhost:8000
```

## Layout

```
data/     scrapers, the committed observation record, feature build
model/    River models, one per (dam, horizon), pickled state
eval/     baselines, prequential backtest, risk rules, prediction ledger
pipeline/ run.py — the loop
web/      static dashboard (GitHub Pages)
```

## Design notes

- The target is **ΔRWL over the horizon**, never the raw level. Levels are so
  autocorrelated that predicting them looks impressive while beating nothing.
- Features at issue time *t* use observations up to *t* plus the rainfall
  **forecast** for t+1…t+h, so the model is operational rather than merely
  autoregressive.
- The model is a plain scaler + linear regression. Trees and ensembles come
  only if the simple version is measured and found wanting.
- Predictions are never clipped. When conditions exceed anything in the
  training history the dashboard says so, because suppressing extremes would
  gut the tool exactly when it matters.

Sibling project: [Hangin'](https://github.com/Zeref538/hangin), a PH air-quality
forecaster, whose refresh-and-publish pattern Pulso reuses.
