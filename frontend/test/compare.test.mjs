import test from "node:test";
import assert from "node:assert/strict";
import { metricLead, liveStanding } from "../src/compare.js";

test("lower-is-better metrics: smaller value leads", () => {
  assert.equal(metricLead(0.55, 0.58), "model");
  assert.equal(metricLead(0.58, 0.55), "elo");
});

test("higher-is-better metrics: larger value leads", () => {
  assert.equal(metricLead(0.68, 0.62, true), "model");
  assert.equal(metricLead(0.62, 0.68, true), "elo");
});

test("exact ties mark neither side (the old inline check marked Elo)", () => {
  assert.equal(metricLead(0.6, 0.6), null);
  assert.equal(metricLead(0.6, 0.6, true), null);
});

test("missing or non-finite values mark neither side", () => {
  assert.equal(metricLead(null, 0.6), null);
  assert.equal(metricLead(0.6, undefined, true), null);
  assert.equal(metricLead(NaN, 0.6), null);
});

const summary = (modelAcc, eloAcc, modelLL, eloLL, n = 16) => ({
  n_scored: n,
  model: { accuracy: modelAcc, log_loss: modelLL },
  elo: { accuracy: eloAcc, log_loss: eloLL },
});

test("ahead: model leads at least one metric and trails none", () => {
  assert.equal(liveStanding(summary(0.69, 0.62, 0.56, 0.58)), "ahead");
  // tied on accuracy, ahead on log loss is still ahead, not mixed
  assert.equal(liveStanding(summary(0.65, 0.65, 0.56, 0.58)), "ahead");
});

test("behind: Elo leads at least one metric and trails none", () => {
  assert.equal(liveStanding(summary(0.60, 0.66, 0.60, 0.57)), "behind");
});

test("mixed: the two metrics genuinely disagree", () => {
  assert.equal(liveStanding(summary(0.69, 0.62, 0.60, 0.57)), "mixed");
});

test("unknown: nothing scored, missing summary, or all ties", () => {
  assert.equal(liveStanding(undefined), "unknown");
  assert.equal(liveStanding(summary(0.69, 0.62, 0.56, 0.58, 0)), "unknown");
  assert.equal(liveStanding(summary(0.65, 0.65, 0.58, 0.58)), "unknown");
});
