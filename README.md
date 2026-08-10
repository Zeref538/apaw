# APAW

**A**daptive **P**rediction of **A**ccumulating **W**ater — and *apaw*, Filipino
for *to overflow, to brim over*, which is what a reservoir does when the rain
keeps coming.

**A self-improving nowcaster for Luzon dam levels and spill risk.**
Forecasts reservoir water level 1–7 days ahead for the nine major dams PAGASA
publishes, learns from every new observation, and reports the horizons where a
naive baseline still beats it.

**[Live dashboard →](https://zeref538.github.io/apaw/)**

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

A horizon with fewer than **200** scored forecasts is published with its count
and **not ranked** — small-n verdicts are noise, not skill.

| Horizon | APAW | Persistence | Best baseline | n | Verdict |
|---|---|---|---|---|---|
| +1d | **0.323** | 0.362 | 0.362 persistence | 853 | **APAW** |
| +2d | **0.536** | 0.874 | 0.858 drift | 215 | **APAW** |
| +3d | **0.546** | 1.083 | 1.012 drift | 187 | ahead, but n<200 — unranked |
| +4d | **0.518** | 0.984 | 0.984 persistence | 161 | ahead, but n<200 — unranked |
| +5d | **0.435** | 0.807 | 0.807 persistence | 117 | ahead, but n<200 — unranked |
| +6d | **0.539** | 0.981 | 0.981 persistence | 117 | ahead, but n<200 — unranked |
| +7d | **0.528** | 0.902 | 0.902 persistence | 144 | ahead, but n<200 — unranked |

*As of 2026-08-10. These move as the collector accrues history — the
[live dashboard](https://zeref538.github.io/apaw/) is always current.*

**The model is now ahead of both baselines at every horizon**, including +1d,
where persistence beat it for months. Only +1d and +2d clear the 200-forecast
gate and are *ranked*; the rest are ahead but are published unranked, because
a verdict on 117 points is not a verdict. They unlock themselves as the
collector accrues history.

### How that happened, and how we know it isn't the search fitting itself

The earlier model was one linear regressor per (dam, horizon). Given the
history that exists, that gave each of the 63 models **13 to 94 rows** to fit
15 coefficients — which is why it lost.

`eval/experiment.py` searched **3,776 configurations** (25 River estimators ×
feature sets × pooling schemes × target scaling × shrinkage × baseline
blending). Searching that hard against one evaluation set is a good way to
find a number that means nothing, so the calendar was cut in two before
anything ran: everything is **ranked only on dates before 2025-11-01**, and the
winner met the later dates exactly once.

| | dev (ranked on) | holdout (seen once) | horizons beaten |
|---|---|---|---|
| Winner | 0.615 | **0.617** | **7 / 7** |
| Old linear model | — | 0.991 | 3 / 7 |

*(mean ratio to the best baseline; below 1.0 beats it)*

Dev 0.615 → holdout 0.617 is the number that matters. A search that slips by
0.002 into data it was never allowed to see is measuring a real effect, not
its own tuning.

The winner is an **Aggregated Mondrian Forest** (50 trees, aggregation off) —
but the estimator was the smaller half of it. **Pooling every dam and horizon
into one model**, with the dam one-hot and the horizon as a numeric feature,
turns ~94 training rows into ~1,750. Every strong configuration in the search
pooled something. Per-dam target scaling is required to make that work, since
the dams differ in how far their level moves by a factor of twelve (La Mesa
0.16 m, San Roque 1.91 m); pooled raw, San Roque would write the model.

Split by rain source, MAE is 0.352 m for ERA5-proxy rows (n=1074) and 0.410 m
for real archived forecasts (n=684). Those groups differ by **era** as well as
by rain source, so whichever looks better, the gap is not a clean measure of
what the shortcut is worth. It is published because the shortcut exists.

Regenerate with `uv run python eval/backtest.py`. That command also rebuilds
the model state, by replaying the committed history in order — which is why
the state itself is not in git. The forest reaches ~88 MB and grows with every
observation, so it lives in the Actions cache and is rebuilt on a miss.
Capping it small enough to commit was measured and costs most of the gain
(holdout mean ratio 0.64 uncapped against 0.82 at 50 MB).

## How the loop works

```
        ┌──── twice daily, GitHub Actions ────┐
        │                                     │
  scrape PAGASA  →  score the predictions whose
  /flood table       actual just landed  →  learn_one
        │                     │                  │
   Open-Meteo            error log +         model state
   rainfall            learning curve      (cached, rebuildable)
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
| PAGASA `/flood`, same page | Flood watch for 18 river basins + 4 dam sub-basins — the only nationwide signal here | Daily |
| [Open-Meteo](https://open-meteo.com) archive | Rainfall, temperature, humidity, ET₀, averaged over sampled catchment points | 2015→, ~5 day lag |
| Open-Meteo previous runs | What the rain forecast *said*, at each lead time 1–7 days | 2025→ |
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
- **"Non-Flood Watch" contains "Flood Watch".** A substring test flips every
  quiet basin into an alarm.
- **Open-Meteo's forecast archive starts in 2025.** Earlier rows fall back to
  observed rain and are scored separately, not quietly mixed in.
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
uv run python eval/experiment.py        # the model search (dev/holdout split)
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
  **forecast** for t+1…t+h — and that forecast is the one actually archived at
  that lead time, not observed rain reused as if it had been known. Rows
  predating the forecast archive keep an ERA5 proxy and are reported under a
  separate MAE so the optimism is visible.
- Rainfall is a **catchment mean** over sampled points around each dam. Rain at
  the wall is not what fills a reservoir.
- A horizon with fewer than 200 scored forecasts is published with its sample
  count and **not ranked**. Small-n verdicts are noise.
- A second target rides along: whether each river basin will be under flood
  watch, scored against the same persistence discipline.
- One pooled Mondrian forest covers all nine dams and all seven horizons, with
  the dam and the horizon as features. The simple per-dam linear model came
  first and was replaced only after being measured and found wanting — the
  search that replaced it is in `eval/experiment.py` and is reproducible.
- Predictions are never clipped. When conditions exceed anything in the
  training history the dashboard says so, because suppressing extremes would
  gut the tool exactly when it matters.

Sibling project: [Hangin'](https://github.com/Zeref538/hangin), a PH air-quality
forecaster, whose refresh-and-publish pattern APAW reuses.
