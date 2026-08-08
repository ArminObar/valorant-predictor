# APPLY — patches 0076 + 0077: reschedule-gap fix, then the unit tracker

Two patches, applied in order. 0076 is the approved reschedule-gap fix
(LOG entry 59, ASSUMPTIONS §58): a suspended 0.0 first sighting no
longer consumes a match's one freeze slot, and CLV is reported only when
the entry is a true freeze, so the fabricated exact-0.00 CLVs disappear
(they become null, honestly). 0077 is the unit tracker (ASSUMPTIONS
§59): hypothetical quarter-Kelly sizing in imaginary units over the
EV-clean graded moneyline picks starting 2026-08-08, provisional with
the EV gate, with a flat 1u companion line, shipped in the markets
payload and as a panel on Markets. No dependency changes. No model
serving change: BUNDLE_BEHAVIOR_REV not bumped (markets/display side
only). Pre-registered behavior changes: close-only picks now show CLV
null instead of +0.00; the refresh odds report gains a
skipped_unpriceable counter; the markets payload gains entry_kind per
pick and a unit_tracker block.

## Base

Applies on top of origin/main at 28b17bf (patch 0075).

## Apply

```bash
cd ~/Downloads/valorant-predictor
ls ~/Downloads/007[67]-*.patch || ls patches/applied/007[67]*.patch
git am ~/Downloads/0076-*.patch
git log --oneline -1
git am ~/Downloads/0077-*.patch
git log --oneline -1
```

Each `git log` line must show that patch's subject. If `git am` fails
partway: `git am --abort`, confirm `git status --porcelain` clean, retry.

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

Expect 198 Python tests (188 after 0076, plus 10 tracker tests) and 44
JS tests. `npm run audit` needs Chrome (tips + mobile stages). Sandbox
already ran pytest, npm test, build, audit:lint, audit:render green;
tips and mobile run on your machine per standing procedure.

## BEFORE snapshot — run against live BEFORE pushing

```bash
python3 - <<'PYEOF' | tee /tmp/clv-before.txt
import json, urllib.request
d = json.load(urllib.request.urlopen("https://vpredict.onrender.com/api/markets"))
zero = [p for p in d["picks"] if p.get("clv_pct") == 0.0]
print("exact-0.0 CLV picks:", len(zero))
for p in zero: print("  ", p["match"], p["source"], p.get("entry_captured_at"))
print("unit_tracker in payload:", "unit_tracker" in d)
PYEOF
```

## Push, then verify live AFTER Render deploys

```bash
git push
# wait for Render deploy, then confirm the served bundle actually changed:
curl -s https://vpredict.onrender.com/ | grep -o 'index-[a-zA-Z0-9]*\.js'
ls frontend/dist/assets/*.js
```

The two filenames must match (STATE.md workflow note; Render "Live" is
not proof). Then, after the next 10-minute odds tick:

```bash
python3 - <<'PYEOF'
import json, urllib.request
d = json.load(urllib.request.urlopen("https://vpredict.onrender.com/api/markets"))
zero = [p for p in d["picks"] if p.get("clv_pct") == 0.0
        and p.get("entry_kind") == "close"]
print("fabricated zeros remaining (must be 0):", len(zero))
nul = [p for p in d["picks"] if p.get("clv_pct") is None
       and p.get("close_captured")]
print("close-only picks now honestly null:", len(nul))
t = d.get("unit_tracker") or {}
print("tracker:", t.get("n_staked"), "staked,",
      t.get("units_pnl"), "units, provisional:", t.get("provisional"))
PYEOF
```

The three previously fabricated rows (KRU vs G2, Eternal Fire vs
FNATIC, Shopify Rebellion Black vs 2Game) should move from +0.00 to
null. In the runtime logs, `skipped_unpriceable` appearing with a
nonzero count in an odds tick is the capture-side fix working: a
suspended price got counted and left the slot open instead of burning
it.

## Rollback

```bash
git revert <0077-sha> <0076-sha>   # or: git reset --hard 28b17bf (before push only)
```

Both patches are additive on the serving side; reverting restores the
prior payload shape. The odds log is append-only and untouched by both.
