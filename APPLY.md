# APPLY — patch session 2026-07-26 (late): patches 43–45

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
The map-pool question was an investigation, so it is reported in chat
with reproduction commands — nothing built, your call pending.

Run everything from the repo root: `cd ~/Downloads/valorant-predictor`.

## 1. Apply and verify

First, per your own workflow note, confirm the downloads exist:

    ls ~/Downloads/00*.patch

Move them in and apply, in order:

    mkdir -p patches
    mv ~/Downloads/0043-*.patch ~/Downloads/0044-*.patch ~/Downloads/0045-*.patch patches/
    git am patches/0043-*.patch patches/0044-*.patch patches/0045-*.patch

If `git am` complains about uncommitted local edits: `git stash`, apply,
`git stash pop`.

Then verify:

    source .venv/bin/activate
    python -m pytest                  # expect 145 passed
    cd frontend
    rm -rf node_modules && npm ci     # cold install, per LOG entry 40
    npm test                          # expect 12 pass
    npm run build                     # must succeed
    cd ..

`python -m pytest` count: 143 in the sandbox came from its Python 3.12;
your 3.14 venv has passed the same suite with 2 extra parametrizations
before — the number that matters is **0 failed**, and the two new tests
are `test_spa_fallback_serves_shell_for_client_routes` and
`test_spa_fallback_never_masks_api_or_asset_404s` in `tests/test_api.py`.

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

## 4. What was deliberately not done

- No "tailing the model" payout number (your instruction; the gated
  Market Picks EV/CLV panel remains the correct version of that idea).
- No map-pool code change: the investigation (in chat) found the pool
  logic working exactly as specified and the spec lagging the June 24
  rotation by design; options are listed there and wait on your
  decision.
- No commit-authorship rewrite: that remains your deliberate,
  well-rested, mirror-backup-first action from the previous session.
