# APPLY — patch 0084: restore the truncated head from the Mac log

One patch (ASSUMPTIONS §68, LOG 62 addendum). Adds --before to
--push-log for a strictly-older surgical merge, plus the corrected
timeline and the raw-path correction on the record. No server behavior
change; the merge runs FROM THE MAC through the 0081-gated ingest.

## Apply and gate

```bash
cd ~/Downloads/valorant-predictor
git am ~/Downloads/0084-*.patch
git log --oneline -1
source .venv/bin/activate && python3 -m pytest
cd frontend && npm test && npm run build && npm run audit && cd ..
git push
```

Expect 236 Python tests and 44 JS. (Push keeps the repo and image
consistent; the merge itself needs only the Mac-side apply.)

## Evidence first (Render Shell) — finalizes LOG 62's trigger line

```bash
ls -la /data/odds/
ls /data/odds/raw/ | head -5        # the CORRECT raw path
du -sh /data/odds/raw 2>/dev/null; df -h /data
```

On the Mac: `crontab -l`. Paste all of it. A renamed original in
/data/odds still supersedes everything: stop and paste if one exists.

## The merge (Mac)

```bash
cd ~/Downloads/valorant-predictor
python scripts/capture_odds.py --push-log --before 2026-07-29T19:39:25.114281Z
```

Expected output shape: "--before ...: N of 21106 local records
qualify", then the ingest counts — appended = the restored head,
unpriceable = pre-0076 suspended rows correctly refused at the door,
duplicates ≈ 0, invalid 0. Nothing pushed can collide with anything
the server holds: strictly older by construction.

## Close-out

Wait one 10-minute tick, then in the Shell:

```bash
python3 scripts/gap_audit.py
```

Criteria unchanged from §67: pre-capture-era back to ~27; capture-era
coverage back toward the recorded ~70%; the four marquee matches
covered again; exactly one casualty (Cloud9 vs LOUD); the header's
"first line written" now shows the restored head's write order
honestly (earliest capture 2026-07-24, first written 2026-07-29 —
that divergence is the healed-log signature the line exists to show).
Paste the output; LOG 62's trigger line gets finalized from the
evidence block, or recorded as unidentified-operational.

## Rollback

The merge appends real recovered captures; they stay. `git revert`
removes only the CLI flag.
