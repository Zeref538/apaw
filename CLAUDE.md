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
   persists between runs.
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

## Commands

```bash
uv sync --group dev
uv run pytest -q                      # always before touching the collector
uv run python data/fetch_dams.py      # scrape today's levels (idempotent)
uv run python data/fetch_weather.py   # Open-Meteo archive + 7-day forecast
uv run python data/backfill_wayback.py  # one-shot; re-run retries failures
uv run python data/build_table.py     # join into data/modeling_table.csv
```

## Conventions

- Target is **ΔRWL over the horizon**, never the raw level. Levels are so
  autocorrelated that predicting them looks impressive while beating nothing.
- Features at issue-time *t* use observations up to *t* plus the rainfall
  *forecast* for t+1..t+h. Backward windows must never include t+1 — there are
  tests for this; keep them.
- Deliberate shortcuts get a `ponytail:` comment naming the ceiling and the
  upgrade path. Two are live: point-rainfall instead of catchment-mean, and
  perfect-foresight rain in the backtest.
