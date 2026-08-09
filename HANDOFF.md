# APAW — Context for a fresh session

> What someone (or some agent) needs to know before touching this repo, with
> no prior conversation. Spec: [PRD.md](PRD.md) · status: [PLAN.md](PLAN.md) ·
> rules: [CLAUDE.md](CLAUDE.md)

## What this is

**APAW** — *Adaptive Prediction of Accumulating Water*; also *apaw*, Filipino
for *to overflow*. It forecasts reservoir water level 1–7 days ahead for the
nine major Luzon dams, flags spill risk in plain language, tracks which river
basins are under flood watch nationwide, and improves itself on every run.

Live: https://zeref538.github.io/apaw/ · Repo: https://github.com/Zeref538/apaw

The one-sentence identity: **a live ML system that learns every cycle and
proves it with a visible learning curve — all on free infrastructure.**

## Who's building it

Owner: John Andrei Martinez (GitHub `Zeref538`), AI/ML engineering student,
portfolio at johnandrei.vercel.app.

Sibling project: **Hangin'** (github.com/Zeref538/hangin), a PH air-quality
forecaster. APAW reuses its refresh-and-publish pattern and its
plain-English-then-technical voice, but has its own visual identity — a light
bathymetric chart rather than Hangin's dark console.

## Non-negotiable constraints

1. **₱0.** GitHub Actions, open data, Open-Meteo (no key), GitHub Pages. If
   something needs paid compute or data, stop and re-scope.
2. **Honest evaluation.** Every result against a naive baseline, prequentially.
   Horizons where the baseline wins are published as losses.
3. **Incremental, not retrain-from-scratch.** River `learn_one`; state persists
   between runs.
4. **Educational framing.** Not an official warning. PAGASA and the LGUs are
   the authorities.

## The things that will bite you

These cost real debugging time to find. All are pinned by tests — keep them.

- **PAGASA keeps no archive.** `/flood` shows today and yesterday only. A
  missed collector run is a permanently lost observation. This is why the cron
  runs twice daily and why `data/dam_levels.csv` is committed, never ignored.
- **Nine dams, not eight.** San Roque sits in the table with the seven usual.
- **Magat appears as both "Magat" and "Magat Dam"** across the history. Names
  go through `data/dams.py:canonical()` on the way in.
- **`0.00` means "not defined", not zero.** Caliraya has no NHWL; Ipo, La Mesa
  and Caliraya have no rule curve. Left as zero, every spill rule fires.
- **The published 24-hour deviation leaks the future.** PAGASA prints one value
  per snapshot and shows it against both the today and yesterday rows, so on
  the yesterday row it is the *t → t+1* change. Taken at face value, a naive
  baseline "predicts" the next day to 0.05 m. It is recomputed from our own
  series in `build_table.py`.
- **"Non-Flood Watch" contains "Flood Watch".** A substring test flips every
  quiet basin into an alarm.
- **Coordinates** come from PAGASA's KML, where **Magat's placemark is
  mislabelled `<name>Layers</name>`**.
- **Open-Meteo's previous-runs archive starts in 2025.** Earlier dates return
  nulls, so older rows fall back to ERA5 observed rain and are scored
  separately.
- **Open-Meteo's rate limit is hourly, not per-burst.** Retrying with backoff
  spends the remaining budget on doomed requests; `fetch_weather.py` fails fast
  on 429 instead. It also writes to a temp file and swaps, so a failed rebuild
  can never leave `data/weather.csv` missing.
- **`json.dump` writes bare `NaN`**, which is invalid JSON — one missing
  reference elevation blanked the whole dashboard until `_clean()` was added.

## First moves in a fresh session

1. `uv sync --group dev && uv run pytest -q` — 26 tests; they encode the traps
   above.
2. `uv run python pipeline/run.py` — one full cycle locally.
3. Check the Action is still green. If the parser broke, PAGASA changed the
   page; fix the parser and refresh `tests/fixtures/`.

## Definition of done (v1) — reached

A live dashboard, a green twice-daily Action running unattended, an honest
baseline comparison including losses, and a growing archive that PAGASA itself
does not keep.

## Where to take it next

See PLAN.md §What's next. The short version: the biggest remaining constraint
is simply **history**, and the collector fixes that by running.
