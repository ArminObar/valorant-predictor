/* Pure geometry for the match-page rating-history chart. Kept out of
   React so node --test can pin it the way time.js is pinned: given the
   API's rating_history teams, produce polyline-ready coordinates.

   Layout rules: y grows downward (higher rating = smaller y), the most
   recent match of EVERY team sits on the shared right edge (trajectories
   are right-aligned, evenly spaced by match, not by date — the caption
   says so), and the rating domain is padded so lines never touch the
   frame. */

export function buildRatingChart(teams, opts = {}) {
  const w = opts.w ?? 640;
  const h = opts.h ?? 180;
  const padL = opts.padL ?? 42;
  const padR = opts.padR ?? 46;
  const padY = opts.padY ?? 26;
  const entries = Object.entries(teams || {})
    .filter(([, t]) => t && Array.isArray(t.points) && t.points.length > 0);
  if (!entries.length) return null;

  const all = entries.flatMap(([, t]) => t.points.map((p) => p.rating));
  let lo = Math.min(...all);
  let hi = Math.max(...all);
  if (hi - lo < 20) { const m = (hi + lo) / 2; lo = m - 10; hi = m + 10; }
  const span = hi - lo;
  lo -= span * 0.08;
  hi += span * 0.08;

  const maxLen = Math.max(...entries.map(([, t]) => t.points.length));
  const sx = (i, len) => maxLen === 1
    ? w - padR
    : padL + ((w - padL - padR) * (i + (maxLen - len))) / (maxLen - 1);
  const sy = (r) => padY + ((hi - r) / (hi - lo)) * (h - 2 * padY);

  const lines = entries.map(([key, t]) => {
    const dots = t.points.map((p, i) => ({
      x: +sx(i, t.points.length).toFixed(1),
      y: +sy(p.rating).toFixed(1),
      rating: p.rating, won: p.won, opponent: p.opponent, ts: p.ts,
    }));
    return {
      key, name: t.name, dots,
      points: dots.map((d) => `${d.x},${d.y}`).join(" "),
      end: dots[dots.length - 1],
    };
  });

  const mid = (lo + hi) / 2;
  return {
    w, h, padL, padR, padY,
    lo: Math.round(lo), hi: Math.round(hi),
    mid: Math.round(mid), midY: +sy(mid).toFixed(1),
    lines,
  };
}
