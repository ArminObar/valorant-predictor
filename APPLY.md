# APPLY — patch 0073: display-consistency sweep (audit fixes)

One patch, six audited findings fixed plus one guard. LOG entries 52-54,
ASSUMPTIONS §55. No dependency changes, no model-behavior changes,
BUNDLE_BEHAVIOR_REV deliberately not bumped (no retrain on deploy).

What it fixes: the pending list dropping the soonest matches past its
cap (soonest-first at 500, counts always from the uncapped summary);
the Schedule masthead's dead "live accuracy" key (plus the audit
fixture drift that green-washed it, and the match-page fixture that had
only ever exercised the fallback branch); the Markets win-rate/graded
labels; the Schedule's version attribution (serving bundle vs per-pick
frozen versions, now shown on the match page); the unattributed pending
probability (favored view, same string as the Schedule card); and a
key-matched name mapping so a listing that reorders teams can never
caption a frozen probability with the wrong name. All percentage
strings now come from one module, `frontend/src/lib/prob.js`.

Checked, not changed: /api/model already reads the bundle from disk on
every request — no cache exists; the behavior is pinned by a new
regression test that swaps the bundle mid-process. The Model tab's test
metrics stay pinned to evaluate.py's artifact on purpose.

## Base

Applies on top of origin/main at adfc3d2 (patch 0072, tooltip repair).

## Apply

```bash
cd ~/Downloads/valorant-predictor
ls ~/Downloads/0073-*.patch || ls patches/applied/0073*.patch
git am ~/Downloads/0073-*.patch
git log --oneline -1
```

The last line must show the 0073 subject (display-consistency sweep).
If `git am` fails partway: `git am --abort`, confirm
`git status --porcelain` is clean, retry.

## Gates — no dependency change, warm tree is fine

```bash
python3 -m pytest            # expect 177 passed
cd frontend
npm test                     # expect pass 44
npm run build
npm run audit                # lint 0 errors; RENDER AUDIT: all routes clean;
                             # TIP AUDIT: all 8 pops anchored, on top, on screen
cd ..
```

The tip-geometry stage needs your installed Chrome; it ran everywhere
else in the build environment and must complete here before shipping.

## Ship

```bash
git push
```

## Verify against live production after deploy

The audit's cross-endpoint check, now asserting the fixed behaviors.
Run it once Render finishes deploying:

```bash
python3 - <<'PYEOF'
import json, urllib.request
g = lambda p: json.load(urllib.request.urlopen(
    "https://vpredict.onrender.com/api/" + p))
up = g("upcoming"); sb = g("scoreboard"); mk = g("markets")
preds = up["predictions"]
rows = {str(r["match_id"]): r for r in sb["pending"] + sb["graded"]}
bad = 0
for p in preds:
    mid = str(p["match_id"]); md = g("match/" + mid)
    for src in (md.get("ledger"), md.get("prediction"), rows.get(mid)):
        if src and (src["p_model"] != p["p_model"]
                    or src["p_elo"] != p["p_elo"]):
            bad += 1; print("VALUE MISMATCH", mid)
    if mid not in rows:
        bad += 1; print("MISSING FROM SCOREBOARD", mid)   # truncation fix
for k in mk.get("picks", []):
    r = rows.get(str(k["match_id"]))
    if r and round(k["p_model"], 4) not in (round(r["p_model"], 4),
                                            round(1 - r["p_model"], 4)):
        bad += 1; print("MARKET MISMATCH", k["match_id"])
s = sb["summary"]
if s["n_pending"] != len(sb["pending"]) and len(sb["pending"]) != 500:
    bad += 1; print("PENDING COUNT/LIST MISMATCH",
                    s["n_pending"], len(sb["pending"]))
print("serving bundle:", g("model").get("version"),
      "| predictions header:", up.get("model_version"),
      "| per-row versions:", sorted({p["model_version"] for p in preds}))
print("checked", len(preds), "matches +", len(mk.get("picks", [])),
      "picks:", bad, "problems")
PYEOF
```

Expect `0 problems`. The version line is informational: header and
per-row versions may legitimately differ after a retrain; the site now
says so instead of implying otherwise.

## What to check on the live site after deploy

- Schedule masthead shows two stats: locked picks AND live accuracy
  (the second has never rendered before this patch).
- Schedule subtitle reads "Serving bundle …; each pick keeps the
  version it froze under."
- A pending row on the Scoreboard names the favored team next to its
  percentage, matching the Schedule card for the same match.
- A match page's locked line shows "· model <version>" for the pick.
- Markets: the gate line says "EV-clean picks," and the summary line
  says win rate covers every graded pick.
