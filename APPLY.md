# APPLY — patch 0078: audit hardening + alias hygiene + Trends + prior-map counts

One patch, four approved items, packaged together by owner direction.
Supersedes the four individually numbered files (0078-0081) delivered
earlier in this session: apply ONLY this one. No dependency changes.
No model serving change: BUNDLE_BEHAVIOR_REV not bumped (audit tooling,
odds linking, derived views, display metadata only).

Item A — audit (LOG 60): the render gate now asserts payload-driven
content per route (MUST_CONTAIN), with the markets mock carrying a
populated unit_tracker. Proven both ways: the committed Markets page
renders the tracker panel in the harness; the pre-0077 page fails it.
Item B — alias hygiene (LOG 61, ASSUMPTIONS §60): poisoned
Cloud9 -> LOUD seed alias removed; raw identity now beats alias
redirect; any name match is refused when book and prediction starts
differ by > 6 h; unlinked fixtures stored once, counted every pass;
markets counts orientation-dropped groups (skipped.n_groups_unpriced).
Item C — Trends (ASSUMPTIONS §61): seventh tab, per-team last-10-map
windows (win rate, spread, pistols, combined kills, FK/12, won-round
method mix, agents) built each full cycle into trends.json, served at
/api/trends. Clutch/economy trends explicitly absent (inputs never
scraped; stated on the page).
Item D — prior-map counts (ASSUMPTIONS §62): team1/team2_prior_maps
frozen with the low_history flag (ledger ALTERs, idempotent), published
verbatim, shown as "low history (a/b)" with named tooltips on Schedule,
Scoreboard, and the match page; pre-column rows stay null.

Pre-registered behavior changes: /api/upcoming rows and new ledger rows
gain team1_prior_maps/team2_prior_maps; markets skipped gains
n_groups_unpriced; capture stops re-appending unlinked fixtures every
pass; a 7th "trends" tab and /api/trends appear; refresh report gains a
"trends" phase.

## Base

Applies on top of patch 0077 (the unit-tracker commit).

## Apply

```bash
cd ~/Downloads/valorant-predictor
ls ~/Downloads/0078-*.patch || ls patches/applied/0078*.patch
git am ~/Downloads/0078-*.patch
git log --oneline -1
```

The last line must show the 0078 subject (audit + alias hygiene +
trends + prior-map counts). If `git am` fails partway: `git am --abort`,
confirm `git status --porcelain` clean, retry. If both an old four-file
set and this single file are in Downloads, apply ONLY this one.

## Production aliases.json — optional one-line edit (Render Shell)

The disk copy was seeded once, so the seed fix does not reach it. The
two code layers in this patch (raw-identity precedence + the 6 h start
gate) neutralize the entry either way; removing it is hygiene, not a
requirement. In the Render Shell, whenever convenient:

```bash
python3 - <<'PYEOF'
import json
p = "/data/odds/aliases.json"
d = json.load(open(p))
gone = d.pop("Cloud9", None)
open(p, "w").write(json.dumps(d, indent=1, ensure_ascii=False) + "\n")
print("removed:", gone, "| remaining:", len(d))
PYEOF
cat /data/odds/aliases.json
```

## Gates (all must pass before push)

```bash
source .venv/bin/activate
python3 -m pytest
cd frontend
npm test
npm run build
npm run audit
cd ..
```

Expect 210 Python tests and 44 JS tests. Sandbox ran every stage
runnable there green, including the REAL Chrome tips and mobile audits
against this exact tree (10 routes total across stages; content
assertions on /markets, /trends, /upcoming; tips expects exactly 1
icon on /trends; mobile covers /trends at 390x844). Run the full
`npm run audit` locally anyway per standing procedure.

## Push, then verify live

```bash
git push
# after Render deploys, the served bundle must match the local build:
curl -s https://vpredict.onrender.com/ | grep -o 'index-[a-zA-Z0-9]*\.js'
ls frontend/dist/assets/*.js
```

The filenames must match (Render "Live" is not proof). The unit
tracker panel is proven to render and paint from this tree, so if the
hashes match and the panel still is not on /markets in your browser,
hard-refresh (cached index.html); if the hashes differ, check Render's
Events/build log for this commit (the 0075 incident class).

After the next FULL 30-minute cycle (not the 10-minute odds tick):

```bash
python3 - <<'PYEOF'
import json, urllib.request
t = json.load(urllib.request.urlopen("https://vpredict.onrender.com/api/trends"))
print("trends teams:", t.get("n_teams"), "generated:", t.get("generated_at"))
u = json.load(urllib.request.urlopen("https://vpredict.onrender.com/api/upcoming"))
withc = [p for p in u["predictions"] if p.get("team1_prior_maps") is not None]
print("upcoming rows with prior-map counts:", len(withc), "of",
      len(u["predictions"]))
m = json.load(urllib.request.urlopen("https://vpredict.onrender.com/api/markets"))
print("unpriced groups counted:", m.get("skipped", {}).get("n_groups_unpriced"))
PYEOF
```

Trends should report ~200 teams; the /trends tab should render the
table. Prior-map counts appear on rows frozen AFTER this deploy (older
frozen rows stay null by design, §62). In the runtime logs, any
`LINK GATE:` warning is the start-time gate refusing a cross-link, and
`UNLINKED` lines now appear once per fixture instead of every pass.

## Rollback

```bash
git revert <0078-sha>          # or reset --hard before push
```

Everything is additive: derived views, audit tooling, nullable ledger
columns (the ALTERs are harmless to leave in place on revert).
