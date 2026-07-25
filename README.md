# vpredict

Win probabilities for pro Valorant matches, published before the matches
start, graded in public against a baseline that is genuinely hard to beat.

**Live: <https://vpredict.onrender.com>**

## Why I built this

I wanted to know if stats I could scrape myself could actually beat a
tuned Elo rating at calling pro Valorant matches. I also wanted a public
record I could not quietly edit when the answer embarrassed me. So every
prediction freezes to a ledger before match start, and the site grades
them as results come in, next to Elo's call on the same match.

## What it does

The pipeline scrapes vlr.gg politely, builds features with a strict
as-of rule (only matches that finished before the target match started
can contribute), trains a calibrated map-level model, and turns per-map
probabilities into a series probability with an exact dynamic program
over the best-of format. Upcoming matches get predicted on a schedule.
The first prediction per match is frozen forever. Later retrains cannot
touch it. Elo's probability is logged at the same instant, so the
comparison is locked at prediction time too.

Everything runs on one small Render instance with a persistent disk. A
refresh cycle crawls new results, grades the ledger, retrains when the
data or the model definition has moved, and predicts the next matches.

## Honest results

Two years of real data: 6,796 matches across all vlr tiers. After the
minimum-history rule that leaves 5,489 usable matches, split
chronologically, never randomly. The most recent slice is the untouched
test window. One command regenerates every number:

```bash
python scripts/evaluate.py --data data/raw/matches.jsonl
```

On the current regeneration the model beats tuned Elo (K=24, tuned on
validation only) on test log loss at both grains: 0.6693 vs 0.6719 at
map level, 0.6570 vs 0.6580 at series level, with accuracy 62.1% vs
61.3% on 824 test series. Those gaps are small. I report them anyway,
because the walk-forward backtest below tells the fuller story. The
live site serves the current summary at `/api/results`, published from
the same script's output.

Two things I refuse to do with these numbers. I never pick a model on
test-window performance, validation selects and the test set is read
once. And I never pool tiers in a headline without the per-tier table
next to it, because tier-2 volume can hide tier-1 weakness.

## The finding I show instead of hiding

A walk-forward backtest replays the whole deployment: for every
completed match in the store, the same frozen-style prediction the live
system would have made, under bundles retrained on the production
cadence. Its verdict is that Elo leads most of the two-year history,
and the model's edge only shows up in the recent period, which is
exactly what the static test window measures. That result is on the
site, labeled as a simulation, separated from the live ledger, and
protected by a run-once rule so I cannot rerun it until it flatters me.

The backtest also caught a real calibration bug the static evaluation
could not see: in one July 2025 window, isotonic calibration saturated
to exact 0 and 1 plateaus right after its admission threshold was first
crossed, so a handful of predictions claimed certainty. The fix bounds
every calibrated output away from 0 and 1, shipped as a labeled model
change with the old result archived, not overwritten.

## Model selection, the boring honest version

The candidate families are plain logistic regression and a heavily
regularized LightGBM. On the corrected data their validation gap
measured 8e-5 log loss, which is machine noise. Instead of pretending
one family won, selection is now a procedure: rolling-origin scoring
over five expanding chronological folds, and the incumbent keeps the
job unless a challenger wins by more than one paired standard error.
The serving bundle right now is logistic regression with isotonic
calibration. A third calibrator (a smoothed, strictly monotone isotonic
variant) is in the menu and loses on validation, so the step version
serves. All of that is in `MODEL_CARD.md` and `WALKTHROUGH.md`.

## Bugs I am weirdly proud of finding

These are all in `LOG.md` as symptom, cause, fix, and why tests missed
them. The short versions:

- **Every stored timestamp was lying.** vlr.gg sends US-Eastern wall
  time in a field named `data-utc-ts` when you have no cookies. So all
  start times were 4 to 5 hours early, quietly shifting my
  chronological splits. The parser now localizes properly and a
  marker-guarded one-time migration rewrote the store. Frozen
  probabilities were untouched, and the split counts came out identical
  before and after, which is the only reason the earlier numbers were
  still usable.
- **The phantom match.** Bracket pages list unresolved slots as TBD.
  Both sides of one fixture collapsed to the same placeholder key and
  the system froze a prediction for a match between nobody and nobody.
  Placeholder fixtures are now refused, and the one frozen phantom row
  is flagged and excluded from scoring instead of deleted, because the
  ledger is append-only even when it is embarrassing.
- **The silent scheduler.** In production, the refresh scheduler's INFO
  logs were dropped by a logging config quirk, so I could not tell if
  the 6-hour cycle was running. The fix wires a handler explicitly.
  Every cycle now prints a full JSON verdict per step.
- **The 16 second match page.** The match detail endpoint walked the
  whole store with full validation on every click. A single-pass slim
  loader plus a cache keyed on the store file's identity took it to
  about 3 s cold and under 1 s warm, and a test pins the fast path to
  byte-identical output against the reference implementation.
- **Retrains that never converged.** A deploy that changes the model
  definition now bumps a behavior revision stamped into the bundle, and
  the refresh cycle retrains exactly once when it sees a mismatch. No
  more waiting out the age cadence to pick up a changed definition.

## The market panel

Odds are captured locally at prediction freeze and again near start:
Cloudbet from its feed API, Pinnacle via response interception, raw
prices only, append-only log. De-vigging happens at analysis time, Shin
method first. The site shows the frozen model probability against the
captured price with EV and closing line value, series moneyline only.
Totals prices are captured but excluded from EV on purpose: upcoming
predictions average a uniform map pool because the veto has not
happened, and that assumption distorts predicted series length more
than it distorts the winner call. Publishing totals EV would be false
precision. The EV column stays labeled unvalidated until 100
market-covered picks have graded. Pre-registered gate, not a vibe. None
of this is betting advice.

## The site

The frontend leads with the series call: two team plates and a tug bar.
Per-map rows lead with an Elo lean bar showing which side each map's
history favors, with the model's per-map number demoted to small text.
That layout exists because of an honest limitation: pre-veto features
are series-level, so per-map model numbers cluster near the series
number and looked broken. The lean bar is the part that actually varies
by map. A small note on the model page explains the current serving
selection, and the scoreboard, results, and backtest panels stay
visually separated because they answer different questions.

## Run it yourself

```bash
pip install -e . && pip install pytest httpx   # or: make setup
make test          # 137 tests
make backfill      # deep history walk, resumable, interrupt-safe
make evaluate      # writes data/reports/
```

Going live:

```bash
python scripts/train.py
python scripts/predict_upcoming.py --crawl
uvicorn vpredict.serving.api:app --port 8000
```

Or deploy `render.yaml`: one web service, persistent disk at `/data`,
`VPREDICT_REFRESH=1` so the service schedules its own 6-hour cycle.
Each cycle runs as a subprocess so its memory returns to the OS and a
crash cannot take the API down. The crawler checks robots.txt at
runtime, spaces requests at least 1.1 s apart, and caches every page to
disk. Public API endpoints are rate limited per IP.

## Repository map

```
src/vpredict/
  scraping/     polite fetcher, list and match parsers, resumable crawler
  data/         pydantic schema, JSONL store, timezone migration
  features/     as-of engine (the leakage rule), assembly, splits
  modeling/     Elo baselines, selection policy, series DP, predict
  evaluation/   tier classifier, calibration monitor, walk-forward backtest
  odds/         capture, Shin de-vig, fixture linking, EV and CLV analysis
  serving/      SQLite ledger, refresh cycle, FastAPI app
scripts/        evaluate | train | predict_upcoming | refresh | backtest | ...
frontend/       Vite + React scoreboard UI
tests/          137 tests: leakage, parsers, series math, ledger, API,
                odds, markets, backtest, timezone, selection, security
```

## Project rules

No temporal leakage, enforced by as-of eligibility plus poison-future
tests plus runtime spot checks. Chronological splits only. Validation
selects, test is read once. A tie with Elo is a legitimate finding and
gets reported as one. No fabricated numbers anywhere, every figure in
this file regenerates from a script in this repo. `LOG.md` records what
actually happened, including the bugs.

## Conduct and credits

Data comes from [vlr.gg](https://www.vlr.gg), scraped respectfully:
robots.txt honored at runtime, at least 1.1 s between requests,
aggressive disk caching, no parallel hammering. Selector knowledge was
grounded in two open-source scrapers, axsddlr/vlrggapi (MIT) and
akhilnarang/vlrgg-scraper, credited here; all code in this repository
is original. Not affiliated with Riot Games. Probabilities are
educational output, not betting advice.

More depth: `WALKTHROUGH.md` for the methodology, `MODEL_CARD.md` for
the live model, `ASSUMPTIONS.md` for every judgment call, `LOG.md` for
the build diary.
