# LOG

Engineering log, newest at the bottom. Bugs are written up as
symptom → cause → fix → why earlier testing missed it → lesson.

---

## 1. 2026-07-23 — Recon: community scrapers are NOT stale

GitHub's API was rate-limited from the build sandbox's shared IP, so staleness
evidence came from shallow clones instead: axsddlr/vlrggapi (MIT) and
akhilnarang/vlrgg-scraper both had commits dated 2026-07-18 — five days before
this build — and Vanshbordia/vlrdevapi 2026-07-09. sanjaybaskaran01/StatsVLR
failed to clone with an authentication prompt, meaning the repository is no
longer publicly reachable. Net: the build brief's premise ("several have gone
stale") holds for exactly one of four; recorded in ASSUMPTIONS §1 rather than
quietly adopted. vlrgg-scraper has no license file, so nothing from it was
copied; its real-page fixture was used for local validation only.

## 2. 2026-07-23 — Scaffold mishap: brace expansion

`mkdir -p a/{b,c}` ran under a shell without brace expansion and created a
literal `{src` directory. Removed; directories recreated with explicit paths.
Trivial, logged because the junk directory would otherwise have shipped.

## 3. 2026-07-23 — Listing parser validated against real vlr.gg HTML

Before any live traffic existed, the results-listing parser was run against a
genuine 135 KB vlr.gg results-page snapshot found in a cloned repo's test
fixtures (used locally, not redistributed): 50 of 50 match cards parsed with
correct ids, team names, events, and statuses. This validated the listing
selectors months of layout drift could have broken — but note entry 9 for what
snapshot validation of *one page type* cannot catch.

## 4. 2026-07-23 — Session interruption; state reconciled from disk

The build session was cut off mid-batch. On resumption the working tree was
audited file-by-file: four files believed unwritten (leakage tests, feature
builder, baselines, evaluate script) were in fact complete on disk. Lesson:
after an interrupted run, verify the filesystem before regenerating anything —
the alternative was duplicating or clobbering finished work.

## 5. 2026-07-23 — Bug: Elo replay order (non-commutativity)

**Symptom (latent):** the build-time leakage spot-check would have raised
false "LEAKAGE" errors on real schedules mixing Bo1/Bo3/Bo5 with dense timing.
**Cause:** Elo updates do not commute. The live path applies updates in
estimated-finish order (event queue); the spot-check's independent replay
applied the *same set* of updates in start order. Same set, different order,
different ratings — so an honest recomputation could mismatch an honest
original, indicting the leakage guard itself.
**Fix:** the replay now sorts eligible matches by (estimated finish, start,
match id), exactly mirroring the event queue's heap order.
**Why tests missed it:** the synthetic fixture used uniform Bo3 durations and
weekly spacing, under which the two orders coincide.
**Lesson:** when a checker re-derives a stateful computation, the *order
contract* is part of the spec, not an implementation detail. The contract is
now written into both functions' docstrings and exercised by schedules with
overlapping matches.

## 6. 2026-07-23 — Bug: unstable sort under tied timestamps

Maps of one match share an estimated finish time; pandas' default quicksort
may permute such ties differently for the full dataset vs a truncated one.
Aggregations are order-invariant, but the roster "core" derives from the last
five map rows, so tie reordering could flip which rows are "last five" —
nondeterminism between a build and its own verification. Fix: stable sort in
the as-of engine. One-word change; whole class of flaky-verification bugs
removed.

## 7. 2026-07-23 — Bug round-trip: LightGBM 4.7 eval API

The evaluate script used `eval_X=`/`eval_y=` with a TypeError fallback to
`eval_set=`. During review this looked like an invented API and was "fixed" to
plain `eval_set=` — whereupon the smoke run emitted
`LGBMDeprecationWarning: 'eval_set' is deprecated, use 'eval_X' and 'eval_y'`.
LightGBM 4.7 really did migrate. Original structure restored (new API first,
TypeError fallback for older versions). Lesson: check the installed version's
actual behavior before "correcting" working code; the deprecation warning was
the ground truth the review lacked.

## 8. 2026-07-23 — Synthetic end-to-end smoke run (watermarked)

620 seeded-simulator matches (609 usable, 1466 map rows) through the full
pipeline: gate correctly opened LR + LightGBM, leakage spot-check passed on a
schedule with genuinely overlapping matches, and the test window reported
LR(C=0.03)+Platt at 0.6013 log loss vs tuned Elo (K=16) at 0.5922. Elo winning
narrowly is the *expected* honest outcome — the simulator is itself a
latent-strength world, so Elo is close to its true model — and it demonstrated
the report will happily print an unflattering comparison. Every output carried
the SYNTHETIC watermark. These numbers say nothing about real Valorant and
appear nowhere in project documentation as results.

## 9. 2026-07-23 — Field bug: map names concatenated with veto labels

**Found by:** first live scrape (project owner's machine), not by any test.
**Symptom:** stored map names like "LotusPICK", "AscentPICK", "BreezePICK".
Decider maps carry no veto label, so the same map is stored under two keys —
per-map history silently fragments, roughly halving per-map sample sizes and
degrading per-map Elo, map-filtered snapshots, and map dummies.
**Cause:** vlr.gg nests the label inside the name span:
`<span>Lotus<span class="picked">PICK</span></span>`. `get_text()` on the name
span concatenates the child, and the guard `startswith("pick")` inspected the
wrong end of "LotusPICK". The reference implementation this parser's selectors
were grounded in (vlrggapi, MIT) contains the *identical* flaw — grounding in
community code transferred a community bug.
**Fix:** extract the span's direct text only (child tags excluded), skip
label/duration spans outright, and defensively strip an uppercase
PICK/BAN/DECIDER suffix on every path (uppercase-only, so no real map name can
be mangled). Regression tests in `tests/test_parsers.py` drive the full match-
page parser over the nested-label structure and pin pick-vs-decider key unity.
**Why offline validation missed it:** the real snapshot on hand was a
*listing* page; map headers only exist on match pages, which were validated
structurally, from selector descriptions — descriptions that omitted the
nesting.
**Remediation (map names are baked into stored records):** stop any crawl
running old code; then
`rm data/raw/matches.jsonl` (and `data/processed/features.joblib` if present);
then `python -m vpredict.scraping.crawl --backfill --since-days 730
--max-pages 400`. All previously fetched match pages re-parse from the disk
cache for free; only listing pages (15-min TTL) and genuinely new match pages
touch the network.

## 10. 2026-07-23 — Field bug: top-up early-exit blocks historical backfill

**Found by:** the same live session.
**Symptom:** after an initial crawl, re-running with a larger `max_pages`
returns "stored: 0" instantly instead of going deeper.
**Cause:** the crawler treated "every match on this listing page is already
known" as "caught up" unconditionally. Correct for topping up with new
results; fatal for deepening history, because the walk toward older pages must
pass *through* pages of known matches.
**Fix:** the two intents are now separate code paths with opposite stop rules.
`crawl_results` (top-up) keeps the early exit — it is the cheap scheduled-job
path and now stops even on an all-known page 1. `backfill_results` walks
through known pages; known matches are never refetched — their *stored* start
times drive the `since` stop rule — so a backfill's network cost is exactly
the unknown match pages plus listing pages. A CLI was added
(`python -m vpredict.scraping.crawl [--backfill] [--since-days N]
[--max-pages N] [--tier-b]`) so both paths are invocable without writing code.
Offline tests in `tests/test_crawl.py` pin both behaviors and the
stored-timestamp stop rule against a canned fetcher.

## 11. 2026-07-23 — First live-scrape validation (external)

Reported from the field after the fixes above were identified: 150 matches /
810 map-team rows with zero missing side splits, zero missing first-kill
counts, and first-kill counts internally consistent per round. This is the
first real-data confirmation of the Tier A parsing path end to end. Full
test suite after both fixes: 18/18 passing. Next milestone (by explicit
decision): `scripts/evaluate.py` on the re-parsed real store, reported
separately from the synthetic run; training-bundle persistence, ledger/API,
frontend, and deployment are all held until that number exists.

## 12. 2026-07-23 — Staged-backfill hardening: interrupt safety made real

A full 2-year backfill is ~20,000 match pages ≈ 6+ hours at the 1.1 s floor,
so it WILL be interrupted. Audit of what was already true: the HTML cache
persists per fetch (no network work is ever lost) and the store write is
tmp-then-atomic-replace (no interrupt can corrupt it). What was NOT true:
parsed matches were held in memory and upserted once at the end, so a Ctrl-C
at hour five discarded five hours of parses (recoverable from cache, but at a
full re-parse cost) and a 20k-match batch would have held the whole dataset in
RAM. Fix: the crawler now flushes to the store every 250 parsed matches
(`config.CRAWL_FLUSH_MATCHES`) and, via try/finally, flushes everything parsed
on ANY exit including KeyboardInterrupt — so an interrupt loses at most the
single in-flight match, and a SIGKILL/power loss at most one flush window.
Resume is a plain re-run of the same command: known matches are skipped using
stored timestamps, so resume overhead is just the listing-page walk back to
the frontier (~1.1 s per page). Pinned by
`tests/test_crawl.py::test_interrupt_persists_progress_and_resume_completes`.

## 13 — 2026-07-23 · Extended K grid; match-level results; Elo wins at series grain
Extended the Elo K grid to 128 per review: K=50 is an interior optimum
(val 0.6591; 64 gives 0.6598, degrading beyond), so the earlier grid-edge
concern is resolved and the map-level comparison stands un-flattered.
Built series-level evaluation: veto notes parsed to recover unplayed decider
maps (59/136 test series veto-completed, 16 mean-prob fallback, 61 full),
exact best-of DP over per-map probabilities. Finding, reported as-is per the
spec's "a tie with Elo is a legitimate finding" rule: at MATCH grain the
tuned Elo baseline beats the model (LL 0.6411 vs 0.6615, acc 65.4% vs 62.5%).
Mechanism diagnosed, not guessed: map-effective Elo is WORSE than overall Elo
at map grain (0.6849 vs 0.6820), so Elo's series edge is not map knowledge —
it is probability spread. The C=0.03 + Platt model is better calibrated per
map but more compressed toward 0.5, and DP aggregation rewards spread.
Actionable later (discrimination-preserving regularization), deliberately NOT
tuned now — serving ships first per the project owner's ordering.

## 14 — 2026-07-23 · Tier breakdown; tier-1-restricted training hurts
Keyword tier classifier over observed 2026 event strings (tier1 VCT /
tier2 Challengers+Evolution Series / Game Changers / other), mapping counts
printed in the report for auditability. The validation window (Jun 23–Jul 5)
contains ZERO tier-1 matches — a real VCT calendar gap between stages — so
the restriction experiment selects/calibrates on the full val window for
both arms (which also cleanly isolates the training-set effect). Result:
training on tier-1 rows only (131 matches) is worse everywhere, including on
tier-1 test rows (LL 0.6989 vs 0.6836; acc 48.9% vs 53.3%). Cross-tier data
helps tier-1 prediction at this sample size; restriction is rejected.

## 15 — 2026-07-23 · Serving layer, scoreboard, frontend, deploy
Ledger (SQLite): predictions refused inside 5 min of start; the FIRST
prediction per match is frozen — later calls, even from newer bundles, are
ignored; grading fills results idempotently; Elo's probability is stored
beside the model's so the public comparison is fixed at prediction time.
Prediction path reuses build.py's _assemble_row and was verified byte-exact
against training rows on real matches (worst |Δ| = 0.0 across 6 spot checks);
a drift guard raises if serving-time features go missing rather than
zero-filling silently. Pre-veto series probability: uniform-weight mean over
the current pool (top-7 by 60-day frequency) through the exact DP —
pick/ban-informed weights are documented future work. Fixed a path split
where the ledger default and the API disagreed on the SQLite location.
Deploy: Render disks attach to a single service, so the refresh cycle runs
in-process behind VPREDICT_REFRESH=1 instead of a cron service that could
never see the disk; render.yaml documents this and the Railway equivalent.
Frontend (Vite/React, Rajdhani+Inter, no Riot trade dress) builds clean and
is served by the API. e2e verified in an isolated env: train on the real
1250-match store -> two upcoming fixtures -> 2 frozen ledger rows -> API
serves upcoming + scoreboard + static UI. 29 tests green.

## 16 — 2026-07-23 · Collinearity check (spec non-negotiable) + docs milestone
Implemented the outstanding collinearity requirement as evaluate.py §5: VIF
via auxiliary regressions plus top pairwise correlations, training rows,
continuous/context features. Findings put hard numbers under the coefficient
investigation from entry 15: round_share_diff VIF 115.2, side efficiencies
~47, elo_diff/map_elo_diff ~39 with r=+0.99 between them, while the
independent features (fk, pistol, rest, roster, context) all sit near 1.
The report now states explicitly that coefficients are not marginal effects.
Headline tables verified unchanged by the addition. Also removed dead lines
in predict.py's column selection and pinned the Dockerfile COPY now that
README.md exists. Wrote the three remaining spec docs — README.md (headline
results + single-script reproducibility guarantee), WALKTHROUGH.md (the
methodology for a reader new to rigorous evaluation, with the compression
trade-off and the tier experiment as case studies), MODEL_CARD.md (live
bundle card with limitations stated plainly, including the series-grain gap
and uniform pool weights). Suite at 32 tests.

## 17 — 2026-07-23 · Two-year dataset: gap closes; C sweep flat; stability finding
The deep crawl landed: 6,796 matches (2024-07-24 → 2026-07-22; the sender's
"5,546" was the increment over the earlier 1,250, which is fully contained).
5,489 usable / 13,337 map rows; split 3,842/823/824. Ran the identical
protocol: validation selection now picks LightGBM (121 trees) + isotonic
(val finally large enough for isotonic), tuned Elo K drops 50 → 24 as
predicted once cold-start pressure vanished, and the model beats Elo at
BOTH grains — map 0.6671 vs 0.6704, series 0.6500 vs 0.6555 LL (64.3% vs
61.7% acc, 824 series; provenance 331 full / 291 veto / 202 fallback).
ECE 0.0247.
The authorized compression fix (sweep LR C, recalibrate, select by
validation SERIES log loss) was implemented as evaluate.py §6 and the
answer is that C stopped mattering: test series LL is 0.6375 for every C in
[0.03, 3.0] — compression was a small-data artifact. The sweep surfaced a
better finding: plain LR beats the selected LightGBM on the untouched test
window at both grains while losing validation selection. Deliberately NOT
switching (test-set selection); shipped bundle stays the validation choice,
the disagreement is documented in the model card, and the frozen ledger
arbitrates. Protocol upgrade queued: rolling-origin validation.
Tier-1-restriction re-test at 752 t1 training matches: within noise
(0.6771 vs 0.6790 on t1 test LL, accuracy still worse); conclusion updated
from "hurts" to "no demonstrated benefit"; all-tier training stays.
Collinearity at scale: round_share 97.7, side efficiencies ~40, elo pair
~12.7 (r=+0.96) — structure unchanged, elo less entangled with two years of
separation.
Operational: full runs at this scale exceed the interactive execution
window (feature build 50 s at 0.69 GB peak RSS; 12 default leakage
spot-checks ≈ 13 s each; two LightGBM selections), so evaluate.py gained
--features-cache and --spot-checks; identical numbers either way, and the
runtime leakage spot-checks were exercised separately at full scale (pass).
Deploy implication recorded: 512 MB instances cannot run the
retrain/predict cycle (~0.7 GB peak); serving alone is light.

## 18 — 2026-07-23 — unanchored `data/` in .gitignore excluded package source

*(Numbering assumes the file currently ends at entry 10, per the references
in ASSUMPTIONS §1–3; renumber if it has drifted.)*

**Symptom.** First Render deploy built successfully, then crashed at
runtime with `ModuleNotFoundError: No module named 'vpredict.data'`.

**Cause.** `.gitignore` contained the unanchored pattern `data/`, which git
matches at any depth. It excluded the intended repo-root `data/` directory
*and* `src/vpredict/data/` (`schema.py`, `store.py`) — so the committed
tree, which is what the deploy builds from, was missing part of the
package. The local working tree still had the files, so everything worked
locally.

**Fix.** Anchored the pattern to `/data/` so only the repo-root data
directory is ignored; committed the previously-excluded
`src/vpredict/data/` files.

**Why testing missed it.** The entire test suite runs against the local
working tree, where the files exist. Nothing ever exercised the *committed*
tree installed as a package. Remediation shared with entry 19:
`scripts/smoke_container.sh` now builds the image from `git archive HEAD`
(deploy-shaped context) and imports every `vpredict.*` submodule inside the
container, so a file missing from git fails the smoke test locally instead
of the deploy.

## 19 — 2026-07-23 — frontend mount silently skipped in the container; site served 404 at /

**Symptom.** After fixing entry 18 the deploy came up and `/api/*` worked,
but `/` returned "Not Found". No error or warning anywhere in the logs.

**Cause.** `api.py` resolved the frontend as
`Path(__file__).resolve().parents[3] / "frontend" / "dist"`. In a source
checkout that lands on the repo root; in the container the package is
pip-installed into site-packages, so `parents[3]` is
`/usr/local/lib/python3.12/` while the Dockerfile puts the build at
`/app/frontend/dist`. The guard `if dist.exists():` then evaluated false
and skipped the static mount *silently* — a missing frontend was treated as
a normal configuration rather than a fault worth logging.

**Fix.** New `src/vpredict/frontend_locate.py`: resolution order is the
`VPREDICT_FRONTEND_DIR` env var, then `/app/frontend/dist`, then
`<ancestor>/frontend/dist` walking up from the module (reproduces the old
dev behaviour without hardcoding `parents[N]`), then `<cwd>/frontend/dist`.
A candidate counts only if it contains `index.html`, so an empty dist is
treated as absent. When nothing matches it logs a WARNING listing every
path tried; when the env var is set but invalid it warns and falls through
to the candidates (serving the site beats failing on a typo, but the
misconfiguration stays visible). `api.py` now calls
`locate_frontend_dist()` and mounts `if dist is not None`.

**Why testing missed it.** Same blind spot as entry 18 from a different
angle: tests ran where the relative path resolves and the files exist;
nothing verified that the *installed* package in the *container* actually
serves its frontend. The `dist.exists()` guard converted a deployment fault
into silence. Remediation: the same `scripts/smoke_container.sh` boots the
built container and asserts `GET /api/health` returns 200 and `GET /`
returns 200 with an HTML body.

## 20 — 2026-07-23 — production: LightGBM bundle unpickle dies on missing libgomp.so.1

**Symptom.** First Render deploy: container built, static frontend served,
but the API died loading the model bundle — `OSError: libgomp.so.1: cannot
open shared object file` raised from joblib unpickling the LightGBM booster.

**Cause.** The runtime stage of the Dockerfile (`python:3.12-slim`) ships no
GNU OpenMP runtime; LightGBM's native library links against it. The import
cost is deferred — nothing touches `lightgbm` until the bundle is first
unpickled — so the container "works" right up to the moment it serves.

**Fix.** Install `libgomp1` (and `curl`, for the healthcheck) in the runtime
stage. Redeployed green.

**Why testing missed it.** Same blind spot as entries 18–19: nothing
exercises the committed tree, installed as a package, inside the runtime
container. The dev Mac has Homebrew's `libomp`, so the dependency is
invisible locally. Remediation is `smoke_container.sh` (build the image, run
a `--no-crawl` cycle and hit `/api/model` inside it) — pending a Docker
install on the Mac.

## 21 — 2026-07-24 — production: refresh cycle called crawl_results() without its required `since`

**Symptom.** Every scheduled cycle logged `results crawl failed:
crawl_results() missing 1 required positional argument: 'since'`. The store
never topped up; the site sat frozen at its seed data. The cycle otherwise
"succeeded" — fault isolation converted the TypeError into a log line.

**Cause.** Call-site drift. Entry 10 split the crawler into top-up/backfill
modes and made `since` a required positional on both; the call in
`src/vpredict/serving/refresh.py` kept the old zero-argument form. No test
ever executed `refresh_cycle` — crawler and ledger were each unit-tested,
and the integration seam between them ran for the first time in production.

**Fix.** `topup_since()` in serving/refresh.py: anchor the crawl's lower
bound to the newest *completed* stored match minus
`config.TOPUP_OVERLAP_DAYS` (3 d — listings are newest-first but entries can
appear slightly out of order, and store-anchoring self-heals an outage of
any length); with an empty store, bound the first crawl to
`config.TOPUP_BOOTSTRAP_DAYS` (30 d). Both constants are judgment calls,
untuned (ASSUMPTIONS §11). The cycle now records the `since` it used in its
output.

**Why testing missed it.** The seam itself was untested. The regression test
(`tests/test_refresh_contract.py`) runs the real `refresh_cycle` with heavy
steps stubbed, records the crawler call, and binds it against the *real*
`crawl_results` signature — verified to fail on the pre-fix code with the
production message verbatim, and to catch the next signature drift the same
way.

## 22 — 2026-07-24 — production: in-process refresh OOM-killed at 512 MB (exit 137)

**Symptom.** With `VPREDICT_REFRESH=1` on the Render Starter instance
(512 MB), the worker died exit 137 (128 + SIGKILL: the cgroup OOM killer)
mid-cycle. Mitigation in place: `VPREDICT_REFRESH=0` and manual updates
(run predictions locally, gzip the ledger into `seed/`, push, re-download in
the Render shell).

**Cause — measured, not guessed.** With the measurement wiring (edits C–F)
applied, `scripts/memharness.py` on a Linux/py3.12 sandbox attributes the
footprint per phase. Full store (6,796 matches), `refresh.py --no-crawl`,
forced retrain: peak 1,221 MB (wait4, child process tree). Attribution:
`grade` climbs 79→565 MB parsing the whole store into pydantic `Match`
objects and keeps the list alive for the predict step; `train/load_store`
then parses the entire store a *second* time (+~550 MB coexisting);
`build_features` adds only ~90 MB over 240 s; model fitting is negligible.
Roughly 85–90 % of the peak is the match store materialized twice — the ML
is nearly free. A four-point growth curve (store limits 1,700 / 3,400 /
5,100 / 6,796) is linear: peak ≈ 155 MB + 156 MB per 1,000 matches
(residuals < 7 MB), i.e. on that environment the untrimmed cycle outgrew
512 MB around ~2,300 matches. Absolute numbers are environment-specific
(the dev Mac measured ~0.69 GB for the same cycle: different allocator,
Python, and library builds); the *attribution shape* is the robust finding.
Reproduce: `python scripts/memharness.py run --force-retrain -- python
scripts/refresh.py --no-crawl`.

**Fix.** Not yet applied — trim design proposed and awaiting sign-off:
stream store consumption (an `iter_matches` generator; `grade` consuming
one match at a time; the maps frame built incrementally without retaining
the object graph) so no full materialization exists anywhere in the cycle,
plus running refresh as a subprocess so memory returns to the OS between
cycles. Post-trim, rerun the growth curve for the real "when does it
outgrow 512 MB again" answer.

**Why testing missed it.** No test enforces a memory budget, and dev
machines with ≥16 GB never surface a 512 MB ceiling. The measurement wiring
only landed after the incident. The budget has to be made artificial to
fail early: `smoke_container.sh` should run the cycle under
`docker run --memory=512m`.

## 23 — 2026-07-24 — memory trim: streaming store; cycle 1,221 → 296 MB, slope 156 → 18 MB per 1k matches

**What changed.** The cycle no longer materializes the store anywhere.
`store.iter_matches` streams validated records one at a time (honoring
`VPREDICT_STORE_LIMIT` with the same lean two-pass cap); `maps_frame` /
`matches_frame` consume any iterable and retain only their row dicts;
`Ledger.grade` pulls the small ungraded-id set from sqlite first and scans
the stream once; `train_and_save` builds the frame straight from the
iterator (its private full copy — the cycle's second — is gone);
`_needs_retrain` counts lines instead of loading; `upsert_matches` is now a
streaming sorted merge with memory O(batch) — the old version loaded and
rewrote the whole store on every call, so each 250-match crawl flush cost a
full-store materialization inside the crawl phase (never visible in
`--no-crawl` measurements, but it would have reintroduced the spike the
moment crawling re-enabled). Two invariants now hold: the store file is
sorted by `(start_ts, match_id)` (upsert maintains it; pass-through lines
are copied verbatim, never re-validated), and nothing in the refresh cycle
holds more than one Match at a time. The scheduler (`VPREDICT_REFRESH=1`)
spawns `python -m vpredict.serving.refresh` as a subprocess instead of
calling in-process: memory returns to the OS between cycles, and an OOM
kill now takes the child, not the API.

**Measured acceptance (sandbox Linux/py3.12, wait4 child-tree peaks;
cgroup readings discarded — shared cgroup).** Full store (6,796 matches),
forced retrain, `--no-crawl`: peak 296.3 MB against the 440 MB target
(pre-trim: 1,220.7 MB). Per phase: grade flat at 79 MB; the streaming
frame build holds ~68 MB; `build_features` remains the largest resident
(~90 MB over 238 s); model fitting negligible. Post-trim growth curve
(limits 1,700 / 3,400 / 5,100 / 6,796 → 203.6 / 230.0 / 261.9 / 296.3 MB,
residuals < 2.5 MB): peak ≈ 170.5 MB + 18.2 MB per 1,000 matches, versus
156.1 MB per 1,000 pre-trim. Extrapolated crossings — extrapolations, not
measurements: 440 MB at ≈ 14,800 matches, 512 MB at ≈ 18,700; at the
current ~65 matches/week that is 2+ years of headroom. Absolute numbers
are environment-specific; Mac/Render verification and the
`VPREDICT_REFRESH=1` flip are the owner's acceptance steps. Reproduce:
`python scripts/memharness.py run --force-retrain -- python
scripts/refresh.py --no-crawl`.

**Why the old code was shaped that way.** Loading the store into a list was
the natural first implementation and correct at 150 matches; nothing ever
re-examined it as the store grew 45×, because no test or measurement put a
budget on memory (entry 22). The eight new tests in
`tests/test_streaming_store.py` pin the merge semantics (changed counts,
collisions, a replacement whose timestamp moved must re-sort), the
never-validates-pass-through guard, streamed grading, and the `-m`
entrypoint the scheduler spawns.

## 24 — 2026-07-24 — production: model selection flipped between consecutive retrains (LightGBM ↔ LR)

**Symptom (owner-reported production logs).** Two refresh retrains ~3.5 h
apart on nearly identical data selected different architectures:
`lightgbm(best_iter=121)` at 01:06, `logistic_regression(C=1.0)` at 04:43,
validation log loss 0.6591 both times (as printed, 4 dp). The deployed
model can therefore silently change family between retrains. Frozen ledger
rows are unaffected (model_version is stamped per row), but the public
model-vs-Elo aggregate now mixes families.

**Cause.** A near-tie with no switching hysteresis: `select_model` is a
bare argmin over validation log loss, so any perturbation — a handful of
new matches shifting rows and the chronological split boundary, or
cross-environment numeric differences — flips the winner. Sandbox
experiment on the seed snapshot (features built once, both candidates fit
three times on bit-identical inputs): fully reproducible within this
machine — LGBM 0.658507 and LR(C=0.3) 0.660068 all three runs, gap
−0.0016. Within-machine training nondeterminism is therefore NOT the
confirmed mechanism here; the flip is attributable to data deltas between
the two production retrains and/or environment differences (LGBMClassifier
sets `random_state` but not `deterministic`/`n_jobs`, so thread count and
OpenMP/BLAS builds can move the fourth decimal across machines). This is
the two-year report's validation/test stability finding (entry 17,
WALKTHROUGH §7) surfacing in production, as that report predicted it could.

**Fix.** Pending owner decision; options on record: (a) champion/challenger
hysteresis — keep the incumbent unless the challenger beats its validation
log loss by a margin (e.g. one paired SE of the per-row loss difference);
(b) pin `deterministic=True` and a fixed `n_jobs` so identical data gives
identical selection per machine; (c) rolling-origin selection — k expanding
chronological folds, select on aggregate fold loss; measured cost is small
(features build once; both candidates refit in ~1–2 s here, so k=5 adds
roughly ten seconds per retrain). (c) reduces selection variance and (a)
prevents silent flips outright; they compose.

**Why testing missed it.** Selection was tested for correctness on fixed
data, never for stability: nothing asserts that a retrain with no (or few)
new matches keeps the same architecture. A regression test for (a) would
encode exactly that.

## Entry 25 — Odds capture built, offline-validated; first live run is on the Mac (2026-07-24)

The §13 pre-registration is now code: `src/vpredict/odds/` (Shin de-vig by
bisection with multiplicative always computed beside it; append-only capture
log with freeze/close state derived from the log itself; conservative
fixture linking — exact-normalised, then the alias table, else stored
UNLINKED and reported, never fuzzy), a Cloudbet Feed API client written
against the current public docs, a Pinnacle source that intercepts the JSON
the matchups page loads for itself rather than scraping its DOM, and
`scripts/capture_odds.py` for a 10-minute cron. 14 tests, all offline.

The build sandbox cannot reach either book, so two surfaces are
UNVALIDATED until the first Mac run — the same protocol that shipped the
scraper (entries 9/10, which that first run then caught two bugs in;
expect the same class here): (a) Cloudbet's actual Valorant market key —
the client discovers any two-outcome home/away market matching
winner/moneyline hints and logs every key it saw, so the first run pins the
real one; (b) Pinnacle's guest-API shapes — a zero-parse run logs loudly
and `--debug` dumps every intercepted body to disk for a one-paste fix.

## Entry 26 — Retrain-cadence bug: every production cycle retrained (2026-07-24)

**Symptom.** The item-2 steady-state measurement retrained despite a
minutes-old bundle; the cycle JSON said "1307 new matches". 1307 is not a
count of new matches — it is 6,796 total store records minus 5,489 usable
matches, a constant.

**Cause.** `save_bundle` recorded `n_matches` = USABLE matches (after the
≥3-prior-maps rule) while `_needs_retrain` compared it against
`count_matches()` = TOTAL store records. Like versus unlike, permanently
≥100 apart — so every 6-hour cycle retrained, on Render too: wasted CPU
and maximal exposure to entry 24's selection-flip surface.

**Fix.** Bundles now record `n_store_records` at train time and
`_needs_retrain` compares like with like. A pre-fix bundle (no field)
triggers exactly one labelled "retrain once", so the fleet converges
without manual bundle surgery. Verified: the next plain cycle skipped
retrain and predicted 104 upcoming.

**Why testing missed it.** The retrain decision and the save path were
each tested in isolation, with hand-built bundle dicts whose `n_matches`
happened to equal the store count. No test ever fed `_needs_retrain` a
bundle produced by the real `save_bundle` against the real store.

A second, smaller bug from the same measurement: the synthetic upcoming
fixture used `winner=None` where the schema demands `Literal["team1",
"team2", ""]`, so predict failed instantly — and the harness's fault
isolation reported it only as a 0.0 s phase in the timing table, which
nearly hid it. Measurement fixtures now use `winner=""`; the lesson (an
errored phase should be loud, not fast) is noted here rather than papered
over.

## Entry 27 — Render OOM root cause: the API unpickles the bundle on every health probe (2026-07-24)

**Symptom.** The trim passed on the Mac (329.9 MB vs the 440 budget) yet
Render OOM-killed with `VPREDICT_REFRESH=1` plus a shell-run cycle.

**Cause.** The 440 budget assumed the cycle had the box to itself; it
shares the 512 MB cgroup with the API. And the API is not small:
`_bundle_meta` unpickles the FULL bundle — importing sklearn, LightGBM,
NumPy — on every `/api/health` call, which Render's health probes hit
constantly. Measured (sandbox, uvicorn + seed bundle): 49 MB at startup,
174 MB after the first health call, stable there; 49–51 MB when no bundle
file exists. The unpickle path costs ~125 MB of permanently resident
libraries. A scheduler cycle plus the shell cycle the owner ran means
174 + 2×~300 MB — the kill was arithmetic, not bad luck.

**Measurements** (post-trim code, full 6,796-match store, 104-match
realistic upcoming; sandbox — the Mac ran ~10% above sandbox on the trim):
steady-state cycle (grade + predict 104, no retrain) 238.9 MB peak / 40 s;
retrain cycle ~302 MB peak / ~240 s, and predict's internal peak (~251 MB)
is below training's, so retrain bounds the cycle. Reproduce the API
numbers with `scripts/measure_api_rss.sh`, the cycle numbers with
`scripts/memharness.py`.

**Verdict, recorded.** On Starter, current code does not fit: 174 + ~300 +
margin > 512. Two exits, owner's choice pending: (a) Standard ($25, 2 GB)
— fits everything with ~4× headroom, zero further engineering; (b) stay on
Starter and build the meta-sidecar fix (`save_bundle` writes
`model.meta.json`; the API reads JSON and never unpickles), dropping the
API to ~55 MB and the child budget to ~407 MB, which fits even the retrain
cycle with real headroom. The sidecar is worth building eventually on
either instance — probes should not unpickle models — but only (a) requires
no new code. Until one of the two lands, `VPREDICT_REFRESH` stays 0.

## Entry 28 — Selection policy and calibration monitor landed (2026-07-24)

Entry 24's three options composed, exactly as recommended there:
deterministic pins (`deterministic=True, force_row_wise=True, n_jobs=1` —
seconds of cost), rolling-origin family selection (5 expanding
chronological folds over the last half of train+val, per-family pooled
per-row losses, ~3 s per retrain), and champion/challenger hysteresis
(keep the incumbent unless the challenger wins by more than one paired SE).
The regression test entry 24 demanded exists: identical data keeps the
incumbent architecture. And the policy has already been observed doing its
job live: the first workspace retrain under it logged "challenger margin
0.63 paired SE (<= 1): incumbent kept" — LR ahead on the folds, inside
noise, flip absorbed. Selection diagnostics are stamped into the bundle
and the cycle JSON, so any future switch arrives with its margin attached.

The §13 calibration monitor also landed: Wilson-interval cells at fixed
edges with report/act thresholds (n ≥ 30 / n ≥ 100), one global
Spiegelhalter Z as the early warning, extrapolation cells outside
[0.15, 0.88], per tier, probabilities never modified, served at
`/api/calibration`.

One divergence, deliberate and temporary: `scripts/evaluate.py` still uses
the old single-shot validation selection, so the serving protocol and the
frozen two-year report now differ. The next full evaluation run adopts the
rolling+hysteresis protocol and produces a new dated results file; the old
file stays frozen as the record of the old protocol.

## Entry 29 — Every stored start time was 4–5 h early: vlr's `data-utc-ts` is Eastern wall time (2026-07-24)

**Symptom.** The live Upcoming tab showed Rex Regum Qeon vs ZETA DIVISION
at "Jul 24, 12:00 AM" for a Toronto viewer; the match actually starts
~08:00 UTC = 4:00 AM EDT. Every displayed time was exactly 4 h early.

**Cause.** Not the frontend — `fmtTime` was already rendering
viewer-local. The stored value itself was wrong: `_parse_utc_ts` read
vlr.gg's `data-utc-ts` attribute and stamped it `timezone.utc`, but for a
cookieless client vlr populates that attribute with the wall clock in the
site's default display timezone, US Eastern — the attribute name lies.
Ledger row 698894 carried `04:00:00+00:00`; Cloudbet's `startTime` for the
same fixture (genuine UTC) reads 08:00. So every `start_ts` in the store
was EDT/EST wall time mislabeled UTC: 4 h early in summer, 5 h in winter.

**Fix.** Parser localizes the attribute to `America/New_York` and converts
to UTC (DST-aware; the one ambiguous fall-back hour resolves to fold=0 —
a ≤1 h error possible for at most one wall-clock hour per year). A
marker-guarded one-time migration (`vpredict.data.migrate`) reinterprets
every stored `start_ts` the same way — store, upcoming, and ledger
metadata — then RE-SORTS the store, because the +4/+5 h shift is not
uniform across DST seams and (start_ts, match_id) order is an invariant.
It auto-runs at the top of the refresh cycle (Render self-heals; the
marker makes every later call a no-op) and `scripts/migrate_store_tz.py`
runs it manually. Applied to the seed store: 6,796 matches + 104 ledger
rows; RRQ–ZETA reads 08:00Z after; VCT Pacific starts now cluster
07:00–11:00 UTC — the real 16:00–20:00 KST/JST broadcast window (they
previously implied midday-Asia starts, which nobody plays). Frontend time
rendering moved to `frontend/src/time.js` — viewer-local with an explicit
zone label, naive strings defensively treated as UTC — with a node --test
suite (`npm test`) asserting a known UTC instant renders correctly under
non-UTC zones.

**Ledger policy.** `start_ts` on frozen rows was corrected as match
METADATA, with the migration report as the audit record; `made_at`,
`p_model`, `p_elo` and every other frozen field are untouched. The freeze
property strengthens under the correction: every recorded `made_at`
predates the TRUE start by 4–5 h more than the ledger previously claimed.

**Evaluation impact, bounded.** A uniform shift cancels in every
start-vs-start comparison, so eligibility, rest-day diffs, Elo event
order, and split membership are unchanged except where a pair straddles a
DST seam (±1 h on a 4–5 h shift): usable matches 5,489, map rows 13,337,
and split counts are IDENTICAL before and after migration. Third-decimal
metric movement plus a validation-selection flip did occur — see the
2026-07-24 results file and MODEL_CARD Limitations.

**Why testing missed it.** The parser test supplied the fixture attribute
and asserted structure, never the semantic instant — and the semantic
claim ("this attribute is UTC") was validated against the attribute's own
NAME, not against an independent clock. Nothing in the offline corpus
could contradict it: every stored time was consistently wrong, and
consistency is what the tests checked. The first independent clock the
system ever met was Cloudbet's `startTime` — and the user's own eyes on a
match they were awake for. The regression tests now pin the instant, both
Python-side (EDT and EST dates) and JS-side.

## Entry 30 — First live Cloudbet run: entry 25's surface (a) validated, three findings (2026-07-24)

The protocol run entry 25 gated on happened on the Mac: 101 fixtures
checked, 16 captured, 0 source errors. Findings, each now acted on:

1. **Real market keys pinned**: `esport_valorant.winner` (matched the
   winner hints as designed), `esport_valorant.handicap` (ignored — out of
   scope), `esport_valorant.totals`. Coverage is better than the ~10/week
   §13 estimate — Cloudbet prices moneyline, totals, and handicap on
   Valorant broadly. Note the totals key contains no "map": the totals
   parser therefore filters by EXCLUSION (kill/round/player/per-map names
   rejected) plus a numeric guard (lines > 4.5 are not map counts).
2. **11 fixtures unlinked**, all the same shape: the book shortens org
   names ("Secret" for Team Secret, "Titan" for Wuxi Titan Esports Club,
   "G2" for G2 Esports). Entry 25's "linking never guesses" rule held —
   they were stored unlinked, not mislinked. The new suggestion layer
   (`vpredict.odds.fuzzy` + `scripts/suggest_aliases.py`) keeps that rule:
   fuzzy proposes, a human confirms, aliases.json stays the audit trail.
   All 11 names resolve unambiguously against the same prediction set the
   run used (tested).
3. **Capture-state keys widened** to (source, match, market, line) so a
   moneyline freeze cannot suppress the totals freeze for the same match;
   pre-totals log rows land at line=None unchanged. A non-blocking flock
   in `capture_odds.py` makes overlapping cron fires exit cleanly instead
   of double-appending freeze rows.

Surface (b) — Pinnacle's intercepted shapes — remains UNVALIDATED until
its first Mac run; `--debug` dumps every intercepted body for a one-paste
fix if the parse count is 0.

## Entry 31 — Walk-forward backtest landed; first run surfaces an isotonic saturation episode the static protocol could never see (2026-07-24)

The item-7 build (ASSUMPTIONS §16) ran end-to-end on the corrected store
in the sandbox — the validation run; the owner's Mac run is the official
record. 6,487 simulated predictions (5,291 scored), 97 production-cadence
retrains, 701 s. Selection behaved exactly as designed across two years:
two family switches total (LR → LightGBM 2025-02-17 at 1.13 paired SE,
back at 1.51 SE ~two months later), everything else held by hysteresis.

**Headline finding.** Aggregated over the full walk, map-effective Elo
leads the model on log loss in three of four tiers — the opposite of the
static test-window report. The per-tier-by-half-year split (now part of
the served report) localizes it: in the most recent period the walk
AGREES with the static evaluation (model ahead in tier-1 and tier-2,
Elo ahead in Game Changers), so the pre-veto pool-mean quantity is not
what erases the edge; the deficit is historical, concentrated in the
early small-data era (tier-1 2024H2: model 0.7476 vs Elo 0.6694, n=31)
and in one acute episode:

**July 2025, tier-2: model 0.8096 vs Elo 0.6211 (n=211), with published
probabilities spanning 0.000–1.000.** Reproduced, not guessed: retrain 41
(2025-06-26) had 783 validation rows — under the 800-row isotonic gate —
and fitted Platt with range [0.005, 0.995]; retrain 42 one week later had
847 rows, isotonic was admitted for the first time, and the fitted
calibrator mapped ~24 % of the raw-score range onto a 0.999999 plateau.
At 4-decimal ledger rounding those publish as 1.0000; each wrong one
costs ~13.8 nats at the metric clip, and the era's extreme calls were
right only 74 % of the time. The episode fades as validation grows
(retrains 46+ are back to beating Elo).

**Why the existing protocol missed it.** The static evaluation fits ONE
calibrator on the final ~2,000-row validation window — it structurally
cannot exercise the admission boundary, because it never sees a 800-row
validation set. Only a deployment replay meets every intermediate data
size, which is precisely the argument for having built one. Retrain log
entries now record `calibrator` and `n_val_rows` so a future episode is
visible without a reproduction.

**No tuning happened.** The run stands as-is under the run-once rule.
The candidate hardenings (clip calibrated outputs away from exact 0/1
the way Platt's tails do; or admit isotonic only when it beats Platt by
a margin; or raise the gate) are REPORTED, not built — if one is adopted
later, the model changes, the backtest re-runs under the new version
label, and this result stays archived. That is the doctrine's designed
path, not an exception to it.

**Fixture lessons (test-authoring, not production bugs).** Synthetic
walk histories must (a) use 2-1 series so every match contributes both
label classes to any fold, and (b) contain upsets — a linearly separable
tiny validation slice turns the Platt calibrator into a step function
that freezes outputs and silently defeats sensitivity assertions. Both
are now comments in the fixture.

**Ops note.** The first launch died silently at ~1,250 predictions:
background children are reaped when the invoking sandbox shell exits —
not OOM (260 MB RSS, no kernel kill records). `setsid` detaches cleanly;
recorded here because a half-written rows file from a reaped run looks
exactly like a crash.

## Entry 32 — Field failure on patch 0019: a saturated Platt published exactly 1.0; outputs are now bounded (2026-07-24)

**Symptom.** On the owner's Mac, `test_walk_produces_ledger_shaped_graded_rows`
failed with `p_model == 1.0` exactly. The same test passed in the build
sandbox.

**Cause.** Not isotonic — the fixture's validation slice is 3 rows against
the 800-row admission gate, so both walk retrains fit Platt. Platt on a
tiny, linearly separable slice explodes: the reproduced fixture bundle has
slope −59.4 on the logit scale — a step function whose tails are 0/1 to
float precision — and on the sandbox 34/99 of the raw-score grid already
sat within rounding distance of 1.0. The sandbox test passed by NUMERIC
LUCK: this machine's lbfgs/BLAS happened to land every fixture row's raw
score on the sub-0.99995 side of the step; the Mac's landed one on the
other side, and `round(·, 4)` published certainty. Same pathology FAMILY
as entry 31's July-2025 episode (a saturated calibrator meeting a rounding
boundary), different calibrator — which settled the hardening choice: an
isotonic-beats-Platt-by-margin rule would have fixed neither this failure
nor bounded Platt.

**Fix (patch 0020), two independent bounds.** (1) Both calibrator
transforms clip to `[CAL_OUTPUT_CLIP, 1 − CAL_OUTPUT_CLIP]` = [0.005,
0.995] — the range a HEALTHY Platt fit spans on its own (entry 31's r41
measurement), i.e. the most a calibrator can claim is what a sane fit
could evidence. (2) Published probabilities are rounded then clamped one
rounding-ulp inside (0, 1), because series aggregation defeats the map
clip alone: a Bo5 of 0.995s is 0.999999, which rounds to 1.0000. Both
bounds are pinned by tests that construct the saturating fits explicitly.
Measured impact on the static report: three fourth-decimal digits (ECE
0.0274→0.0275, one GC cell, one tier-1-arm cell); every headline number
unchanged.

**The gate then caught its own blind spot.** Re-running the sandbox
backtest under `--replace` was REFUSED: the bundle version is date +
parameter/data hash, so a pure BEHAVIOR change on the same data and day
produced an identical version — "model changed" detection could not see
code. `BUNDLE_BEHAVIOR_REV` (config, rev 2 = this hardening) now feeds the
version hash; bump it whenever prediction-affecting behavior changes
without data changing. A refusal doing exactly its job, one level up from
where it was aimed.

**Why testing missed it.** The assertion `0.0 < p < 1.0` was correct as a
SPEC, but the code did not guarantee it — the test encoded a hope, and the
sandbox numerics happened to honor it. The lesson is the same one entry 29
taught about the timezone attribute: a property that has never been
falsified is not a property that has been verified. The bound is now a
guarantee, so the assertion holds on every machine for a reason.

**Pickled-bundle note.** Calibrator behavior lives in code, not pickle
state, so deployed bundles adopt the clip on deploy without a version
change; the interim delta is nil for in-band predictions (live upcoming
calls sit within 0.15–0.88), and the next retrain stamps the
behavior-rev'd version.

## Entry 33 — "TBD vs TBD": the first graded scoreboard result was the model predicting a team against itself (2026-07-24, night)

**Symptom.** A highlighted "TBD vs TBD" row with a green result mark,
visually inside the Backtest panel, read as a live win. The owner's first
graded headline (model LL 0.5373 vs Elo 0.6931) was this row.

**Cause, three layers.** (1) vlr lists unresolved bracket slots as "TBD";
the upcoming crawler stores them; both sides normalize to the SAME team
key ("tbd"), so the prediction is a team against itself: Elo is exactly
0.5 (LL ln 2 = 0.6931 — the arithmetic identifies the row), and p_model
0.5843 is pure intercept bias on zero-information features, not signal.
Six such self-collided rows sat in the seed ledger. (2) The frozen ledger
kept the placeholder NAMES forever even after the real match graded by
id. (3) Layout: the graded table rendered untitled directly beneath the
Backtest panel, so a live-ledger row read as backtest content.

**Fix (patch 0022).** Prediction path skips fixtures whose team keys
collide (counted as `skipped_placeholder`; the slot gets a real
prediction when the bracket resolves). grade() backfills placeholder
names from the completed match — display metadata, same §15 precedent as
start_ts; frozen probabilities and keys untouched — plus a one-time
`backfill_names` sweep in the refresh cycle for rows graded before the
fix. The live headline metrics now score graded NON-low-history rows
only, the same pre-registered rule the backtest uses (§16), with both
counts shown; the placeholder row stays in the record, flagged, unscored.
Frontend: the graded table got its own titled panel inside the LIVE
section and the Backtest panel moved last. Consequence stated plainly:
the owner's scoreboard headline goes from "1 graded" to "1 graded,
low-history, nothing scored yet" — which is the true state.

**Why testing missed it.** Every fixture in the test suite has two
distinct teams, because that is what a match is; nobody wrote the case
where the scraper's input violates the definition. The invariant
(distinct team keys) existed implicitly everywhere and explicitly
nowhere. It is now explicit at the prediction choke point and pinned by a
test that feeds the degenerate fixture directly.

## Entry 34 — Stand-in features ship; the ensemble's selector was biased toward the incumbent and said so in its own table (2026-07-24, late night)

One pre-registered evaluation run (§19), one test read. Three findings:

**1. The stand-in features pass their gate — barely, and one of them is a
duplicate.** Best candidate validation map LL improved 0.66007 → 0.65977
with `core_absent_diff` and `newface_diff` in; the §19 gate says ship, so
they ship. Test movement is third-decimal and mixed (map 0.6672 → 0.6676,
series 0.6530 → 0.6501) — consistent with a small real signal plus noise.
The embarrassment, printed by the run's own collinearity table: the two
features correlate at +1.00. With full 5-player lineups (100% coverage),
|core − last| = |last − core|, so they are the same quantity under two
denominators. Under L2 a perfect duplicate splits weight and changes
nothing predictive (the span is identical), so this round ships as
evaluated; the duplicate is dropped in the next feature round rather than
burning another test read on a provable no-op.

**2. The ensemble selection stands — incumbent — but the selector is
biased and the table shows it.** Both blends lose validation (0.6608 /
0.6597 vs 0.6511) and both beat the incumbent on test (map 0.6630 /
0.6615 vs 0.6676; per-tier best). The bias: the incumbent's validation
number comes from its isotonic calibrator FITTED ON that same validation
window, while the blends were fitted only on out-of-fold train rows — the
§19 protocol protected the blends from leaking and forgot the incumbent
enjoys exactly the optimism it was protecting against (measured: raw
0.6598 vs calibrated-on-val 0.6511, a 0.0087 gift). No switch happens —
selecting on the test columns is the sin this project exists to name —
but §19b (ASSUMPTIONS) pre-registers the fair selector for the NEXT
evaluation: every candidate, incumbent included, scored on validation via
out-of-fold-fitted calibration. The per-tier blend's test showing also
matches the walk-forward finding that Elo deserves more trust in tier-1,
which is why this lead is worth a fair rematch rather than a shrug.

**3. Selection flipped to LightGBM again (gap 5e-5)** — the fourth lead
change of a dead heat the hysteresis policy exists to absorb. Production
keeps its incumbent; the report shows the single-shot pick, as always.

## Entry 35 — The TBD row's second layer: the freeze rule itself keeps the slot, plus a self-inflicted file overwrite (2026-07-24, night)

**Symptom.** After 0022, a graded "TBD vs TBD" still renders as a normal
result ("TBD won in 2 maps") with empty "tbd" recent-form blocks.

**Cause, two layers.** (1) Structural, and permanent by design: the
placeholder call froze FIRST for that match id, and the first call per
match is immutable — so when the bracket resolved, the real fixture's
prediction was refused by the freeze rule. The slot is occupied forever;
0022's skip prevents NEW occupations, it cannot evict old ones. The
names-backfill can only fire if the server store holds the resolved
completed match — the seed store has ZERO completed matches with
placeholder identity, so if names persist across two refresh cycles, the
server store lacks that record, which is the same suspected crawl gap as
"only 1 of last night graded." (2) Display: the detail view rendered any
graded row as a result, and the history endpoint emitted an empty block
per key with the key as the fallback name — a collided "tbd" key renders
twice with no rows. Fixed: the endpoint flags `placeholder` (collided
keys or placeholder names), skips their history, drops empty blocks; the
page renders the honest explanation, including the freeze-rule cost,
instead of a result line. Pinned by test.

**Session blunder, on the record.** While applying the fix, the edit
script's last line wrote the App.jsx buffer to the api.py path — api.py
became 145 lines of JSX. pytest's collection error caught it within one
command; `git checkout` restored it; the edits were reapplied with
per-file writes and content assertions. Why testing caught it instead of
missing it: the suite imports the module, and a Python file full of JSX
cannot be imported. Frequent commits made the recovery a one-liner.

## Entry 36 — The site was running blind and standing still: INFO logs never emitted, deploys never retrained (2026-07-25)

**Symptom.** Render logs contain no "refresh scheduler enabled" and no
"refresh cycle:" lines despite curl showing generated_at current — the
cycle demonstrably runs and the breadcrumbs demonstrably don't print.
Separately, the served model_version is the pre-feature bundle days...
hours after the feature deploy: the site predicts autonomously on the OLD
model.

**Cause 1 — the API process never configured logging.** The refresh
SUBPROCESS calls basicConfig in its own main and prints the cycle JSON,
but the API process (which logs "refresh scheduler enabled" and "refresh
subprocess ok") configures nothing: its INFO records fall to Python's
last-resort handler, which emits WARNING and above only. Every scheduler
breadcrumb was dropped at the source; searching for them could never
succeed. Fix: the vpredict logger tree gets its own handler and INFO
level with propagation off — one line, every environment, regardless of
what uvicorn or any runner did to the root logger. Note for the owner's
remaining puzzle: the subprocess's own "refresh cycle:" line and JSON
SHOULD appear in the service stream; if they still don't after this
deploy, watch the live tail during the boot cycle rather than trusting
dashboard search, and check whether a separate Render service is the
thing actually cycling.

**Cause 2 — deploys never retrained, by omission.** _needs_retrain
compares bundle age and store counts; nothing compared the bundle to the
CODE. So a deploy that redefines the model (patch 0023's features) serves
the old bundle until the 7-day cadence — answered plainly: yes, the cycle
only retrains on its own trigger, and no, a deploy did not force one.
That was a gap, not a decision. Fix, same converge-once pattern as entry
26: bundles record BUNDLE_BEHAVIOR_REV (now bumped on ANY model-
definition change, features included — rev 3); a bundle carrying an older
or missing rev triggers exactly one "model definition changed ... retrain
once". The live pre-rev bundle fires this on the first cycle after
deploy, and serving converges to the deployed definition in minutes
instead of days.

**Version-hash footnote.** The owner's local retrain (…-fdda66b1) and the
sandbox's (…-a5ac1940) differ because LightGBM's best_iter lands in the
model NAME and varies across machines (entry 28's known numerics) — the
hash is doing its job, not drifting.

**Why testing missed both.** The logging gap: tests run under pytest,
which configures logging, so INFO always flowed in CI and never in
production — the test now asserts the vpredict tree emits regardless of
the runner. The retrain gap: every trigger test fed the trigger exactly
the conditions it checked; nobody wrote "the world changed and the bundle
didn't" until the world did.

## Entry 37 — Seven maps, one number: the per-map panel was honest, quantized, and unreadable (2026-07-25)

**Symptom.** Live per-map probabilities showed one identical value across
the entire 7-map pool (61.3% on every map of Nongshim RedForce vs Global
Esports, match 698897) despite map-specific Elo being a real trained
feature. Suspected: the per-map path silently falling back to the series
number.

**Cause — three compounding real properties, zero wiring bugs.** The
per-map path is correct: one feature row per pool map, that map's one-hot
set, `map_elo_diff` from the per-map Elo blend, payload written from the
per-row outputs (never from `p_model` — the live series number reads
0.6671, the exact Bo3 DP of 0.6134, which the fallback hypothesis cannot
produce). What actually happens in the shipped LR(C=0.03)+isotonic
bundle: (1) swap augmentation forces every symmetric-invariant feature to
exactly zero weight in a linear model — all 11 map dummies, best_of,
playoff, hist_min carry coefficients of 0.00000, by mathematical
necessity; (2) the one surviving map-varying input, `map_elo_diff`, is
crushed by C=0.03 to 0.000254 log-odds per Elo point (it is collinear
with `elo_diff` at r≈+0.96, so L2 gives it almost nothing) — real
per-map Elo edges of +27 to +176 move the raw probability by under one
point; (3) the isotonic calibrator is a step function with ~18 output
levels whose plateaus near 0.6 are 1.9–5.5 points wide, so the whole
per-map spread lands inside one plateau and every map snaps to the same
published value. 0.6134 is literally one of the calibrator's output
levels. Reproduced end-to-end on the seed store (all seven maps → 0.6381,
the adjacent plateau; Render's topped-up store sits one plateau lower).
`maps_dist` is consistent by construction — it is the exact Bo-N
distribution of the uniform pool MEAN of the same calibrated per-map
probabilities, so there is no second path to corrupt; totals EV reads the
frozen ledger and stays excluded pending the independence fix, which
dwarfs plateau granularity anyway. No scored number is affected:
grading uses frozen `p_model`/`p_elo`; `per_map` is display-only.

**Fix (this patch) — display honesty, model untouched.** The payload now
carries `per_map_elo`, each pool map's Elo lean from the same feature-K
snapshot the feature row consumes, and the UI shows it beside each map
with a plain-language note that calibrated probabilities land on a small
set of learned levels and can tie. When the headline is a frozen ledger
row, the panel says the per-map numbers are the current model's live
view. No model change, no BUNDLE_BEHAVIOR_REV bump. Pre-registered
instead of hot-fixed: a smooth monotone calibration candidate enters the
calibration menu next model round under the standard validation
selection (ASSUMPTIONS §21) — overriding isotonic for cosmetics would
violate the selection policy. The LR capacity limit (no map
interactions; per-map effects enter only through one crushed
coefficient) is logged as future work in the same section.

**Why testing missed it.** Tests assert the wiring — distinct features
in, payload written from per-row outputs — and the wiring is correct.
"Per-map outputs are distinct" was never asserted because it is not a
valid invariant: a step calibrator may legitimately tie any number of
maps. Nothing false was ever computed, so no assertion could have
failed. The new contract test pins what IS invariant: `per_map_elo`
matches the snapshot the features consume and varies when history is
map-dependent, so the UI always has real per-map signal to show however
the calibrator quantizes.

## Entry 38 — The hero paragraph sat on the divider bar: fixed-viewBox decoration vs growing content (2026-07-25)

**Symptom.** The homepage intro paragraph ending "a verdict" overlapped
the teal/coral divider bar and read as broken.

**Cause.** The bar was drawn INSIDE the hero's background SVG at fixed
viewBox coordinates (y=330 of 420) under `preserveAspectRatio: slice`.
That was fine when the hero's content was short; patch 0030 added the
stat card and the next-up strip, the hero grew taller, the sliced SVG
scaled up with it, and the bar landed mid-content. Decoration positioned
in scaled artwork coordinates cannot promise clearance from content
positioned in layout coordinates.

**Fix.** The bar (and its notch) left the SVG and became a pinned HTML
element at the hero's bottom edge, with the hero's bottom padding
enlarged so content always clears it by construction — the two now live
in the same coordinate system, so no future content growth can recreate
the overlap. Same gradient, same notch, same look.

**Why testing missed it.** Nothing renders layout: esbuild parses, node
--test exercises pure modules, pytest never sees a pixel. A geometry
regression between two coordinate systems is exactly the class of bug
the current suite is blind to; catching it earlier would need visual
regression snapshots, which are noted as future tooling, not promised.

## Entry 39 — Match-detail clicks took 16-19 s: a per-group pandas loop, paid in full by every click (2026-07-26 session)

**Symptom.** Match detail pages noticeably slow since the rating chart
(patch 0034); measured 16-19 s per request on the full 6,796-match
store.

**Cause.** Two multipliers. First, `matches_lite_from_maps` rebuilt its
per-match dicts with a pandas groupby that ran a boolean mask, a
`sort_values`, and an `.iloc[0]` PER MATCH — 6,796 small frames of
overhead totalling 12.7 s, while the Elo replay itself cost 0.11 s.
Second, the endpoint rebuilt those lites from the store on every click
even though the store only changes when the refresh cycle tops it up:
maximum cost, zero reuse.

**Fix.** Both multipliers. The builder is now a single pass (one
filter, one sort, one walk over contiguous groups), pinned
byte-identical to a verbatim copy of the old implementation by test:
12.7 s -> 0.19 s. And the serving path now goes through
`cached_matches_lite`, one cache entry keyed by the store file's
identity (path, mtime_ns, size) — an append-only JSONL cannot change
without moving both — built under a lock so concurrent cold requests
serialize. Measured on the real store: cold click 16-19 s -> 3.1 s,
warm clicks -> 0.85 s (the remaining team-history stream plus the
0.1 s replay). Chart output unchanged to the decimal.

**Why testing missed it.** Every functional test runs on toy stores
where both multipliers are invisible; nothing in the suite asserts a
latency budget, and the 0034 real-data spot check verified correctness
without timing. A perf regression gate (endpoint budget on a seeded
store) is noted as future tooling, not promised.

## Entry 40 — npm ci refused the vite 8 bump: incompatible peer range shipped, verified with the wrong command (2026-07-26 session)

**Symptom.** After applying 0039/0040, `npm ci` on the owner's machine
failed with ERESOLVE: the root project pins vite ^8.1.5 while
@vitejs/plugin-react 4.7.0 declares peer support only up to vite 7. The
install never happened, so the `npm test` run after it exercised stale
node_modules and verified nothing.

**Cause.** Patch 0039 bumped vite 5 -> 8 to clear the dev-chain esbuild
advisories but left the react plugin on the 4.x line, whose declared
peer range stops at vite 7. The mismatch shipped because it was
verified with the wrong command: `npm install vite@latest` on a warm
tree, which tolerates the peer conflict, instead of a cold `npm ci`,
which is exactly what the runbook tells the owner to run and exactly
what enforces peer ranges strictly.

**Fix.** @vitejs/plugin-react ^6.0.4, whose declared peer range is
vite ^8 (its rolldown/babel peers are marked optional and are not
needed by this config), lockfile regenerated. Verified with the
correct command this time, from scratch: `rm -rf node_modules &&
npm ci` exits 0, `npm test` passes 8, `npx vite build` succeeds,
`npm audit` reports zero vulnerabilities.

**Why testing missed it.** Two masking layers: the verification ran
install-on-a-warm-tree rather than ci-from-scratch, and the install
output was tail-truncated, which hid the peer warning npm printed. The
runbook command (`npm ci`) is now the command the verification runs.

## Entry 41 — The scoreboard starver: the eternal cache served pre-completion bodies, so predicted matches could never grade (2026-07-25/26 session)

**Symptom.** Live n_graded frozen at 1 for days while real matches
finished. Every pending ledger row stayed pending; the store, checked
directly, showed those matches as "live" or "upcoming" long after they
ended — 698897 still "live" 13+ hours after start, while vlr.gg's page,
fetched fresh, said completed with a 2-1 winner. Cached body age: 11
hours, from before completion.

**Cause.** A four-step interaction, each step individually reasonable.
The upcoming radar fetches match pages before they start and every
fetch writes the disk cache. The completed crawl fetches match pages
with no TTL, per the "completed pages cannot change" rule — which is
only sound when the cached body postdates completion; the cache does
not record which side of completion its body came from. So when a
predicted match later appeared on the results listing, the crawler
parsed the stale pre-completion body, upserted a "live" record, and
from then on the id was known (never re-listed as new) and the cache
was eternal (never refetched): trapped on both layers. Grading
requires completed-with-winner, so the row could never grade. The
mechanism selectively targets exactly the matches that pass through
the upcoming radar — which is exactly the set the ledger predicts —
which is why history looked pristine while the live scoreboard
starved from the day predictions went live.

**Fix.** Three parts. The completed path now verifies the parse: a
listing that says completed meeting a body that does not parse as
completed forces one network refetch (which also rewrites the cache
entry, permanently healing it); if even the fresh body is not final,
the completed path stores NOTHING — the id stays unknown and the next
crawl retries. A healing pass in the refresh cycle (before grade, so
releases grade in the same cycle) refetches any stored record still
non-final well past start + assumed duration + slack, bounded by a
lookback so dead fixtures stop consuming requests; the store only
ever moves forward to completed-with-winner, never to a guess. And
regression tests now model the cache as what it is — the same URL
returning different bodies across lifecycle states — poisoning a
cache with a live body and pinning: refetch happens, non-final is
never stored, heal releases only the trapped row.

**Why testing missed it.** The crawl tests used a canned fetcher with
one body per URL, so no test could express "the cache and the network
disagree" — the defining property of a cache — and the eternal-cache
rule was reasoned about only from the completed side, then written
into ASSUMPTIONS §2 as if it covered every cached body. The two-year
backfill fetched everything after completion, so all historical data
validated clean; the bug could only begin once predictions and the
upcoming radar went live. And monitoring watched n_graded without any
check joining ledger-pending rows against the live site — the store
was allowed to testify to its own freshness. The diagnosis flipped
only when a probe compared the stored status against a fresh fetch of
the same page.

## Entry 42 — The tab-click trap: match detail shadowed every tab, and no view had a URL (2026-07-26 session)

**Symptom.** From any match detail view, clicking a top-level tab
highlighted the tab but kept showing the match; only the in-page back
button escaped. Browser back/forward did nothing meaningful anywhere on
the site, a reload always reset to the upcoming list, and there was no
such thing as a link to a specific tab or match.

**Cause.** Navigation was two `useState` variables in `App`: `tab` and
`openMatch`. The render gated on `openMatch` FIRST — while a match was
open, the tab content never rendered, so tab clicks mutated state that
had no visible effect. Nothing wrote to the browser's history, so the
URL never changed and back/forward had nothing to walk. Two views, one
render slot, no addresses.

**Fix.** Views own URLs now (react-router 6): `/upcoming`,
`/scoreboard`, `/model`, `/backtest`, `/match/:id`, with `/`
redirecting to `/upcoming`. Tabs are `NavLink`s, so clicking one IS
navigation and always lands on that tab's own default view; a match
detail is a page, not a modal squatting over every tab; back/forward,
reload, middle-click, and shared links behave like any normal site.
Server side, a narrow fallback answers unmatched extensionless GETs
with the SPA shell so deep links survive a reload, while `/api` and
extensioned paths (missing assets, sensitive-file probes) keep their
honest 404s — pinned by two new API tests.

**Why testing missed it.** Navigation existed only as implicit state
coupling inside one component, so there was nothing for a test to
address: the frontend suite covers pure functions (`node --test` on
chart/time), and no navigation sequence was expressible, let alone
pinned. Manual checks always left a match via the in-page back button —
the one path that worked — because that is the path the person who
wrote the view habitually used. The fix makes navigation a first-class,
addressable thing (URLs), which is also what makes it testable at the
server boundary.

## Entry 43: Three regressions in the visual-redesign handoff, caught in review, never shipped (2026-07-28 session)

**Symptom.** The redesign handoff (drop-in `index.html`, `index.css`,
`App.jsx`) claimed routes and data flow untouched. Review against the
current tree found three regressions: the route table had no `/` entry,
so the landing page was orphaned and the root URL would have rendered
the 404 view; the theme attribute was applied only in a post-mount
effect, so a stored light choice on a dark-system machine would flash
dark on every load; and the stylesheet dropped the Elo win color, so a
metric row where Elo wins would have rendered in the model's teal,
visually crediting the model with Elo's win.

**Cause.** The handoff was produced against the right file but outside
a running browser, and rebuilt the route table and stylesheet from
scratch. Nothing in the repo asserts the route table or the
theme-persistence contract, so nothing could have flagged the drops
automatically.

**Fix.** Root route restored. Theme logic extracted to
`frontend/src/theme.js` (pure module, storage injected) and applied
pre-render from `main.jsx`, so the stored choice paints before first
render and a throwing or absent `localStorage` (private windows,
locked-down contexts) degrades to the system theme without breaking
the page. `.metric-val.elo` rules restored. Eight new node tests pin
the theme contract: default, round trip, junk values, throwing
storage, attribute set and clear, pre-render init.

**Why testing missed it.** It could not have: the defects arrived in
the handoff, and the repo's frontend tests only reach pure modules by
design (`node --test`, no DOM). The theme contract is now in that
reachable set. The route table still is not; it stays a manual review
item, checked here by diffing the route block against HEAD.

## Entry 44: The upcoming page published the live model, not the frozen call (2026-07-28 session)

**Symptom.** The probability on an Upcoming card disagreed with the same
match's detail page, by as much as 0.2332 on a live match. The gap grew
with time-to-start and jumped after retrains.

**Cause.** `run_predictions` wrote `upcoming_predictions.json` from the
current cycle's fresh engine output for every match, every cycle, while
the detail page and Markets served the frozen ledger row. The api.py
docstring already said "/api/upcoming: latest pre-match predictions (as
published to the ledger)"; the implementation drifted from the stated
intent. A second consequence: matches whose freeze window had passed
(`too_late`, no ledger row) were still published, so an uncalled match
displayed as a call and then vanished at start without ever reaching
Markets.

**Fix.** The payload is now built FROM the ledger: the engine runs only
for matches with no frozen row (or whose display extras need a rebuild
after a fresh disk), the published p_model/p_elo/maps_dist/model_version
are the stored row's values verbatim, and a match without a row is not
published at all. Schedule and naming fields still come from the current
listing, so reschedules and resolved TBDs display correctly while the
call stays frozen. Side effect: cycles where everything is frozen skip
the expensive feature build entirely, which matters at the new cadence.

**Why testing missed it.** The freeze rule was tested at the ledger
layer only; nothing asserted the published JSON against the ledger. A
single local cycle shows zero drift by construction, so the bug needed
multiple cycles or a retrain to become visible, and production was the
first place both happened. Four tests now pin payload==ledger, absence
of uncalled matches, the engine skip, and reschedule display.

## Entry 45: The markets build read the scoreboard endpoint and inherited its 100-pending cap (2026-07-28 session)

**Symptom.** None yet, latent: with more than 100 pending frozen rows,
the Mac-side markets build would silently drop the oldest pending
matches from the join and their picks would never appear.

**Cause.** publish_markets fetched ledger rows over HTTP from
/api/scoreboard, whose pending list is capped at 100 for the UI.

**Fix.** The markets build now runs in the refresh cycle on the server
and reads the ledger directly (limit 100000). The Mac script keeps
working for offline analysis; its HTTP path keeps the cap, which is now
documented on the endpoint it borrowed.

**Why testing missed it.** The board has never exceeded 100 pending
rows; nothing exercised the truncation branch. Caught by reading the
join's inputs during the server-side move, not by a failure.

## Entry 46: One placeholder price took down the markets build for a day (2026-07-30 session)

**Symptom.** markets.json frozen at 2026-07-29T19:30:30 while both odds
sources kept capturing (44 cloudbet, 719 pinnacle rows, fresh
timestamps). Matches with real captures never appeared or updated on
the Markets tab.

**Cause.** Two data-dependent crashes in build_picks, both introduced
by patch 0055 and both reproduced in a sandbox before fixing. First:
the consensus column runs devig on EVERY priced source's entry, and
devig's implied() deliberately raises on any decimal price at or below
1.0 (a placeholder or suspended market). Before 0055 only the single
headline entry was ever de-vigged, so a degenerate pair on a
non-headline book had no path into the strict guard; after 0055, one
such record anywhere killed the entire build, every tick. Second,
independent: pick groups sorted by raw (match, market, line) tuples,
and a lineless totals row alongside a lined one crashes tuple
comparison with None < float. Timeline pinned it: the 0055 commit
landed 19:21:40Z, the first in-cycle build succeeded at 19:30:30Z, and
the first record of the newly live streams (cloudbet server captures
plus the 719-row seed) poisoned every build after.

**Fix.** The pipeline is now total over bad records: an unpriceable
entry sidelines that source, an unpriceable close becomes no close, a
fully unpriceable group drops, and every skip increments a counter
carried in markets.json ("skipped"), the refresh log line, and a
Markets-panel note when nonzero. The strict ValueError stays in
devig.py where analysis code should be loud; the caller decides.
Group ordering uses a None-safe key. Secondary fix in the same round:
--push now re-sends the last ODDS_PUSH_WINDOW_H hours instead of only
that run's appends, so a failed push self-heals next fire (server
ingest dedupes), and a push failure prints into the report and exits
nonzero instead of dying before the report.

**Why testing missed it.** Every fabricated test price was sane, so the
strict guard never fired in CI; the old headline-only path meant two
years of Mac builds never fed it a non-headline pair either; and the
capture pass shares the strict log parser but never runs the pick
math, which is exactly why capture stayed healthy while the build died
— the discriminator that located the bug. Five regression tests now
pin both mechanisms, the counter, and that one bad record can never
block another match's picks.

## Entry 47: The "0058 didn't work" crash was 0058 never running, plus two real gaps found on re-audit (2026-07-30 session)

**Symptom.** After 0058 was believed deployed, the identical build
failure fired with a new value: "decimal odds must be > 1.0, got
[0.0, 0.0]". Separately, the day separators from 0057 were not visible
on the live site.

**Cause.** One root for both: patches 0057 and 0058 never reached
origin/main. Verified two ways. The remote tip at diagnosis time was
99a7162 (0056, how-it-works), so no deploy could contain either patch.
And the committed 0058 code, fed the exact reported value [0.0, 0.0]
in a sandbox, produced one pick and n_unpriceable=1 with no exception:
the running service was provably older code, whose strict guard is
designed to fail the build loudly. The local 34-test pass earlier that
night proved both patches were applied locally; the push is what never
happened. Re-audit found two genuine gaps anyway: NaN prices slipped
through the 0058 comparison (NaN compares False with everything) and
would have emitted NaN into markets.json rather than crashing, and any
unforeseen per-group failure would still have killed the whole build.

**Fix.** 0059 hardens the class, not the value: a single _priceable
predicate (both decimals finite and above 1.0) filters capture records
before grouping, so entry falls back to the first priceable freeze and
a source whose records are all placeholders simply never appears;
unlinked degenerate records neither crash nor count. Every pick group
runs inside last-resort isolation: an unexpected failure increments
n_group_errors, logs a full traceback, and the rest of the build
ships. Both counters travel in markets.json, the refresh log, and the
Markets note. Deploy verification is now a recorded one-liner instead
of an assumption.

**Why testing missed it.** Nothing in CI can catch an unpushed push;
the discrepancy between the reported value and the committed code's
behavior was itself the diagnostic. The NaN gap was missed because no
test used non-finite floats, and comparisons that silently return
False do not announce themselves.

## Entry 48: The Upcoming title tooltip lost the paint-order fight it never had to enter (2026-07-30 session)

**Symptom.** The info tooltip on the Upcoming page title rendered cut
off, its lower half disappearing behind the first match card. The same
component on the Model tab displayed cleanly.

**Cause.** The pop was absolutely positioned inside the title's own
stacking environment. On Model it only ever overlays content inside
the same panel, so its z-index settles the fight locally. On Upcoming
it has to escape the page header downward into sibling territory,
where DOM-later positioned elements (the cards, which carry their own
positioning for the tug bar) can win the paint order against a
z-index trapped in the header's context, and the pop's fixed 264px
width could also run past narrow viewports. Same component, different
inherited battlefield, exactly the per-instance inheritance suspected.

**Fix.** Class fix, not container archaeology: every pop is now
viewport-fixed, measured from its trigger with getBoundingClientRect,
clamped to the viewport with a responsive width, and closed on scroll
or resize so it can never sit stale. No ancestor stacking context or
clipping box can trap or cut it anywhere, current pages or future
ones. Verified safe first: the entrance keyframes are from-only and
leave no lingering ancestor transforms that would hijack fixed
positioning. Hover, focus, click-to-pin, Escape, and outside-click
behavior are unchanged because the pop stays inside its wrapper.

**Why testing missed it.** The node suite never paints; stacking-order
bugs need a browser, a specific ancestor chain, and a sibling that
fights back, a combination only the Upcoming page had.
