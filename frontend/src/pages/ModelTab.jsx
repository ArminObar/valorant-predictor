import React, { useEffect, useRef } from "react";
import { useApi, fmtPct } from "../lib/useApi.js";
import { TitleWithInfo, TIPS } from "../components/InfoTip.jsx";
import { buildRatingChart } from "../chart.js";

export function RecentResults() {
  const { data, err } = useApi("/api/results");
  if (err || !data || !data.generated_at || !data.series) return null;
  const s = data.series, m = data.map, sel = data.selected || {};
  const tiers = data.per_tier || [];
  return (
    <div className="panel">
      <TitleWithInfo title="Where the model stands (recent test window)"
        info={"Matches split in time order: the oldest 70% trains, the "
          + "next 15% tunes, the newest 15% stays untouched until scoring. "
          + "The model never saw this window. The accent marks each leader "
          + "on its own; when accuracy and log loss disagree, both marks "
          + "stay. Every number regenerates from scripts/evaluate.py. "
          + "Nothing is typed in by hand."} />
      <p className="note">
        Scored on the newest 15% of matches, held out untouched.
        Lower is better for log loss and Brier.
      </p>
      <div className="mgroup">
        <div className="mgroup-title">Series
          <span className="mgroup-sub">
            what the site publishes &middot; {s.n} held-out series
          </span>
        </div>
        <div className="metrics">
          <div className="metric head">
            <div className="metric-label" />
            <div className="metric-val">model</div>
            <div className="metric-val elo">elo</div>
          </div>
          <Metric label="correct picks" pct higher
            model={s.model.accuracy} elo={s.elo.accuracy} />
          <Metric label="log loss"
            model={s.model.log_loss} elo={s.elo.log_loss} />
          <Metric label="brier" model={s.model.brier} elo={s.elo.brier} />
        </div>
      </div>
      <div className="mgroup">
        <div className="mgroup-title">Maps
          <span className="mgroup-sub">
            one row per map played &middot; {m.n_rows} held-out maps
          </span>
        </div>
        <div className="metrics">
          <div className="metric head">
            <div className="metric-label" />
            <div className="metric-val">model</div>
            <div className="metric-val elo">elo</div>
          </div>
          <Metric label="correct picks" pct higher
            model={m.model.accuracy} elo={m.elo.accuracy} />
          <Metric label="log loss"
            model={m.model.log_loss} elo={m.elo.log_loss} />
          <Metric label="brier" model={m.model.brier} elo={m.elo.brier} />
        </div>
      </div>
      <div className="mgroup">
      <div className="mgroup-title">By event tier
        <span className="mgroup-sub">map grain &middot; never pooled</span>
      </div>
      <div className="table-scroll">
      <table className="ledger">
        <thead>
          <tr><th>tier</th><th className="num">test map rows</th>
            <th className="num sep">model acc</th><th className="num">elo acc</th>
            <th className="num sep">model LL</th><th className="num">elo LL</th></tr>
        </thead>
        <tbody>
          {tiers.map((t) => {
            const acc = metricLead(t.model_acc, t.elo_acc, true);
            const ll = metricLead(t.model_ll, t.elo_ll);
            return (
              <tr key={t.tier}>
                <td>{t.tier}</td>
                {t.n_map_rows ? (
                  <>
                    <td className="num">{t.n_map_rows}</td>
                    <td className="num sep"><Lead win={acc === "model"}>{fmtPct(t.model_acc)}</Lead></td>
                    <td className="num dim"><Lead win={acc === "elo"}>{fmtPct(t.elo_acc)}</Lead></td>
                    <td className="num sep"><Lead win={ll === "model"}>{t.model_ll.toFixed(4)}</Lead></td>
                    <td className="num dim"><Lead win={ll === "elo"}>{t.elo_ll.toFixed(4)}</Lead></td>
                  </>
                ) : (
                  <td colSpan={5} className="dim">no test rows</td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
      </div>
      <p className="note" style={{ margin: "10px 0 0" }}>
        Slices differ in size and the small ones swing.
      </p>
      </div>
      <p className="note">
        Generated {fmtTime(data.generated_at)} over
        {" "}{data.store?.n_matches_usable} usable matches.
        Model: {sel.name} + {sel.calibration}.
      </p>
      <p className="note" style={{ margin: 0 }}>
        The two-year backtest is the tougher half of the story.{" "}
        <Link className="linklike" to="/backtest">see the full backtest</Link>
      </p>
    </div>
  );
}


export function ModelTab() {
  const { data, err } = useApi("/api/model");
  if (err) return <p className="empty">API unreachable.</p>;
  if (!data) return <p className="empty">Loading&hellip;</p>;
  if (data.error) return <p className="empty">{data.error}</p>;
  const rows = [
    ["version", data.version],
    ["algorithm", data.model_name],
    ["calibration", data.cal_name],
    ["trained", data.trained_at && fmtTime(data.trained_at)],
    ["matches in store", data.n_matches],
    ["elo baseline K", data.elo_k_baseline],
    ["half-life (days)", data.params?.half_life_days],
    ["roster factor", data.params?.roster_factor],
  ];
  return (
    <>
    <RecentResults />
    <div className="panel">
      <TitleWithInfo title="Model details (live bundle)" info={TIPS.model} />
      {data.synthetic_data && (
        <p className="warn">This model was trained on made-up demo data.</p>
      )}
      <table className="kv">
        <tbody>
          {rows.map(([k, v]) => (
            <tr key={k}><td className="dim">{k}</td><td>{String(v ?? "n/a")}</td></tr>
          ))}
        </tbody>
      </table>
      <p className="note" style={{ margin: "12px 0 0" }}>
        Predicts one map at a time from vlr.gg history, using only matches
        finished before the predicted match started. Per-map probabilities
        combine into one calibrated series probability.
      </p>
    </div>
    </>
  );
}
