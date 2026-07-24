# State

Last updated: 2026-07-24 (evening)

## What this is

A calibrated win-probability model for professional Valorant matches.
Predicts per-map probabilities and aggregates them over the veto into a
series probability, now with a market-odds comparison alongside Elo.
Python / Pandas / scikit-learn / LightGBM, FastAPI + React frontend,
custom vlr.gg scraper, Cloudbet odds capture.

Repo: `~/Downloads/valorant-predictor` on my Mac (macOS, zsh, Python 3.14,
Homebrew, venv at `.venv`).
GitHub: https://github.com/ArminObar/valorant-predictor
**Live: https://vpredict.onrender.com**

## Current numbers

6,796 matches scraped, 5,489 usable, window 2024-07-24 -> 2026-07-22.

| grain | model | Elo baseline |
|---|---|---|
| map (2,118 rows) | 0.6671 LL / 0.2370 Brier / 59.5% | 0.6704 / 0.2388 / 59.0% |
| match (824 series) | 0.6500 LL / 0.2262 Brier / 64.3% | 0.6555 / 0.2317 / 61.7% |

- Shipped: LightGBM (best_iter=121) + isotonic, OR logistic regression,
  selected by a new hysteresis policy (patch 11) rather than raw argmin.
- Model leads Elo on log loss in every tier. Best: Game Changers.
  Hardest: tier-1.

## Deployment status

Live on Render **Standard** ($25/mo, 2 GB, 5 GB disk at `/data`).

- `VPREDICT_REFRESH=1` — autonomous refresh is ON as of today. First
  cycle should log "retrain once" (cadence-fix convergence) then settle
  to real >=7-day / >=100-match cadence.
- Memory trim landed and verified: 1,188 MB -> 330 MB peak on my Mac.
  Render was still OOMing on Starter because the API process (~174 MB,
  unpickles the bundle on every health check) shares the 512 MB cgroup
  with the refresh cycle. Standard's 2 GB fixes this with headroom.
  A free-tier alternative (meta-sidecar, API never unpickles) was
  designed but not built — parked since Standard was taken instead.

## Odds capture — new today

- Cloudbet Feed API live: first run matched 16/101 fixtures, 0 errors.
  Prices moneyline, totals, and handicap markets on Valorant — better
  coverage than the ~10/week estimate.
- 11 fixtures unlinked on first run (book uses shortened team names).
  Fuzzy-match suggestion mode requested to replace manual aliasing.
- Pinnacle via Playwright (response interception) built, not yet
  confirmed live — check debug output if 0 fixtures parsed.
- Cron capture every 10 min specified in APPLY.md, not yet confirmed
  installed.
- Shin de-vig implemented, multiplicative kept as sensitivity column.

## Open work (sent to Fable, not yet returned)

1. Fuzzy fixture-name matching for odds linking
2. Pinnacle confirmation / debug fix if needed
3. Cron idempotency confirmation
4. First autonomous Render refresh cycle confirmation (no OOM, cadence
   settles correctly)
5. Markets + EV: moneyline and map totals only (kill totals, first
   blood, player props explicitly out of scope). EV = model_prob *
   decimal_odds - 1. Scoreboard shows selection, model prob, market
   implied + de-vigged prob, EV%, graded outcome. UI must label
   extrapolation (outside ~0.15-0.88 series-grain range) and gate EV
   display behind an "unvalidated" flag until n>=100 graded
   market-covered picks.
6. **Timezone bug** — live site showed match times 4 hours early
   (fixed-zone rendering instead of viewer-local). Fix requested,
   confirm landed.
7. Walk-forward backtest as a separate, one-time-run scoreboard section
   (BACKTEST vs LIVE, never merged, per-tier, run once and never tuned
   against). Compute cost not yet reported.

## Known findings, not yet acted on

- Plain LR beats the selected LightGBM on the two-year test window at
  both grains but loses validation selection. Deliberately not
  switched — frozen ledger arbitrates.
- Selection was flipping between retrains due to a now-fixed cadence
  bug (bundles recorded usable-match count, retrain check compared
  total-record count, so it always saw "new matches" and retrained
  every 6-hour cycle). Fixed in patch 13.

## Where to find things

Repo root: `ASSUMPTIONS.md`, `LOG.md` (symptom -> cause -> fix -> why
testing missed it, currently ~28 entries), `WALKTHROUGH.md`,
`MODEL_CARD.md`, `README.md`, `render.yaml`, `Dockerfile`,
`MEMORY_RUNBOOK.md`, `APPLY.md` (latest patch runbook).

Read those on disk rather than asking me to restate them.

## Deadline

Hack the North hacker application due Monday. Essay not yet drafted —
still need: the real founding moment/argument, which failure hit
hardest, and whether anyone else has seen the project.
