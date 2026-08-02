import React from "react";
import { useApi, fmtPct, fmtPctOpp, fmtSigned } from "../lib/useApi.js";
import { groupByDay } from "../daygroups.js";
import { DayRow } from "../components/daybits.jsx";
import { TitleWithInfo, TIPS } from "../components/InfoTip.jsx";
import { Masthead, MASTHEAD_TIPS } from "../components/Masthead.jsx";

export function MarketPicks({ standalone = false }) {
  const { data, err } = useApi("/api/markets");
  if (err) return standalone
    ? <p className="empty">API unreachable.</p> : null;
  if (!data) return standalone
    ? <p className="empty">Loading&hellip;</p> : null;
  const gate = data.gate || {};
  const evStat = gate.ev_validated
    ? { value: (data.summary && data.summary.avg_ev_pct != null)
        ? fmtSigned(data.summary.avg_ev_pct)
        : "n/a", label: "avg ev" }
    : { value: `${gate.n_graded ?? 0}/${gate.required ?? "?"}`,
        label: "ev-clean graded \u00b7 unvalidated", tone: "ink" };
  const s = data.summary;
  const picks = data.picks || [];
  return (
    <div className={standalone ? "page" : "panel"}>
      {standalone ? (
        <Masthead eyebrow="model against the books"
          tip={MASTHEAD_TIPS.markets} title="Markets"
          stats={[evStat,
            { value: String(picks.length), label: "picks", tone: "ink" }]} />
      ) : (
        <TitleWithInfo title="Market picks: model vs real odds"
          info={TIPS.markets} />
      )}
      <p className="note">Locked model probability vs the captured price. Not betting advice.</p>
      {!gate.ev_validated && (
        <p className="warn">
          EV stays unvalidated until {gate.required} EV-clean picks grade
          ({gate.n_graded} so far; flagged picks don't count toward the
          gate, so this can trail the graded total below).
        </p>
      )}
      {((data.skipped?.n_unpriceable ?? 0) > 0
        || (data.skipped?.n_group_errors ?? 0) > 0) && (
        <p className="note">
          {(data.skipped?.n_unpriceable ?? 0) > 0 && (
            <>{data.skipped.n_unpriceable} captured price
            {data.skipped.n_unpriceable === 1 ? "" : "s"} skipped as
            unpriceable (placeholder or non-finite odds). </>
          )}
          {(data.skipped?.n_group_errors ?? 0) > 0 && (
            <>{data.skipped.n_group_errors} pick group
            {data.skipped.n_group_errors === 1 ? "" : "s"} skipped on an
            internal error (logged). </>
          )}
          Skips are counted, never hidden.
        </p>
      )}
      {picks.length === 0 ? (
        <p className="empty">
          No market-covered picks yet. Prices are captured every 10 minutes.
        </p>
      ) : (
        <>
          {s && s.n_graded > 0 && (
            <p className="note">
              {s.n_graded} graded &middot; win rate {fmtPct(s.win_rate)}
              {s.avg_ev_pct != null && <> &middot; avg EV {fmtSigned(s.avg_ev_pct)}</>}
              {s.avg_clv_pct != null && <> &middot; avg CLV {fmtSigned(s.avg_clv_pct)} &middot;
                beat close {fmtPct(s.beat_close_rate)}</>}
              . Win rate covers every graded pick; the EV and CLV averages
              exclude flagged picks.
            </p>
          )}
          <p className="note">
            The highlighted side is the pick: the higher-EV side at its
            best entry price. Every number in a row belongs to that side.
            When the model itself leans the other way, the row says so.
          </p>
          <div className="table-scroll">
          <table className="ledger">
            <thead>
              <tr><th>match</th><th>pick</th><th className="num">model</th>
                <th className="num">implied</th><th className="num">de-vig (cons)</th>
                <th className="num">EV</th><th>result</th></tr>
            </thead>
            <tbody>
              {groupByDay(picks, { dir: "desc" }).map((g) => (
                <React.Fragment key={g.key}>
                  <DayRow label={g.label} span={7} today={g.isToday} />
                  {g.rows.map((p) => (
                <tr key={`${p.match_id}-${p.market}-${p.line ?? ""}`}>
                  <td>{p.match}
                    <span className="dim"> &middot; {p.market === "maps_total"
                      ? "map total" : "moneyline"} &middot; {p.source}</span></td>
                  <td><span className="badge pick">{p.selection}</span>
                    {p.source && <span className="badge dim">{p.source}</span>}
                    {p.p_model < 0.5 &&
                      <span className="dim"> &middot; model favours the
                        {" "}other side {fmtPctOpp(p.p_model)}</span>}
                    {p.extrapolated &&
                      <span className="badge" title={"Outside the range "
                        + "where calibration was checked (15% to 88%). "
                        + "Trust it less."}>
                        extrapolation</span>}
                    {p.ev_excluded === "totals_independence_bias" &&
                      <span className="badge" title={"Map totals assume "
                        + "maps are independent. Measured reality disagrees "
                        + "by about 7 points, so this EV is excluded until "
                        + "that is fixed."}>EV excluded</span>}</td>
                  <td className="num">{fmtPct(p.p_model)}</td>
                  <td className="num dim">{fmtPct(p.implied)}</td>
                  <td className="num dim">{fmtPct(p.shin_consensus ?? p.shin)}</td>
                  <td className={`num ${p.ev_excluded ? "dim"
                      : p.ev_pct >= 0 ? "ok" : "miss"}`}>
                    {p.ev_excluded ? "excluded"
                      : fmtSigned(p.ev_pct)}</td>
                  <td className={p.graded ? (p.won ? "ok" : "miss") : "dim"}>
                    {p.graded ? (p.won ? "won \u2713" : "lost \u2717") : "pending"}
                    {p.graded && p.clv_pct != null &&
                      <span className="dim"> &middot; CLV{" "}
                        {fmtSigned(p.clv_pct)}</span>}
                  </td>
                </tr>
              ))}
                </React.Fragment>
              ))}
            </tbody>
          </table>
          </div>
          <p className="note">
            Entry price and EV use the best available book for the pick
            (labeled). Best-of-books EV is upward biased by construction;
            the consensus de-vig column is the cross-book fair probability.
            The validation gate counts one pick per match and market,
            however many books priced it.
          </p>
        </>
      )}
    </div>
  );
}
