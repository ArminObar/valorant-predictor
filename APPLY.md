# APPLY — patch 0082: roster-continuity features, Phase 1 (ships ON per §66)

One patch, owner-approved scope (ASSUMPTIONS §66): membership-only
roster-continuity features, no performance stats, no new scraping, no
parser changes. The pre-registered ablation decided the default:
primary and guard both MET, so the family ships ON and
BUNDLE_BEHAVIOR_REV bumps 4 -> 5, which triggers exactly ONE retrain on
deploy. Frozen ledger rows are immune by construction (§8).

New: src/vpredict/features/roster.py (batch sweep + serving query,
pinned equal by test), two columns roster_ext_maps_diff and
roster_coplay_diff in training and serving (serving is bundle-driven:
it computes them only when the trained schema carries them),
scripts/ablate_roster.py (the §66 harness; the only source of the
numbers), roster_phase1-2026-08-09.md (this run's record), five
feature tests, MODEL_CARD updates, and the in-build leakage spot-check
now cross-validates the roster sweep against an independent
truncated-history recomputation.

## Base

Applies on top of patch 0081 (markets provenance + ingest hardening).
Apply 0081 first if you have not.

## Apply

```bash
cd ~/Downloads/valorant-predictor
git am ~/Downloads/0082-*.patch
git log --oneline -1
```

## Gates

```bash
source .venv/bin/activate
python3 -m pytest
cd frontend && npm test && npm run build && npm run audit && cd ..
```

Expect 230 Python tests and 44 JS tests.

## Push, then verify the one retrain

Deploy triggers a single retrain (rev 5). After the next FULL cycle:

```bash
python3 - <<'PYEOF'
import json, urllib.request
d = json.load(urllib.request.urlopen(
    "https://vpredict.onrender.com/api/model"))
print("version:", d.get("version"))
PYEOF
```

The version string must change once and then hold. In the Render Shell,
confirm the new bundle carries the family:

```bash
python3 - <<'PYEOF'
import joblib
b = joblib.load("/data/models/model.joblib")
print([c for c in b["feature_names"] if c.startswith("roster")])
print("behavior rev:", b.get("behavior_rev"))
PYEOF
```

Expect roster_stability_diff plus the two new columns, behavior rev 5.
Low-history matches predicted AFTER the retrain will differentiate by
lineup pedigree instead of collapsing to shared defaults; already-
frozen predictions never change. The identical-probability plateau
behavior (§21/LOG 37) is unrelated and unchanged.

## Rollback

```bash
git revert <0082-sha>
```

Reverting also reverts the rev bump; the next deploy retrains once
back onto the previous schema. Frozen rows unaffected either way.
