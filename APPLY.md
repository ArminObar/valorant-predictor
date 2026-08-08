# APPLY — patch 0080: the coverage-gap audit lands as a standing script

One patch, owner-requested (ASSUMPTIONS §64). No dependency changes, no
serving-behavior change, no frontend change, BUNDLE_BEHAVIOR_REV
untouched. Adds src/vpredict/odds/coverage_audit.py (importable logic,
definitions shared with the live linker), scripts/gap_audit.py (thin
read-only CLI), and six tests pinning every bucket. Also records the
2026-08-08 baseline run and the accepted Cloud9 vs LOUD casualty with
its reproduced self-collapse mechanism.

## Base

Applies on top of patch 0079 (Trends scoping).

## Apply

```bash
cd ~/Downloads/valorant-predictor
ls ~/Downloads/0080-*.patch || ls patches/applied/0080*.patch
git am ~/Downloads/0080-*.patch
git log --oneline -1
```

## Gates (all must pass before push)

```bash
source .venv/bin/activate
python3 -m pytest
cd frontend && npm test && npm run build && npm run audit && cd ..
```

Expect 223 Python tests and 44 JS tests (frontend untouched; the audit
stages should read identically to the 0079 run).

## Push, then use it

After Render deploys (the image copies scripts/), the standing check is
one command in the Render Shell:

```bash
python3 scripts/gap_audit.py
```

Same output shape as the 2026-08-08 baseline (58 covered / 51 expected
gap / 1 accepted casualty / bug buckets 0), so drift is a diff. The
sum check must always read OK; anything in the UNEXPLAINED bucket or a
NEW captured-never-linked entry is a real finding. Locally it runs
against any synced data root with --data.

## Rollback

```bash
git revert <0080-sha>
```

Pure addition; nothing else references it.
