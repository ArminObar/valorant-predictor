import test from "node:test";
import assert from "node:assert/strict";
import { buildRatingChart } from "../src/chart.js";

const pts = (rs) => rs.map((r, i) => ({
  ts: `2026-07-${10 + i}T12:00:00+00:00`, rating: r,
  won: i % 2 === 0, opponent: `opp${i}`,
}));

test("empty teams -> null", () => {
  assert.equal(buildRatingChart({}), null);
  assert.equal(buildRatingChart({ a: { name: "A", points: [] } }), null);
});

test("trajectories right-align on the shared newest edge", () => {
  const g = buildRatingChart({
    long: { name: "L", points: pts([1500, 1510, 1520, 1530]) },
    short: { name: "S", points: pts([1490, 1480]) },
  });
  const long = g.lines.find((l) => l.key === "long");
  const short = g.lines.find((l) => l.key === "short");
  assert.equal(long.end.x, short.end.x);          // both end "now"
  assert.ok(short.dots[0].x > long.dots[0].x);    // shorter starts later
});

test("higher rating sits higher (smaller y) inside a padded domain", () => {
  const g = buildRatingChart({
    a: { name: "A", points: pts([1450, 1550]) },
  });
  const [loDot, hiDot] = g.lines[0].dots;
  assert.ok(hiDot.y < loDot.y);                   // y inverted
  assert.ok(g.lo < 1450 && g.hi > 1550);          // domain padded
  assert.ok(loDot.y < g.h && hiDot.y > 0);        // inside the frame
});
