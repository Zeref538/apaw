# Pulso — Handoff / Kickoff Context

> Copy this whole folder into a fresh empty repo folder, open a new session
> there, and paste the "Kickoff prompt" below. This file is the context a fresh
> agent needs to start building with zero prior conversation.

## What this is

**Pulso** — a self-improving dengue nowcaster for the Philippines. Predicts
regional dengue cases 1–4 weeks ahead from weather + case history, and keeps
improving via incremental (online) learning on a free, scheduled pipeline.
Full spec in [PRD.md](PRD.md); phased build in [PLAN.md](PLAN.md).

The one-sentence identity: **a live ML system that learns every cycle and
proves it with a visible learning curve — all on free infrastructure.**

## Who it's for / who's building it

- Owner: John Andrei Martinez (GitHub `Zeref538`) — AI/ML engineering student,
  portfolio at johnandrei.vercel.app. This becomes a portfolio project card.
- Sibling project: **Hangin'** (github.com/Zeref538/hangin) — PH air-quality
  forecaster. Pulso reuses Hangin's proven pattern (GitHub Actions hourly/daily
  refresh, honest backtest vs naive baseline, React dashboard) and ADDS the new
  parts: online/incremental learning, drift detection, and a self-improvement
  learning curve. Study Hangin' first as the template.

## Non-negotiable constraints (these are hard requirements)

1. **₱0 cost.** Free tier only — GitHub Actions cron, open/public data,
   Open-Meteo (no key), free static host (Vercel or GitHub Pages). If a step
   seems to need paid compute/data/GPU, stop and re-scope. No exceptions.
2. **Honest evaluation.** Every result compared to a naive persistence baseline
   on a chronological holdout. A model that can't beat persistence at some
   horizon is reported as such — no cherry-picking.
3. **Incremental, not retrain-from-scratch.** The daily/weekly loop uses
   `partial_fit` / River. Cumulative model state persists between runs.
4. **Educational framing.** Not a medical tool. Visible disclaimer. No clinical
   or individual advice.

## The single biggest risk — resolve it FIRST

**Is there a free, refreshable source of PH regional dengue case data?**
Phase 0 exists to answer this before any modeling. Candidates: OpenDengue global
database (includes PH), DOH/PIDSR weekly bulletins. If none refreshes cleanly
for free, the documented fallbacks are: (a) switch to ILI/flu or another
reportable disease with open data, or (b) a clearly-labeled
"historical + simulated live updates" mode. **Do not build the model until a
data source is confirmed.**

## Kickoff prompt (paste into the fresh session)

> I'm starting Pulso, a self-improving dengue nowcaster for the Philippines.
> Read PRD.md, PLAN.md, and HANDOFF.md in this folder — they're the full spec.
> Hard constraints: free tier only (GitHub Actions + open data + Open-Meteo +
> free static host), honest backtest vs a naive baseline, incremental learning
> via River/partial_fit, educational framing with a disclaimer. Start with
> Phase 0: confirm a free, refreshable PH dengue data source and build the
> fetcher — do NOT build the model until the data source is proven. Show me the
> Phase 0 plan and the data-source options you find before writing pipeline
> code.

## First moves for the new agent

1. Confirm the data source (Phase 0 gate) — report options + a working fetch.
2. Set up the repo: `git init`, a `CLAUDE.md` working contract, `pyproject.toml`,
   and the folder layout in PLAN.md.
3. Only after data is proven: baseline → incremental model → Actions loop →
   dashboard, following PLAN.md phases in order.

## Definition of done (v1)

A live dashboard showing regional dengue forecasts and a learning curve that
trends down over time; a green daily GitHub Action running unattended; a README
with the honest baseline comparison; and a portfolio card in the house format
(metric like `beats naive at 2–4wk · learns weekly`).
