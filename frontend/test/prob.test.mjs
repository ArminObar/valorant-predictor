import test from "node:test";
import assert from "node:assert/strict";
import { fmtPct, fmtPctOpp, flipProb, favored, fmtSigned }
  from "../src/lib/prob.js";

test("fmtPct is one decimal with a percent sign", () => {
  assert.equal(fmtPct(0.61), "61.0%");
  assert.equal(fmtPct(0.5835), "58.4%");
});

test("flipProb reproduces the server's 4-decimal complement", () => {
  // round(1 - p, 4) is what markets.json ships for the opposite side.
  assert.equal(flipProb(0.61), 0.39);
  assert.equal(flipProb(0.5835), 0.4165);
  assert.equal(flipProb(0.1545), 0.8455);
});

test("side identity: a client flip equals the server-shipped complement", () => {
  // Every 4-dp ledger probability: the string a page shows for team2 via
  // fmtPctOpp must equal the string another page shows for the same side
  // from the server's own round(1 - p, 4) value. This is the invariant a
  // shared formatter exists to hold.
  for (let i = 1; i < 10000; i++) {
    const p = i / 1e4;
    const serverSide = Math.round((1 - p) * 1e4) / 1e4;
    assert.equal(fmtPctOpp(p), fmtPct(serverSide));
  }
});

test("favored uses the ledger's own rule: team1 iff p >= 0.5", () => {
  assert.deepEqual(favored(0.61, "RED", "BLU"),
    { name: "RED", pct: "61.0%", team1: true });
  assert.deepEqual(favored(0.39, "RED", "BLU"),
    { name: "BLU", pct: "61.0%", team1: false });
  // exactly 0.5 counts as team1, matching ledger.summary()'s accuracy check
  assert.equal(favored(0.5, "RED", "BLU").name, "RED");
});

test("known 1-dp artifact stays documented, not hidden", () => {
  // A handful of 4-dp probabilities display sides summing to 99.9/100.1.
  // 0.1545 is one: 15.4% and 84.5%. Fixed-precision rounding, not data.
  assert.equal(fmtPct(0.1545), "15.4%");
  assert.equal(fmtPctOpp(0.1545), "84.5%");
});

test("fmtSigned: two decimals, explicit sign, matches server rounding", () => {
  assert.equal(fmtSigned(13.1), "+13.10%");
  assert.equal(fmtSigned(-2.47), "-2.47%");
  assert.equal(fmtSigned(0), "+0.00%");
});
