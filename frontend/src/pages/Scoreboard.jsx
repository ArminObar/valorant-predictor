import React from "react";
import { useApi, fmtPct, favored } from "../lib/useApi.js";
import { Masthead, MASTHEAD_TIPS } from "../components/Masthead.jsx";
import { Metric } from "../components/bits.jsx";
import { BacktestSummary } from "../components/BacktestSummary.jsx";
import { fmtTime } from "../time.js";
import { groupByDay } from "../daygroups.js";
import { DaySep, DayRow } from "../components/daybits.jsx";
import { TitleWithInfo, TIPS } from "../components/InfoTip.jsx";
import { MarketPicks } from "./MarketPicks.jsx";

export function Scoreboard({ onOpen }) {
  const { data, err } = useApi("/api/scoreboard");
  if (err) return <p className="empty">API unreachable.</p>;
  const s2 = (data && data.summary) || {};
  if (!data) return <p className="empty">Loading&hellip;</p>;
  const s = data.summary;
  return (
    <div className="page">
      <Masthead eyebrow="the running record" tip={MASTHEAD_TIPS.scoreboard}
        title="Scoreboard"
        stats={[
          ...(s2.model?.accuracy != null
            ? [{ value: fmtPct(s2.model.accuracy),
                 label: "correct picks" }] : []),
          { value: String(s2.n_graded ?? (data.graded || []).length),
            label: "graded", tone: "ink" },
        ]} />
    <>
      <div className="panel">
        <TitleWithInfo
          title={`Live scoreboard \u00b7 ${s.n_graded} graded, ${s.n_pending} pending`}
          info={TIPS.scoreboard} />
        {s.n_scored === 0 ? (
          <p className="empty">
            {s.n_graded > 0
              ? `${s.n_graded} graded so far, all low-history, so nothing
                 is scored yet. The scoreboard fills in as matches finish.`
              : `Nothing graded yet. The scoreboard fills in as predicted
                 matches finish.`}
          </p>
        ) : (
          <div className="metrics">
            <div className="metric head">
              <div className="metric-label" />
              <div className="metric-val">model</div>
              <div className="metric-val elo">elo</div>
            </div>
            <Metric label="correct picks (accuracy)" pct higher
              model={s.model.accuracy} elo={s.elo.accuracy} />
            <Metric label="log loss" model={s.model.log_loss} elo={s.elo.log_loss} />
            <Metric label="brier" model={s.model.brier} elo={s.elo.brier} />
          </div>
        )}
        {s.n_scored > 0 && (
          <p className="note" style={{ margin: "14px 0 0" }}>
            {s.n_scored} scored{s.n_low_history > 0 &&
              `, ${s.n_low_history} low-history rows listed but unscored`}.
            Lower is better for log loss and Brier.
          </p>
        )}
      </div>
      {data.graded.length > 0 && (
        <div className="panel">
          <div className="panel-title">Graded matches (live ledger)</div>
          <div className="table-scroll">
          <table className="ledger">
            <thead>
              <tr><th>match</th><th>start</th><th className="num">model</th>
                <th className="num">elo</th><th>result</th></tr>
            </thead>
            <tbody>
              {groupByDay(data.graded, { dir: "desc" }).map((g) => (
                <React.Fragment key={g.key}>
                  <DayRow label={g.label} span={5} today={g.isToday} />
                  {g.rows.map((r) => {
                const winner = r.team1_won ? r.team1_name : r.team2_name;
                const ok = (r.p_model >= 0.5) === Boolean(r.team1_won);
                return (
                  <tr key={r.match_id} className="clickable"
                      onClick={() => onOpen(r.match_id)}>
                    <td>{r.team1_name} <span className="dim">vs</span> {r.team2_name}
                      {Boolean(r.low_history) && (
                        <span className="badge" title={
                          r.team1_prior_maps != null
                            ? `${r.team1_prior_maps} and `
                              + `${r.team2_prior_maps} prior maps when this `
                              + `locked (often a TBD bracket slot). Kept in `
                              + `the record, not scored.`
                            : "Almost no history "
                              + "when this locked (often a TBD bracket slot). "
                              + "Kept in the record, not scored."}>low history
                          {r.team1_prior_maps != null
                            && ` (${r.team1_prior_maps}/${r.team2_prior_maps})`}
                        </span>
                      )}
                    </td>
                    <td className="dim">{fmtTime(r.start_ts)}</td>
                    <td className="num">{fmtPct(r.p_model)}</td>
                    <td className="num dim">{fmtPct(r.p_elo)}</td>
                    <td><span className={`chip ${ok ? "win" : "loss"}`}>
                      {winner} {ok ? "\u2713" : "\u2717"}</span></td>
                  </tr>
                );
              })}
                </React.Fragment>
              ))}
            </tbody>
          </table>
          </div>
        </div>
      )}
      {data.pending.length > 0 && (
        <div className="panel">
          <div className="panel-title">Pending ({s.n_pending})</div>
          {data.pending.length < s.n_pending && (
            <p className="note">
              Showing the {data.pending.length} soonest.
            </p>
          )}
          {groupByDay(data.pending, { dir: "asc" }).map((g) => (
            <React.Fragment key={g.key}>
              <DaySep label={g.label} today={g.isToday} />
              {g.rows.map((r) => {
                const fav = favored(r.p_model, r.team1_name, r.team2_name);
                return (
            <div className="pending-row clickable" key={r.match_id}
                 role="button" tabIndex={0}
                 onClick={() => onOpen(r.match_id)}>
              <span>{r.team1_name} <span className="dim">vs</span> {r.team2_name}</span>
              <span className="dim">{fmtTime(r.start_ts)} &middot; model{" "}
                {fav.name} {fav.pct}</span>
            </div>
                );
              })}
            </React.Fragment>
          ))}
        </div>
      )}
      <MarketPicks />
      <BacktestSummary />
    </>
    </div>
  );
}
