# APPLY — patch 0079: Trends date-range and tournament scoping, all-history default

One patch, one owner-approved item (ASSUMPTIONS §63). No dependency
changes, no model serving change, BUNDLE_BEHAVIOR_REV untouched.

RETRACTION NOTE: an earlier 0079 file named
"0079-tracker-backdate-..." was delivered and then retracted by owner
direction (the unit tracker keeps its 2026-08-08 start boundary, §59
addendum). If that file is still in Downloads, DELETE it; apply only
this Trends patch as 0079.

What ships: the Trends tab defaults to ALL real scraped history
(career table over the full store), keeps the §61 recent-form view as
a "current form" preset, and adds custom scoping by date range and
tournament. The store decomposes each full cycle into a fact table
(one row per team-map, trends_rows.json) plus precomputed views
(trends.json); /api/trends serves presets statically and aggregates
custom scopes from the cached fact table per request (measured 15-43 ms
on the two-year store). Tournament picker uses normalized names (872
keys from 3,088 raw event strings, heuristic pinned by test). Metrics
became coverage-aware: a map missing a metric's inputs is excluded
from numerator and denominator (matters for FK in two ~88%-coverage
historical quarters), and nothing is estimated: unknown tournaments
and bad dates clamp to an empty view, never an error.

Pre-registered behavior changes: /api/trends response shape becomes
{generated_at, params, tournaments, view:{scope, n_teams, teams}} and
accepts ?preset=current_form, ?from=YYYY-MM-DD, ?to=YYYY-MM-DD,
?event=<tournament name>; the refresh report's trends line gains
teams_all/teams_current/tournaments/rows; processed/ gains
trends_rows.json (~7 MB).

## Base

Applies on top of patch 0078 (the combined audit/alias/trends/counts
commit).

## Apply

```bash
cd ~/Downloads/valorant-predictor
ls ~/Downloads/0079-*.patch || ls patches/applied/0079*.patch
git am ~/Downloads/0079-trends-*.patch
git log --oneline -1
```

The last line must show the 0079 Trends-scoping subject. If `git am`
fails partway: `git am --abort`, confirm `git status --porcelain`
clean, retry.

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

Expect 217 Python tests and 44 JS tests. Sandbox ran everything green
on this exact tree, including real-Chrome tips (9 popovers) and mobile
(9 routes at 390x844, /trends with the new controls included).

## Push, then verify live

```bash
git push
curl -s https://vpredict.onrender.com/ | grep -o 'index-[a-zA-Z0-9]*\.js'
ls frontend/dist/assets/*.js
```

After the next FULL 30-minute cycle (the fact table builds there):

```bash
python3 - <<'PYEOF'
import json, urllib.request
def get(u):
    return json.load(urllib.request.urlopen(
        "https://vpredict.onrender.com" + u))
d = get("/api/trends")
print("all-history teams:", d["view"]["n_teams"],
      "| tournaments:", len(d["tournaments"]))
c = get("/api/trends?preset=current_form")
print("current-form teams:", c["view"]["n_teams"])
name = urllib.parse.quote(d["tournaments"][0]["name"])
e = get("/api/trends?event=" + name)
print("event scope:", d["tournaments"][0]["name"], "->",
      e["view"]["n_teams"], "teams")
q = get("/api/trends?from=2025-01-01&to=2025-03-31")
print("2025-Q1 scope:", q["view"]["n_teams"], "teams")
PYEOF
```

Expected magnitudes from the seed: ~800 all-history teams, ~200
current-form, ~870 tournaments, 2025-Q1 around 260 teams. On /trends:
the page lands on "all history", the two preset pills switch views,
the date inputs and tournament box scope live, and out-of-data scopes
show the empty-state line instead of an error. Until the first full
cycle after deploy, custom scopes report "fact table not built yet" in
the scope block: expected, not a failure.

## Rollback

```bash
git revert <0079-sha>          # or reset --hard before push
```

Derived views and display only. trends_rows.json is regenerated or
ignored either way.
