/** Derive the scoreboard's one-line backtest summary from the same
 * /api/backtest payload the full table renders. Pure and separate so
 * `node --test` can pin it, and so every number the summary shows is
 * computed from the served payload, never typed into the JSX.
 *
 * Ties (equal log loss) count for neither side, so eloLeads +
 * modelLeads can be less than n and the rendered sentence stays
 * literally true either way. */
export function summarizeBacktestTiers(perTier) {
  const scored = Object.entries(perTier || {}).filter(
    ([, m]) => m && m.n_scored > 0
      && Number.isFinite(m.model_ll) && Number.isFinite(m.elo_ll));
  return {
    n: scored.length,
    eloLeads: scored.filter(([, m]) => m.elo_ll < m.model_ll).length,
    modelLeads: scored.filter(([, m]) => m.model_ll < m.elo_ll).length,
  };
}
