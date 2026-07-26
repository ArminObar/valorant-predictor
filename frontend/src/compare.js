/** Comparison helpers for metric displays (ASSUMPTIONS §37).
 *
 * metricLead decides ONE metric's winner, direction-aware, and returns null
 * on ties or missing values so neither side gets marked; the old inline
 * checks green-marked Elo on an exact tie because `model < elo` is false.
 * Every green marker in the UI routes through this so accuracy and log loss
 * are judged independently: they can genuinely disagree, and when they do
 * both markers stand.
 *
 * liveStanding reduces the live scoreboard summary to one word for the
 * backtest intro, so the sentence about the live record is derived from the
 * payload at render time, never typed in: it flips with the data. */
export function metricLead(model, elo, higherIsBetter = false) {
  if (!Number.isFinite(model) || !Number.isFinite(elo) || model === elo) {
    return null;
  }
  return (higherIsBetter ? model > elo : model < elo) ? "model" : "elo";
}

export function liveStanding(summary) {
  if (!summary || !(summary.n_scored > 0)) return "unknown";
  const leads = [
    metricLead(summary.model?.accuracy, summary.elo?.accuracy, true),
    metricLead(summary.model?.log_loss, summary.elo?.log_loss, false),
  ];
  const model = leads.filter((l) => l === "model").length;
  const elo = leads.filter((l) => l === "elo").length;
  if (model > 0 && elo === 0) return "ahead";
  if (elo > 0 && model === 0) return "behind";
  if (model > 0 && elo > 0) return "mixed";
  return "unknown";
}
