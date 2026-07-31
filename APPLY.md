# APPLY — v2 redesign series: patches 0062-0069

Eight patches rebuild the frontend to the v2 spec (ASSUMPTIONS §50 for
the pre-registered calls, §51 for the closing parity audit). Backend
untouched: pytest stays at 174 throughout; fonts remain on the
CSP-allowed Google hosts and the hero serves same-origin.

## Base

The series applies on top of patches 0060 and 0061. Base commit for
the ten-patch sequence: 13037a5 (origin/main, the 0059 commit). The
first delivery of this runbook wrongly started the am at 0062 and
omitted the 0060/0061 prerequisite; corrected here and verified
against a fresh clone of 13037a5 before resend.

## Apply

```bash
mv ~/Downloads/006[0-9]-*.patch ~/Downloads/valorant-predictor/patches/
cd ~/Downloads/valorant-predictor
git am patches/0060-*.patch patches/0061-*.patch patches/0062-*.patch \
       patches/0063-*.patch patches/0064-*.patch patches/0065-*.patch \
       patches/0066-*.patch patches/0067-*.patch patches/0068-*.patch \
       patches/0069-*.patch
python -m pytest                      # expect 174 passed
cd frontend && rm -rf node_modules && npm ci && npm test && npm run build && cd ..
git push
```

npm test expects 38 (34 plus scheduleGroups and countdown; theme and
daygroups expectations updated deliberately with the v2 contract).

## After the deploy

Hard refresh once. Then check: Home plays the muted hero (poster only
under reduced motion or Save-Data); the theme lands light ivory for
everyone (new vpredict-theme-v2 key) with Home fixed dark; six tabs
including how it works; Schedule shows Today and Tomorrow groups, then
Results for the last three days, countdown chips ticking; Markets
masthead reads "graded, ev unvalidated" until the gate passes; every
integrity affordance from the preserve list is visible in the new
skin.

## Patch 0070 (audit repair, applies on the ten-patch tip)

Your two uncommitted hand fixes are superseded by this patch: stash
them first, and after the gates pass, drop the stash rather than pop
it, because popping would re-impose the hand versions over the
repaired files.

```bash
cd ~/Downloads/valorant-predictor
git stash                      # hand fixes out of the way
git am patches/0070-*.patch
git log --oneline -1           # confirm the 0070 subject before anything else
python -m pytest               # expect 174
cd frontend && rm -rf node_modules && npm ci   # devDependencies changed
npm test                       # expect 38
npm run audit                  # expect 0 lint errors, all routes clean
npm run build && cd ..
git push
git stash drop                 # hand fixes now redundant
```
