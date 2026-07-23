# ASSUMPTIONS

Every material decision made without asking, with the reasoning and the risk.
The build brief granted ownership of these calls; this file is the record.
Bugs and session events live in `LOG.md`; this file is about *choices*.

## 1. Build environment and data acquisition

**The build sandbox cannot reach vlr.gg.** The environment's network
allowlist covers package registries and GitHub only. Consequences, chosen
deliberately over stalling: parsers were written against selector knowledge
extracted from two actively maintained open-source scrapers and validated
offline against one real 135 KB vlr.gg results-page snapshot; full live
verification was deferred to the first run on the project owner's machine.
That run has since happened (2026-07-23: 150 matches, 810 map-team rows, zero
missing side splits or first kills) and found two parser/crawler bugs the
offline validation could not have caught — see LOG entries 9 and 10.

**Community scraper evaluation — the brief's premise was wrong, and that is
recorded rather than papered over.** The brief assumed several community
options had gone stale. Evidence gathered 2026-07-23 (shallow clones, last
commit dates): axsddlr/vlrggapi — MIT, last commit 2026-07-18;
akhilnarang/vlrgg-scraper — no license file, last commit 2026-07-18;
Vanshbordia/vlrdevapi — on PyPI, last commit 2026-07-09. Only
sanjaybaskaran01/StatsVLR is gone (repository no longer publicly reachable).
Decision anyway: build a self-contained scraper rather than depending on a
third-party hosted API, because uptime, rate-limit policy, and cache behavior
must be ours to control, and the project's politeness rules (below) are
requirements, not preferences. Selector knowledge from vlrggapi (MIT) informed
our original code; nothing was copied from the unlicensed repository, and its
real-page fixture was used for local validation only, never redistributed.

**Kaggle cold-start datasets: skipped.** Allowed by the brief, but unreachable
from the sandbox, schema-mismatched with our store, and redundant once the
scraper worked. If a cold start is ever needed, the store's JSONL schema is the
integration point.

## 2. Scraping conduct

robots.txt is fetched and parsed before any other request; a 4xx response is
treated as "no restrictions" per RFC 9309, a 5xx or network failure refuses to
crawl rather than crawling blind. Hard floor of 1.0 s between network requests
(configured 1.1 s), single-threaded, honest User-Agent naming the project.
Every fetched page is cached to disk keyed by URL hash; completed match pages
are cached forever (they cannot change), listing and upcoming pages carry a
15-minute TTL. This makes every crawl safely re-runnable and makes re-parsing
after a parser fix nearly free — a property that already paid for itself (LOG
entry 9's remediation).

Two completed-match crawl modes exist because they have opposite stop rules
(LOG entry 10): *top-up* stops at the first listing page containing nothing
new (the cheap scheduled-job path), *backfill* walks through pages of known
matches using their stored start times for the stop rule and never refetches a
known match page.

## 3. Temporal semantics — the leakage rule

**Eligibility is estimated finish, not start.** vlr.gg exposes only a match's
start time. Using "prior start < current start" would leak: an overlapping
match that started earlier but had not finished when match M began would count
as history. Rule adopted: a prior match is eligible for M's features only if
`start + assumed_duration(best_of) <= M.start`, with assumed durations of
1.5 h (Bo1), 3 h (Bo3), 5 h (Bo5) in `config.ASSUMED_DURATION_HOURS`.

Risk, stated honestly: a real Bo3 running longer than 3 h could be admitted
slightly before it truly finished. The error is bounded (tens of minutes, rare)
and the alternative — day-granularity eligibility — throws away legitimate
same-day bracket information (a semifinal genuinely finishes before the final
starts). The constants are configurable; the direction of the compromise is
conservative for the common case.

**Overtime rounds are counted but not side-attributed.** The map header
exposes regulation CT/T splits plus an OT lump. OT sides alternate and
reconstructing attribution would be guesswork; per the brief's rule against
silent approximation, side-efficiency features use regulation rounds only,
while total round counts include OT.

**Shrinkage priors are themselves as-of.** League means used as shrinkage
targets are computed from cumulative prefixes over the estimated-finish
timeline — a global mean computed over the full dataset would leak the future
into every early match through the prior. The leakage tests cover the priors
explicitly.

**Elo obeys the same rule via an event queue.** A match's rating updates are
queued at its estimated finish and applied only once a later match's start
passes that time. Both teams are snapshotted once per match, before any of that
match's own maps update anything, so map 2's features never contain map 1's
result. Elo updates do not commute, so the replay used by the build-time
leakage spot-check applies updates in the identical order as the live event
queue (estimated finish, ties by start order) — see LOG entry 5 for the bug
that motivated pinning this down.

## 4. The feature set — the fate of each original hand-designed metric

The brief listed 13 hand-designed metrics and granted ownership of the final
set. Disposition of each, with reasons:

- **Map win rate — dropped.** Nearly collinear with round share and the side
  efficiencies while being noisier (a 13-11 and a 13-2 are the same win). Round
  share (time-decayed rounds-won fraction, shrunk toward 0.5) is the retained
  aggregate-strength signal.
- **Overall round differential — dropped**, same collinearity reasoning; it is
  an algebraic sibling of round share.
- **Attack / defense side efficiency — kept**, regulation rounds only, each
  shrunk toward the *as-of league mean* for its side (defense prior is 1 −
  attack prior by construction: every attack round is someone's defense round).
- **First-kill differential per 12 rounds — kept**, from per-player FK/FD sums,
  shrunk toward the symmetric prior of 0.
- **Pistol win % — kept, and promoted to Tier A.** The brief assumed economy
  data for it; the round strip on the base match page gives rounds 1 and 13
  winners directly, which is more reliable than the economy tab. Shrunk toward
  0.5 with 16 pseudo-pistols (~8 maps).
- **Bonus / anti-bonus conversion — dropped.** Requires round-by-round bank
  states; the robust economy source is an aggregate per-map table, and parsing
  the per-round bank icons was judged too fragile to ship silently. Not
  approximated, per the brief's rule.
- **Post-plant win % — dropped as originally defined.** The base page exposes
  each round's win method (elim/boom/defuse/time). Boom and defuse imply a
  plant, but elimination rounds are ambiguous with respect to plants, so true
  post-plant conversion is not computable from Tier A. The raw win method is
  *stored* per round for future use; no proxy is silently substituted.
- **Opener conversion % — dropped.** Needs first-kill-to-round-outcome linkage
  (a kill timeline), which Tier A does not provide.
- **Clutch % — replaced by clutch wins per map (Tier B).** The performance tab
  gives 1vX wins but not attempts, so a true percentage is not computable.
- **Multi-kill round % — replaced by multikill rounds per map (Tier B)**, same
  denominator problem.
- **Economy stability index — replaced by outcome-based full-buy win % and
  low-buy (eco + semi-eco) win % (Tier B).** Outcome rates are directly
  interpretable and shrinkable; a hand-built "stability index" would smuggle in
  arbitrary weights.
- **League-normalized versions — replaced by Elo-as-feature plus A−B
  differencing.** Subtracting league means adjusts for environment but not for
  opponent strength; a pre-match Elo difference (overall and per-map) does both
  jobs more directly and is itself leak-free by construction.

Tier B columns are auto-dropped when column coverage is below 90 % (or absent),
so the model degrades gracefully when the economy/performance tabs are not
scraped. Added context features: best-of, a playoff flag (keyword match on the
series string: playoff, final, semifinal, quarterfinal, upper/lower bracket,
knockout, elimination), map identity dummies, `hist_min` = log1p of the smaller
team's prior map count, and rest days (capped at 30, log1p, differenced).

**Roster turnover.** The "current core" is the five most frequent players over
a team's last five eligible maps. Historical map weights are multiplied by
`roster_factor ** players_changed` (grid {0.5, 0.8, 1.0}; 1.0 disables). A
roster-stability feature (mean lineup overlap with the core over the last five
maps) is also emitted. This implements the brief's "decay or reset on
turnover" as a tunable decay; a hard reset is the 0-ish end of the same knob.

**Hand-assigned weights were not included in the brief.** The
importance-vs-hand-weights chart therefore defaults to uniform weights over
the 13 original metric names (`config.HAND_WEIGHTS`), used for that chart
only, never for prediction. Paste the real weights there to fix the chart.

## 5. Modeling and evaluation protocol

- **Grain: one row per (match, map)**, oriented to the as-listed team1.
  Match/series-level aggregation (and the pre-veto map-pool weighting) is
  deliberately deferred to the serving milestone.
- **Symmetry by swap augmentation, training only.** Tree models have no reason
  to satisfy P(A beats B) = 1 − P(B beats A); appending every training row
  with diffs negated and the label flipped teaches it. Evaluation rows are
  never augmented.
- **Splits: chronological 70/15/15 by match**, never by map, so a series never
  straddles a boundary. Validation does triple duty — model selection, early
  stopping, calibration — a deliberate, documented compromise to preserve an
  untouched test window; with more data the right refinement is a second
  validation slice.
- **Model menu is gated by usable match count** per the brief: < 500 →
  regularized logistic regression only; 500–3000 → plus heavily regularized
  LightGBM; > 3000 → same menu, no neural networks. Selection by validation
  log loss.
- **Calibration:** Platt scaling always fitted; isotonic only when the
  validation window has ≥ 800 rows (isotonic overfits small samples); the
  better of the two by validation log loss is kept.
- **Baselines:** constant 0.5; favourite = higher pre-match Elo
  (accuracy-only by nature); Elo with K tuned on validation log loss over
  {16, 24, 32, 40, 50}. A model that ties Elo is a legitimate finding, per the
  brief — the synthetic smoke run demonstrated the report will say so (LOG
  entry 8).
- **Feature-Elo K is fixed at 32 while baseline K is tuned.** Retuning the
  feature K would require rebuilding the feature matrix inside the selection
  loop for marginal gain; rating *differences* are not very K-sensitive. The
  asymmetry is intentional and cheap to revisit.
- **Rows require ≥ 3 prior eligible maps for both teams** (`MIN_MAPS_HISTORY`);
  below that, features are mostly shrinkage priors and the row is noise.

## 6. Data-quality rules and the synthetic-data policy

- The store is append-only JSONL of typed records, idempotently upserted by
  match id; a parser change that alters stored fields is handled by deleting
  the derived store and re-parsing from the immutable HTML cache (procedure in
  LOG entry 9). The cache, not the store, is the source of truth for raw HTML.
- Every synthetic record carries `synthetic: true`; any report built from data
  containing one synthetic row is watermarked in stdout, in the results file,
  and across the calibration figure. No number appears in project
  documentation unless `scripts/evaluate.py` produced it from real data —
  which also means the README's results section stays explicitly empty until
  the first real-data evaluation.
- Tier B parsers return None on any structural surprise and the crawler
  proceeds without them; Tier B failures never block Tier A.

## 7. Constants chosen without tuning (and where they live)

`config.py` is the single home for all of these. Chosen by judgment, not
search, and flagged as such: shrinkage strengths (60 pseudo-rounds for round
rates, 16 pseudo-pistols), per-map Elo blend M = 10 maps, assumed match
durations (above), decay half-life default 90 d and roster factor default 0.8
(both sit on declared tuning grids; the ablation harness that tunes them is
scheduled with the training milestone, currently held pending the first
real-data evaluation), rest-day cap 30, prediction ledger freeze margin 300 s,
map-pool window 60 d / size 7 for the deferred serving milestone.

## 8. Serving & scoreboard semantics
- **Freeze rule.** A prediction is accepted only ≥5 minutes before scheduled
  start (`LEDGER_FREEZE_MARGIN_S`), and the first accepted prediction per
  match is immutable — later calls (including from retrained bundles) are
  ignored. "Called in advance" therefore means the earliest public call.
- **Pre-veto aggregation.** Upcoming-match series probabilities average
  per-map model probabilities over the current pool (top-7 maps by 60-day
  play frequency) with UNIFORM weights, then apply the exact best-of DP.
  Team-specific pick/ban tendencies are future work; the uniform choice is
  stated on the model card.
- **As-of NOW.** Serving features use the same eligibility rule as training
  (matches whose estimated end precedes the prediction moment), so nothing
  in-progress leaks in.
- **Retraining cadence.** The refresh cycle retrains when the bundle is ≥7
  days old or ≥100 new matches arrived; the frozen ledger makes model
  upgrades safe — past predictions never change.
- **Elo comparison column.** The tuned-K Elo baseline probability is logged
  at the same moment as the model's, so the public model-vs-Elo comparison
  cannot be recomputed favourably later.
- **Single-service deploy.** Managed persistent disks (Render/Railway) bind
  to one service; the refresh loop therefore runs in-process
  (`VPREDICT_REFRESH=1`) rather than as a separate cron that couldn't see
  the ledger.
