# APAW — portfolio integration brief

*Paste this whole file into a session working in the `Portfolio` repo. It is
self-contained: what the project is, the verified numbers, and the exact edit.*

## What APAW is

**A**daptive **P**rediction of **A**ccumulating **W**ater — also *apaw*, Filipino
for *to overflow*. A self-improving nowcaster for the nine major Luzon dams:
it forecasts reservoir water level 1–7 days ahead, translates that into spill
risk, and **learns from every new observation** rather than being retrained.

It sits next to **Hangin'** under *ML & Forecasting* and is deliberately the
harder sibling. Hangin' is a pooled batch model over 1.9 years of data. APAW is
an **online** system over a dataset that did not exist until it started
collecting one — and the evaluation discipline is the point of the project.

| fact | value |
|---|---|
| target | ΔRWL over the horizon (never the raw level — levels are too autocorrelated to beat anything) |
| model | one pooled `river` AMFRegressor (Mondrian forest, 50 trees, aggregation off), dam one-hot + horizon numeric |
| data | 1,517 dam observations, 9 dams, 22 river basins, Open-Meteo catchment rainfall |
| evaluation | prequential — predict, then learn, in strict date order; 1,794 scored forecasts |
| result | **beats persistence and drift at all 7 horizons** (+1d 0.323 m vs 0.362 m, n=853) |
| model search | 3,776 configurations, ranked on dates < 2025-11-01, holdout scored once |
| generalisation | **dev 0.615 → holdout 0.617** mean ratio to best baseline, 7/7 horizons |
| cost | ₱0 — GitHub Actions, Open-Meteo, GitHub Pages, no keys |

**The four things that make it portfolio-worthy, in order:**

1. **It built the dataset it learns from.** PAGASA publishes a daily dam
   bulletin and keeps **no archive** — the page shows today and yesterday, then
   the reading is gone forever. A twice-daily collector commits every reading,
   seeded from 166 Wayback snapshots. A missed run is a permanent data loss,
   which is why the scrape runs before the model and the commit step runs even
   on failure.
2. **A model search that was built not to fool itself.** Searching 3,776
   configurations against one evaluation set reliably produces a number that
   means nothing. The calendar was split before the search ran: ranking reads
   only dates before 2025-11-01, and the holdout was scored **once**. It slipped
   0.002 — that near-zero gap, not the win itself, is the evidence.
3. **The finding was about data, not algorithms.** The original design — one
   linear model per (dam, horizon) — gave each of 63 models **13 to 94 rows** to
   fit 15 coefficients, and lost to persistence. Pooling every dam and horizon
   into one model turned ~94 rows into ~1,750 and did more than any change of
   estimator.
4. **It publishes what it cannot yet defend.** A horizon with fewer than 200
   scored forecasts is shown with its count and explicitly *not ranked*, even
   though it is ahead. The README's verdict is generated from the metrics on
   every run, so the claim cannot drift from the evidence.

**Honest limits, stated on the dashboard:** only 2 of 7 horizons currently clear
the 200-forecast bar; the rest are ahead but uncertified and will qualify as the
collector runs. Rainfall is a sampled catchment mean, not a real watershed
polygon. It is educational, not a flood advisory — PAGASA and the LGUs are the
authorities, and the disclaimer is permanent.

**Links:** repo https://github.com/Zeref538/apaw · live dashboard
https://zeref538.github.io/apaw/

---

## What to paste where

**This file is not what goes in the codebase.** The block below is a JavaScript
object; it goes into `Portfolio/src/data.js`, in the `projects` array,
**immediately after the Hangin' card** (currently line 229) so the two
forecasting projects sit together.

No `App.jsx` change is needed — `groups: ["ML & Forecasting"]` already exists in
`projGroups` at `App.jsx:233`.

```js
  {
    title: "APAW — Self-Improving Dam Level & Spill-Risk Nowcaster",
    groups: ["ML & Forecasting"],
    description:
      "Forecasts reservoir water level 1–7 days ahead for the nine major Luzon dams and turns it into plain-language spill risk. PAGASA publishes a daily dam bulletin and keeps no archive — the page shows today and yesterday, then the reading is gone — so the project starts by building the dataset it learns from: a twice-daily collector, seeded from 166 Wayback snapshots, that commits every reading before the model runs. The model is online, not batch: one pooled River Mondrian forest updated with learn_one as each label arrives, scored prequentially against persistence and drift baselines. Choosing it was the interesting part. A search over 3,776 configurations will find something that beats the baselines on the dates you already have, so the calendar was split before the search ran — ranking reads only dates before 2025-11-01 and the holdout was scored exactly once. It slipped 0.002 (dev 0.615 to holdout 0.617 mean ratio) and beat both baselines at all seven horizons. The real finding was about data rather than algorithms: one model per dam per horizon gave each of 63 models 13–94 rows to fit 15 coefficients, and pooling them into one turned that into ~1,750.",
    tags: ["River", "Online Learning", "Time-Series", "Python", "Open-Meteo", "GitHub Actions"],
    metric: "Beats baselines at all 7 horizons · dev 0.615 → holdout 0.617",
    category: "Online ML · Forecasting · MLOps",
    date: "2026",
    image: "/projects/apaw-1.jpg",
    images: [
      "/projects/apaw-1.jpg",
      "/projects/apaw-2.jpg",
      "/projects/apaw-3.jpg",
      "/projects/apaw-4.jpg",
    ],
    link: "https://github.com/Zeref538/apaw",
    demo: "https://zeref538.github.io/apaw/",
    demoLabel: "live dashboard",
    highlights: [
      "Built the dataset the model learns from: PAGASA keeps no archive, so a twice-daily collector commits every reading and the scrape runs before the model — a modelling bug can never cost an observation that cannot be re-fetched",
      "Split the calendar before searching 3,776 configurations, so the winner was ranked on dates it could see and scored once on dates it could not; dev 0.615 → holdout 0.617 mean ratio is what makes the 7/7 result credible rather than a search reporting its own luck",
      "The win came from pooling, not from a fancier estimator: one model per (dam, horizon) starved each of 63 models on 13–94 rows, and pooling every dam and horizon into a single Mondrian forest turned that into ~1,750 — with per-dam target scaling, since the dams differ in movement by 12×",
      "Publishes what it cannot defend: a horizon under 200 scored forecasts is shown with its count and explicitly not ranked even though it is ahead, and the README's verdict is regenerated from the metrics every run so the claim cannot drift from the evidence",
      "Caught a real data leak — PAGASA prints one 24-hour deviation per snapshot against both the today and yesterday rows, so on the older row it is the future change; taken at face value a naive baseline 'predicts' tomorrow to 0.05 m. Recomputed from our own series and pinned by a regression test",
    ],
  },
```

## Suggested screenshots

| file | what |
|---|---|
| `apaw-1.jpg` | the animated dam cross-section with the coloured elevation zones and the forecast line |
| `apaw-2.jpg` | the nine-dam grid |
| `apaw-3.jpg` | the "Where it wins, where it loses" scoreboard — solid bars for ranked horizons, striped for provisional |
| `apaw-4.jpg` | the learning curve, model vs persistence over calendar time |

Take them from https://zeref538.github.io/apaw/ in **dark mode**, which is the
project's stronger look and contrasts with Hangin's screenshots.

## A note on the numbers

Everything above is regenerated by the pipeline, so it moves. `metric` and the
`+1d` figures are as of **2026-08-10**. The direction of travel is one-way — the
unranked horizons cross the 200-forecast bar as the collector runs, expected
around **21 August 2026** — so the card understates rather than overstates.
Re-read the live README before a big application.
