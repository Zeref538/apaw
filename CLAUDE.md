# APAW — working contract

Self-improving nowcaster for PAGASA dam reservoir levels and spill risk.
Spec: [PRD.md](PRD.md) · phases: [PLAN.md](PLAN.md)

## The four hard rules

1. **₱0.** GitHub Actions, open data, Open-Meteo (no key), free static host.
   If something seems to need paid compute or data, stop and re-scope.
2. **Honest evaluation.** Every result against a naive persistence baseline on
   a chronological split. Report losses. A horizon where persistence wins gets
   published saying so.
3. **Incremental, never retrain-from-scratch.** River `learn_one`; model state
   persists between runs — via the Actions cache, not git. The forest reaches
   ~88 MB, which cannot be committed twice a day. On a cache miss the state is
   rebuilt by replaying the committed history in order with `learn_one`, which
   is the same prequential pass, not a batch refit. The observation record is
   the real state.
4. **Educational framing.** Not an official warning. Disclaimer stays visible.
   PAGASA and the LGUs are the authorities; we are a portfolio project.

## Data facts worth not rediscovering

- **PAGASA keeps no archive.** `/flood` shows today and yesterday only. A
  missed collector run is a permanently lost observation — this is why the
  cron runs twice daily and why `data/dam_levels.csv` is committed, never
  gitignored.
- **9 dams**, not 8: San Roque is in the table alongside the seven usual ones.
- **Magat appears as both "Magat" and "Magat Dam"** across the history. All
  names go through `data/dams.py:canonical()` on the way in.
- **Coordinates** come from PAGASA's own KML, where **Magat's placemark is
  mislabelled `<name>Layers</name>`**.
- **`0.00` means "not defined", not zero.** Caliraya has no NHWL; Ipo, La Mesa
  and Caliraya have no rule curve. Left as zero, every spill rule fires.
- The Wayback seed is sparse (166 dates over 5 years) and mostly supports
  h=1. Longer horizons fill in as the collector accrues its own history.
- **"Non-Flood Watch" contains "Flood Watch"** — a substring test turns every
  quiet basin into an alarm. Test the negative first.
- **Open-Meteo's previous-runs archive starts in 2025.** Earlier dates return
  nulls, so those rows fall back to ERA5 observed rain and are scored under
  `fcst_source == "era5_proxy"`, separately from real forecasts.
- **`json.dump` writes bare `NaN`**, which is not valid JSON. One missing
  reference elevation blanked the whole dashboard before `_clean()`.
- SVG charts bake resolved colours into paint attributes, so a theme change
  must redraw them. CSS variables alone never reach an attribute already in
  the DOM.

## Commands

```bash
uv sync --group dev
uv run pytest -q                      # always before touching the collector
uv run python data/fetch_dams.py      # scrape today's levels (idempotent)
uv run python data/fetch_weather.py   # Open-Meteo archive + 7-day forecast
uv run python data/fetch_rain_forecast.py  # archived forecasts at real leads
uv run python data/backfill_wayback.py  # one-shot; re-run retries failures
uv run python data/build_table.py     # join into data/modeling_table.csv
uv run python eval/backtest.py        # honest scoreboard + warm-start state
uv run python eval/experiment.py      # model search; ranks on dev, holdout once
uv run python eval/experiment.py --focus --family amf50,amf100   # tune one family
uv run python eval/basin_forecast.py  # the second target
uv run python pipeline/run.py         # one full cycle
```

## Conventions

- Target is **ΔRWL over the horizon**, never the raw level. Levels are so
  autocorrelated that predicting them looks impressive while beating nothing.
- Features at issue-time *t* use observations up to *t* plus the rainfall
  *forecast* for t+1..t+h. Backward windows must never include t+1 — there are
  tests for this; keep them.
- Forward rain uses the **archived forecast at the lead time we would have
  had**, not observed reanalysis. Where the archive doesn't reach, the row is
  marked `era5_proxy` and scored separately — never silently mixed in.
- Rainfall is a **catchment mean** over sampled points, not a reading at the
  wall.
- A horizon under `MIN_SCORED` (200) scored forecasts is published with its n
  and explicitly not ranked. Never call a winner on a handful of points.
- Deliberate shortcuts get a `ponytail:` comment naming the ceiling and the
  upgrade path. One is live: the catchment cross is a stand-in for real
  watershed polygons.
- **One pooled model, not one per (dam, horizon).** Dam is a one-hot feature
  and horizon is numeric. Splitting them back out starves each model — it was
  13-94 rows each before pooling, and it lost. Target is scaled per dam
  because their movement differs 12x.
- **Model changes go through `eval/experiment.py`, never a hunch.** It ranks
  only on dates before `SPLIT` and touches the holdout once. If you widen the
  search, do not also start reading the holdout to choose — that is how a
  search starts reporting its own luck.
