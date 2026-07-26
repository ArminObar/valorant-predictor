# APPLY — patch session 2026-07-26 (late): patches 43–46

What landed, mapped to your list: **1** tab-click trap fixed (clicking
any top-level tab always shows that tab's own default view; a match
detail can no longer shadow it) and **2** real routes — `/upcoming`,
`/scoreboard`, `/model`, `/backtest`, `/match/:id` — so browser
back/forward, reloads, and shared deep links behave like any normal
site (patch 0043, LOG entry 42, ASSUMPTIONS §34). **3** the scoreboard
page now ends with a one-paragraph backtest summary whose numbers are
derived at render time from the same `/api/backtest` payload, linking
to the full per-tier table at its new home, the `backtest` tab (patch
0044, ASSUMPTIONS §35). Layout only: no metric, and none of the
"Elo wins most of the history" framing, changed. The "what you'd have
won tailing the model" percentage was **not built**, as instructed.
The map-pool investigation came back with your decision — option B —
and patch 0046 ships it: pool MEMBERSHIP is now recency-weighted
(14-day half-life inside the unchanged 60-day window; ASSUMPTIONS §36,
new tests, plus `scripts/inspect_pool.py` to see the decision on any
store). Measured on the real store: the corrected pool applies
retroactively on deploy — Sunset in, Fracture out, immediately; Pearl
yields the last slot to Summit as live Stage 2 plays accrue. Averaging
across the pool stays uniform, frozen ledger rows never move, and the
published backtest artifact is untouched (a future backtest RE-RUN
inherits the rule, run-once stays run-once).

Run everything from the repo root: `cd ~/Downloads/valorant-predictor`.

## 1. Apply and verify

First, per your own workflow note, confirm the downloads exist:

    ls ~/Downloads/00*.patch

Move them in and apply, in order:

    mkdir -p patches
    mv ~/Downloads/0043-*.patch ~/Downloads/0044-*.patch \
       ~/Downloads/0045-*.patch ~/Downloads/0046-*.patch patches/
    git am patches/0043-*.patch patches/0044-*.patch \
       patches/0045-*.patch patches/0046-*.patch

If `git am` complains about uncommitted local edits: `git stash`, apply,
`git stash pop`.

Then verify:

    source .venv/bin/activate
    python -m pytest                  # expect 152 passed
    cd frontend
    rm -rf node_modules && npm ci     # cold install, per LOG entry 40
    npm test                          # expect 12 pass
    npm run build                     # must succeed
    cd ..

`python -m pytest` count: 150 in the sandbox on its Python 3.12; your
3.14 venv carries 2 extra parametrizations — the number that matters is
**0 failed**. New this session: 2 SPA-fallback tests in
`tests/test_api.py` and 7 pool tests in `tests/test_pool.py`. Patch
0046 is backend-only, so the frontend cold install below is for
0043/0044 and does not need repeating for it. Optional but satisfying —
watch the pool decide, on your local store:

    python scripts/inspect_pool.py

**Expected `npm audit` output — read before reacting:** it will report
GHSA-qwww-vcr4-c8h2 (React Router RSC-mode CSRF; shows as 2 highs, one
per package). This is known, documented, and deliberately accepted:
the vulnerable code path is framework-mode server actions, which this
static SPA does not have; the advisory-clean line is react-router 8,
which requires React ≥ 19.2 — a framework major that gets its own
patch later, not a ride-along. Full reasoning: ASSUMPTIONS §34,
including why npm's suggested "fix" (a downgrade) would be worse.

## 2. Look at it locally (optional but 30 seconds)

    cd frontend && npm run dev

Vite's dev server handles the SPA routes natively and proxies `/api` to
`localhost:8000` if you have the API running. Click a match, then click
a tab: the tab wins now. Use the browser back button: it works. Or test
the built article exactly as production serves it:

    cd frontend && npm run build && cd ..
    uvicorn vpredict.serving.api:app --port 8000

then open http://localhost:8000/scoreboard directly — a deep link that
would have 404'd before patch 0043.

## 3. Deploy

Nothing in `render.yaml` or the `Dockerfile` changes; push and Render
rebuilds both stages (the Dockerfile's `npm ci` picks up the new
lockfile, the pip install picks up the api change):

    git push

After deploy, three spot checks:

    https://vpredict.onrender.com/scoreboard     -> loads (deep link)
    https://vpredict.onrender.com/api/health     -> JSON, ok true
    https://vpredict.onrender.com/assets/nope.js -> 404, not HTML

Fourth check, for the pool: in Render's Shell tab run

    python scripts/inspect_pool.py

(read-only) — expect Sunset in and Fracture out of the serving pool at
once; Pearl's slot passes to Summit as Stage 2 plays land over the
coming days. Upcoming predictions adopt the new pool at the first
refresh cycle after deploy; already-frozen ledger rows keep their
original calls by design.

## 4. What was deliberately not done

- No "tailing the model" payout number (your instruction; the gated
  Market Picks EV/CLV panel remains the correct version of that idea).
- No half-life tuning to force a same-day Summit flip: even a 7-day
  half-life cannot seat 15 stored plays on the frozen snapshot (§36),
  so 14 stands as agreed instead of being bent to flatter deploy day.
  Option C (tier-restricted pool) stays future work.
- No commit-authorship rewrite: that remains your deliberate,
  well-rested, mirror-backup-first action from the previous session.
