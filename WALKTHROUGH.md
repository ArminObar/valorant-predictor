# Walkthrough — how this project evaluates itself

Written for a reader who codes but is new to rigorous ML evaluation. Each
section explains one guardrail, why it exists, and where it lives in the
code. The theme throughout: *most ways of evaluating a sports model flatter
it.* This project's design removes the flattery one mechanism at a time.

## 1. The target is a probability, not a pick

"Who wins?" is the wrong question to grade — a coin-flipper is right half
the time. The deliverable is **P(team A wins)**, graded with log loss and
Brier score, which punish confident wrongness and reward honest uncertainty.
Accuracy is reported, but it's the least informative column in every table.
A model that says 55% and means it beats a model that says 90% and doesn't.

## 2. Leakage: the as-of rule

The cardinal sin in temporal prediction is using information that didn't
exist yet. Every feature here is computed **as of a cutoff** (the match's
start time in training; *now* in serving), and a match only enters a team's
history once its *estimated end* — start plus a duration allowance per
format — precedes that cutoff (`features/asof.py`). Start-time alone isn't
enough: a match that began before yours but finished after it would leak its
result backwards.

This rule is enforced three ways, because trusting yourself is how leaks
happen: a **poison-future test** (inject a fake future result, assert
features for past matches don't move — `tests/test_leakage.py`), **runtime
spot checks** inside `build_features` (recompute random rows from scratch,
assert bit-equality), and a **serving equivalence check** performed during
the build (predict-time rows reproduced training rows exactly, max |Δ| = 0).

## 3. Chronological splits only

Random cross-validation on temporal data trains on the future and tests on
the past — the model gets credit for hindsight. Here matches are sorted by
start time and split 70/15/15 **by match** (never splitting a match's maps
across sets): fit on train, tune and calibrate on validation, and touch the
test window exactly once, at report time (`features/build.py::chronological_split`).
The test window is the last ~2.5 weeks of the dataset — the closest offline
stand-in for "the future."

## 4. Baselines are the bar, not decoration

Two baselines that cost nothing to run: **favourite** (pick the higher
pre-match Elo) and a **tuned Elo** whose K is grid-searched on validation —
the extended grid [16…128] finds an interior optimum each time (K=50 on the
3.5-month window; K=24 once two years of history removed cold-start
pressure), so the baseline is genuinely competitive, not a strawman. The project's own rule:
*a tie with Elo is a legitimate finding.* Section 7 shows why that rule
earned its keep.

## 5. Map grain → series probabilities

The model trains at map grain (more rows, richer signal), but the deliverable
is a series probability. Aggregation is an exact dynamic program over per-map
probabilities: P(win the best-of) = sum over all paths to the clinch
(`modeling/series.py`). For completed matches, the maps a 2-0 series never
played are recovered from the stored veto note ("…; Split remains") when its
prefix agrees with what was actually played; otherwise unplayed slots fall
back to the mean of played-map probabilities. The report counts all three
provenances (331/291/202 in the current test window) — a number you can't
audit is a number you shouldn't trust.

For *upcoming* matches the veto hasn't happened, so per-map probabilities
are averaged over the current pool (top-7 maps by 60-day frequency) with
uniform weights — a stated simplification, on the model card.

## 6. Calibration: making 65% mean 65%

Raw classifier scores aren't probabilities. Platt scaling (a one-variable
logistic regression on the validation outputs) is fitted after model
selection; isotonic regression is only allowed when validation is large
enough to support it, because isotonic overfits small samples. A third
candidate, a smoothed strictly monotone isotonic variant, competes under
the same gate; the step version currently wins validation and serves. The
calibration curve plots predicted probability against observed frequency —
points on the diagonal mean the numbers can be taken literally. Expected
Calibration Error (ECE) summarizes the gap: 0.067 at map grain here, with
~35–40 rows per bin, so wobble of ±0.08 per bin is sampling noise, not
signal.

## 7. Case study: the compression trade-off (why Elo wins the series grain)

The most instructive arc in this project. On the first real dataset (3.5
months, 901 usable matches) the model beat Elo at map grain (0.6724 vs
0.6820 log loss) and **lost at series grain** (0.6615 vs 0.6411). Chasing
that led somewhere concrete:

- Adding a map-effective Elo row at map grain showed map-specific ratings
  are *worse* there (0.6849) — so Elo's series edge is not map knowledge.
- The mechanism is **probability spread**. Heavy regularization (C=0.03,
  chosen honestly on validation) plus Platt compresses the model's per-map
  probabilities toward 0.5. The series DP amplifies spread: three maps at
  0.55 give a series probability of ~0.57, while three at 0.65 give ~0.72.
  Elo's well-separated ratings survive aggregation; the model's compressed
  ones don't.
- The coefficient table made this vivid: Elo features carry small *negative*
  weights while round-share/side-efficiency carry the load. That is not
  "Elo hurts" — it's collinearity redistribution, and §8 quantifies it.

The authorized fix — sweep C looser, recalibrate, select by validation
*series* log loss — was then run on the two-year dataset (5,489 usable
matches), and the answer is a lesson in itself: **C stopped mattering.**
Test series log loss is 0.6375 for every C from 0.03 to 3.0; the
compression was a small-data artifact, not a knob to turn. Meanwhile the
gap closed on its own: at this scale the selected model beats Elo at both
grains on the test window (current regeneration: series 0.6570 vs 0.6580,
map 0.6693 vs 0.6719).

The sweep surfaced a subtler finding worth more than the original question:
plain LR beat the then-selected LightGBM on the untouched test window at
both grains while losing the validation comparison. The tempting move —
ship LR because test prefers it — is exactly the sin this walkthrough
exists to name: selecting on the test window makes it a second validation
set and un-earns every number reported from it. So nothing was switched on
test evidence; the disagreement was reported as a stability finding.

The finding then resolved into something cleaner (2026-07-24). After a
timestamp correction to the store, the LR-vs-LightGBM validation
comparison was measured at a gap of 8e-5 log loss — both candidates'
losses are now printed in the report header — which is machine-noise
territory: a fresh single-shot selection can legitimately name either
family on different hardware. The response was not to pick a winner but to
change the selection *procedure*: production now scores families by
rolling-origin (five expanding chronological folds) and keeps the
incumbent unless a challenger wins by more than one paired standard error.
The serving bundle therefore holds the incumbent — after the
timezone-corrected retrains that is plain LR — while the report's
single-shot protocol names its own pick each regeneration; when the two
diverge, the divergence is documented, never reconciled by hand. Two instruments neither model was tuned against arbitrate: the
frozen ledger (§10) and the walk-forward backtest (§11) — whose full-walk
verdict, for honesty's sake, is that the model's edge over Elo is recent,
not lifelong.

## 8. Collinearity: why you must not read the coefficients

`evaluate.py` §5 computes VIF via auxiliary regressions. The strength-signal
features are massively entangled — round_share_diff VIF ≈ 98, side
efficiencies ≈ 40, the two Elo diffs ≈ 13 with r = +0.96 between them —
while the genuinely independent features (first-kill diff, pistol, rest,
roster stability, context) all sit near 1. Under L2 the shared signal gets
distributed arbitrarily across the correlated set, so individual weights are
meaningless as marginal effects; prediction quality is unharmed. This is the
difference between a *predictive* model and an *explanatory* one, and the
report says so out loud rather than letting a reader tell coefficient
stories.

## 9. Tiers, and an experiment that said no

The scrape spans every vlr tier. A keyword classifier (auditable mapping,
counts printed) splits results: the model is strongest on tier-2
Challengers and Game Changers; on tier-1 VCT it currently produces both
better probabilities and slightly better picks than Elo (399 tier-1 test
rows) — but per-tier orderings at a few hundred rows are soft, and one
(Game Changers) flipped sign across a regeneration. The obvious hypothesis — "train only on tier-1 to predict
tier-1" — was tested properly: restriction applied to *training rows only*,
selection/calibration shared. At small scale (131 tier-1 training matches)
it lost everywhere, including on tier-1 itself (0.6989 vs 0.6836) — sample
size beat domain match. Re-tested at two years (752 tier-1 training
matches), the gap collapsed to noise (tier-1 test log loss 0.6771 restricted
vs 0.6791 all-tier, accuracy still worse). Verdict: no demonstrated benefit
at any scale tried; all-tier training stays.

## 10. The scoreboard: evaluation that can't be gamed

Every offline number above shares one weakness: the evaluator also built the
model. The ledger removes that. Predictions are written to SQLite **at least
5 minutes before match start**; the first prediction per match is frozen —
later calls, even from retrained bundles, are ignored; Elo's probability is
logged at the same instant. Grading fills in results and nothing else.
Whatever the model-vs-Elo story becomes, it will be written in rows that
existed before the matches did.

## 11. The deployment, replayed: why one test window isn't enough

Every static protocol above meets exactly one training size, one
validation size, one calibrator fit. A deployed system meets *all* of
them, in order. The walk-forward backtest replays that: from a 300-match
warmup to the end of the store, every completed match gets the same
pre-veto probability the live ledger freezes, called at the last legal
moment, through the serving code path itself, under bundles retrained on
the production cadence with the production selection policy. The as-of
rule is enforced at the walk's grain by test: a match that had not
finished at the call moves the prediction by exactly nothing.

Its first run rewrote the headline in a useful way. Aggregated over two
years, map-effective Elo leads the model on log loss in three of four
tiers — while the most recent period agrees with §3's test window (model
ahead where the test window says so). The edge is real and recent, not
lifelong; a static split cannot tell those apart. The run also caught the
project's sharpest bug-class finding: the week the growing validation
slice first crossed isotonic's 800-row admission gate (July 2025), the
freshly admitted calibrator saturated ~24% of the score range to a
0.999999 plateau, and one month of tier-2 predictions published extreme
probabilities that were wrong a quarter of the time. Platt, one retrain
earlier at 783 rows, was fine. No static split exercises "the first week
past the threshold" — only a replay does.

Two disciplines keep the instrument honest. **Separation:** the backtest
is served as its own section — simulated, large-sample, *not
independently verifiable* — and is never merged with the frozen ledger,
which is small and verifiable. **Run-once:** the runner refuses to
regenerate the result unless the shipped model has changed, and then the
old result is archived, never edited — findings get documented, not
silently patched (the July-2025 episode stays in the record exactly as
found). The temptation to fix the calibrator and quietly re-run is the
same sin as §7's, one level up.

## Reproducing everything

```bash
python scripts/evaluate.py --data data/raw/matches.jsonl
```

One script, every number, including the figures — plus
`scripts/backtest.py` for the walk-forward section, which additionally
enforces its own run-once rule. If a claim in this repository can't be
traced to a script's output, the claim is wrong.
