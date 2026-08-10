# APPLY — patch 0083: rebuild the odds log's lost head from /data/raw

One patch (ASSUMPTIONS §67, LOG 62). No model change, no frontend
change, BUNDLE_BEHAVIOR_REV untouched. Ships the rebuild tool, its
importable core with five tests, and the audit header's "first line
written" fingerprint.

## Apply and gate

```bash
cd ~/Downloads/valorant-predictor
git am ~/Downloads/0083-*.patch
git log --oneline -1
source .venv/bin/activate && python3 -m pytest
cd frontend && npm test && npm run build && npm run audit && cd ..
git push
```

Expect 235 Python tests and 44 JS.

## Preflight in the Render Shell (BEFORE any apply)

```bash
ls -la /data/odds/
df -h /data && du -sh /data/raw
python3 scripts/rebuild_odds_from_raw.py        # dry run
```

- If ls shows a renamed original (odds.jsonl.bak or similar): STOP and
  paste it — merging the original beats any replay.
- The ls mtimes, df, du, plus `crontab -l` on the Mac are the trigger
  evidence LOG 62 still needs; paste them regardless.
- The dry run prints the raw inventory (cloudbet daily files must reach
  back before 2026-07-29), the cutoff, and every row it would append,
  grouped per match. Review, then:

```bash
python3 scripts/rebuild_odds_from_raw.py --apply
```

## Mac side (Pinnacle history)

```bash
cd ~/Downloads/valorant-predictor
python3 - <<'PYEOF'
import json
r = json.loads(open("data/odds/odds.jsonl").readline())
print("Mac log first row:", r["source"], r["captured_at"])
PYEOF
python scripts/capture_odds.py --push-log      # gated since 0081
```

If the Mac log's first row predates 2026-07-29, the push also restores
head rows the server raw may lack; the gate drops suspended rows this
time.

## Close-out

Wait one 10-minute tick, then:

```bash
python3 scripts/gap_audit.py
```

Success criteria pinned in §67, close is a diff not a feeling:
pre-capture-era back to ~27; capture-era coverage back toward the
recorded ~70%; the four marquee matches out of the suspended-only
bucket; exactly one casualty (Cloud9 vs LOUD) still; the header's new
"first line written" line printed. Paste the output; the LOG-62
trigger line gets finalized from the preflight evidence.

## Rollback

The tool appends only; `git revert` removes the tool. Appended rows
are real recovered captures and stay.
