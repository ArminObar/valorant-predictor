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
