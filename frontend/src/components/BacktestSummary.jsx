import React from "react";
import { Link } from "react-router-dom";
import { useApi } from "../lib/useApi.js";
import { summarizeBacktestTiers } from "../backtestSummary.js";
import { liveStanding } from "../compare.js";

export function BacktestSummary() {
  const { data, err } = useApi("/api/backtest");
  if (err || !data || !data.window) return null;
  const w = data.window;
  const t = summarizeBacktestTiers(data.per_tier);
  if (!t.n) return null;
  return (
    <div className="panel">
      <div className="panel-title">
        Two-year backtest: the longer record
        <span className="badge" title={"Computed after the fact from "
          + "stored data. You cannot verify it like the live scoreboard, "
          + "which is why the two stay apart."}>
          simulated</span>
      </div>
      <p className="note" style={{ margin: 0 }}>
        Two years replayed as if live: {w.n_predictions} simulated
        predictions, worst stretches included, nothing trimmed to flatter
        the model. Elo wins {t.eloLeads} of {t.n} tiers on log loss.
        It never mixes into the live numbers above.{" "}
        <Link className="linklike" to="/backtest">
          see the full backtest
        </Link>
      </p>
    </div>
  );
}

export function LiveStandingClause() {
  const { data } = useApi("/api/scoreboard");
  const standing = liveStanding(data?.summary);
  const sb = (
    <Link className="linklike" to="/scoreboard">live scoreboard</Link>
  );
  if (standing === "ahead")
    return <>; the model is currently ahead on the {sb}.</>;
  if (standing === "behind")
    return <>; the model is currently behind on the {sb}.</>;
  if (standing === "mixed")
    return <>; the model is currently splitting the {sb} with Elo.</>;
  return <>. The {sb} tracks the same head-to-head live.</>;
}

