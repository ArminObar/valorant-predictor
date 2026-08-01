# APPLY — patch 0072: tooltip repair + tip-geometry gate

One patch. Fixes both reported tooltip symptoms (misplaced pops, and
pops that never appear) at their single root cause, and adds a real-
browser gate so this class cannot pass silently again. LOG entry 51,
ASSUMPTIONS §54. Backend untouched. The Scoreboard/Markets number
question is deliberately NOT touched (see the findings report).

## Base

Applies on top of origin/main at 5ef409f (the hero re-encode commit).

## Apply

```bash
mv ~/Downloads/0072-*.patch ~/Downloads/valorant-predictor/patches/
cd ~/Downloads/valorant-predictor
git am patches/0072-*.patch
git log --oneline -1        # must show the 0072 commit
```

## Gates — dependency change, so cold install first

package.json gained one devDependency (puppeteer-core, drives your
installed Chrome; nothing ships to production).

```bash
cd frontend
rm -rf node_modules && npm ci
npm test                    # expect 38 passed
npm run audit               # lint + jsdom render + NEW tip geometry
npm run build
cd ..
python -m pytest            # expect 174 passed
```

`npm run audit` now ends with the tip-geometry audit driving your
installed Google Chrome headlessly. Expected last line:

    TIP AUDIT: all 8 pops anchored, on top, on screen

If it cannot find Chrome it fails with instructions (CHROME_PATH).
It does not skip; a gate that can skip is not a gate.

## Ship

```bash
git push
```

## What to check on the live site after deploy

- Hover the info icon on Schedule: the tooltip appears directly under
  the icon, centered on it, over nothing.
- Scoreboard's three icons (masthead, live scoreboard title, market
  picks title at the bottom) all show tooltips on top of the content.
- Click an icon to pin, Tab to the "full story" link inside the pop,
  Escape closes. Both still work with the pop portaled.
- Page entry animations look unchanged everywhere, including the home
  divider bar draw-in.
