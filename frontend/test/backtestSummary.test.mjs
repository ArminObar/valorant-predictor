import test from "node:test";
import assert from "node:assert/strict";
import { summarizeBacktestTiers } from "../src/backtestSummary.js";

test("counts tier leaders by log loss, per side", () => {
  const t = summarizeBacktestTiers({
    tier1: { n_scored: 100, model_ll: 0.68, elo_ll: 0.67 },
    tier2: { n_scored: 300, model_ll: 0.66, elo_ll: 0.67 },
    game_changers: { n_scored: 80, model_ll: 0.61, elo_ll: 0.62 },
    other: { n_scored: 50, model_ll: 0.70, elo_ll: 0.69 },
  });
  assert.deepEqual(t, { n: 4, eloLeads: 2, modelLeads: 2 });
});

test("unscored tiers and missing metrics are excluded from n", () => {
  const t = summarizeBacktestTiers({
    tier1: { n_scored: 100, model_ll: 0.68, elo_ll: 0.67 },
    empty: { n_scored: 0 },
    broken: { n_scored: 10, model_ll: null, elo_ll: 0.6 },
  });
  assert.deepEqual(t, { n: 1, eloLeads: 1, modelLeads: 0 });
});

test("an exact tie counts for neither side", () => {
  const t = summarizeBacktestTiers({
    a: { n_scored: 10, model_ll: 0.65, elo_ll: 0.65 },
    b: { n_scored: 10, model_ll: 0.60, elo_ll: 0.65 },
  });
  assert.deepEqual(t, { n: 2, eloLeads: 0, modelLeads: 1 });
});

test("empty or absent payloads collapse to zero, never throw", () => {
  assert.deepEqual(summarizeBacktestTiers({}),
    { n: 0, eloLeads: 0, modelLeads: 0 });
  assert.deepEqual(summarizeBacktestTiers(undefined),
    { n: 0, eloLeads: 0, modelLeads: 0 });
});
