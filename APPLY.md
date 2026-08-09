# APPLY — patch 0081: coverage-drop hardening, branch-independent

One patch (ASSUMPTIONS §65). No model change, no frontend change,
BUNDLE_BEHAVIOR_REV untouched. Ships only what is correct under either
surviving mechanism for the coverage drop; the deploy itself then
discriminates between them.

What ships: the legacy /api/ingest/markets route is removed and
scripts/publish_markets.py deleted (markets is server-authoritative; a
surviving Mac cron job now fails loudly instead of silently replacing
the fresh build); every server markets build carries
"builder": "server-refresh" and the gap-audit header prints it, so a
foreign or pre-0081 markets.json is visibly UNSTAMPED; the odds ingest
endpoint now applies §58's priceable gate (suspended rows counted as
"unpriceable", never appended — also blocks --push-log from
re-importing pre-gate rows); the audit header adds the capture-log
time span.

## Base

Applies on top of patch 0080 (the coverage-gap audit).

## Apply

```bash
cd ~/Downloads/valorant-predictor
git am ~/Downloads/0081-*.patch
git log --oneline -1
```

## Gates

```bash
source .venv/bin/activate
python3 -m pytest
cd frontend && npm test && npm run build && npm run audit && cd ..
```

Expect 225 Python tests and 44 JS tests.

## Push, then run the discriminator

After deploy, wait two or three 10-minute odds ticks, then in the
Render Shell:

```bash
python3 scripts/gap_audit.py
wc -l /data/odds/odds.jsonl
```

Read it against §64's baseline (58 covered / 51 expected gap / 1
casualty):

- Covered recovers toward 58 AND the header shows
  builder: server-refresh -> mechanism B (legacy Mac markets push) was
  live and is now closed. Also run `crontab -l` on the Mac and delete
  any publish_markets line — the job can only fail loudly now, but it
  should not keep firing.
- Covered stays near 35 -> mechanism A confirmed: the log lost rows.
  Say the word and 0082 is the capture-rebuild tool that reconstructs
  them from /data/raw (full response bodies, per source, per day —
  nothing unrecoverable). No deploy alone can recover coverage in this
  branch; the rebuild does.

Either way, paste the full audit output. The wc -l line against the
baseline header's "capture log: N rows" settles the log question in
one comparison.

## Rollback

```bash
git revert <0081-sha>
```

Restores the legacy route; do that only if something unexpected breaks,
since the route's only known caller is the stale legacy job.
