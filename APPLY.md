# APPLY — patch 0075: mobile pass + hero autoplay resilience + TBD resolution

One patch, three approved items in priority order. LOG entries 56-58,
ASSUMPTIONS §57. No dependency changes, no model-behavior changes,
BUNDLE_BEHAVIOR_REV not bumped. One pre-registered behavior change:
half-resolved bracket slots ("X vs TBD") no longer freeze predictions;
they get a real first call once fully resolved (§57).

Item 1 — mobile: kv table scroll-wrapped; tip buttons gain a ~41px hit
area (visual unchanged); pending rows and tabs touch-sized at <=720px;
masthead stats wrap; root clips stray sideways scroll; NEW permanent
gate `npm run audit:mobile` (real Chrome, 390x844, touch, all 8 routes:
hard-fails horizontal overflow, probes effective tap areas).

Item 2 — hero video: element and files were already policy-correct (no
audio track exists; verified). Ships a readiness-race retry
(loadeddata/canplay), preload="auto", and first-touch recovery for
OS-refused autoplay (iOS Low Power Mode cannot be autoplayed through,
by spec; the first tap anywhere now starts it).

Item 3 — TBD resolution: placeholder keys are adoptable, never
identities. Placeholder sides adopt the listing identity at publish
time; the LEDGER heals at resolution (keys/names only — the frozen call
is untouched, verified on the two real snapshot rows); the half-resolved
guard hole is closed; every non-aligned naming event is flagged
(per-row name_status + payload "naming" block + counters).

## Base

Applies on top of origin/main at 2670f7b (patch 0074).

## Apply

```bash
cd ~/Downloads/valorant-predictor
ls ~/Downloads/0075-*.patch || ls patches/applied/0075*.patch
git am ~/Downloads/0075-*.patch
git log --oneline -1
```

The last line must show the 0075 subject. If `git am` fails partway:
`git am --abort`, confirm `git status --porcelain` clean, retry.

## BEFORE snapshot — run against live BEFORE pushing

```bash
python3 - <<'PYEOF' | tee /tmp/tbd-before.txt
import json, urllib.request
u = json.load(urllib.request.urlopen("https://vpredict.onrender.com/api/upcoming"))
s = json.load(urllib.request.urlopen("https://vpredict.onrender.com/api/scoreboard"))
seen = set()
for r in u["predictions"] + s["pending"]:
    if "tbd" in (r["team1_name"] + r["team2_name"]).lower() and r["match_id"] not in seen:
        seen.add(r["match_id"])
        print(r["match_id"], "|", r["team1_name"], "vs", r["team2_name"],
              "| https://www.vlr.gg/" + str(r["match_id"]))
print(len(seen), "TBD-named rows before the fix")
PYEOF
```

## Gates — no dependency change, warm tree is fine

```bash
python3 -m pytest            # expect 184 passed
cd frontend
npm test                     # expect pass 44
npm run build
npm run audit                # lint 0 errors; render clean; tips all 8;
                             # MOBILE AUDIT: all 8 routes fit 390px
cd ..
```

audit:mobile is new and REQUIRED from now on for any frontend change —
same Chrome requirement as audit:tips.

## Ship

```bash
git push
```

## AFTER verification — deployed AND one 30-minute refresh has run

The refresh cycle's publish step performs the resolution, so allow one
full refresh (not just an odds tick).

```bash
python3 - <<'PYEOF'
import json, urllib.request
u = json.load(urllib.request.urlopen("https://vpredict.onrender.com/api/upcoming"))
s = json.load(urllib.request.urlopen("https://vpredict.onrender.com/api/scoreboard"))
left = [r for r in u["predictions"] + s["pending"]
        if "tbd" in (r["team1_name"] + r["team2_name"]).lower()]
print("naming block:", u.get("naming"))
print(len(left), "TBD-named rows remain")
for r in left[:10]:
    print(" ", r["match_id"], r["team1_name"], "vs", r["team2_name"],
          "| check https://www.vlr.gg/" + str(r["match_id"]))
PYEOF
```

Expected: every match whose vlr page shows two real names has left the
TBD list, `naming.resolved` lists the healed ids on the cycle that healed
them, and any row still TBD-named should be TBD on vlr as well (a
genuinely unresolved slot — correct). Rows listed under
`naming.unmatched` are the flag working: real-key mismatches (the rebrand
subspecies) surfacing themselves for a look.

## Mobile verification — this IS the real-device pass

1. `npm run audit:mobile` (part of `npm run audit`) — real Chrome,
   phone viewport, all routes.
2. On your actual phone after deploy: each page scrolls only
   vertically; info tips open on a comfortable tap; pending rows tap
   easily; the nav bar is compact; the hero autoplays (and in Low Power
   Mode, starts on your first touch anywhere).
