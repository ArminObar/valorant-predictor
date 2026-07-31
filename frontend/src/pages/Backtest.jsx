import React from "react";
import { useApi, fmtPct } from "../lib/useApi.js";
import { fmtTime } from "../time.js";
import { Lead } from "../components/bits.jsx";
import { metricLead } from "../compare.js";
import { LiveStandingClause } from "../components/BacktestSummary.jsx";
import { Masthead, MASTHEAD_TIPS } from "../components/Masthead.jsx";

export function Backtest() {
  const { data, err } = useApi("/api/backtest");
  if (err) return <p className="empty">API unreachable.</p>;
  if (!data) return <p className="empty">Loading&hellip;</p>;
  if (!data.window)
    return (
      <p className="empty">
        The backtest has not been run on this deployment yet.
      </p>
    );
  const w = data.window;
  const tiers = Object.entries(data.per_tier || {});
  return (
    <div className="panel">
      <Masthead eyebrow="simulated \u00b7 kept apart from the live record"
        warn tip={MASTHEAD_TIPS.backtest} title="Backtest"
        stats={[
          ...(data.n_predictions
            ? [{ value: data.n_predictions.toLocaleString(),
                 label: "simulated calls", tone: "ink" }] : []),
          ...(data.n_retrains
            ? [{ value: String(data.n_retrains), label: "retrains",
                 tone: "ink" }] : []),
        ]} />
      <p className="note">
        Two years replayed, worst stretch included. {w.n_predictions} simulated
        predictions, {w.n_retrains} retrains,
        {" "}{fmtTime(w.first_prediction)} to {fmtTime(w.last_prediction)}.
        Elo wins most of this history<LiveStandingClause />
      </p>
      <div className="table-scroll">
      <table className="ledger">
        <thead>
          <tr><th>tier</th><th className="num">n scored</th>
            <th className="num sep">model acc</th><th className="num">elo acc</th>
            <th className="num sep">model LL</th><th className="num">elo LL</th></tr>
        </thead>
        <tbody>
          {tiers.map(([tier, m]) => {
            const acc = metricLead(m.model_acc, m.elo_acc, true);
            const ll = metricLead(m.model_ll, m.elo_ll);
            return (
              <tr key={tier}>
                <td>{tier}</td>
                {m.n_scored ? (
                  <>
                    <td className="num">{m.n_scored}</td>
                    <td className="num sep"><Lead win={acc === "model"}>{fmtPct(m.model_acc)}</Lead></td>
                    <td className="num dim"><Lead win={acc === "elo"}>{fmtPct(m.elo_acc)}</Lead></td>
                    <td className="num sep"><Lead win={ll === "model"}>{m.model_ll.toFixed(4)}</Lead></td>
                    <td className="num dim"><Lead win={ll === "elo"}>{m.elo_ll.toFixed(4)}</Lead></td>
                  </>
                ) : (
                  <td colSpan={5} className="dim">no scored rows</td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
      </div>
      <p className="note" style={{ margin: 0 }}>
        tier1 is the top circuit, never pooled. Lower is better for log loss.
        The accent marks each comparison's leader; accuracy and log loss can
        disagree, and both marks stay.
        {data.synthetic_data && (
          <span className="badge">contains synthetic data</span>
        )}
      </p>
    </div>
  );
}
