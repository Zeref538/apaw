# PRD — Pulso: Self-Improving Dengue Nowcaster

**Status:** draft, not started · **Name:** Pulso (Filipino/Spanish: *pulse*) ·
**Est. effort:** ~4 weeks part-time · **Cost:** ₱0 (free tier only — hard req)

---

## 1. Problem

Philippine dengue surveillance is **reactive** — DOH reports confirmed cases
after they happen, on a weekly lag. By the time a spike is visible in the
report, the outbreak is already underway. Dengue transmission tracks weather
(rainfall and temperature drive mosquito breeding) with a delay, so
near-term case counts are *forecastable* — but no free, public tool does it,
and no student-portfolio ML model demonstrates a system that **keeps learning
as new weeks arrive** rather than being trained once and frozen.

## 2. What Pulso is

A forecaster that predicts dengue cases per Philippine region 1–4 weeks ahead
from weather + recent case history — and, crucially, **improves itself every
cycle** via incremental (online) learning, with a public dashboard that shows
its accuracy getting better over calendar time.

The portfolio thesis: **a live, self-improving ML system**, not a static model.
The differentiator versus a normal forecasting project is the MLOps loop —
scheduled data refresh, incremental model updates, drift detection, and a
visible learning curve — all on free infrastructure.

## 3. Goals

- Forecast regional dengue cases 1–4 weeks ahead, with plain-language risk
  levels (low / rising / high).
- **Incremental learning:** the model updates on each new week's labeled data
  via `partial_fit` / River — never a from-scratch retrain.
- **Self-improvement, proven:** log prediction-vs-actual error every cycle and
  chart it over time so the improvement is visible, not claimed.
- **Drift-aware:** detect distribution shift (e.g. a season change or an
  anomalous outbreak) and adapt / flag it.
- **Honest evaluation:** always compare against a naive baseline on a
  chronological holdout (the discipline that made Hangin' credible).

### Non-goals

- Not a medical/clinical tool — educational forecasting with a visible
  disclaimer. No individual diagnosis, no treatment advice.
- No paid compute, no GPU, no paid data. If a data source isn't free and
  public, it's out.
- Not real-time streaming — the cadence is a scheduled daily pipeline heartbeat
  with weekly label updates.

## 4. Cadence (be honest about this)

- **Daily:** GitHub Actions cron fetches fresh **weather** data and republishes
  the dashboard (the visible "pulse").
- **Weekly:** when new **case counts** are published, the model does an
  incremental update on that labeled week, logs its error, and the learning
  curve gains a point.
- So "daily refresh" = pipeline + features + dashboard daily; "self-improving"
  = incremental label updates weekly.

## 5. Users

| user | need |
|---|---|
| Primary — recruiter/hiring manager | See a live, self-improving ML system with an honest evaluation and MLOps automation |
| Secondary — a curious PH resident | A readable regional dengue risk outlook |

## 6. Functional requirements

### 6.1 Data
- **FR-1** Source free, public dengue case data for PH regions (candidate:
  OpenDengue global database, which includes PH; DOH/PIDSR weekly bulletins as
  a secondary). **Phase 0 must confirm a working, refreshable source before
  anything else is built.**
- **FR-2** Weather features from Open-Meteo (free, no key): rainfall,
  temperature, humidity — with engineered lags (dengue responds to weather
  weeks earlier).
- **FR-3** All fetched data cached in-repo (CSV/parquet) with a timestamp;
  pipeline is idempotent and resumable.

### 6.2 Model
- **FR-4** Online/incremental regressor per region (River, or sklearn
  `partial_fit` — SGDRegressor / PassiveAggressive). No full retrain in the
  daily loop.
- **FR-5** Forecast horizons: 1, 2, 3, 4 weeks ahead.
- **FR-6** Drift detection (River ADWIN or a rolling-error threshold); on drift,
  adapt learning rate / reset window and flag it in the log.
- **FR-7** Persist model state between runs (committed to repo or a free store)
  so learning is cumulative across days.

### 6.3 Evaluation (the credibility core)
- **FR-8** Naive baseline: last-week persistence (and a seasonal-naive variant).
- **FR-9** Every cycle logs, per region/horizon: prediction, actual (when it
  arrives), error (MAE), and the baseline's error on the same target.
- **FR-10** **Learning curve:** rolling model-error over calendar time, shown
  against the baseline — the headline artifact.
- **FR-11** Chronological holdout for the initial backtest; no future data
  leaks into past training.

### 6.4 Product
- **FR-12** Static dashboard (React or plain HTML, free host): PH region map /
  heatmap of risk, per-region forecast chart, the self-improvement learning
  curve, and a model-performance panel.
- **FR-13** Plain-language risk levels with a visible educational disclaimer.

## 7. Non-functional requirements

- **NFR-1** 100% free: GitHub Actions (cron), open data, free static host
  (Vercel/GitHub Pages). No paid anything — enforced.
- **NFR-2** Daily job runs in minutes, well within free Actions limits.
- **NFR-3** Reproducible: pinned deps, committed data snapshots, seeded splits.
- **NFR-4** Fails safe: a bad/late data fetch keeps the last good dashboard up.

## 8. Success metrics (published)

| metric | target |
|---|---|
| Forecast skill vs naive persistence (MAE) | beat baseline at the 2–4 week horizons |
| Self-improvement | rolling error trends **down** over the tracked period |
| Drift response | at least one detected+handled drift event, documented |
| Automation | daily Action green streak; zero manual intervention for weeks |

Ship tiers:
- **Minimum:** incremental model + daily Action + baseline comparison + dashboard.
- **Good:** + learning curve showing improvement over time, drift detection live.
- **Headline:** beats baseline at 2–4wk horizons with a documented drift-adapt
  event and a multi-week hands-off green Actions streak.

## 9. Milestones

| week | deliverable | exit gate |
|---|---|---|
| 1 | **Phase 0:** confirm free dengue data source; build refreshable fetcher + weather join | one command produces a clean regional weekly table with weather features |
| 2 | Incremental model + chronological backtest vs naive baseline | model beats (or honestly ties) baseline on holdout; metrics logged |
| 3 | GitHub Actions daily cron: fetch → update → log → publish; drift detection | Action runs unattended for 3+ days, state persists, learning curve updates |
| 4 | Dashboard, disclaimer, README, portfolio card | live dashboard with map + forecast + learning curve; write-up done |

## 10. Risks

| risk | mitigation |
|---|---|
| **Dengue data isn't freely refreshable** (biggest risk) | Phase 0 gate — confirm the source *first*; fallback to ILI/flu or a different reportable disease with open data, or a well-documented static-with-simulated-updates mode clearly labeled as such |
| Weekly labels make "self-improving" slow to show | Backfill history so the learning curve starts populated; daily heartbeat keeps the system visibly live |
| Online model underperforms a batch retrain | It's a design choice for continual learning — measure and report the tradeoff honestly |
| Reporting lag / revised case numbers | Version each data pull; note revisions rather than silently overwriting |
| Health-advice liability optics | Educational framing + disclaimer; no clinical claims |

## 11. Open questions

- Disease: commit to dengue, or pick ILI/flu if its open data refreshes more
  cleanly? (Decide in Phase 0.)
- Model store: commit state to the repo (simple, versioned) vs a free external
  store? Repo is the lazy default unless state gets large.
- Granularity: region-level only for v1, or attempt province-level if data
  supports it?

## 12. Stack

Python · River (online ML) or scikit-learn `partial_fit` · pandas · Open-Meteo
API · GitHub Actions (cron) · React or plain HTML dashboard · Vercel/GitHub
Pages · pytest.
