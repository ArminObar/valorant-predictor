# APPLY — patch 0074: canonical market sides + explicit pick labeling

One patch, the two approved fixes from the markets investigation.
LOG entry 55, ASSUMPTIONS §56. No dependency changes, no model-behavior
changes, BUNDLE_BEHAVIOR_REV deliberately not bumped (no retrain on
deploy). markets.json rebuilds on the first 10-minute odds tick after
the deploy, so allow one tick before judging the live numbers.

Fix 1 — the orientation scramble (the real bug from item 2): when two
books listed the same match in opposite home/away order, the per-side
best-price comparison collapsed onto one team (the other never entered
the menu) and the consensus de-vig mixed a favourite's number with an
underdog's — the displayed value that matched no book and no baseline.
Sides are now canonical (team1/OVER vs team2/UNDER) and every capture —
entry, close, every consensus contribution — maps through its own
linked orientation. Selection, EV, CLV, grading, and naming all follow.
Four new regression fixtures with disagreeing orientations.

Fix 2 — pick labeling (item 1, owner-approved semantics): max-EV
selection stays, including negative-EV picks. The pick side now wears a
distinct badge, the column is named "pick", a note above the table
states every number in a row belongs to the badged side, and any row
where the model leans the other way says so inline with the complement
probability. Applied on /markets, the Scoreboard embed, and the match
page's market table.

## Base

Applies on top of origin/main at 86e7397 (patch 0073).

## Apply

```bash
cd ~/Downloads/valorant-predictor
ls ~/Downloads/0074-*.patch || ls patches/applied/0074*.patch
git am ~/Downloads/0074-*.patch
git log --oneline -1
```

The last line must show the 0074 subject (canonical market sides). If
`git am` fails partway: `git am --abort`, confirm `git status
--porcelain` is clean, retry.

## Gates — no dependency change, warm tree is fine

```bash
python3 -m pytest            # expect 181 passed
cd frontend
npm test                     # expect pass 44
npm run build
npm run audit                # lint 0 errors; RENDER AUDIT: all routes clean;
                             # TIP AUDIT: all 8 pops anchored, on top, on screen
cd ..
```

## BEFORE snapshot — run this against live BEFORE pushing

Capture the current picks so the after-state has something honest to be
compared with:

```bash
python3 - <<'PYEOF' | tee /tmp/markets-before.txt
import json, urllib.request
d = json.load(urllib.request.urlopen(
    "https://vpredict.onrender.com/api/markets"))
for p in d["picks"]:
    print(f"{p['match_id']} {p['match']} | pick {p['selection']} "
          f"@{p['price_entry']} {p['source']} | model {p['p_model']} "
          f"| shin {p['shin']} cons {p['shin_consensus']} "
          f"| ev {p['ev_pct']}")
    if p["n_books"] > 1 and abs(p["shin"] - p["shin_consensus"]) >= 0.05:
        print("  ^ SCRAMBLE SUSPECT (mixed-side consensus)")
    if p["ev_pct"] < 0:
        print("  ^ negative-EV pick (expected; now labeled in the UI)")
PYEOF
```

## Ship

```bash
git push
```

## AFTER verification — once deployed AND one odds tick has run

```bash
python3 - <<'PYEOF' | tee /tmp/markets-after.txt
import json, urllib.request
d = json.load(urllib.request.urlopen(
    "https://vpredict.onrender.com/api/markets"))
bad = 0
for p in d["picks"]:
    print(f"{p['match_id']} {p['match']} | pick {p['selection']} "
          f"@{p['price_entry']} {p['source']} | model {p['p_model']} "
          f"| shin {p['shin']} cons {p['shin_consensus']} "
          f"| ev {p['ev_pct']}")
    if p["n_books"] > 1 and abs(p["shin"] - p["shin_consensus"]) >= 0.05:
        bad += 1; print("  ^ STILL SCRAMBLED — should not happen")
print(bad, "problems")
PYEOF
diff /tmp/markets-before.txt /tmp/markets-after.txt
```

Expect `0 problems`. In the diff, expect: every SCRAMBLE SUSPECT line
gone, with those matches' consensus now within a couple of points of
their own-book shin; some of those selections legitimately flipping to
the previously shut-out team (usually the favourite); negative-EV picks
still present — that is the recorded semantics — now badged and
annotated in the UI. Entry prices and CLV on unaffected picks should
not move.

## What to check on the live site after deploy

- Markets table: the pick name sits in a highlighted badge, the column
  header reads "pick", and the note above the table explains that every
  number in a row belongs to the badged side.
- Any underdog pick (model below 50%) carries "model favours the other
  side X%" inline — the dual-team ambiguity this patch was approved to
  remove.
- Same treatment on the match page's Market comparison table.
