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
