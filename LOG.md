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
