/* The regression test the timezone bug demanded (LOG entry 29): a known UTC
 * instant must render correctly under a non-UTC locale, with the zone
 * labeled. Runs with node's built-in runner (`npm test`), zero deps.
 * Explicit locale + timeZone make the expected strings deterministic.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { fmtCountdown, fmtTime, parseUtc } from "../src/time.js";

// The live-site bug case: RRQ vs ZETA, true start 2026-07-24 08:00 UTC.
const RRQ_ZETA_UTC = "2026-07-24T08:00:00+00:00";

test("known UTC instant renders in a non-UTC zone with the zone labeled", () => {
  assert.equal(
    fmtTime(RRQ_ZETA_UTC, { locale: "en-US", timeZone: "America/New_York" }),
    "Jul 24, 04:00 AM EDT",
  );
  assert.equal(
    fmtTime(RRQ_ZETA_UTC, { locale: "en-US", timeZone: "America/Chicago" }),
    "Jul 24, 03:00 AM CDT",
  );
});

test("winter instants pick up the standard-time zone name", () => {
  assert.equal(
    fmtTime("2026-01-10T02:00:00+00:00",
            { locale: "en-US", timeZone: "America/New_York" }),
    "Jan 9, 09:00 PM EST",
  );
});

test("UTC rendering is exact (no hidden extra conversion)", () => {
  assert.equal(
    fmtTime(RRQ_ZETA_UTC, { locale: "en-US", timeZone: "UTC" }),
    "Jul 24, 08:00 AM UTC",
  );
});

test("a naive ISO string is treated as UTC, never viewer-local", () => {
  // Without the guard, Date() parses this as LOCAL wall time and the
  // rendered instant would depend on the machine running the code.
  assert.equal(parseUtc("2026-07-24T08:00:00").getTime(),
               parseUtc("2026-07-24T08:00:00Z").getTime());
});

test("missing timestamps render as a dash, not 'Invalid Date'", () => {
  assert.equal(fmtTime(null), "n/a");
  assert.equal(fmtTime("not-a-date"), "n/a");
});


test("fmtCountdown ladders through starting, minutes, hours, days", () => {
  const now = Date.parse("2026-07-31T12:00:00+00:00");
  assert.equal(fmtCountdown("2026-07-31T12:03:00+00:00", now), "starting");
  assert.equal(fmtCountdown("2026-07-31T12:42:00+00:00", now), "in 42m");
  assert.equal(fmtCountdown("2026-07-31T14:05:00+00:00", now), "in 2h 05m");
  assert.equal(fmtCountdown("2026-08-02T15:00:00+00:00", now), "in 2d 3h");
  assert.equal(fmtCountdown("2026-07-31T11:00:00+00:00", now), null);
});
