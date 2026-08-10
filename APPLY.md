# APPLY — patch 0085: entry orientability fix, parity pin, era gate label

One patch (ASSUMPTIONS §69, LOG 63). Fixes the real bug behind the 23
bug-bucket matches: an unorientable earliest freeze silently unpriced
whole matches that later rows could price. No model change, no
frontend change, BUNDLE_BEHAVIOR_REV untouched; markets.json rebuilds
on the next tick after deploy.

## Apply and gate

```bash
cd ~/Downloads/valorant-predictor
git am ~/Downloads/0085-*.patch
git log --oneline -1
source .venv/bin/activate && python3 -m pytest
cd frontend && npm test && npm run build && npm run audit && cd ..
git push
```

Expect 241 Python tests and 44 JS.

## Close-out (Render Shell, after one 10-minute tick)

```bash
python3 scripts/gap_audit.py
```

Expected movement, pinned before looking: the 23 leave 2c (bucket back
to zero — the parity test now guarantees this class cannot recur);
covered rises by ≈23; skipped counters show n_entries_unorientable > 0
and n_groups_unpriced correspondingly lower; the gate's n_graded drops
by the pre-markets-era count (picks with entries before
2026-07-25T06:20:25Z are labeled pre_markets_era, visible, excluded
from validation). Remaining gap = never-listed + the 4 genuinely
suspended-only + 3 alias-era casualties, all previously dispositioned.
Paste the output and this investigation closes end to end.

## Rollback

`git revert <0085-sha>`; the next tick rebuilds markets.json under the
old rules. No data is written by this patch at all.
