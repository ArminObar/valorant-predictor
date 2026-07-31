import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import App from "../src/App.jsx";

const ROUTES = ["/", "/upcoming", "/scoreboard", "/model", "/markets",
                "/backtest", "/how", "/match/m1"];
const errors = [];
const realErr = console.error;
console.error = (...a) => { errors.push(a.join(" ")); };

const P = {
  "/api/upcoming": { model_version: "vp-2026-07-26", predictions: [{
    match_id: "m1", team1_name: "RED", team2_name: "BLU",
    start_ts: new Date(Date.now() + 7.2e6).toISOString(), p_model: 0.61,
    best_of: 3, event: "VCT Stage 2", low_history: false }] },
  "/api/scoreboard": { graded: [{ match_id: "g1", team1_name: "AAA",
    team2_name: "BBB", start_ts: new Date(Date.now() - 8.6e7).toISOString(),
    p_model: 0.58, team1_won: 1, model_correct: 1, elo_correct: 0,
    p_elo: 0.51, maps_won_1: 2, maps_won_2: 0, model_version: "vp" }],
    pending: [], summary: { n_graded: 18, model_accuracy: 0.6875,
    model: { accuracy: 0.6875, log_loss: 0.5582, brier: 0.19 },
    elo: { accuracy: 0.625, log_loss: 0.5789, brier: 0.2 } } },
  "/api/model": { version: "vp-2026-07-26", trained_at:
    "2026-07-26T09:00:00+00:00", n_train: 5489, features: [] },
  "/api/results": { model: { accuracy: 0.621, log_loss: 0.657,
    brier: 0.226 }, elo: { accuracy: 0.613, log_loss: 0.658, brier: 0.23 },
    series: { model: { accuracy: 0.621, log_loss: 0.657,
    brier: 0.226 }, elo: { accuracy: 0.613, log_loss: 0.658, brier: 0.23 } },
    map: { model: { accuracy: 0.59, log_loss: 0.6693, brier: 0.237 },
    elo: { accuracy: 0.588, log_loss: 0.6719, brier: 0.239 } },
    window: "recent" },
  "/api/markets": { picks: [], gate: { ev_validated: false, n_graded: 3,
    required: 30 }, skipped: { n_unpriceable: 0, n_group_errors: 0 },
    summary: null, generated_at: new Date().toISOString() },
  "/api/backtest": { n_predictions: 6800, n_retrains: 97, tiers: [{
    tier: "tier1", n: 399, model_acc: 0.569, elo_acc: 0.561,
    model_ll: 0.679, elo_ll: 0.684 }], summary: { model_acc: 0.59,
    elo_acc: 0.588 } },
  "/api/match/m1": { match_id: "m1", team1_name: "RED", team2_name: "BLU",
    event: "VCT Stage 2", start_ts: new Date(Date.now() + 7.2e6)
    .toISOString(), p_model: 0.61, p_elo: 0.55, best_of: 3,
    frozen_at: new Date().toISOString(), maps: [], rh: [], recent1: [],
    recent2: [] },
};
globalThis.fetch = (url) => {
  const key = Object.keys(P).find((k) => String(url).startsWith(k));
  return Promise.resolve({ ok: !!key, status: key ? 200 : 404,
    json: () => Promise.resolve(P[key] ?? {}) });
};

let fails = 0;
for (const r of ROUTES) {
  errors.length = 0;
  document.body.innerHTML = '<div id="root"></div>';
  try {
    const root = createRoot(document.getElementById("root"));
    await act(async () => {
      root.render(<MemoryRouter initialEntries={[r]}><App /></MemoryRouter>);
    });
    await act(async () => { await new Promise((res) => setTimeout(res, 30)); });
    const tabs = document.querySelectorAll(".tab").length;
    const bad = errors.filter((e) => !/not wrapped in act/.test(e));
    if (bad.length) { fails += 1; realErr(`FAIL ${r}: ${bad[0].slice(0, 160)}`); }
    else realErr(`OK   ${r}  tabs=${tabs} text=${document.body.textContent.length}ch`);
    root.unmount();
  } catch (e) { fails += 1; realErr(`THROW ${r}: ${String(e).slice(0, 160)}`); }
}
realErr(fails === 0 ? "RENDER AUDIT: all routes clean" : `RENDER AUDIT: ${fails} failing`);
process.exit(fails === 0 ? 0 : 1);
