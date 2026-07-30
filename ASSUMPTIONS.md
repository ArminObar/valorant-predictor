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
map-pool window 60 d / size 7, membership recency half-life 14 d (§36).

## 8. Serving & scoreboard semantics
- **Freeze rule.** A prediction is accepted only ≥5 minutes before scheduled
  start (`LEDGER_FREEZE_MARGIN_S`), and the first accepted prediction per
  match is immutable — later calls (including from retrained bundles) are
  ignored. "Called in advance" therefore means the earliest public call.
- **Pre-veto aggregation.** Upcoming-match series probabilities average
  per-map model probabilities over the current pool (top-7 maps by
  recency-weighted play frequency — 14-day half-life within a 60-day
  window, §36) with UNIFORM weights, then apply the exact best-of DP.
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
  to one service; the refresh loop therefore runs from inside the service
  (`VPREDICT_REFRESH=1`) rather than as a separate cron that couldn't see
  the ledger. (Refined 2026-07-24: each cycle is now spawned as a
  subprocess of the service rather than run in-process — see §12 and LOG
  entry 23.)

## 9. Deploy fixes and the memory measurement standard (2026-07-23)

**Frontend location strategy.** The dist directory resolves in order:
`VPREDICT_FRONTEND_DIR`, `/app/frontend/dist`, `<ancestor>/frontend/dist`
walking up from the module, `<cwd>/frontend/dist`; a candidate must contain
`index.html` (an empty dist is "absent", not "mounted and 404ing"). An env
var that is set but invalid logs a warning and falls through to the
candidates rather than failing hard — serving the site beats dying on a
typo, and the warning keeps the misconfiguration visible. Absence is never
silent: a warning lists every path tried (LOG entry 19).

**Smoke tests exercise the committed tree, not the working tree.** The
container smoke test builds from `git archive HEAD` because both deploy
bugs (LOG entries 18–19) lived precisely in the gap between working tree
and committed-tree-installed-as-package. A working-tree mode exists for
pre-commit iteration, but the deploy-shaped build is the default.

**Binding memory number = cgroup peak inside a Linux container.** That is
what Render enforces, so that is the instrument; macOS figures
(`/usr/bin/time -l`, getrusage) are indicative only. "Before" measurements
run under a 1 GB container limit — measuring a ~0.69 GB workload at 512 MB
just OOM-kills the run — and 512 MB enforcement is a separate post-trim
run. Budget target 440 MB (~85% of 512) for page-cache accounting and
OOM headroom. Risk, stated honestly: local Docker on Apple silicon
measures arm64 while Render runs x86-64; accepted as second-order at the
magnitudes involved, with final verification on Render.

**Forced retrains on the full real store are legitimate.** The
`VPREDICT_FORCE_RETRAIN` switch exists so measurement runs exercise the
expensive path; a forced full-data retrain produces the same bundle a
scheduled retrain would, and the frozen ledger makes retrains safe by
construction, so baseline runs need no sandbox.

**Growth-curve semantics.** The x-axis is stored-match count capped via
`VPREDICT_STORE_LIMIT` in store-file (crawl) order — not chronological
order, which is irrelevant for memory scaling and is the only thing these
runs measure. Store-limited runs are measurement-only: any bundle or
prediction they produce is garbage by design, so growth runs *always*
execute inside a disposable cloned workspace via `VPREDICT_WORKSPACE`, and
the harness refuses to run growth until the operator explicitly
acknowledges having verified that wiring (procedure in MEMORY_RUNBOOK.md).
The extrapolated budget-crossing match count is always labelled an
extrapolation from the measured points, never a measurement.

## 10. Market odds baseline — decisions on record, execution parked (2026-07-23)

Execution is parked until the deployed site is working and seeded. The
investigation's decisions are recorded now so the pilot is designed against
them rather than re-litigated later.

**"Market" means observed bookmaker prices.** Sources whose odds are
house-originated by models (PandaScore's traded odds, Rimble's simulation
pricing) are excluded — logging them as "market" would compare our model to
a competitor model wearing a market costume. Direct scraping of book sites
is rejected on ToS, geo-blocking (offshore books gate by server region, so
a US-region Render box sees a different book than a Toronto browser), and
this project's politeness rules; aggregator or official book APIs only.
Rivalry, named in the original plan, suspended all betting in February 2026
and is not a source. Candidate order from the 2026-07-23 investigation:
OddsPapi (free tier; carries Pinnacle, GG.BET, Thunderpick), BetsAPI
fallback, Cloudbet's official feed as a sanctioned single-book supplement.

**Pre-registered expectation: the market baseline is likely tier-1-only,
and that is a finding, not a failure.** The best available prior —
OddsPapi's own worked example, a vendor marketing figure, not our
measurement — showed ~10 Valorant fixtures with odds in a week, against
the ~65 matches/week our crawl averages. If per-tier line availability
comes back negligible below tier 1, the deliverable is exactly that table:
per-tier availability-by-start and availability-at-freeze (NULL-at-freeze
rates), reported per tier and never pooled, with the model card scoping the
market comparison to "where the market speaks". The pilot is designed to
report sparse coverage cleanly — a market column that exists only for
tier 1 while the model covers all tiers is itself evidence about where the
market is soft, which is the point of the comparison.

**Capture and de-vig protocol (unchanged from the investigation, for when
this unparks).** Market implied probability is captured in the same
transaction that freezes model and Elo (identical information cutoff;
NULL when no line exists at that instant), plus a last-tick-before-start
snapshot as a closing proxy, both forward-only — no historical backfill,
even where vendors offer timestamped history; vendor history is used only
to audit our own capture integrity. Raw prices are stored append-only and
de-vigged at analysis time: Shin's method primary (margin loads onto
longshots, and tier-2 margins run wider, so proportional normalization
would flatter the market's underdog pricing exactly where our model is
strongest), multiplicative as a sensitivity column, per-tier mean overround
reported as its own table. One headline book per row by fixed sharpness
priority (Pinnacle > GG.BET > Bet365 > Thunderpick > any), priority pinned
in config, all captured books stored, never silently averaged.

## 11. Session decisions, 2026-07-24 — crawl-since fix, measurement wiring, doc alignment

**README amended, not rewritten.** The rewrite task assumed the README still
carried stale small-data claims; origin/main's README already holds the
two-year results, verified figure-by-figure against
`results-2yr-2026-07-23.md` (STATE.md's bug 3 is stale on this point).
Amendments only: live URL under the title, the LR-vs-LightGBM stability
finding surfaced with the non-switch rationale, a dated
status-and-limitations section, test count corrected to the suite's actual
40. The requested single merged results table was declined in favour of the
existing two: the map table's map-effective-blend row has no series
analogue, and merging grains would blur exactly the distinction the project
is careful about.

**0.6620, not 0.6619.** MODEL_CARD and WALKTHROUGH cited plain LR's test map
log loss from the flat C ≥ 0.1 sweep rows (0.6619). The validation-selected
LR is C = 0.03, whose test map figure is 0.6620. All documents now cite the
★-selected row — the number the selection protocol actually earns — for a
cosmetic 0.0001 in the honest direction.

**LOG renumbering.** Two deploy-era entries titled "Entry 11/12" collided
with existing entries 11/12; renumbered to 18/19 with all cross-references
updated (including two in this file).

**Top-up window constants.** `TOPUP_OVERLAP_DAYS = 3` and
`TOPUP_BOOTSTRAP_DAYS = 30` (config.py) are judgment calls, untuned. The
`since` bound is anchored to the newest completed *stored* match rather than
to "now minus a fixed window" so a top-up self-heals after an outage of any
length; the overlap covers listings gaining entries slightly out of order.

**Store-limit semantics (measurement wiring D).** `VPREDICT_STORE_LIMIT=n`
returns the chronologically FIRST n matches — simulating the store as it was
when it held n matches, which is what a peak-vs-store-size curve needs. The
capped path is a deliberate two-pass read (timestamps first, validate only
selected lines): capping after a full parse would leave the curve's dominant
term flat in n and the fit meaningless — the first implementation did
exactly that and measured 730 MB at a 1,700 limit; the two-pass version
measures 424 MB. `upsert_matches` reads via an uncapped private reader:
upsert rewrites the file from what it loads, so a capped read there would
silently truncate the real store if the env var leaked into a crawl. A test
pins both behaviours.

**Workspace precedence (measurement wiring E).** `VPREDICT_WORKSPACE`
re-roots every data path and deliberately takes precedence over
`VPREDICT_DATA`, so a lingering deploy variable can never aim a
size-limited retrain at the real bundle or freeze garbage predictions into
the real ledger.

**Wiring reconstructed from the harness contract.** PATCH_NOTES.md lives
only on the dev Mac, not in the repository; edits C–F were implemented to
the contract `scripts/memharness.py` and `src/vpredict/memprof.py` document
(exact env-var names, growth-mode semantics, phase reporting). If the local
PATCH_NOTES prose differs in detail, it should win — but the harness
enforces this contract mechanically, so drift risk is low.

**Measurement caveats, stated once.** The 2026-07-24 numbers in LOG entry 22
come from a Linux/py3.12 sandbox: wait4 child-tree peaks are authoritative
there; cgroup readings were discarded (shared cgroup, high-watermark
poisoned by unrelated work); absolute numbers are environment-specific (the
Mac measured ~0.69 GB for the same cycle) while the per-phase attribution
and the linearity of the growth curve are the transferable findings.

## 12. Memory trim invariants (2026-07-24)

Full narrative and measurements in LOG entry 23; the *decisions* on record:

**The cycle streams, always.** No step of the refresh cycle may hold more
than one `Match` at a time: `iter_matches` is the only sanctioned reader
inside the cycle, frame builders consume iterables, grading scans a stream
against a small id set, and training builds its frame straight from the
iterator. `load_matches` survives for scripts, tests, and small files
(upcoming.jsonl), with a docstring saying exactly that. The risk accepted:
the cycle now parses the store up to three times per run (top-up bound,
grade, train) instead of sharing one list — ~20–25 s of CPU at the current
store size, traded for a ~925 MB peak reduction.

**The store file is sorted, and upsert keeps it that way.** Invariant:
lines ordered by `(start_ts, match_id)`. The streaming merge relies on it
and maintains it; the capped reader's yield order depends on it. A
replacement whose timestamp moved re-merges to its new position (a test
pins this). Pass-through lines are copied verbatim — never re-validated —
so the changed-count semantics are preserved by parsing only colliding
lines. Memory is O(batch); the old load-everything-rewrite made every
250-match crawl flush cost a full-store materialization.

**Refresh is a subprocess.** The scheduler spawns
`python -m vpredict.serving.refresh` rather than calling in-process:
memory returns to the OS between cycles, and an OOM kill takes the child,
never the API. `scripts/refresh.py` delegates to the same entrypoint so
cron and the scheduler cannot drift apart.

**Acceptance protocol.** The sandbox measured 296.3 MB at full store
against the 440 MB target and a growth slope of 18.2 MB per 1,000 matches
(LOG 23), but sandbox numbers do not accept the deliverable: the owner's
Mac harness run and the `VPREDICT_REFRESH=1` flip on the deployment are the
acceptance steps, and the predict phase has not yet been measured with real
upcoming matches (it shares the streaming path by construction).

## 13. Odds capture, CLV, and the calibration monitor — pre-registered 2026-07-24, execution gated

Owner-specified design, recorded before any code exists. Build order:
odds capture first, then the calibration monitor; neither starts until the
memory trim is verified and accepted on the deployment.

**Capture runs locally (owner's Mac, Toronto), not on Render.** Geo-blocking
is not a factor locally, and a real browser (Playwright) passes bot
detection a bare request will not. Cloudbet's official free feed API is
wired FIRST as a correctness harness for capture and de-vig, before
anything points at a book that does not want to be read. Raw prices are
stored append-only; nothing is de-vigged at capture time. De-vig happens at
analysis time: Shin's method primary, multiplicative as a sensitivity
column beside it. Capture fires at the same instant the ledger freezes each
prediction, and again near scheduled start — the closing capture exists
because CLV needs a close to compare against.

**Evaluation framing: closing line value.** The use case is edge detection,
so alongside log loss and Brier the market comparison reports CLV: did the
de-vigged close move toward the frozen prediction relative to the de-vigged
freeze-time line. That is the measurable proxy for genuine edge on far
fewer matches than profit would need. Coverage honesty: the market will
price roughly tier-1 only (~10 fixtures/week of ~65), so **Elo stays** — it
is the only baseline for the ~85 % of matches with no line.

**Calibration monitor over the ledger.** Bucketed predicted-vs-observed
rates, per bucket and per tier. Reporting threshold n ≥ 30 per cell; action
threshold n ≥ 100 per cell with a Wilson 95 % interval excluding the cell's
mean predicted probability. Early warning with less data: one global
Spiegelhalter Z over all graded rows (informative from ~50–100 graded).
Explicitly rejected: per-match error correction — this is drift detection,
not noise chasing. Predictions outside the calibration-validated range
(~0.15–0.88 at series grain) are flagged `extrapolation` on the ledger row
and in the UI; the probability itself is never modified.

## 14. Odds, selection, and monitor — implementation decisions (2026-07-24)

§13 pre-registered the designs; these are the calls made while building.

**Book priority is Pinnacle, then Cloudbet — fixed, for the headline
column only.** Pinnacle is the sharpest widely referenced book and the
standard CLV yardstick, so when both books price a match, the headline
model-vs-market comparison uses Pinnacle. Every captured book is stored in
full; nothing is averaged, silently or otherwise (`ODDS_BOOK_PRIORITY`).

**Shin by bisection, not closed form.** The two-outcome closed form
exists, but bisection on the insider fraction z is robust for any outcome
count and its monotonicity is trivially testable. Multiplicative is always
computed beside it; the gap between the columns is itself reported, since
it measures margin-model sensitivity.

**Capture state lives in the log.** "Has this (source, match) a freeze? a
close?" is derived by scanning the append-only capture log — no state
file, so a crashed or re-run cron pass is idempotent by construction. A
freeze is the first capture after a prediction appears; a close is the
first capture within `ODDS_CLOSE_WINDOW_MIN` = 20 minutes of start; a
match already started is counted as a missed close, never backfilled.

**Linking never guesses.** Exact normalised names (both orientations),
then the user-edited alias table, else the capture is stored UNLINKED with
the fixture named in the log. A fuzzy matcher would occasionally be
confidently wrong in a file that exists to be an audit trail.

**Cloudbet's Valorant market key is discovered, not assumed.** The docs'
samples don't show esports, so the client accepts any two-outcome
home/away market whose key matches winner/moneyline hints, logs every key
seen, and stores raw responses; the first Mac run pins the real key
(LOG entry 25).

**Selection: procedure-level comparison.** Each rolling fold re-runs each
family's full procedure (LR re-picks C, LightGBM re-early-stops), because
the deployable object is the procedure, not one frozen hyperparameter.
Folds are 5 expanding windows over the last half of train+val, in
chronological order, test window untouched. Hysteresis compares pooled
per-row losses PAIRED (same rows), switching only past one SE — the
paired SE is the right scale because both models score identical rows.
`n_jobs=1` costs seconds and buys within-machine determinism; cross-
machine numerics can still differ, which hysteresis absorbs.

**Monitor cells are fixed-edge, not quantile.** Quantile bins move as data
arrives — a monitor wants stable cells, so edges are pinned at
[0.15, 0.35, 0.50, 0.65, 0.88] with extrapolation zones outside. The
action rule (n ≥ 100 AND Wilson 95% excluding the cell's mean prediction)
is deliberately two-keyed so small samples cannot page anyone.

**EV "unvalidated" threshold, pre-registered for item 4:** the EV column's
unvalidated label drops at n ≥ 100 graded, market-covered picks —
matching the monitor's action threshold — with per-tier reporting
regardless of n. Recorded now so the scoreboard build cannot tune it.

**Cadence-fix semantics.** Bundles record `n_store_records`; a pre-fix
bundle triggers exactly one labelled "retrain once" so every deployment
converges to honest counting without manual surgery (LOG entry 26).

## 15. Timezone remediation, alias suggestions, markets & EV — session decisions (2026-07-24, evening)

**Ledger start_ts corrected as metadata; frozen fields untouched.** LOG
entry 29's migration rewrites `start_ts` on already-frozen ledger rows.
The freeze rule exists so probabilities and call times can never be
revised — `made_at`, `p_model`, `p_elo`, `p_maps_dist` are exactly that
and are untouched; `start_ts` is match metadata that was provably wrong by
4–5 h, and displaying known-wrong times forever is the worse integrity
outcome. The correction strengthens the freeze property (every call
predates the TRUE start by more than the ledger previously claimed), and
the migration marker file is the audit record. Risk accepted: rows in the
one ambiguous DST fall-back hour per year can land 1 h off; same bound as
the fixed parser.

**Migration is run-once by marker, with auto-heal in the refresh cycle.**
Applying the ET-reinterpretation twice would corrupt the store, so a
marker file gates it; the refresh cycle applies it before crawling so the
Render disk self-heals with no shell step, and old rows can never mix with
fixed-parser rows unmigrated. `--force` exists solely for re-seeding
old-format data onto an already-marked disk, and says so loudly. The
migration is byte-equivalent to re-parsing the HTML cache with the fixed
parser (same reinterpretation), chosen because the cache lives only on the
Mac; running the cache re-parse afterwards and diffing is a valid audit.

**Fuzzy linking proposes; it still never links.** §14's "linking never
guesses" survives: the capture path is unchanged (exact normalized, then
aliases, else UNLINKED). The fuzzy layer runs OFFLINE over unlinked log
rows and produces suggestions a human confirms into aliases.json — the
audit trail stays human-approved. Scoring: generic org tokens (esports/
team/club/gaming/...) are dropped, token subsets and acronyms score high,
and PROTECTED roster qualifiers (academy, GC, ...) present on one side
but not the other zero the score outright — "G2" must never suggest "G2
Academy". Near-ties within 0.05 are surfaced as ambiguous and never
auto-accepted; `--yes` auto-accepts only unambiguous proposals ≥ 0.90.
Thresholds chosen by judgment against the 11 field-observed cases, all of
which resolve unambiguously (tested).

**Markets & EV definitions (spec item 5), on the record before grading
starts.** A *pick* exists per (match, market, line) on the headline source
(§14 book priority): the side with higher EV at the ENTRY price, where
entry = the earliest freeze capture (the public "called at" price) and
close = the latest close capture. EV = frozen model probability × raw
decimal entry price − 1; the Shin and multiplicative de-vigged
probabilities are stored beside it for fair-value comparison and never
blended into EV. CLV = entry/close − 1 on the pick's side (needs a close;
missing closes are excluded from CLV aggregates and counted). Extrapolated
picks (model probability outside the §13 band, now config-owned) are
shown, labeled, and EXCLUDED from EV/CLV aggregates — win rate still
counts them. The §14 pre-registered gate applies: EV displays
"unvalidated" until ≥ `EV_MIN_GRADED_PICKS` = 100 graded market-covered
picks. Scope is series moneyline and map totals ONLY (model card).

**Totals are priced from the frozen distribution or not at all.** The
maps-played distribution comes from the same pool-mean per-map probability
and exact best-of DP as the series probability, is computed at prediction
time, and freezes into the ledger (`p_maps_dist`) with the first call.
Rows frozen before the column existed are simply not priced for totals —
recomputing with a newer model would let upgrades rewrite the public
totals call. `maps_played` on graded rows is grading metadata (like
`team1_won`), filled at grade time and backfilled once for rows graded
before the column existed. Cloudbet totals identification is by exclusion
(the live key `esport_valorant.totals` contains no "map"): reject
kill/round/player/per-map names and any line > 4.5 — map-count lines are
small, kill totals are 150+. Capture convention: for `maps_total` rows,
price_home = OVER, price_away = UNDER.

**The markets report is a derived view pushed over an authenticated
ingest.** The odds log lives on the Mac (§13), the ledger behind the live
API — so `scripts/publish_markets.py` joins them on the Mac and POSTs the
derived JSON to `/api/ingest/markets`, guarded by a shared bearer token
(`VPREDICT_INGEST_TOKEN`; endpoint disabled when unset, constant-time
compare, size-capped). Overwriting the report can never touch either
source of truth. Rejected alternative: committing the report to git and
redeploying per update — auditable but turns every odds refresh into a
deploy.

**Capture overlap is locked, not detected.** A non-blocking `fcntl.flock`
in `capture_odds.py` makes a second concurrent pass exit 0 immediately.
The log-derived state (§14) already makes SEQUENTIAL re-runs idempotent;
the lock closes the remaining race where two CONCURRENT passes both read
"no freeze yet" and both append one. flock releases with the process, so
no stale-lockfile handling exists to get wrong.

**Walk-forward backtest cost protocol (item 7, measured before building).**
The feature matrix is built ONCE and reused across every simulated
retrain: each row's features are as-of its own match start by the leakage
rule, so they do not depend on when the model trains — a retrain at
simulated time T trains on rows finishing before T. `scripts/
backtest_cost.py` replays the production retrain trigger over the real
store timeline (92 retrains over 635 days at 7 d / 100-match cadence,
warmup 300) and times the true retrain unit (rolling-origin scores +
hysteresis + final fit ≈ 2.4 s on a 1-core box): production-cadence total
≈ minutes, retrain-before-every-match ≈ 3.4 h there. Numbers regenerate
from the script on any machine.

## 16. Walk-forward backtest protocol (2026-07-24, evening — pre-registered before the single run)

Owner-approved build (production cadence, BACKTEST/LIVE separation,
per-tier). Decisions made while building, on the record before the one
official run:

**The simulated quantity is the ledger's quantity.** Every call is the
pre-veto, pool-mean series probability from `predict_one` — the same
function live serving invokes — with the map pool recomputed as-of each
call. NOT the veto-informed map-set probability the evaluation report's
series section uses: the backtest simulates what the live system would
have frozen, and the live system does not know the veto at freeze time.
The two numbers are therefore comparable across the BACKTEST and LIVE
sections and deliberately not comparable to `results.md` §2.

**Call time = start − freeze margin (the latest legal call).** Live
first-accepted calls happen whenever a refresh cycle first sees the match
— hours to days early, at the operator's cadence, which is not a property
of the model. The latest legal moment is the sharpest well-defined
alternative: it uses exactly the information a legal call could have had,
it is deterministic, and it makes every simulated call maximally
informed rather than dependent on an arbitrary simulated crawl schedule.
Recorded consequence: backtest calls are on average slightly
better-informed than live first calls.

**Retrains replay the production procedure on sliced rows.** Trigger:
6-hour ticks (phase-anchored at the warmup boundary), firing on the
production rule (bundle ≥ 7 d old OR ≥ 100 newly finished matches);
first bundle at warmup = 300 finished matches. Each retrain runs the
train_and_save sequence on matches finished by the tick —
chronological_split (the newest 15 % held out untouched, exactly as
production does), rolling-origin family scores, hysteresis against the
walk's previous bundle, select_model, and per-retrain Elo-K tuning.
Slicing the once-built feature matrix equals rebuilding it at the cutoff:
every row's features depend only on matches finishing before that row's
own start, so rows at or before any cutoff are identical either way (the
as-of test pins this in both directions at the walk grain).

**Low-history rows are made, counted, and not scored.** The live ledger
predicts low-history matches and flags them; the backtest does the same,
and per-tier metrics are computed over graded non-low-history rows so
they measure the model, not the prior. Both counts are reported.

**Run-once is enforced mechanically, not by promise.** The runner refuses
to overwrite an existing result; `--replace` is honoured only when the
SHIPPED bundle's version differs from the one recorded in the existing
result, and the old summary is archived first. Re-running against an
unchanged model is refused by code, because that is what tuning against
the test would look like.

**Validation run vs the official run.** The engine was validated in the
build sandbox with a full run over the real (timezone-corrected) store;
those numbers appear in the session report as the sandbox validation run.
The OFFICIAL published record is the owner's Mac run (`APPLY.md` §9),
which the run-once gate then protects. Cross-machine numeric noise can
move third-decimal metrics and dead-heat selections (ASSUMPTIONS §14);
the two runs are expected to agree to that tolerance, and any larger gap
is a bug to investigate, not a result to pick from.

**Markets inside BACKTEST.** The market join is structural: simulated
probability vs genuinely captured prices, labeled BACKTEST, populated
only where the local odds log links a capture — near-empty until odds
accumulate, and stated as such rather than padded. Entry/close/EV/CLV
definitions are §15's, unchanged.

## 17. Calibrated-output bounds, decided before the first official backtest run (2026-07-24, late)

**Timing: hardening BEFORE the official run does not touch run-once.**
Run-once protects published results from being tuned against and quietly
regenerated. No official backtest result exists yet — the owner's Mac run
was blocked by the very failure that forced this decision — so hardening
now means the FIRST published record is of a model whose outputs the
project would defend, instead of a knowingly defective one followed
immediately by a labeled re-run. The pre-hardening sandbox validation run
was archived by the `--replace` machinery (its numbers stay quoted in the
session record), and the owner's official run happens once, against the
hardened model. Deciding the change on the basis of a diagnosed mechanism
and a red test is a bug-class fix; deciding it on the basis of which
backtest numbers improve would have been tuning. The July-2025 result
itself is unchanged in the archived record.

**Clip over isotonic-margin, because the failures decide it.** Two
saturation modes were observed in the field: isotonic plateauing at 0/1
the week it first cleared its 800-row admission gate (LOG 31), and Platt
becoming a −59-slope step function on a 3-row separable slice (LOG 32).
An "isotonic must beat Platt by a margin" rule addresses only admission
churn: it would have fixed neither observed failure and bounds nothing.
The clip bounds ANY calibrator's claims, which is the actual invariant
the ledger needs. The margin rule stays on record as a possible future
addition if calibrator selection ever proves churny — it solves a
different problem than the one that occurred.

**Constants and their provenance.** `CAL_OUTPUT_CLIP = 0.005`: the range
a healthy Platt fit spans on its own (~[0.0049, 0.9952], measured on
retrain r41's 783-row slice) — the most any calibrator may claim is what
a sane fit could evidence. Judgment anchored to a measurement, not a
tuned value. `PROB_DECIMALS = 4` names the existing ledger rounding; the
publish clamp sits one rounding-ulp inside (0, 1) because series
aggregation defeats the map-grain clip alone (Bo5 of 0.995s = 0.999999 →
rounds to 1.0000). Probabilities of exactly 0/1 are evidentially
indefensible and break log-loss accounting; both bounds are pinned by
tests that construct the saturating fits explicitly.

**`BUNDLE_BEHAVIOR_REV` exists because the gate caught its own blind
spot.** The bundle version was date + parameter/data hash; a pure code
change on unchanged data produced an identical version, and the backtest's
run-once gate — correctly — refused a `--replace` it could not
distinguish from a same-model re-run. The revision constant (rev 2 = this
hardening) feeds the version hash so behavior changes are detectable; the
cost is a human obligation to bump it, recorded in the constant's comment.

**Deployment semantics.** Calibrator behavior lives in code, not pickled
state: deployed bundles adopt the clip on deploy without a version bump.
Interim delta is nil for in-band predictions (live upcoming calls sit
inside 0.15–0.88); the next cadence retrain stamps the behavior-rev'd
version. Static-report impact, measured: three fourth-decimal digits;
every headline number unchanged.

## 18. Live scoreboard scoring rule aligned with the backtest (2026-07-24, night)

The live headline metrics now score graded non-low-history rows only —
the rule §16 pre-registered for the backtest — after LOG entry 33's
placeholder row became the first "result". Nothing is hidden: total
graded, low-history, and scored counts are all served and shown, flagged
rows stay visible in the graded table, and frozen probabilities are
untouched. The alternative (scoring self-collided placeholder calls into
the public headline) misrepresents the model in both directions at small
n. Placeholder fixtures (colliding team keys) are no longer predicted at
all; names on old rows backfill at grade time as display metadata (§15
precedent).

## 19. Ensemble, stand-in features, and one test read — pre-registered before running (2026-07-24, late night)

Registered before any evaluation executes, so nothing below can be tuned
against results.

**Stacked ensemble (owner item a).** Stage-1 for out-of-fold fitting is
the LR procedure's RAW probabilities (fit_lr, C picked per fold as
always) — the dead heat (§17/LOG 32 context: 8e-5) makes the family
choice immaterial and LR is deterministic cross-machine. Elo input is the
K=24 prematch probability (the production baseline K; K was tuned on
validation once, a status shared with every validation choice). OOF
protocol: 5 expanding chronological folds over the TRAIN slice's last
half; stage-2 fits ONLY on those out-of-fold train rows — never on
validation, because stage-1's production calibrator fits there and
stacking on it would leak. Candidate list, fixed now: (1) incumbent
pipeline unchanged; (2) global blend sigma(a + b*logit(p_model_raw) +
c*logit(p_elo)); (3) per-tier blend, one (a,b,c) per tier, tiers under
200 OOF rows fall back to the global fit. Selection by validation MAP log
loss; every candidate's test columns are printed (C-sweep precedent), the
selected one also reported at series grain through the identical DP
machinery. The blend, if selected, replaces the calibrator role
end-to-end; it is a model change (behavior/feature versioning applies).

**Stand-in features (owner item c), exactly two, Tier A.** From lineups
already scraped at 100% coverage: `core_absent_diff` (share of the
5-player core missing from the team's most recent eligible lineup, A−B)
and `newface_diff` (share of that lineup outside the core, A−B). Both
derive only from PRIOR eligible maps through the engine, so the as-of
rule applies by construction and the poison test covers them via full
snapshot comparison. The "star absent by first-kill share" variant is NOT
computable — per-player FK is aggregated at parse time — and would need a
per-player scraping pass; recorded as future work. Ship gate, fixed now:
the new features ship only if validation log loss improves against the
same split without them; otherwise the result is recorded and the
features are reverted.

**Patch timing: deferred, not faked.** The store's patch field is
populated on 0 of 6,790 completed matches, and hardcoding a patch-date
table from memory risks fabricated data. Two honest routes recorded:
parser addition + cache re-parse on the owner's machine, or an
owner-verified date table; neither is built this round.

**Per-map form: not built, on measurement.** (team, map) cells have a
median of 3 rows and 14% reach 10; a map-conditional form feature would
be shrinkage prior for most of the pool, and per-map Elo already carries
the deep-data signal. Recorded, revisit if the store doubles.

**Bradley-Terry / TrueSkill: not built, reasoning sharpened.** Beyond
parameter count (~1,000 teams, median 11 maps each), a batch latent-
strength fit is frozen at train-end while Elo keeps updating as-of
through validation and test; making BT as-of means refitting at every
prediction time, which re-derives online Elo at far higher cost. The
gated menu's Elo features already occupy this role.

**Version integrity.** `make_version` now hashes the feature-name list —
a feature-set change on the same params/day previously produced an
identical version string, the same blind spot §17 fixed for behavior
(the run-once gate must be able to see feature changes too).

**One test read.** This entire batch — features in or out by the gate,
ensemble candidates — is evaluated in a single evaluate.py run: one new
dated results file, one read of the test window.

## 19b. Fair ensemble selector — pre-registered for the NEXT evaluation (2026-07-24, late night)

LOG entry 34's finding: §19's selector compared blends fitted on
out-of-fold train rows against an incumbent whose validation score
includes its calibrator's fit-on-validation optimism (measured 0.0087).
Next evaluation, every candidate — incumbent included — is scored on
validation through out-of-fold-fitted calibration (Platt on the same OOF
train predictions), selection by that number, calibration for DEPLOYMENT
still fitted as production fits it. Registered now, before any such run,
so the blends' strong test columns in this round cannot influence the
rule. This round's selection (incumbent) stands.

## 20. Maps-total EV excluded from aggregates and the gate — owner-directed (2026-07-24, night)

The frozen maps distribution assumes independent maps; measured reality
over 3,654 graded Bo3s puts P(2-0) at 60.7% against the assumption's
53.5% (LOG 34 context). A ~7-point probability bias flows straight into
maps-total EV — systematically flattering overs — so, by owner direction:
totals picks stay fully visible in the record (frozen data is the
record), each carries `ev_excluded: "totals_independence_bias"`, their EV
cell displays "excluded" rather than a known-biased number, and they are
left out of EV/CLV aggregates AND the EV validation gate — a biased EV
cannot help validate EV. CLV is excluded with EV because the pick's SIDE
was chosen by the biased max-EV rule, contaminating what CLV would
measure. Moneyline is untouched. Reinstatement condition, fixed now: the
one-parameter within-series correlation fix, shipped as a versioned model
change with a labeled backtest re-run — `config.EV_EXCLUDE_TOTALS` flips
only then.

## 21. Per-map display honesty now; smooth calibration pre-registered — decided 2026-07-25

Context: LOG entry 37. The shipped bundle's per-map probabilities can
legitimately tie across the whole pool (step-function isotonic over a
sub-point raw spread). Owner-approved disposition, in three parts:

**Now (frontend + payload only, no rev bump).** The serving payload gains
`per_map_elo` — each pool map's Elo lean from the identical feature-K
snapshot the feature row consumes — and the per-map panel explains the
calibration step function in plain language and shows the lean beside
each probability. Judgment call: the lean is the FEATURE Elo (K=32
map-effective blend), not the tuned baseline K, because the chip's claim
is "this is the model's per-map input", and that must be literally true.
Display-only; the ledger schema is untouched, and a frozen headline is
labeled as such next to the live per-map view. Risk: none to the record;
the chips could mislead if a future bundle stops consuming map Elo, so
the contract test ties the payload to the snapshot rather than to a
constant.

**Next model round (pre-registered before any further test read, same
discipline as §16/§19b).** A smooth monotone calibration candidate —
isotonic with monotone (PCHIP) interpolation between plateau midpoints —
joins Platt and step isotonic in the calibration menu, selected by the
existing validation rule, nothing else changed. This is a model-definition
change: BUNDLE_BEHAVIOR_REV bumps, the deploy retrains once, and the
backtest's run-once gate sees it. If the smooth candidate loses
validation, step isotonic stays and the display note remains the honest
answer. Explicitly rejected: swapping the calibrator outside selection
because the steps look bad — that is cosmetics overriding the
pre-registered policy.

**Future work, logged not scheduled.** The linear model structurally
cannot express per-map effects beyond the single `map_elo_diff`
coefficient: swap augmentation zeroes map identity exactly (correct
behavior, not a bug), and L2 with elo_diff collinearity crushes what
remains. Genuine per-map differentiation needs interaction terms or the
tree family; both go through the standard gated selection when data
supports them, and neither is promised.

## 22. Homepage leads with the recent window; every displayed number is a served artifact — decided 2026-07-25

Owner-directed emphasis flip, executed with these judgment calls:

**What leads and why.** The hero and the model tab now open with the
recent-test-window comparison (series grain first — it is the deliverable
the ledger publishes — then map grain, then per tier), because it is the
honest strongest current result: the untouched newest 15 percent of a
chronological split, confirmed by a fresh `scripts/evaluate.py` run on
2026-07-25 after the timezone migration and the stand-in retrain. The
two-year backtest loses no visibility: it keeps its own panel, the hero
links to it, the model tab links to it, and its framing states plainly
that Elo wins most of the full history, including the early data-starved
era. Emphasis changed; no number changed; nothing moved more than one
click away.

**No hardcoded metrics, enforced by construction.** The frontend contains
zero typed-in numbers for either window. The recent-window figures render
only from `GET /api/results`, whose sole producer is
`scripts/evaluate.py` (the JSON is written from the same in-scope arrays
that format `results.md`, so it cannot diverge from the report) moved by
`scripts/publish_results.py`, which refuses synthetic-watermarked or
structurally incomplete artifacts with named reasons. Until a publish
happens, the hero falls back to the pre-existing prose (a claim the
owner's fresh run verified) and the model tab simply omits the panel —
rendering nothing rather than inventing something.

**Featured live prediction stays series-level.** The hero's "next up"
strip shows the series probability only, not per-map chips, until §21's
calibration round lands — featuring the quantized per-map display on the
homepage would amplify exactly the artifact §21 exists to fix. It reuses
the served upcoming JSON, filters placeholder fixtures, and carries the
same low-history badge as everywhere else.

**Cosmetic widening, recorded.** The scoreboard's metric component keyed
its higher-is-better direction on the exact label "accuracy"; it now
keys on the substring so "series accuracy" colors correctly. Display
logic only.

## 23. Logo-home, divider clearance, inline tie note — session decisions (2026-07-25, late)

Three owner-directed small items, with the judgment calls recorded:

**Logo navigates home.** "Home" is defined as the default landing state:
match detail closed, upcoming tab, scrolled to top. The logo gets
button semantics (role, tabIndex, Enter) and a glow hover instead of the
generic clickable outline, which would box the wordmark.

**Divider bar moved out of the artwork.** Root-cause fix, not a nudge:
the overlap existed because decoration lived in scaled SVG coordinates
while content lives in layout coordinates (LOG entry 38). The bar is now
a pinned element under enlarged bottom padding, so clearance holds for
ANY future hero height. Rejected alternative: lowering the rect's y in
the viewBox, which merely re-tunes the same fragile coupling.

**Tie note renders conditionally.** The one-line "ties are expected"
note appears among the per-map rows only when at least two displayed
probabilities actually tie at ledger precision; on the rare untied
payload the note would itself be the confusing element. Wording states
the mechanism (shared calibration levels) and points at the Elo lean,
per LOG entry 37's finding that the ties are correct output.

## 24. Polish pass scope — aesthetic only, one motion moment (2026-07-25, late)

The site's identity already exists (the win-probability tug of war, teal
vs ember, Rajdhani display over a dark arena); the polish sharpens it
rather than importing a new look. The single deliberate motion is the
tug fill sweeping in on mount — the signature element earning the
boldness budget — and the active tab's underline becomes the same
two-tone gradient as the tug bar, tying navigation to the motif.
Everything else is quiet consistency: card depth and hover lift on
clickables only, table row hover, pill badges, visible keyboard focus in
the accent color. `prefers-reduced-motion` disables the animation and
the lifts wholesale. Explicitly out of scope and untouched: every word
of copy, every number, every honest-disclosure sentence, all layout
structure.

## 25. Smooth calibrator lands in the menu — §21 option B executed (2026-07-25, late)

Implementation decisions, all inside the pre-registered frame:

**The candidate.** `SmoothIsotonicCalibrator`: fit the identical sklearn
isotonic, collapse it to one knot per plateau (mean input, level output),
join the knots with scipy's PCHIP — monotone by construction through
monotone knots — hold the end levels outside the knot span exactly as
`out_of_bounds="clip"` does, and bound the output with the same
`CAL_OUTPUT_CLIP` as every other calibrator. Fewer than two plateaus
means nothing to interpolate, so it degrades to the step. The scipy
interpolant is rebuilt per call so no scipy object is ever pickled into
a bundle.

**Same admission gate as step isotonic (≥800 validation rows)**, because
it is derived from the identical isotonic fit; giving it a different
gate would make the comparison unfair in either direction.

**Selection stays the standard rule, and the decision now travels.**
`fit_calibrator` returns every candidate's validation log loss; the
scores land in the bundle meta (`calibration_val_ll`, visible at
`/api/model`), the results header, and `results_summary.json`. Whether
smooth wins or loses must be readable, never asserted — the tests pin
the candidate's properties (monotone, midpoint-exact, smoother than the
step, bounded, degenerate-safe) and deliberately do not pin a winner.

**Behavior rev 3 → 4**, because the menu change can change output shape
if the new candidate wins: the deploy retrains once via the existing
trigger, and the version hash moves.

**Backtest re-run policy under run-once.** The rev-4 retrain changes the
bundle version, which makes `scripts/backtest.py --replace` legal. The
discipline is about the definition AS EXECUTED: if the retrain selects
`smooth_isotonic`, serving output changed and a labeled `--replace
--push` re-run is warranted (prior result archives automatically); if
step isotonic is retained, the executed definition is unchanged, the
re-run would be a plain-retrain replay, and it should be skipped — with
this section as the recorded reason either way.

**First measurement (sandbox, seed store, recorded before the owner's
binding retrain).** Calibration validation log losses under the
production selector (LR incumbent retained): platt 0.65924, isotonic
0.65073, smooth_isotonic 0.65996 — the step wins by a real margin and
the smooth candidate ships nowhere. One structural caveat rides with
that number: every calibrator is FITTED and SCORED on the same
validation window (the documented triple-duty compromise, §5), and
smoothing removes exactly the flexibility that lets the step mold
itself to that window, so this protocol is expected to favor the step
even when the smooth variant would generalize as well or better. The
right test of that hypothesis is the already-noted protocol refinement
(a separate calibration slice, or out-of-fold scoring inside
validation); until that lands, the validation rule stands and so does
its verdict.

## 26. Match-page rating history chart — decisions (2026-07-25, late)

A trust-building visual, built so it cannot drift from the record:

**Same rating, not a lookalike.** The lines are the overall Elo of the
site's own comparison family — tuned baseline K read from the live
bundle, `DEFAULT_ELO_K` fallback when no bundle is readable — replayed
under the identical eligibility rule and order as every other as-of
surface (estimated finish before the cutoff, event-queue order). The
cutoff is the predicted match's start, so each line ends at the overall
rating the as-of snapshot reports for that cutoff (the consistency test
pins trajectory-end == snapshot to one decimal). The ledger's frozen
p_elo was computed from the store as it existed at freeze time, so
history scraped later can shift the replayed line slightly without ever
touching the frozen number; the chart claims context, not the freeze.

**Post-match points, right-aligned, evenly spaced by match.** One point
per completed match (the team's rating just after it), last
`RATING_TRAJECTORY_N = 10`, both teams sharing the right edge as "now".
Even spacing by match rather than by date reads cleaner for streaky
schedules, and the caption states the choice so nobody mistakes it for
a time axis.

**Display context only, degrade to nothing.** The block is additive
JSON on the existing match endpoint; any failure logs a warning and
omits the chart rather than breaking the page, placeholders never get
one, and nothing here reads or writes the frozen ledger. Cost accepted:
one more streaming pass over the store per detail-page request, in line
with the endpoint's existing team-history pass.

**Geometry is a pure module.** `frontend/src/chart.js` computes every
coordinate outside React so `node --test` pins right-alignment, y
inversion, and domain padding the same way `time.js` is pinned.

## 27. Per-map display: the lean leads, the percentage never hides — decided 2026-07-25 (late)

The owner offered two designs; option (a) — Elo lean primary, model
percentage secondary — was chosen over removing the percentage, for two
reasons. First, disclosure: the calibrated per-map probability is the
model's actual output, and a site whose whole premise is showing its
work should not delete a model output because it looks repetitive;
demoting it to small text keeps the record complete. Second, the ties
are not universal: the calibrator has a few dozen levels, some matches
DO straddle a boundary, and option (b) would discard real variation on
exactly those rows. The lean is rendered as a centered diverging bar
(right of center favours team1, echoing the tug motif) scaled to the
pool's largest lean, with the signed number beside it; the model
percentage sits at the row's end in small dim text labeled "model". The
0031 conditional tie line is superseded by this hierarchy plus the
rewritten standing note, and is removed rather than left as clutter.
Payloads predating `per_map_elo` fall back to the plain
name/bar/percentage row. Presentation only: no number, threshold, or
model behavior changed.

## 28. Polish round two — aggressive, inside the same identity (2026-07-25, late)

Round one (§24) was judged too timid; this pass raises the hierarchy
and depth while keeping every word and number in place. The moves: a
brighter dim tone and a faint dot grid over the arena backdrop (pure
CSS, no assets); the wordmark and key numerals enlarged; the tab row
becomes a segmented control whose active pill carries the two-tone
underline; panels and cards gain radius, padding, and an entry rise;
clickable cards grow a teal-to-ember edge bar on hover instead of a
chevron (the right edge of cards is already busy with times and
percentages); panel titles brighten and carry a small two-tone tick;
team names get color dots that bind the palette to its meaning; the
hero's stat and next-up cards go glass (backdrop blur, feature-gated
behind @supports); the footer gets the same two-tone rule. The
teal/ember split is now ONE motif used in five small places rather than
scattered novel decoration. Reduced motion disables the rise, the
sweep, and the lifts. Explicitly untouched: all copy, all numbers, all
honest-disclosure language, all layout structure and information
order.

## 29. Full redesign: the tactical board — scope and decisions (2026-07-26 session)

**Scope read as unambiguous and interpreted strictly.** "Visual only,
everything else exactly as-is" means: zero markup changes, zero copy
changes, zero number changes, zero information-order changes. The
redesign is therefore a single-file stylesheet rewrite; App.jsx is
untouched, which makes the owner's carry-over guarantees (per-map lean
rows, calibrator verdict, rev-4 trigger) hold by construction rather
than by care.

**Rewrite over a fourth append layer.** Three polish passes had begun
overriding one another; a redesign that cannot touch markup needs one
authoritative sheet. Every class rendered by App.jsx was inventoried by
grep and verified covered; the production vite build compiles clean.

**The direction.** The page becomes a designed surface grounded in the
subject: a tactical-board backdrop (faint contour rings sweeping from a
teal pole and an ember pole over graph dots, pure CSS, no assets), a
full-bleed hero and footer like broadcast bands, a thin two-tone spine
holding the left margin on wide screens, and an angular clipped-corner
plate system replacing rounded web cards — the HUD language of the
game, executed with the site's own teal/ember split as the single
recurring motif (tab pill underline, panel-title ticks, hover edge
bars, footer rule, hero bar, team dots). Shell widens to 1040px with
the reading measure preserved inside panels.

**Costs accepted, stated.** clip-path clips outer shadows, so plates
use borders plus an inner top light instead of drop shadows (flat
angular depth, intentional); the clipped notch loses its border line,
so a rotated hairline redraws the diagonal. Fonts stay Rajdhani+Inter:
the pairing is subject-appropriate and already loaded; a third face
would add weight without adding identity. Sandbox has no pixel
rendering, so the aesthetic verdict is the owner's; the sheet is
deliberately one revertable commit.

## 30. The lites cache — design decisions (2026-07-26 session)

Owner-approved fix for LOG entry 39, with the calls recorded:

**Cache the lites, not per-team Elo.** The expensive object is the
store-derived lite list; the replay over it costs 0.11 s and caching
per-team ratings would add invalidation surface for no measurable win.

**Key = (path, mtime_ns, size), one entry.** The store is append-only
JSONL: any top-up moves both mtime and size, and nanosecond mtime
makes same-second double top-ups safe. One entry suffices because the
process serves one store; a different path (tests, tools) simply
replaces the entry.

**Base lites only.** `extra_maps` (veto-known deciders) varies per
call on the prediction path, so extras are never cached; the serving
chart needs none.

**Build under the lock.** Concurrent cold requests serialize behind
one multi-second build instead of duplicating it; the lock is held
only during a miss.

**Shared-object contract.** The returned list is shared across
requests and documented immutable; the only consumer
(`elo_trajectory`) reads and copies, never mutates.

**Resident memory accepted.** A few MB of lites now stay resident in
the API process — which on Render is also the refresh process
(VPREDICT_REFRESH in-process, §8). Accepted against the measured 2 GB
headroom; the refresh cycle's own streaming paths are unchanged.

**Scope stops at the approved brief.** The warm click's remaining
0.85 s is the team-history streaming pass; caching it too was not
approved and is left as recorded future work rather than smuggled in.

## 31. Security hardening — audit decisions (2026-07-26 session)

Findings and the calls made, per the owner's audit list:

**CORS: removed, not scoped.** The middleware allowed every origin,
method, and header. But no legitimate cross-origin consumer exists: the
frontend is served same-origin by this app and the dev server proxies
/api (vite.config.js). Removing the middleware entirely is stricter
than any allowlist and costs nothing; a future consumer gets an
explicit origin list, never "*".

**Rate limiting: in-memory sliding window, per client IP, /api only.**
120/min default (config RATE_LIMIT_PER_MIN, env-overridable, 0
disables), 429 + Retry-After. In-memory on purpose: single-process
service, limiter state is worthless across deploys, and a distinct-IP
cap bounds the table under address-spoofing floods. Client IP from the
first X-Forwarded-For hop, which Render sets at its TLS edge.

**Headers.** nosniff, DENY framing, strict referrer, minimal
Permissions-Policy, and a CSP with scripts locked to 'self'.
'unsafe-inline' is granted to STYLES only, because React style
attributes drive the tug and lean bars; the trade is recorded rather
than silently taken (inline scripts remain blocked, which is the part
that matters for XSS).

**Ingest guard.** Already timing-safe (hmac.compare_digest) and already
opaque on failure; hardened to byte-wise comparison so no header value
the transport can deliver raises, and covered by tests including
oversized tokens.

**Input surface.** match_id is the only free-form parameter; it never
reaches SQL (parameterized reads, python-side compares) or the
filesystem; it now gets a length/printability guard returning a clean
400. Unhandled exceptions anywhere return a generic 500 with the
traceback logged server-side only.

**Dependencies.** pip-audit: zero known vulnerabilities across project
dependencies (the only hit was the sandbox's own pip). npm audit: two
advisories, both confined to the dev-server chain via old esbuild;
fixed by bumping vite 5 -> 8, after which audit is clean, tests pass,
and the production build succeeds.

**Static exposure.** The only mount serves the built frontend
directory; the data disk is never mounted; traversal and direct-path
probes are pinned by test to 404 without leaking bytes.

## 32. Repo hygiene for the portfolio cut (2026-07-26 session)

**README rewritten in full.** The old file was accurate but read like
documentation; the new one reads like the person who built it, keeps
every load-bearing claim (frozen ledger, honest backtest verdict,
selection discipline, bug stories), and carries the current
regeneration's numbers (series 0.6570 vs 0.6580, map 0.6693 vs 0.6719,
62.1% vs 61.3%) plus the live test count (137). Rule inherited from the
frontend copy: no em dashes anywhere in the README.

**STATE.md and patches/ untracked.** STATE.md is a personal working
scratchpad (deadlines, half-drafted notes) and patches/ holds applied
patch artifacts; neither is part of the published project, so both move
to .gitignore and out of tracking. History still contains them until
the owner runs the history rewrite in the session notes.

**Doc staleness corrected, minimally.** MODEL_CARD's architecture lead
and two serving-family clauses said the serving bundle was LightGBM;
after the timezone-corrected retrains the incumbent the hysteresis
policy holds is plain LR, and the card now says so without touching its
dated metrics block. WALKTHROUGH §7's "current regeneration" figures
updated to the current regeneration; its serving-bundle sentence now
describes the mechanism (hold the incumbent, document divergence)
instead of naming a family that can flip; §6 mentions the third
calibration candidate. The card's dated metrics block (2026-07-24
regeneration) is left as a dated snapshot on purpose — refresh it from
the next `scripts/evaluate.py` run rather than by hand.

## 33. Correcting §2: cache-forever is only sound after completion (2026-07-26 session)

§2 recorded "completed match pages are cached forever (they cannot
change)". The premise was wrong in one case that production found (LOG
entry 41): a body cached from the upcoming radar predates the result,
and the completed crawl trusted it forever. §2 stands as the historical
record; this section records the correction and the new rules.

**Verify, then trust.** The completed path treats "listing says
completed, body parses non-final" as proof of a pre-completion cache
body and forces exactly one network refetch, which also rewrites the
cache entry. Cached-forever now applies to bodies that have EARNED it
by parsing as completed.

**The completed path never stores a non-final state.** If even the
fresh body is not final (listing/page race, postponement, reversion),
nothing is stored and the id stays unknown, which makes the next crawl
retry it for free. The store moves forward to completed-with-winner or
not at all.

**The healing pass.** Runs inside the refresh cycle, after crawl and
before grade so releases grade in the same cycle, and only when
crawling is enabled (offline cycles stay offline). Candidates: stored
records still upcoming/live at start + assumed duration +
HEAL_SLACK_HOURS (2 h — a genuinely long match costs one polite probe
and is never overwritten, because heal also refuses non-final bodies),
within HEAL_LOOKBACK_DAYS (14 d — bounds a cancelled fixture's cost to
one request per cycle for two weeks, then silence). Worst case on
deploy day: ~15 extra polite requests at the fetcher's 1.1 s spacing;
steady state: zero.

**Frozen rows untouched.** Healing edits only the match store; the
ledger's frozen predictions never change, and grading merely fills
outcomes — same rule as always, now actually reachable.

## 34. Real routes: decisions behind the router (2026-07-26 session)

**BrowserRouter over HashRouter.** The ask was URLs that behave "the way
they do on any normal site", and `/scoreboard` is that; `#/scoreboard`
is the compromise you make when you can't touch the server. We can:
the cost is a ~20-line SPA fallback in `api.py`. It is deliberately
narrow — only 404s, only GET/HEAD, never `/api/*`, never a path whose
last segment has an extension — so a stale bundle hash or a probe for
`ledger.sqlite` still 404s honestly (every sensitive artifact path has
an extension; the existing static-mount security test passes untouched,
and the handler can only ever emit `dist/index.html`). Extensionless
non-routes (`/nonsense`) get the shell and the client renders a small
not-found panel; that 200-for-unknown-pages trade is standard SPA
behaviour, accepted deliberately.

**A dependency, not a hand-rolled router — and the version is an
eyes-open compromise.** Hand-rolled history handling is where popstate,
focus, and middle-click bugs live, so react-router it is. Version
walk, because no reachable version is audit-silent: v6 and v7 ≤ 7.17
carry an open-redirect advisory in `<Link>`/`useNavigate`
(GHSA-wrjc-x8rr-h8h6) — the one surface this app actually uses — fixed
in 7.18.1; 7.18.1 itself carries GHSA-qwww-vcr4-c8h2, an RSC-mode CSRF
that requires framework-mode server actions, code paths that cannot
execute in this static SPA (no SSR, no RSC, no actions; FastAPI serves
`dist/`); the fully clean line is react-router 8, whose floor is React
≥ 19.2 — a framework major that does not belong inside a navigation
patch. npm's own suggested "fix" is a downgrade to 7.11.0, which would
REINTRODUCE the open-redirect advisory on a live surface to silence an
unreachable one. So: pinned exact 7.18.1, residual advisory named
here, exit path = a deliberate React 19 + react-router 8 patch later.
Per LOG entry 40 the change was verified with a cold `rm -rf
node_modules && npm ci`, `vite build`, and the node test suite.

**Tab clicks reset to the tab's default view — on purpose.** That is
the requested semantics and the router gives it by construction
(navigation remounts the route). It also means returning to a tab
re-fetches and shows defaults rather than restoring scroll/filter
state; if per-tab state ever needs to survive, it goes in query params,
not back into component state.

**Match detail's back button.** `navigate(-1)` — the real history —
with one guard: on a direct deep link there is no in-app history, so it
falls back to `/upcoming` instead of walking the user off the site.

**Addendum (2026-07-26): the residual advisory verified unreachable —
evidence, not just a claim.** Challenged directly ("is it actually
exploitable in this app, walk through what an attacker would need"),
the answer was re-derived from the artifacts. First, the accounting:
`npm audit`'s "2 high severity vulnerabilities" is ONE advisory,
GHSA-qwww-vcr4-c8h2 ("RSC Mode CSRF Bypass Allows Action Execution
Before 400 Response", published 2026-07-22/24, affects react-router
>= 7.12.0 < 8.3.0, patched only in 8.3.0 whose peer floor is React
19), counted once on `react-router` and once on `react-router-dom` —
the latter transitively, with an empty `via` list. The maintainers'
own scoping note: "This only affects your application if you are
using the unstable RSC APIs." The other advisory people reach for,
the open redirect in Link/useNavigate (GHSA-wrjc-x8rr-h8h6), is not
installed at all — fixed in 7.18.1, which is the reason for the pin.

The CSRF flaw is server-side (a forged request makes react-router's
SERVER runtime execute a route action before the 400). Exploiting it
here requires four things, and each fails independently and
absolutely — every check re-runnable from the repo root:

1. *A server running react-router's RSC pipeline.* None exists: the
   production image's final stage is `python:3.12-slim`; Node lives
   only in the discarded frontend build stage, so no process in the
   deployment can execute JavaScript at all.
   Verify: `grep -n FROM Dockerfile`.
2. *An app calling the unstable RSC (or framework-mode action) APIs.*
   The entire router surface is `BrowserRouter` plus Link, NavLink,
   Navigate, Route, Routes, useLocation, useNavigate, useParams —
   declarative client mode, the mode the advisories exclude.
   Verify: `grep -rn 'from "react-router' frontend/src/` and
   `grep -rnE "createBrowserRouter|RouterProvider|loader:|action:|<Form|useFetcher|useSubmit|RSC" frontend/src/`
   — the only hit is our own `<FormDots>` W/L component.
3. *The vulnerable bytes shipping somewhere.* The built bundle
   contains zero RSC transport markers, including the
   `text/x-component` string literal that survives minification,
   while provably containing the app and the client router.
   Verify (after `npm run build`):
   `grep -c "text/x-component" frontend/dist/assets/index-*.js` -> 0;
   `grep -c "react-router" frontend/dist/assets/index-*.js` -> nonzero.
4. *Ambient credentials for a forged request to ride.* There are
   none: no cookies or sessions anywhere in the backend, frontend
   fetches set no credentials option, and the only state-changing
   endpoints (ingest) require an explicit Bearer token header —
   never attached automatically by a browser — compared in constant
   time (patch 0039) and disabled outright when the env var is
   unset. Verify:
   `grep -rniE "cookie|SessionMiddleware" src/vpredict/serving/` and
   `grep -rn credentials frontend/src/`.

The patched-away open redirect gets the same belt-and-braces: even
hypothetically present, it needs a navigation target built from
attacker-influenced input, and every `to`/`navigate` target in the
app is a route literal, `navigate(-1)`, or
`/match/${encodeURIComponent(id)}` with the id from our own API; the
one stranger-typed string (the `/match/:id` URL segment) flows into a
backend-validated API fetch, never into a navigation target.

Conclusion, recorded so a future auditor sees the reasoning and not a
trust-me: the flagged code has no host process, no invoking API call,
no shipped bytes, and no credentials to abuse — four independent
walls. No code change is therefore the correct action; npm's
suggested downgrade to 7.11 would trade an unreachable server-side
flaw for a client-surface advisory in code we actually execute, and
the React 19 + react-router 8.3.0 bump (the audit-silencing exit
above) changes the ledger, not the risk. Registry re-checked
2026-07-26: 7.18.1 is still the newest 7.x, no backport yet; the
exact pin means nothing drifts while we wait.

## 35. Backtest on the scoreboard: a derived summary, the table one click away (2026-07-26 session)

Presentation only, by explicit instruction — the numbers, and the
honesty of Elo winning most of the history, do not move. What changes:
the scoreboard page no longer ends with the full per-tier backtest
table (two large model-vs-Elo tables on one page read as repetition);
it ends with a one-paragraph summary carrying the same "simulated"
badge and the same kept-apart framing, linking to `/backtest`, where
the full table now lives as its own tab with a proper empty state.

The summary's numbers ("Elo wins X of N tiers, the model wins Y") are
NOT prose: they are computed at render time from the same
`/api/backtest` payload the full table draws, by a pure function
(`frontend/src/backtestSummary.js`) pinned by node tests — ties count
for neither side so the sentence stays literally true, and if the
long-run picture ever flips, the sentence flips with the data instead
of flattering anyone. Nothing on either page is typed in by hand.

## 36. Map-pool membership is recency-weighted, half-life 14 days (2026-07-26 session)

The June 24 rotation (patch 13.00: Pearl and Fracture out, Summit and
Sunset in; VCT Stage 2 runs patch 13.01 with the new seven) exposed the
cost of raw 60-day frequency: the served pool kept both rotated-out maps
and, on frozen data, would have until early September — two months of
the old act outweighs two weeks of the new one. Fix (owner's call from
three presented options): keep the 60-day window as a hard support
bound, weight each in-window play by `0.5 ** (age_days / 14)` from its
start time, pool = top 7 by weighted count. Membership only — averaging
across the chosen pool stays uniform (§8), and frozen ledger rows keep
their original first calls by construction.

What the weighting does and does not do, measured on the real store
(`scripts/inspect_pool.py` regenerates every claim): applied
retroactively to data frozen at 2026-07-22 it corrects the pool from
5/7 to 6/7 the moment it deploys — Fracture out, Sunset in — because
it is a read-time transform over plays the store already holds; no
crawl accumulation is needed for the plays that already happened. It
does NOT accelerate exits on a frozen store: a shared exponential decay
preserves ratios, so with zero new data Pearl still holds the last slot
until the window edge does its old-rule work (~Sep 6, measured). The
half-life's advantage is entirely on the inflow side: a play this
fortnight counts roughly double a month-old one, so a rotation's fresh
maps displace idle incumbents after days of normal crawling rather than
weeks of raw-count catch-up. Sensitivity, to close the tuning door:
even a 7-day half-life does not seat Summit on the frozen 07-22
snapshot (15 plays is 15 plays), so no knob value flatters deploy day
and 14 stands as agreed rather than tuned to the outcome.

Consequences for the other caller: the walk-forward backtest replays
the serving path, so any FUTURE backtest regeneration inherits the rule
at historical timestamps (where it also tracks past rotations more
faithfully). The published backtest artifact predates the change and
does not move until deliberately re-run — run-once stays run-once.
Escape hatch: `half_life_days` of None or <= 0 restores raw counts
(used for the old-rule column in the inspection script and pinned by
tests). Ties break alphabetically after weight, deterministically.
Option C from the investigation (derive the pool from tier-1/2 events
only, reacting in days) remains the principled refinement if pool
latency ever matters again.

## 37. Metric presentation: accuracy first, judged independently, and a framed backtest (2026-07-26 session)

Three owner-directed presentation changes, all display-only — no number
on any page moved, and every figure keeps coming from its API payload.

**Ordering.** Accuracy ("correct picks") now leads every metric display
— live scoreboard, hero, model tab, backtest — with log loss and Brier
following as the stricter measure of how confident each call should
have been. The rule is applied uniformly precisely so the ordering
cannot be read as leading with whichever metric flatters a given table:
on the live scoreboard accuracy-first currently favours the model, on
the backtest it currently favours Elo, and both get the identical
layout. Accuracy renders as a percentage in metric rows now (68.8%,
not 0.6875) — the plain-language read was the point.

**Independent winner marking.** Every green marker routes through one
helper (`frontend/src/compare.js: metricLead`), direction-aware and
judged per metric: accuracy gets its own comparison everywhere, instead
of only log loss carrying a marker in the per-tier tables. When
accuracy and log loss disagree in a row — which genuinely happens —
both markers stand; no single verdict is forced, because the
disagreement is a real signal (a side can pick more winners while
pricing them worse). Two latent display bugs died in the move: the old
Metric row marked ELO the winner on an exact tie (`model < elo` is
false on a tie, and isotonic step outputs make exact ties possible in
small slices), and win direction was sniffed from the label string,
which the relabel to "correct picks" would have silently broken. Ties
and missing values now mark neither side, matching §35's tie handling.

**Backtest framing.** /backtest now opens with the framing paragraph:
this is the model's toughest exam on purpose — full history, worst
stretch included (the early data-starved era and the since-fixed
calibration episode), nothing trimmed; Elo wins most of it; kept
strictly separate from the live scoreboard so neither record borrows
the other's best window. The sentence about the live record ("currently
ahead", today) is NOT typed in: `liveStanding` derives it from the live
/api/scoreboard payload at render time with four honest states — ahead,
behind, split, or neutral when nothing is scored yet — so if the live
record turns, the backtest page says so in the same breath. Same
principle as §35: sentences flip with the data, never with the author's
mood.

## 38. The landing page, the copy diet, and the raised board (2026-07-26 session)

Four owner-directed changes, visual and copy only. No number moved and
no endpoint changed; the two deliberate additions are noted below.

**The homepage is now a landing page.** "/" no longer redirects to
/upcoming. It renders the wordmark large over the site's own
probability bar (the teal/ember split with the coin-flip notch at 50%,
the one motif the whole design runs on), a one-line tagline, five
doors (upcoming, scoreboard, model, market picks, backtest), a
three-sentence what-this-is that keeps the honesty line (Elo still
wins most of the backtest), and the live next-up strip. The old
full-bleed hero is retired; interior pages get a small wordmark
linking home, above the tab bar. Where the hero's information went,
item by item: its intro paragraph became the landing copy, tightened;
its honesty paragraph survives in the landing copy, the scoreboard
summary, the backtest intro, and the model tab; its recent-window
stat block duplicated the model tab's fuller table and is gone as a
block, not as information; the next-up strip moved to the landing.

**Market picks became directly reachable.** The landing needed a
market-picks door, so /markets is a real route and a fifth tab,
rendering the same MarketPicks component the scoreboard embeds. The
panel stays on the scoreboard: one component, two mounts, zero
divergence possible. The component gained a `standalone` prop so the
route shows loading and unreachable states where the embedded panel
correctly stays silent.

**The board got raised, not replaced.** The backdrop was designed
(patch 0037: contour rings from two poles over graph dots) but tuned
so faint it read as one flat colour. The rework keeps the exact motif
and gives it presence: ring alphas up roughly 60%, two soft glow
poles at the same anchors the rings emanate from, background fixed
for depth. Middle ground on purpose: visible atmosphere that never
competes with content.

**Model tab grouping.** The recent-test-window panel now reads as
three plates: Series (the published grain), Maps, and By event tier.
Each title row carries the context the old row labels repeated, so
labels shrink to correct picks / log loss / brier and the reader
scans three short blocks instead of one flat list of alternating
green numbers.

**The copy diet.** Every rendered sentence on the site was rewritten
shorter: plain, direct, student register, no hedging, no filler
transitions, and zero em dashes in rendered text or frontend source
(comments included, so the sweep is checkable in one command:
`grep -rn "—" frontend/src frontend/index.html` with the real
character returns nothing). Served backend text was checked too: its
dashes live only in code comments and docstrings, never in anything
sent to a client. Meaning was preserved everywhere. In particular
"Not betting advice", the freeze rule, the low-history rule, the
simulated badge, and every honesty statement survive, just shorter.

## 39. The visual redesign handoff: applied on review, not on trust (2026-07-28 session)

The redesign arrived as three drop-in files with a claim of no
dependency, backend, route, or data-flow changes. The claim was
checked, not assumed. Imports, derived-copy helpers
(`summarizeBacktestTiers`, `metricLead`, `liveStanding`), the
per-metric winner marking, the low-history flags, and the derived
backtest and scoreboard sentences all match the current tree, so the
handoff was cut from the post-49 file. Three regressions were still
found and fixed before anything was committed; they are LOG entry 43.
The dependency claim held: `package.json` untouched, cold `npm ci`
clean.

Judgment calls made while integrating:

- **The backtest summary keeps its integrity sentence.** The handoff's
  copy diet kept the derived "Elo wins X of N tiers" line but dropped
  the clause saying nothing is trimmed to flatter the model. That
  clause is the point of the page, so it returns in compact form. The
  full-history-vs-recent framing survives in both places it lived:
  the scoreboard summary panel and the backtest tab intro, each with
  the derived live-standing clause, none of it hand-typed.
- **Fonts stay on the host the CSP already permits.** The swap
  (Rajdhani/Inter to Space Grotesk/IBM Plex) changes families, not
  hosts, so the security-pass CSP needs no edit. Self-hosting the
  woff2 files remains the right move if third-party requests should
  ever go to zero; deferred because it adds binary weight to the repo
  for no current requirement.
- **Theme verification scope, stated plainly.** The persistence
  contract is proven by unit tests against the storage API surface
  (get, set, junk, throwing, absent) plus a clean production build.
  It was not exercised in a running browser here. A ten-second manual
  check after deploy closes that gap: toggle, reload, confirm the
  choice sticks, once more in a private window.

## 40. The public payload serves the record, and only the record (2026-07-28 session)

Decision: /api/upcoming publishes the frozen ledger values, drops
anything the ledger does not hold, and keeps the fresh model's number
out of the payload entirely. The alternative, publishing both values
labeled, was rejected: two probabilities for one match on a public page
invites exactly the confusion the freeze rule exists to prevent, and
the current view is recoverable any time by running the predictor.
Display metadata (start time, names, event) follows the live listing,
matching §15's rule that names and times are metadata while the call is
the record. Per-map leans are display-only and never in the ledger, so
they freeze in practice by carry-forward of the first published values;
a wiped processed dir rebuilds them once with the then-current engine,
which is stated here rather than hidden. BUNDLE_BEHAVIOR_REV is not
bumped: publishing changed, model behavior did not, and a forced
retrain would change nothing about this fix.

## 41. Refresh cadence: 30 minutes, retrain triggers untouched (2026-07-28 session)

The 6-hour interval was a conservative default, not a constraint. Per
cycle the crawler touches the upcoming pages and one results listing
(3 to 6 requests, 15-minute TTL cache) plus new match pages fetched
once ever; at 30 minutes that adds roughly 150 to 300 requests per day,
serialized at the 1.1 s floor, a few minutes of total crawl time daily,
inside the politeness rules by a wide margin. The scheduler is
run-then-sleep, so cycles cannot overlap at any interval. Grading
latency drops from up to 6 h to up to 30 min, and the never-frozen
window (Entry 44) shrinks from "listed under 6 h out" to "under 30
min". Retraining is unchanged on purpose: the 7-day and 100-new-match
triggers are evaluated per cycle and fire at the same data-driven rate,
and cadence is not model behavior, so BUNDLE_BEHAVIOR_REV stays put.

## 42. Odds capture splits homes: Cloudbet on the server, Pinnacle on the Mac (2026-07-28 session)

The probes settled it: class ii misses (laptop asleep while a match
was listed and started) were a structural limit of running ALL capture
on the Mac. Cloudbet is plain REST, so its leg and the markets build
move into the refresh cycle; Pinnacle needs a real browser and stays on
the Mac, pushing its captures through a new /api/ingest/odds.

Judgment calls, on record before first server capture:

- **The ingest boundary is relaxed by exactly one append-only
  surface.** The hardening pass said ingest writes derived views only.
  /api/ingest/odds appends schema-validated OddsCapture records, deduped
  by full record identity, never truncating, never touching the ledger.
  A stolen token can add odds rows (display and EV inputs) and nothing
  else. Stated as the new wall, not hidden behind the old comment.
- **Two cadences, one scheduler thread.** Full cycle every 30 min; a
  light odds+markets subprocess every 10 min between. Arithmetic: the
  close window is 20 min, so a 30-min-only cadence misses roughly one
  close in three outright. 10 min matches the proven Mac cron rate; 144
  Cloudbet passes per day is what the Mac already did.
- **aliases.json stays a manually synced file.** Making it ingestible
  would let a stolen token redirect odds onto wrong matches, a worse
  failure than the chore of copying a rarely-changing file to /data
  when suggest_aliases adds entries. Revisit only if alias churn grows.
- **Seeding.** The server log starts empty; the Mac's full history is
  pushed once through the same deduping ingest (--push-log), so entry
  captures keep their true earliest timestamps and re-runs are no-ops.

## 43. Best-line selection, pre-registered before the first best-line pick grades (2026-07-28 session)

When more than one book holds a freeze capture for a match, the pick's
side is chosen on each side's best available entry price and EV is
computed at that price, with the providing book named on the pick. All
captured prices stay in the append-only log; nothing is averaged into
EV. Rules fixed now, before any graded pick exists under this policy:

1. **CLV is same-book.** Entry and close come from the entry book only.
   A missing close at that book means no CLV, even if another book has
   one; cross-book CLV would compare two different pricing processes.
2. **The gate counts matches, not book-rows.** n>=100 graded
   market-covered picks means picks, one per (match, market, line),
   however many books priced it. More books add volume by covering more
   matches, never by multiplying rows.
3. **Best-of-books EV is upward biased and says so.** A max over noisy
   prices flatters EV, more so as books are added. The UI ships the
   cross-book consensus Shin de-vig beside every pick (median across
   entry captures; with two books, the midpoint) and a standing footnote
   under both market tables. Price ties break by ODDS_BOOK_PRIORITY.

With a single book the pick reduces exactly to the old headline
behavior, pinned by test.

## 44. The explanatory layer: one page of record, tooltips that defer to it (2026-07-28 session, second pass)

A /how page now explains the whole system in plain language, linked
from the homepage and the footer. Judgment calls: static copy states
rules, never results, so nothing on it can go stale when the numbers
move; the preregistered EV threshold is described as "a preregistered
number" with the actual value living on the markets page where it is
served from data. The old "about" toggles on Scoreboard, Backtest, and
Markets are replaced by small info icons on all five section titles:
hover or focus opens, click pins for touch, Escape or an outside click
closes, and every tooltip is one to two sentences that link to /how
for the full story. The long about-paragraphs were not deleted, they
were rewritten into the page. The footer keeps the standing "not
betting advice" line and gains the /how link, which also gives the
honest backtest framing a permanent home that no homepage redesign can
strip by accident.

## 45. Chronological structure is a display policy, decided once (2026-07-29 session)

All match lists now sort by scheduled start with day separators, grouped
at the VIEWER'S local midnights, the same zone rule as every rendered
time (LOG entry 29). Direction is by list kind, not one global sign:
schedules read soonest first (Upcoming, Scoreboard pending), records
read newest first (Scoreboard graded, Markets). On Markets, descending
start time naturally floats not-yet-started picks above the graded
record, since their start times are the newest in the table. Sorting is
entirely client-side: the API payloads and their order are untouched,
per the instruction that nothing underneath changes. Aggregate panels
(Backtest tiers, the model's test-window panel) and fixed-size widgets
(recent form) have no open time axis and are deliberately excluded.

## 46. Skip-and-count beats crash and beats silence (2026-07-30 session)

Policy set while fixing entry 46: analysis primitives stay strict
(devig raises on prices at or below 1.0; that is a correctness
property), and the pipeline caller is the layer that decides what a bad
record means. Decisions: an unpriceable entry removes that source from
that pick; an unpriceable close is treated as no close (a placeholder
is not a closing price, and grading CLV against it would be fiction); a
group with no priceable source drops. Every one of these increments
"skipped.n_unpriceable" in markets.json, the refresh log, and a
visible Markets note when nonzero, because silently narrowing the data
is exactly what this project does not do. The odds log itself is never
edited: append-only is the rule, the poison record stays in the record.
Push semantics: --push sends the trailing ODDS_PUSH_WINDOW_H=24 hours
of local records every fire, not just the run's appends; idempotent by
server-side dedupe, so transient push failures stop being permanent
record loss on the server.

## 47. Priceability is defined once, and unknown failures degrade to counted skips (2026-07-30 session)

A capture record is priceable when both decimal prices are finite and
above 1.0; the predicate lives in one place and runs before grouping,
so every consumer sees only real prices and the entry price is the
first priceable freeze rather than a placeholder. Records that were
never part of the build (unlinked, or for matches outside the ledger
join) are filtered without counting, so the counter measures actual
data loss, not noise. Above that sits a last-resort rule: a pick group
that fails for any unforeseen reason is skipped with a logged
traceback and a visible n_group_errors count, because one bad group
taking down every other match's picks is a worse failure than any
single bug. Both layers refuse silence: counters ride in markets.json,
the refresh log line, and the Markets panel note. And one process
lesson on record: "deployed" is verified with a code marker
(python3 -c "import vpredict.odds.markets as m, inspect;
print('n_group_errors' in inspect.getsource(m))"), not assumed from a
local test run.

## 48. Date banners read like a schedule, not a footnote (2026-07-30 session)

The §45 separators shipped as hairline mono labels and were easy to
scan past. Restyled after owner direction to the schedule-page pattern
(the lolesports reference): full-width banner bands between days,
weekday and month spelled out, uppercase display type, and the current
day highlighted in the accent color with a left bar. The pattern is
generic schedule furniture; nothing is copied from anyone's assets or
code. Ordering policy, zone rule, and the client-side-only constraint
from §45 are unchanged.
