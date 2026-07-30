import test from "node:test";
import assert from "node:assert/strict";
import { dayKey, dayLabel, groupByDay, sortByStart }
  from "../src/daygroups.js";

const TZ = { timeZone: "America/Toronto", locale: "en-US" };
const NOW = "2026-07-28T16:00:00+00:00";        // Jul 28, noon in Toronto

test("dayKey uses the viewer's zone, not UTC", () => {
  // 02:30 UTC on the 29th is still the evening of the 28th in Toronto.
  assert.equal(dayKey("2026-07-29T02:30:00+00:00", TZ), "2026-07-28");
  assert.equal(dayKey("2026-07-29T02:30:00+00:00",
    { timeZone: "UTC" }), "2026-07-29");
});

test("groups split at local midnight and label with weekday", () => {
  const rows = [
    { match_id: "a", start_ts: "2026-07-29T01:00:00+00:00" },  // Jul 28 local
    { match_id: "b", start_ts: "2026-07-29T05:00:00+00:00" },  // Jul 29 local
  ];
  const gs = groupByDay(rows, { dir: "asc", ...TZ, now: NOW });
  assert.equal(gs.length, 2);
  assert.equal(gs[0].rows[0].match_id, "a");
  assert.match(gs[0].label, /today \u00b7 Tuesday, July 28/);
  assert.equal(gs[0].isToday, true);
  assert.match(gs[1].label, /tomorrow \u00b7 Wednesday, July 29/);
  assert.equal(gs[1].isToday, false);
});

test("desc puts the newest day first, order stable within a day", () => {
  const rows = [
    { match_id: "x", start_ts: "2026-07-27T18:00:00+00:00" },
    { match_id: "y", start_ts: "2026-07-28T18:00:00+00:00" },
    { match_id: "y2", start_ts: "2026-07-28T18:00:00+00:00" },
  ];
  const gs = groupByDay(rows, { dir: "desc", ...TZ, now: NOW });
  assert.deepEqual(gs.map((g) => g.rows.map((r) => r.match_id)),
    [["y", "y2"], ["x"]]);
  assert.match(gs[1].label, /yesterday/);
  assert.equal(gs[1].isToday, false);
});

test("missing start times sort to the tail and group as unscheduled", () => {
  const rows = [
    { match_id: "n", start_ts: null },
    { match_id: "a", start_ts: "2026-07-28T18:00:00+00:00" },
  ];
  for (const dir of ["asc", "desc"]) {
    const gs = groupByDay(rows, { dir, ...TZ, now: NOW });
    assert.equal(gs[gs.length - 1].key, "unscheduled");
    assert.equal(gs[gs.length - 1].rows[0].match_id, "n");
  }
});

test("a different year shows up in the label", () => {
  const l = dayLabel("2025-12-31T18:00:00+00:00", { ...TZ, now: NOW });
  assert.match(l, /2025/);
});

test("sortByStart does not mutate its input", () => {
  const rows = [
    { start_ts: "2026-07-29T05:00:00+00:00" },
    { start_ts: "2026-07-28T05:00:00+00:00" },
  ];
  const copy = rows.slice();
  sortByStart(rows, "asc");
  assert.deepEqual(rows, copy);
});
