# APPLY — patch 0071: visual fidelity to the v2 prototype

One patch. Repaints the interiors to the spec's ivory/warm-charcoal
palettes, lifts Home out of the interior shell, and aligns the small
skin items (cards, tooltip, toggle, columns, home bar). Backend
untouched; no dependency changes. ASSUMPTIONS §53, LOG entry 50.

The hero video/poster re-encode is a separate manual step below
(binaries never travel in patches; the 15.6 MB original stays out of
git per §51).

## Base

Applies on top of origin/main at e08c48a (the audit-repair commit).

## Apply the patch

```bash
mv ~/Downloads/0071-*.patch ~/Downloads/valorant-predictor/patches/
cd ~/Downloads/valorant-predictor
git am patches/0071-*.patch
git log --oneline -1        # must show the 0071 commit
```

## Gates

```bash
python -m pytest            # expect 174 passed (no backend files touched)
cd frontend
npm test                    # expect 38 passed
npm run audit               # eslint + jsdom render harness, zero errors
npm run build
cd ..
```

No `rm -rf node_modules && npm ci` needed: package.json is untouched.

## Re-encode the hero from the design original

Needs the design zip (Vpredict_visual_redesign.zip in ~/Downloads)
and ffmpeg. Run one line at a time.

```bash
which ffmpeg || brew install ffmpeg
cd ~/Downloads
ls Vpredict_visual_redesign*.zip    # if a _1 duplicate exists, delete it first
unzip -o Vpredict_visual_redesign.zip -d vpredict_design
cd ~/Downloads/valorant-predictor
SRC=~/Downloads/vpredict_design/design_handoff_vpredict_v2/assets/hero-video.mp4
ffmpeg -y -i "$SRC" -c:v libx264 -profile:v high -crf 20 -maxrate 4M -bufsize 8M -preset slow -pix_fmt yuv420p -an -movflags +faststart frontend/public/hero.mp4
ffmpeg -y -i "$SRC" -c:v libvpx-vp9 -crf 32 -b:v 0 -row-mt 1 -cpu-used 2 -an frontend/public/hero.webm
ffmpeg -y -ss 1 -i "$SRC" -frames:v 1 -q:v 3 frontend/public/hero-poster.jpg
ls -la frontend/public/     # mp4 ~10-15 MB, webm ~6-10 MB, poster ~150-400 KB
```

The VP9 encode takes a few minutes; that is normal.

## Commit the assets and ship

```bash
git add frontend/public/hero.mp4 frontend/public/hero.webm frontend/public/hero-poster.jpg
git commit -m "hero: re-encode at 1080p from the design original (x264 CRF 20, VP9 CRF 32, q85 poster)"
git push
```

One push, one Render deploy, both commits together.

## What to check on the live site after deploy

- Interiors are warm ivory (light) / warm charcoal (dark toggle), not
  blue-gray on white.
- Home fills the whole viewport edge to edge, no topbar above it, no
  footer below; the divider bar draws in left to right at ~0.75s.
- The hero background is visibly sharper in motion; the first-frame
  poster no longer looks blocky.
- Schedule column is slightly narrower than the other pages.
