# APPLY — patch session 2026-07-24 (evening): patches 15–19

What landed, mapped to your list: **6** timezone (parser root cause +
store/ledger migration + zone-labeled rendering + tests), **1** fuzzy
alias suggestions, **3** capture overlap lock (cron-safe by construction),
**5** markets & EV (totals capture, frozen maps distribution, EV/CLV
scoreboard with guardrails, authenticated publish), **7** walk-forward
backtest BUILT and sandbox-validated (patch 0019; your official run is
§9), **2/4** exact commands below (they need your Mac / the Render
dashboard). All numbers in the session report regenerate from repo
scripts.

Run everything from the repo root: `cd ~/Downloads/valorant-predictor`.

## 1. Apply and verify

Download the five `.patch` files into `patches/`. Fresh apply (none of
15–18 applied yet), in this exact order:

    git am patches/0015-*.patch patches/0016-*.patch patches/0017-*.patch patches/0018-*.patch patches/0019-*.patch

If you already applied 15–18 from the earlier package, apply only the new
one on top:

    git am patches/0019-*.patch

Then verify:

    source .venv/bin/activate
    python -m pytest                 # expect 101 passed
    cd frontend && npm test && cd .. # expect 5 pass (needs Node >= 20)

If `git am` complains (uncommitted local edits), `git stash` first, apply,
`git stash pop`. Patch 0019 contains the backtest engine, the predict_one
refactor, the BACKTEST panel, its tests, and a documentation alignment
pass (README, WALKTHROUGH, this file) — so if 15–18 are applied cleanly,
0019 applies cleanly on top; do not reorder.

## 2. Migrate YOUR store (once, before anything else touches data)

    python scripts/migrate_store_tz.py
    python scripts/migrate_store_tz.py --status   # shows the audit report

Every stored start time was US-Eastern wall time mislabeled UTC — 4 h
early in summer, 5 h in winter (LOG entry 29). This reinterprets and
re-sorts, corrects ledger start metadata (frozen probabilities and
made_at untouched), and writes a run-once marker. Spot-check: RRQ–ZETA
should now read `2026-07-24T08:00:00+00:00` in the audit or the store.
Optional deeper audit later: re-parse the HTML cache with the fixed parser
(LOG entry 9's procedure) and diff — the outputs are equivalent by
construction.

## 3. Deploy, and what Render does by itself

    git push

Render auto-deploys. Its next refresh cycle migrates the disk store
automatically — nothing to run in a shell. In the service Logs, in order:

1. `applying one-time timezone migration (LOG entry 29)` then
   `timezone migration done: {... 'n_matches': ~6800, 'n_ledger_rows': ...}`
   — once, ever. Later cycles skip it silently (marker).
2. The patch-13 convergence, if it hasn't fired yet today:
   `"retrain": "pre-fix bundle (no n_store_records): retrain once"` — once.
3. Settled state on subsequent cycles: `"retrain": "bundle fresh"`, until a
   real trigger (`bundle older than 7d` or `N new matches` with N >= 100).
4. No OOM: Memory graph in the dashboard should stay well under 2 GB
   (measured cycle peak ~300 MB + ~174 MB API process).

That is your item 4 checklist. If a cycle OOMs or the migration line shows
an error, copy the log block into the chat.

Interim note, bounded: between the migration and the next cadence retrain,
the serving bundle was trained on pre-correction timestamps. Row counts
and splits are identical pre/post; drift is third-decimal (session
report), and the next scheduled retrain absorbs it. No action needed.

## 4. See the fix live (your item 6)

Hard-refresh the site (Cmd+Shift+R — the JS bundle changed). Times now
render in YOUR timezone with the zone labeled: RRQ–ZETA shows
`Jul 24, 04:00 AM EDT` in Toronto, not `12:00 AM`. The "Generated" and
scoreboard timestamps carry the label too.

## 5. Pinnacle first run (your item 2 — needs your Mac)

    source .venv/bin/activate
    python scripts/capture_odds.py --once --sources pinnacle --debug

Report the printed fixture count. If it's 0: the newest file in
`data/odds/debug/` is the intercepted body — send it and I fix the parser
in one pass (LOG entry 25 surface (b), same protocol that caught the
scraper bugs).

## 6. Cron, overlap-safe (your item 3)

`capture_odds.py` now takes a non-blocking lock: overlapping runs print
`another capture holds the lock` and exit 0 — no double captures, no stale
lockfiles (the lock dies with the process). Two idempotency layers total:
the lock stops CONCURRENT double-appends; the log-derived freeze/close
state (ASSUMPTIONS §14) already made SEQUENTIAL re-runs no-ops.

    crontab -e

Add (one env line per secret, then the schedule — cron has no shell env):

    CLOUDBET_API_KEY=your_key_here
    VPREDICT_INGEST_TOKEN=your_token_here
    */10 * * * * cd $HOME/Downloads/valorant-predictor && ./.venv/bin/python scripts/capture_odds.py --once >> data/odds/capture.log 2>&1 && ./.venv/bin/python scripts/publish_markets.py >> data/odds/publish.log 2>&1

Verify: `crontab -l` shows it; after 10–20 min,
`tail data/odds/capture.log` shows passes; run
`python scripts/capture_odds.py --once` manually while a cron pass runs to
see the lock message once. macOS note: grant `cron` Full Disk Access in
System Settings → Privacy if the log stays empty.

## 7. Alias suggestions for the 11 unlinked (your item 1)

    python scripts/suggest_aliases.py --dry-run   # look first
    python scripts/suggest_aliases.py             # confirm interactively
    python scripts/capture_odds.py --once         # freezes now link

All 11 field cases resolve unambiguously in tests. Capture itself still
never guesses (ASSUMPTIONS §15) — you confirm, aliases.json records.

## 8. Markets on the site (your item 5)

    openssl rand -hex 24    # make a token

Set it as `VPREDICT_INGEST_TOKEN` in BOTH places: Render → Environment
(service restarts), and the crontab line above (plus your shell profile if
you run publish manually). Then:

    python scripts/publish_markets.py

The scoreboard's "Market picks · LIVE" panel fills: selection, model %,
implied %, Shin de-vig %, EV%, result, CLV on graded rows. Guardrails are
UI, not just docs: probabilities outside 0.15–0.88 carry an
`extrapolation` badge and are excluded from EV/CLV aggregates; the whole
panel shows "EV unvalidated — n/100" until 100 market-covered picks have
graded (pre-registered, ASSUMPTIONS §14). Totals picks only exist for
predictions frozen after this deploy (`p_maps_dist` freezes with the first
call — older rows are not re-priced, by design).

## 9. Walk-forward backtest (your item 7) — BUILT. The official run is yours.

The engine replays the live system over history (ASSUMPTIONS §16): the
ledger's own pre-veto quantity via the serving code path, production
cadence + selection per retrain, per-tier BACKTEST section never merged
with LIVE. It was validated with a full sandbox run on the corrected
store; the run YOU execute is the official published record, and the
run-once gate protects it afterwards.

Run it once (the sandbox validation run took ~12 min on 1 core; your
M-series will be faster; needs the migrated store from §2):

    source .venv/bin/activate
    python scripts/evaluate.py --features-cache data/processed/features_cache.parquet   # builds the cache once (~3 min)
    python scripts/backtest.py --features-cache data/processed/features_cache.parquet

It prints per-tier numbers (a per-tier-by-half-year stationarity table
lives in the JSON) and writes `data/processed/backtest.json`
(served summary), a dated copy plus a full per-match rows file under
`data/reports/` (the audit record). Then publish the existing result to
the site — no recompute, run-once stays intact (needs the §8 token in
your shell):

    python scripts/backtest.py --push-only

Hard-refresh the site: the "Backtest — simulated walk-forward" panel
appears under Market picks, per tier, with the separation language.

Re-running later: only after a model change, with
`--replace` (the script refuses otherwise, archives the old result, and
the old file stays in `data/reports/`). Expect small third-decimal
differences vs the sandbox validation numbers in the session report —
cross-machine numeric noise (ASSUMPTIONS §14/§16); anything bigger,
send both files.

## 10. Patch 0020 — calibrated-output bounds (apply BEFORE your official backtest)

Your red test (`p_model == 1.0` exactly) was a saturated PLATT step
function meeting 4-decimal rounding — isotonic is impossible in that
fixture (3 validation rows vs the 800-row gate), which is also why the
isotonic-margin hardening was the wrong tool: it fixes neither observed
failure. Patch 0020 bounds every calibrator's output to [0.005, 0.995]
and clamps published probabilities one rounding-ulp inside (0, 1), with
tests that construct both saturating fits explicitly. Full reasoning:
`ASSUMPTIONS.md` §17, `LOG.md` entry 32.

    git am patches/0020-*.patch
    python -m pytest                 # expect 106 passed
    python scripts/train.py          # new bundle version (behavior rev)

Then run your official backtest per §9 — first run, no --replace needed,
against the hardened model. It will differ from the session report's
PRE-hardening sandbox numbers mainly in the July-2025 stretch; the
POST-hardening sandbox numbers in the session report are your comparison
baseline. Push the site afterwards (`git push`; Render adopts the clip on
deploy — interim delta is nil for in-band predictions, and the next
cadence retrain stamps the new version).

## 11. Patch 0021: homepage + plain-language copy pass (frontend only)

Adds the intro block above the tabs (what the site is, how it works, an
honest one-line standing that reads the same at 1 graded match or 100,
with links into Upcoming and the Backtest), rewrites every panel's copy
in plain language with tooltips on the badges, and removes every em dash
from the frontend and from the served-JSON label strings. No model or
prediction behavior changes: BUNDLE_BEHAVIOR_REV is untouched, no retrain
needed, no backtest implications.

    git am patches/0021-*.patch
    python -m pytest                 # expect 106 passed
    cd frontend && npm test && cd .. # expect 5 pass
    git push                         # then hard-refresh the site

## 12. Verify autonomy yourself (Render logs + two curls)

The scheduler runs a cycle IMMEDIATELY on every boot, then every 6 h. In
the Render service logs, a healthy deployment shows, in order:

1. Once per boot: `refresh scheduler enabled (subprocess), every 21600s`
2. Per cycle, the health record:
   `refresh cycle: {'ts': ..., 'crawl': {'since': ..., 'stored': N},
   'graded': M, 'retrain': 'bundle fresh', 'predict': {'inserted': ...}}`
3. Then: `refresh subprocess ok in Ns`

THE TRAP: steps are fault-isolated, so a cycle whose crawl FAILED still
ends with `refresh subprocess ok`. Health lives in the `refresh cycle:`
dict, not the ok line. Failure signatures to grep for:
`results crawl failed:` (and `'crawl': {'error': ...}` in the dict),
`grading failed:`, `prediction failed:`, `tz migration failed:`,
`refresh subprocess exited N`, `OOM-killed`.

Decision tree: no scheduler line since the last deploy means the env var
isn't active on the running service. Scheduler line but no cycle dicts
means the subprocess can't spawn. Cycle dicts with a crawl error mean
Render can't reach vlr.gg (paste the exact error line; the fix depends on
which exception it is). Cycles with `stored > 0` but `graded` stuck at 0
while finished matches exist means a grading bug; send the whole dict.

From your Mac, no dashboard needed:

    curl -s https://vpredict.onrender.com/api/model | python3 -m json.tool
    curl -s https://vpredict.onrender.com/api/upcoming | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['generated_at'], d['model_version'], len(d['predictions']))"

`generated_at` advances every completed cycle (models and data are not in
git, so any movement is server-side). The clean experiment: note the
time, touch nothing for 7 hours, curl again. If `generated_at` advanced,
autonomy is real; if it's stale, read the logs against the tree above.

## 13. Patch 0022: the TBD row, three-layer fix

Your "TBD vs TBD" row was not backtest data. It was a live LEDGER row
(the graded table rendered untitled beneath the Backtest panel), frozen
from an unresolved vlr bracket slot where both team keys collapse to
"tbd" — the model predicting a team against itself (Elo exactly 0.5 is
the fingerprint; it was also your first graded headline). Patch 0022:
placeholder fixtures are never predicted again, placeholder names
backfill with the real teams at grade time, the graded table has its own
titled panel with the Backtest panel moved last, and headline metrics now
score non-low-history rows only (the backtest's pre-registered rule),
with all counts shown.

    git am patches/0022-*.patch
    python -m pytest                 # expect 108 passed
    git push

Heads-up on what you'll see after deploy: the scoreboard will read
"1 graded, low-history, nothing scored yet" until a real match grades.
That is the honest state; the 0.5373-vs-0.6931 line was the placeholder.
The next refresh cycle backfills the row's real team names on its own.

## 14. Patches 0023 + 0024: features and ensemble evaluation, then the visual redesign

    git am patches/0023-*.patch patches/0024-*.patch
    python -m pytest                 # expect 109 passed
    cd frontend && npm test && cd .. # expect 5 pass
    python scripts/train.py          # features changed: new bundle version
    git push                         # hard-refresh the site afterwards

0023 ships the stand-in features (validation gate passed; full findings
in LOG entry 34 and the new results.md §7, including the ensemble table
and its honestly-biased selector, fixed by §19b next round). 0024 is the
visual layer: hero landing, clickable match detail pages, repo footer
link. No copy or logic rewrites underneath.

**Consequence of 0023 you should act on: the backtest re-runs, labeled.**
The shipped model changed (new features; the version now hashes the
feature list), so per the run-once doctrine your published backtest is
now the record of the PREVIOUS model. Re-run and re-publish, which the
gate will permit precisely because the version changed, archiving the old
result automatically:

    python scripts/evaluate.py --features-cache data/processed/features_cache.parquet   # rebuilds the cache with the new features (~3 min)
    python scripts/backtest.py --features-cache data/processed/features_cache.parquet --replace --push

The old summary lands in data/reports/ untouched; the site serves the new
one labeled with the new version. Expect the same shape of numbers with
third-decimal movement.

**Deploy check that is still open:** the live site's page title was still
the pre-0021 text (with the em dash) when fetched from the build sandbox.
View-source on the site and check the <title>. If it still shows the em
dash after this push, patches 0021+ never actually deployed; check the
Render deploy log for the commit hash it built.

## 15. Patch 0025: maps-total EV excluded, labeled, pending the fix

Owner-directed. Totals picks stay in the table with the model/implied/
de-vig columns intact; the EV cell reads "excluded" with a plain-language
tooltip; aggregates, CLV, and the n>=100 validation gate count clean-EV
picks only. `config.EV_EXCLUDE_TOTALS` flips back only with the
correlation fix (versioned model change + labeled backtest re-run).

    git am patches/0025-*.patch
    python -m pytest                 # expect 110 passed
    git push

The site updates on the NEXT publish_markets run from your cron (the
served markets.json is regenerated Mac-side); nothing else to do.

## 16. Patch 0026: placeholder rows render truthfully; bug-2 determination

    git am patches/0026-*.patch
    python -m pytest                 # expect 111 passed
    git push

**Bug 1 after this deploy:** the TBD detail page states what it is (a
frozen placeholder slot the freeze rule keeps occupied) instead of "TBD
won in 2 maps". Separately, watch whether its NAMES backfill within two
refresh cycles: if they do, the server store has the resolved match and
all is well; if they persist, the server store never received it — which
is bug 2's suspected cause, not a backfill failure.

**Bug 2 determination (two minutes):** in Render logs, grep the latest
`refresh cycle:` line. Read the dict: `'crawl': {'stored': N}` and
`'graded': M`. If crawl shows `{'error': ...}` — paste that exact line;
Render cannot reach vlr.gg and BOTH bugs share that root. If stored > 0
and graded catches up next cycle, it was pacing. Cross-check without the
dashboard: `curl -s https://vpredict.onrender.com/api/scoreboard | python3 -c
"import json,sys; s=json.load(sys.stdin)['summary']; print(s['n_graded'],
s['n_pending'])"` now and again in ~7 hours.

**Investigation script:** `python scripts/investigate_tier_gap.py`
reproduces every number in the session report (train + validation only;
the test window is untouched by structural assertion).

## 17. Patch 0027: deploys retrain once, and the API finally says so out loud

    git am patches/0027-*.patch
    python -m pytest                 # expect 113 passed
    git push

What you will see after this deploy, in order, in the LIVE log tail
(watch the tail during boot; don't rely on dashboard search): the
scheduler line — now actually emitted — then the boot cycle, whose
retrain reason reads "model definition changed (behavior rev None -> 3):
retrain once", then a fresh bundle. Confirm from your Mac:

    curl -s https://vpredict.onrender.com/api/model | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['version'], d['trained_at'])"

The version will be a NEW hash minted on Render (it will match neither
your …-fdda66b1 nor the sandbox's — LightGBM's best_iter sits in the
hashed name and varies per machine; expected, LOG entry 36). If the
"refresh cycle:" lines STILL don't appear in the tail after this, the
thing updating predictions is not this service's scheduler — check
whether a second Render service (a cron job) exists and read ITS logs.

## 18. Patch 0028: the per-map panel tells the truth (Elo lean + calibration note)

    git am patches/0028-*.patch
    python -m pytest                 # expect 114 passed
    cd frontend && npm test && cd .. # expect 5 pass
    git push

Why: LOG entry 37. The identical per-map percentages were correct model
output, not a fallback bug — a step-function calibrator snapping a
sub-point per-map spread onto one output level. This patch changes the
DISPLAY only: the serving payload gains `per_map_elo` (each pool map's
Elo lean, the model's own per-map input) and the panel explains the
calibration step in plain language. No model change, no behavior-rev
bump, nothing written to the ledger.

After Render's next refresh cycle (up to 6 h post-deploy), match pages
grow an Elo lean beside each map, e.g. `+135 Elo` on Split while every
probability still reads the same number — that pairing IS the finding.
The note appears immediately; the chips wait for the first re-predict
because the seed JSON predates the field.

Pre-registered, NOT in this patch (ASSUMPTIONS §21): a smooth monotone
calibration candidate joins the menu next model round, selected by the
standard validation rule, with a BUNDLE_BEHAVIOR_REV bump so the deploy
retrains once. Do not hand-swap the calibrator before then.

## 19. Patch 0029: the recent-window numbers become a served, sourced artifact

    git am patches/0029-*.patch
    python -m pytest                 # expect 118 passed
    python scripts/evaluate.py       # regenerates results.md + results_summary.json

evaluate.py now writes `data/reports/results_summary.json` from the SAME
in-scope variables that fill the markdown tables — the JSON cannot say
anything results.md does not. New endpoints mirror the markets/backtest
pattern exactly: `GET /api/results` serves
`data/processed/results_summary.json` (empty shape until first publish),
`POST /api/ingest/results` is Bearer-token gated with the token you
already use for publish_markets.py.

Publish order matters — the ingest endpoint must be deployed first:

    git push                         # deploy (with 0030 applied too)
    # wait for Render deploy to finish, then:
    python scripts/publish_results.py   # needs VPREDICT_INGEST_TOKEN exported

`publish_results.py` never computes a number: it validates (refusing
anything synthetic-watermarked or structurally incomplete), copies to
data/processed/, and POSTs. Re-running evaluate.py before publishing
reproduces tonight's fresh numbers as long as the local store hasn't
topped up since; whatever it prints is what the site will show.

## 20. Patch 0030: the homepage leads with the recent window, sourced

    git am patches/0030-*.patch
    python -m pytest                 # expect 118 passed (unchanged)
    cd frontend && npm test && cd .. # expect 5 pass
    git push

What changes where: the hero's prose claim becomes a stat card fed by
GET /api/results (series log loss, series accuracy, map log loss, green
marks the winner), followed by the honest backtest framing and a
clickable "next up" strip with the live series prediction. The model tab
now opens with the full recent-window panel (both grains, Brier, per
tier, provenance line naming evaluate.py and the evaluated model) and
links to the backtest; bundle details follow. The backtest panel's
summary sentence now says outright that it replays the full history
including the early data-starved era. Zero em dashes anywhere in
displayed copy; no number is typed into the frontend.

Until you run publish_results.py (section 19), /api/results is empty:
the hero falls back to the previous prose and the model tab omits the
panel — nothing breaks, nothing is invented. After the publish, hard
refresh and the card appears with exactly the numbers evaluate.py
printed. If the fresh run's numbers ever stop supporting the framing,
the card will say so on its own (green flips sides); the prose fallback
is the only place a claim lives without numbers behind it, so re-check
it whenever the story changes.

## 21. Patch 0031: logo goes home, the hero clears its bar, ties say so inline

    git am patches/0031-*.patch
    python -m pytest                 # expect 118 passed (unchanged)
    cd frontend && npm test && cd .. # expect 5 pass
    git push

Three small confirmed items. Clicking the vpredict wordmark now returns
to the homepage (detail closed, upcoming tab, scrolled up) from
anywhere. The intro paragraph no longer collides with the teal/coral
bar: the bar left the scaling SVG and is pinned in layout coordinates
with guaranteed clearance (LOG entry 38 has the geometry story). And the
per-map panel now says, inline among the rows and only when ties are
actually on screen, that ties are expected and the Elo lean carries the
real per-map difference.
