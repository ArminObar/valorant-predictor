# APPLY — patch session 2026-07-28/29/30: patches 52–59

**Fifth pass added patch 0059** (LOG 47, ASSUMPTIONS §47): record-level
priceability filter (finite and above 1.0 covers 0.0, negatives, NaN,
inf), entry falls back to the first priceable freeze, per-group
last-resort isolation with n_group_errors, extended Markets note.
IMPORTANT: 0057 and 0058 are applied locally but were never pushed;
origin/main ended at 0056 when this was diagnosed. Run
`git log --oneline origin/main..HEAD` to see the unpushed commits,
apply 0059 on top, then one `git push` publishes all three and the
deploy picks them up together. Verify the deploy afterwards in Render
Shell: python3 -c "import vpredict.odds.markets as m, inspect;
print('n_group_errors' in inspect.getsource(m))" should print True.


**Fourth pass added patch 0058** (the markets-build outage fix, LOG 46,
ASSUMPTIONS §46): unpriceable records skip with a visible counter, the
None-line sort is deterministic, --push sends a 24 h idempotent window.
Apply after 0057, `python -m pytest` (expect 169), frontend gates,
push. The build self-heals on the first tick after deploy: check
markets.json generated_at is fresh within 10 minutes and the Render log
"markets" line shows picks plus a skipped count. The odds log needs no
surgery; the poison record stays, counted.


**Third pass added patch 0057**: chronological ordering with day
separators site-wide (Upcoming and Scoreboard pending soonest first,
Scoreboard graded and Markets newest first, day boundaries in the
viewer's timezone). Display only, sorted client-side; apply after 0056,
rerun the frontend gates, push. No server steps.


**Second pass added patch 0056**: the /how explainer page (linked from
the homepage and footer) and short hover tooltips on all five section
titles, each linking to /how. Content only, no logic or data changes;
apply it after 0055 with the same `git am` flow, rerun the frontend
gates, push. No new server steps.


What landed, mapped to your go list. **1** the frozen-payload fix:
/api/upcoming now serves the ledger's first call verbatim, uncalled
matches are never displayed, and all-frozen cycles skip the feature
build (patch 0052, LOG 44, ASSUMPTIONS §40). **2** 30-minute refresh
interval (patch 0053, ASSUMPTIONS §41). **3** Cloudbet capture and the
markets build run in the refresh cycle on the server, on a 10-minute
odds tick between full cycles; the Mac keeps only the Pinnacle leg and
pushes it through the new validated /api/ingest/odds (patch 0054,
LOG 45, ASSUMPTIONS §42). **4** best-line selection across books with
the three pre-registered rules and the bias footnote (patch 0055,
ASSUMPTIONS §43). The OddsPapi trial is **not wired in**: a standalone
probe script was delivered separately, report-first.

## Apply

```bash
mv ~/Downloads/005[2345]-*.patch ~/Downloads/valorant-predictor/patches/
cd ~/Downloads/valorant-predictor
git am patches/0052-*.patch patches/0053-*.patch patches/0054-*.patch patches/0055-*.patch
python -m pytest                       # expect 163 passed
cd frontend && rm -rf node_modules && npm ci && npm test && npm run build && cd ..
git push
```

## One-time steps after the deploy (order matters)

1. Render dashboard, Environment: add `CLOUDBET_API_KEY` (value from
   your crontab env; it can leave the Mac's crontab after step 3).
   `VPREDICT_REFRESH_INTERVAL_S=1800` and `VPREDICT_ODDS_TICK_S=600`
   come from render.yaml; confirm they synced after the deploy.
2. Copy the alias table to the server (rarely changes; repeat only when
   suggest_aliases adds entries): gzip `data/odds/aliases.json` into
   the usual reseed flow, target `/data/odds/aliases.json`.
3. Seed the server's odds log with the Mac's full capture history, once
   (idempotent, safe to re-run):
   `python scripts/capture_odds.py --push-log`
4. Change the Mac crontab line from
   `capture_odds.py --once && publish_markets.py` to
   `capture_odds.py --once --sources pinnacle --push`
   (publish_markets stays available for offline analysis; the server
   now builds markets.json itself).
5. Sanity, next morning: /markets shows book labels and the consensus
   column; Render logs show "odds tick" every 10 min and a full cycle
   every 30; an Upcoming card and its detail page show the same number.
