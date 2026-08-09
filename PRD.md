# PRD — APAW: Self-Improving Dam Level & Flood-Watch Nowcaster

**Status:** live · **Name:** APAW — *Adaptive Prediction of Accumulating
Water*; also *apaw*, Filipino for *to overflow, to brim over* ·
**Cost:** ₱0 (free tier only — hard requirement)

> Supersedes the original dengue scope. No free, refreshable source of current
> PH regional dengue case data exists — see §11.

---

## 1. Problem

Philippine reservoir operation is visible but never *forecast* in public.
PAGASA publishes a dam bulletin each morning — nine major dams with their
water level, the normal high water level (NHWL) and the operating rule curve —
and separately flags which river basins are under flood watch. Both are
snapshots of *now*. Nothing free and public says **where the level is
heading**, which is the question that matters to anyone living downstream of a
dam that is about to release water.

Worse, **PAGASA keeps no archive.** The page shows today and yesterday and
nothing else. There is no public record to learn from, so the record has to be
built.

## 2. What APAW is

A forecaster that predicts reservoir water level 1–7 days ahead for the nine
major Luzon dams from catchment rainfall and recent levels, translates that
into a plain-language spill risk, and **improves itself every cycle** through
incremental learning — with a public dashboard showing its accuracy over
calendar time, including where it loses.

The portfolio thesis: **a live, self-improving ML system**, not a static model.
The differentiator is the MLOps loop — scheduled collection, incremental
updates, drift detection, deferred honest scoring, and a visible learning
curve — all on free infrastructure.

## 3. Goals

- Forecast reservoir level 1–7 days ahead per dam, with plain-language risk
  (Room to spare / Above target / Spilling).
- **Incremental learning:** update on each newly labeled observation via River
  `learn_one` — never a from-scratch retrain.
- **Self-improvement, proven:** log prediction-vs-actual error every cycle and
  chart it over calendar time.
- **Drift-aware:** ADWIN over each model's error stream; adapt and log.
- **Honest evaluation:** always against naive baselines, prequentially, with
  losing horizons published as losses.
- **Build the archive** PAGASA does not keep.

### Non-goals

- Not an official warning or advisory. Educational framing with a visible
  disclaimer; PAGASA and the LGUs are the authorities.
- No paid compute, no GPU, no paid data.
- Not a hydrological simulation. Statistical nowcasting, not HEC-RAS.

## 4. Cadence

**Twice daily**, via GitHub Actions: scrape the bulletin, refresh rainfall,
score any forecast whose target day has arrived, learn from it, issue new
forecasts, republish the dashboard.

A missed run is a **permanently lost observation** — which is why it runs
twice a day and why the raw CSV is committed rather than ignored.

## 5. Users

| user | need |
|---|---|
| Primary — recruiter / hiring manager | A live, self-improving ML system with honest evaluation and real MLOps |
| Secondary — a curious PH resident | Is the dam near me about to spill? |

## 6. Functional requirements

### 6.1 Data
- **FR-1** Scrape the PAGASA dam table — 9 dams, with level, NHWL, rule curve,
  gate opening, inflow/outflow. Idempotent; committed to the repo.
- **FR-2** Scrape the basin flood-watch table from the same page (18 river
  basins + 4 dam sub-basins) — the only nationwide signal here, since the dams
  are Luzon only.
- **FR-3** Rainfall, temperature, humidity and ET₀ from Open-Meteo (free, no
  key), averaged over sampled catchment points rather than read at the wall.
- **FR-4** Forward rainfall must come from the **archived forecast at the lead
  time we would actually have had**, not from observed reanalysis. Where the
  forecast archive does not reach, the fallback is recorded per row and scored
  separately.
- **FR-5** Seed history from Wayback Machine snapshots of the bulletin.

### 6.2 Model
- **FR-6** Online regressor per (dam, horizon), horizons 1–7 days. Target is
  **ΔRWL over the horizon**, never the raw level.
- **FR-7** Online classifier per (basin, horizon) for flood watch, 1–3 days.
- **FR-8** Drift detection (ADWIN) on the error stream; events logged.
- **FR-9** Model state persists between runs and is committed.

### 6.3 Evaluation
- **FR-10** Baselines: persistence (level unchanged) and drift (last 24h change
  extrapolated); for basins, persistence of status.
- **FR-11** Prequential scoring — predict before learning, always in date
  order. Live forecasts go to a ledger with the exact features they saw and are
  scored only once the target day arrives.
- **FR-12** Publish a learning curve and a per-horizon scoreboard **including
  horizons where a baseline wins**.
- **FR-13** A horizon with fewer than 200 scored forecasts is published as "too
  few to call" and is not ranked.

### 6.4 Product
- **FR-14** Static dashboard: animated dam cross-section with named elevation
  zones, nine-dam overview, forecast chart, basin flood-watch board, learning
  curve, scoreboard.
- **FR-15** Plain-language and technical registers, switchable.
- **FR-16** Light and dark themes.
- **FR-17** Visible staleness banner when the newest reading is ≥2 days old.
- **FR-18** Extrapolation flags when conditions exceed the training range.

## 7. Non-functional

- **NFR-1** 100% free: GitHub Actions, open data, Open-Meteo, GitHub Pages.
- **NFR-2** Each run completes in minutes, inside free Actions limits.
- **NFR-3** Reproducible: pinned deps, committed data, committed model state.
- **NFR-4** Fails safe. The scrape runs before the model and the commit step
  runs even on failure, so a modelling bug can never cost an observation.

## 8. Success metrics

| metric | target |
|---|---|
| Forecast skill vs persistence (MAE) | beat it at some horizon, honestly reported |
| Self-improvement | rolling error trends down over the tracked period |
| Drift response | at least one detected and documented event |
| Automation | green Action streak, zero manual intervention |
| Coverage | the archive PAGASA does not keep, growing daily |

## 9. Risks

| risk | mitigation |
|---|---|
| **PAGASA changes the page layout** (highest risk) | Fixture-based parser tests fail loudly; a failed parse writes nothing rather than NaNs |
| No historical archive | Wayback seed plus our own record from day one; thin horizons marked unrankable |
| Sparse history flatters or ruins early metrics | MIN_SCORED gate; publish n beside every figure |
| Forward-rain optimism | Real archived forecasts where available; the remaining gap is measured and published |
| Point rainfall ≠ catchment rainfall | Sampled catchment mean; upgrade path is real basin polygons |
| Mistaken for an official warning | Disclaimer, "not rated" where PAGASA publishes no limits, no alarm language |

## 10. Stack

Python · River (online ML) · pandas · Open-Meteo · GitHub Actions · static
HTML/SVG dashboard · GitHub Pages · pytest · uv.

## 11. Why not dengue (the original scope)

Phase 0 gated the project on a free, refreshable source of PH regional dengue
case data. Verified 2026-08-07, none exists:

| source | granularity | ends | refreshes? |
|---|---|---|---|
| OpenDengue V1.3 | PH admin2, weekly | Nov 2023 | No — bulk release, repo idle since 2025-05 |
| HDX (Cirrolytix/DOH-EB) | province, weekly | 2021 | No — last modified 2022 |
| doh.gov.ph weekly surveillance | region, weekly | current | **403 Cloudflare**, PDF only |
| WHO arbovirus API (`xmart-api-public.who.int/ARBOV`) | country, epiweek | live | **PHL returns 0 rows** |
| WHO WPRO biweekly report #750 | country | live | PH appears only in the methods annex |

The thesis — a live self-improving system on free infrastructure, honestly
benchmarked — survived the pivot intact. Only the subject changed, to one with
genuinely live Philippine data.
