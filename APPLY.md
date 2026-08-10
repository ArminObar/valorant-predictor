# APPLY — patch 0086: the roster-continuity live checkpoint

One patch (ASSUMPTIONS §70). A standing tool, no behavior change
anywhere: no model change, no markets change, no frontend change,
BUNDLE_BEHAVIOR_REV untouched.

## Apply and gate

```bash
cd ~/Downloads/valorant-predictor
git am ~/Downloads/0086-*.patch
git log --oneline -1
source .venv/bin/activate && python3 -m pytest
cd frontend && npm test && npm run build && npm run audit && cd ..
git push
```

Expect 246 Python tests and 44 JS. Push is required for the tool to
exist in the Render Shell's image.

## Usage (Render Shell, anytime)

```bash
python3 scripts/roster_checkpoint.py
```

The tool gates itself per §70: below n=30 qualifying rows it reports
accumulation only and withholds the metrics; at 30-49 it prints
DIRECTIONAL numbers with no verdict; at n>=50 it evaluates the single
pinned criterion (model log loss strictly below Elo log loss on the
low-history slice) and says MET or NOT MET, with the reminder that the
§66 ablation remains the primary evidence. Established-history context
and per-tier cells print with their n. Expected first directional read
at current grading rates: roughly three to four weeks out.

## The outstanding 0082 verification (unchanged, still owed)

Next Shell visit, run the two checks from APPLY 0082 (/api/model
version changed once and held; the bundle listing the roster columns
at behavior rev 5) and report back. The checkpoint's era boundary
(config.ROSTER_LIVE_SINCE) ships provisional-conservative at
2026-08-11T00:00:00Z; once the verified deploy moment is known it
tightens in a one-line config change, and until then the tool prints
the boundary and the slice's model_version stamps so the era claim is
inspectable.

## Rollback

`git revert <0086-sha>` — the tool reads and prints; it writes
nothing, ever.
