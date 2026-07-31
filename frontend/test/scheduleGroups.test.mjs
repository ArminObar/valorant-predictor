import test from "node:test";
import assert from "node:assert/strict";
import { recentResults, scheduleGroups } from "../src/scheduleGroups.js";

const TZ = { timeZone: "America/Toronto", locale: "en-US" };
const NOW = "2026-07-31T16:00:00+00:00";
const up = [
  { match_id: "u2", start_ts: "2026-08-01T18:00:00+00:00" },
  { match_id: "u1", start_ts: "2026-07-31T20:00:00+00:00" },
];
const graded = [
  { match_id: "g1", start_ts: "2026-07-31T01:00:00+00:00" },  // Jul 30 local
  { match_id: "g2", start_ts: "2026-07-29T18:00:00+00:00" },
  { match_id: "gX", start_ts: "2026-07-20T18:00:00+00:00" },  // aged out
];

test("recentResults keeps only the last three viewer-local days", () => {
  const r = recentResults(graded, { ...TZ, now: NOW });
  assert.deepEqual(r.map((x) => x.match_id), ["g1", "g2"]);
});

test("schedule shows upcoming soonest-first, then results newest-first", () => {
  const gs = scheduleGroups(up, graded, { ...TZ, now: NOW });
  assert.deepEqual(
    gs.map((g) => g.rows.map((r) => r.match_id)),
    [["u1"], ["u2"], ["g1"], ["g2"]]);
  assert.equal(gs[0].isToday, true);
  assert.equal(gs[2].results, true);
});

test("empty inputs stay empty without throwing", () => {
  assert.deepEqual(scheduleGroups([], [], { ...TZ, now: NOW }), []);
  assert.deepEqual(scheduleGroups(null, null, { ...TZ, now: NOW }), []);
});
