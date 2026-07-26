# Model card — vpredict serving bundle

## Model details

- **Task.** Pre-match win probability for professional Valorant, trained at
  map grain, aggregated to series probabilities by exact best-of DP.
- **Architecture.** Plain logistic regression (C=0.03) with
  step-isotonic calibration is the current serving bundle, held by the
  production selection policy: rolling-origin
  family scores with one-paired-SE champion/challenger hysteresis over a
  gated menu (LR always; regularized LightGBM admitted at ≥500 usable
  matches; no neural networks by project scope; `LOG.md` entry 28), then
  calibrated on validation by the best of three candidates — Platt, step
  isotonic, and smooth (PCHIP-interpolated) isotonic, the latter two
  admitted at ≥800 validation rows — by validation log loss, with every
  candidate's score stamped into the bundle (`calibration_val_ll`,
  behavior rev 4; `ASSUMPTIONS.md` §21). On the
  current (timezone-corrected) data the single-shot LR-vs-LightGBM
  comparison is a numerical dead heat — candidate validation log losses
  differ by 8e-5 (printed in the results header) — so which family a
  fresh single-shot selection names is machine-noise territory; hysteresis
  holds the incumbent. See Limitations. Validation is large
  enough (~2,000 map rows) to admit isotonic calibration. The persisted
  bundle contains the fitted pipeline, calibrator, feature schema, feature
  parameters (half-life 90 d, roster factor 0.8, feature Elo K=32), the
  tuned baseline K, the selection decision with its margin, training-data
  fingerprint, and a version string (which also encodes a behavior
  revision, so pure code changes to prediction behavior are visible to the
  backtest's run-once gate). Calibrated outputs are clipped to
  [0.005, 0.995] and published probabilities clamped one rounding-ulp
  inside (0, 1): a saturated calibrator (isotonic at its admission
  boundary, Platt on a degenerate slice) can otherwise claim exact
  certainty, which is evidentially indefensible — the two field episodes
  are `LOG.md` entries 31–32.
- **Features.** Differenced team form as of match start: time-decayed round
  share, attack/defense side efficiencies, first-kill diff per 12 rounds,
  shrunk pistol win rate, rest days, roster stability, overall and
  map-specific Elo diffs, map identity one-hots, best-of, playoff flag,
  history depth. Tier-B economy/clutch features are auto-dropped when the
  source tabs weren't scraped (they currently are dropped).
- **Version.** Reported by `/api/model` and stamped on every ledger row.

## Intended use

Educational and portfolio use: public pre-match probabilities with a frozen
audit trail, and a worked example of leakage-safe evaluation. **Not betting
advice**; no wagering use is intended or supported. Not affiliated with
Riot Games or vlr.gg.

## Market scope (2026-07-24)

The market-facing comparison is limited to **series moneyline and
over/under total maps**. Map totals derive from the same exact best-of DP
that already produces the series probability (the scoreline distribution is
the identical recursion with score bookkeeping), so they inherit — and are
more sensitive to — the stated pre-veto assumptions: uniform map-pool
weights and independence across maps. **Kill totals, first blood, map
handicaps, and player props are explicitly out of scope**: they are
different prediction targets that would need their own training and
calibration runs, not derivations of this model's output. Odds are captured
raw and append-only at prediction freeze and again near start; de-vigging
happens at analysis time (Shin primary, multiplicative as the sensitivity
column); the market comparison reports closing line value alongside
accuracy metrics. Market coverage is expected to be roughly tier-1 only, so
the Elo baseline remains the universal comparison for the ~85% of matches
without a line. None of this is betting advice.

## Backtest (2026-07-24)

A walk-forward backtest replays the live system over the full store, once:
for every completed match after a 300-match warmup, the same pre-veto
pool-mean series probability the ledger freezes, called at the last legal
moment (start − freeze margin), under bundles retrained on the production
cadence (7 days / 100 new matches, 6-hour ticks) with the production
selection policy (rolling-origin + one-SE hysteresis) and per-retrain
Elo-K tuning. Feature as-of discipline is the training pipeline's own:
nothing a call sees had finished after the call. Results are served in a
scoreboard section labeled **BACKTEST — simulated, not independently
verifiable**, per event tier only, and are never merged with the LIVE
frozen-ledger section: the backtest is the large-sample estimate, the
ledger is the verifiable record. The run-once rule is enforced in code —
the runner refuses to regenerate the result unless the shipped model has
changed, and the prior result is archived, never replaced silently
(`ASSUMPTIONS.md` §16, `scripts/backtest.py`).

## Training data

Scraped politely from vlr.gg (robots.txt honored, ≥1.1 s spacing, disk
cache). Current store: 6,796 matches, 2024-07-24 → 2026-07-22 (a full two
years at the backfill boundary), **all tiers mixed** — tier-1 VCT (1,073
usable), Challengers/Evolution (2,884), Game Changers (713), other (819).
After the ≥3-prior-maps eligibility rule: 5,489 usable matches / 13,337
map-team rows. Chronological 70/15/15 split by match.

## Metrics (untouched test window, 2026-07-05 → 07-22; regenerated 2026-07-24 after the timestamp correction)

Figures below are the evaluation report's (single-shot protocol; on the
corrected data its LR-vs-LightGBM choice is a dead heat decided by 8e-5 —
this session's regeneration selected plain LR, a re-run on other hardware
may legitimately select LightGBM with third-decimal differences; the
SERVING bundle is currently plain LR under hysteresis — see
Architecture). Map grain (2026-07-24 late regeneration, stand-in features in): log loss 0.6676,
Brier 0.2375, accuracy 59.6%, ECE 0.0345 — versus tuned Elo (K=24) 0.6704
/ 0.2388 / 59.0%. Series grain (824 series, veto-completed map sets): log
loss **0.6501**, Brier **0.2275**, accuracy **63.5%** — ahead of the
map-effective Elo DP baseline (0.6555 / 0.2317 / 61.7%) at the deliverable
grain. Per-tier: the report model leads Elo on log loss in tier-1, tier-2,
and other; Game Changers flipped to Elo on this regeneration (0.6262 vs
0.6201) — previously the model's strongest tier, and a reminder of how
soft these orderings are at a few hundred test rows. Tier-1 remains
hardest (0.6791 / 56.9%). The pre-correction figures (map 0.6671/0.2370/
59.5%, series 0.6500/0.2262/64.3%, LightGBM-selected) live in the dated
snapshot `results-2yr-2026-07-23.md`; split counts and row counts are
identical before and after the correction, and the movement is
third-decimal. Every figure regenerates from `scripts/evaluate.py`.

## Limitations

- **Selection stability.** The LR-vs-LightGBM gap sits inside noise and
  the ordering has now flipped twice: on the pre-correction data,
  validation chose LightGBM while the untouched test window preferred LR
  at both grains; on the corrected data, single-shot validation is a
  measured dead heat (candidate val map LL gap 8e-5, printed in the
  results header; C sweep val-series flat at 0.6309–0.6310 across three
  decades of C) while production's rolling-origin + hysteresis policy
  keeps the incumbent — currently plain LR after the
  timezone-corrected retrains (margin inside one paired SE). No switch is made on test
  evidence; the frozen ledger arbitrates, and the hysteresis policy is
  the pre-registered mechanism for absorbing exactly this instability.
- **Timestamp erratum (2026-07-24, `LOG.md` entry 29).** Every start time
  stored before the fix was US-Eastern wall time mislabeled UTC (4–5 h
  early). A marker-guarded migration corrected the store and ledger
  metadata; frozen probabilities and call times were untouched, and every
  recorded call predates the true start by MORE than previously claimed.
  Eligibility, splits, and row counts are identical before/after (a
  uniform shift cancels in start-vs-start comparisons, except within ±1 h
  of DST seams); metric movement is third-decimal, per the Metrics note.
- **Memory footprint.** The full feature build peaks ~0.7 GB RSS; 512 MB
  deploy instances cannot run the retrain/predict cycle (serving the API
  alone is light). See the deploy notes.
- **Uniform pool weights.** Pool membership is the top-7 maps by
  recency-weighted play frequency (14-day half-life within a 60-day
  window), so map rotations phase in within weeks; averaging across the
  chosen pool is uniform, and team pick/ban tendencies are not modeled.
- **Calibrated outputs are piecewise constant whenever step isotonic
  wins selection.** Step isotonic is a step function (a few dozen output
  levels on current data); a smooth monotone candidate now competes in
  the calibration menu under the standard validation rule (rev 4), and
  whichever wins, the decision and margins are in the bundle meta. The
  per-map spread under the shipped linear model is often narrower than
  one step — swap augmentation zeroes map-identity coefficients exactly,
  and heavy L2 with `elo_diff` collinearity crushes `map_elo_diff` — so
  every pool map can legitimately display the same probability. The UI
  states this and shows each map's Elo lean (the model's own per-map
  input); a smooth monotone calibration candidate is pre-registered for
  the next selection round (`ASSUMPTIONS.md` §21, `LOG.md` entry 37),
  subject to the same validation selection as everything else.
- **Coefficients are not explanations.** VIF up to ~98 among the
  strength-signal features (`data/reports/results.md` §5, regenerated by
  `scripts/evaluate.py`; dated snapshot `results-2yr-2026-07-23.md`);
  individual weights carry
  no marginal-effect meaning.
- **Roster/patch semantics are coarse.** Roster change is a lineup-overlap
  decay factor; patches and agent metas are unmodeled.
- **Low-history flag.** Predictions for teams with <3 prior maps are made
  but flagged `low_history` in the ledger and UI.

## Maintenance

The refresh cycle (scheduled by the service itself on deploy, or
`scripts/refresh.py` on cron — both spawn the same
`python -m vpredict.serving.refresh` entrypoint as a subprocess) tops up
the crawl, grades the ledger, retrains when the bundle is ≥7 days old or
≥100 new matches arrived, and re-predicts. Retraining is safe by
construction: ledger rows are frozen at first prediction, so model upgrades
can never rewrite the public record.

**Production note (2026-07-24, evening).** Automated refresh is ENABLED
on the live deployment (`VPREDICT_REFRESH=1`, Render Standard, 2 GB) —
made viable by the memory trim: the cycle streams the store instead of
materializing it, dropping the measured full-store peak from 1,221 MB to
296 MB with a growth slope of ~18 MB per 1,000 matches (sandbox
measurement; `LOG.md` entries 22–23). First-cycle verification on the
deployment (no OOM; cadence settles after the one labelled
"retrain once") is the open check. A separate production observation is on record: model
selection flipped architecture between two consecutive retrains on nearly
identical data — the stability finding in Limitations surfacing live
(`LOG.md` entry 24). The fix landed 2026-07-24: deterministic fits,
rolling-origin family selection, and one-paired-SE champion/challenger
hysteresis, with the decision and its margin stamped into every bundle
(`LOG.md` entry 28). Until the next full evaluation run,
`scripts/evaluate.py` still uses the older single-shot selection, so the
serving protocol and the frozen two-year report deliberately diverge; the
next dated results file re-aligns them. A calibration monitor now serves
drift detection at `/api/calibration` (report at n ≥ 30, act at n ≥ 100
per cell, Spiegelhalter Z globally; probabilities never modified).
