import React, { useEffect, useState } from "react";
import {
  Link, NavLink, Route, Routes,
  useLocation, useNavigate, useParams,
} from "react-router-dom";
import { fmtTime } from "./time.js";
import { buildRatingChart } from "./chart.js";
import { summarizeBacktestTiers } from "./backtestSummary.js";
import { metricLead, liveStanding } from "./compare.js";

const fmtPct = (p) => `${(p * 100).toFixed(1)}%`;
const fmt4 = (v) => (v == null ? "n/a" : v.toFixed(4));

function useApi(path) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => {
    let alive = true;
    fetch(path)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(r.statusText))))
      .then((d) => alive && setData(d))
      .catch((e) => alive && setErr(e));
    return () => { alive = false; };
  }, [path]);
  return { data, err };
}

/* Signature element: the win-probability tug bar. Team A pulls from the
   left (teal), team B from the right (ember); the notch marks 50%. */
function TugBar({ p }) {
  return (
    <div className="tug">
      <div className="tug-fill" style={{ width: `${p * 100}%` }} />
      <div className="tug-notch" />
    </div>
  );
}

function UpcomingCard({ m, onOpen }) {
  const p = m.p_model;
  const fav = p >= 0.5 ? m.team1_name : m.team2_name;
  return (
    <div className="card clickable" role="button" tabIndex={0}
      onClick={() => onOpen(m.match_id)}
      onKeyDown={(e) => e.key === "Enter" && onOpen(m.match_id)}>
      <div className="card-top">
        <span className="event">{m.event}</span>
        <span className="when">{fmtTime(m.start_ts)} · Bo{m.best_of}</span>
      </div>
      <div className="teams">
        <span className={`team a ${p >= 0.5 ? "fav" : ""}`}>
          <i className="dot a" />{m.team1_name}</span>
        <span className="vs">vs</span>
        <span className={`team b ${p < 0.5 ? "fav" : ""}`}>
          {m.team2_name}<i className="dot b" /></span>
      </div>
      <TugBar p={p} />
      <div className="probs">
        <span className="num a">{fmtPct(p)}</span>
        <span className="mid">
          model picks <b>{fav}</b> · Elo says {fmtPct(m.p_elo)}
          {m.low_history ? (
            <span className="badge" title={"Fewer than 3 recorded maps "
              + "for one or both teams, so this leans on defaults. "
              + "Trust it less."}>low history</span>
          ) : null}
        </span>
        <span className="num b">{fmtPct(1 - p)}</span>
      </div>
    </div>
  );
}

function Upcoming({ onOpen }) {
  const { data, err } = useApi("/api/upcoming");
  if (err) return <p className="empty">API unreachable.</p>;
  if (!data) return <p className="empty">Loading…</p>;
  if (!data.predictions.length)
    return (
      <p className="empty">
        No upcoming predictions right now. New ones appear after the next
        refresh cycle (self-hosting? run
        <code> python scripts/predict_upcoming.py --crawl</code>).
      </p>
    );
  return (
    <>
      <p className="note">
        Matches that have not started yet. Each prediction locks at least
        5 minutes before the match and cannot change after. Generated
        {" "}{fmtTime(data.generated_at)} by model {data.model_version}.
      </p>
      {data.predictions.map((m) => (
        <UpcomingCard key={m.match_id} m={m} onOpen={onOpen} />
      ))}
    </>
  );
}

function Metric({ label, model, elo, higher = false, pct = false }) {
  // Direction is an explicit prop (no label sniffing), the winner comes from
  // metricLead so ties and missing values mark neither side, and each row
  // judges its own metric independently of its neighbours.
  const lead = metricLead(model, elo, higher);
  const show = (v) => (v == null ? "n/a" : pct ? fmtPct(v) : fmt4(v));
  return (
    <div className="metric">
      <div className="metric-label">{label}</div>
      <div className={`metric-val ${lead === "model" ? "win" : ""}`}>{show(model)}</div>
      <div className={`metric-val elo ${lead === "elo" ? "win" : ""}`}>{show(elo)}</div>
    </div>
  );
}

function MarketPicks({ standalone = false }) {
  // A silent null is right when this sits on the scoreboard, wrong when
  // it IS the page: the /markets route passes standalone for real states.
  const { data, err } = useApi("/api/markets");
  if (err) return standalone
    ? <p className="empty">API unreachable.</p> : null;
  if (!data) return standalone
    ? <p className="empty">Loading…</p> : null;
  const gate = data.gate || {};
  const s = data.summary;
  const picks = data.picks || [];
  return (
    <div className="panel">
      <div className="panel-title">
        Market picks: model vs real odds
      </div>
      <p className="note">
        When a sportsbook prices a match we predicted, we compare our
        locked probability to their price. EV is expected profit per $1
        if our probability is right. De-vig strips the bookmaker's
        margin. Live rows only. Not betting advice.
      </p>
      {!gate.ev_validated && (
        <p className="warn">
          EV numbers stay unvalidated until {gate.required} market-covered
          picks grade ({gate.n_graded} so far). The threshold was set
          before the first pick graded. It does not move.
        </p>
      )}
      {picks.length === 0 ? (
        <p className="empty">
          No market-covered picks yet. One appears when a captured price
          lines up with a frozen prediction. Prices are captured every
          10 minutes.
        </p>
      ) : (
        <>
          {s && s.n_graded > 0 && (
            <p className="note">
              {s.n_graded} graded · win rate {fmtPct(s.win_rate)}
              {s.avg_ev_pct != null && <> · avg EV {s.avg_ev_pct}%</>}
              {s.avg_clv_pct != null && <> · avg CLV {s.avg_clv_pct}% ·
                beat close {fmtPct(s.beat_close_rate)}</>}
              {" "}· picks marked "extrapolation" or "EV excluded" sit
              outside these averages. Map totals are excluded for now:
              their probabilities carry a measured bias we have not fixed.
            </p>
          )}
          <table className="ledger">
            <thead>
              <tr><th>match</th><th>selection</th><th>model</th>
                <th>implied</th><th>de-vig</th><th>EV</th><th>result</th></tr>
            </thead>
            <tbody>
              {picks.map((p) => (
                <tr key={`${p.match_id}-${p.market}-${p.line ?? ""}`}>
                  <td>{p.match}
                    <span className="dim"> · {p.market === "maps_total"
                      ? "map total" : "moneyline"} · {p.source}</span></td>
                  <td>{p.selection}
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
                  <td>{fmtPct(p.p_model)}</td>
                  <td className="dim">{fmtPct(p.implied)}</td>
                  <td className="dim">{fmtPct(p.shin)}</td>
                  <td className={p.ev_excluded ? "dim"
                      : p.ev_pct >= 0 ? "ok" : "miss"}>
                    {p.ev_excluded ? "excluded"
                      : `${p.ev_pct > 0 ? "+" : ""}${p.ev_pct}%`}</td>
                  <td className={p.graded ? (p.won ? "ok" : "miss") : "dim"}>
                    {p.graded ? (p.won ? "won ✓" : "lost ✗") : "pending"}
                    {p.graded && p.clv_pct != null &&
                      <span className="dim"> · CLV {p.clv_pct > 0 ? "+" : ""}
                        {p.clv_pct}%</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="note">
            EV = locked probability times the capture price, minus 1.
            Positive means the price looked too generous. De-vig uses
            Shin's method. Only match winners and map totals are scored.
          </p>
        </>
      )}
    </div>
  );
}

function Backtest() {
  const { data, err } = useApi("/api/backtest");
  if (err) return <p className="empty">API unreachable.</p>;
  if (!data) return <p className="empty">Loading…</p>;
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
      <div className="panel-title">
        Backtest: the system replayed over two years
        <span className="badge" title={"Computed after the fact from "
          + "stored data. You can't verify it the way you can the live "
          + "scoreboard, which is why the two are kept apart."}>
          simulated</span>
      </div>
      <p className="note">
        This page is the model's hardest exam, on purpose. The whole
        system is replayed over two years, including its worst stretch:
        the early data-starved era and a calibration bug fixed since.
        Nothing is trimmed to flatter it. It stays strictly separate from
        the live scoreboard, so neither record can borrow the other's
        best window. Over this history, Elo wins most tiers. The model
        has been closing the gap<LiveStandingClause />
      </p>
      <p className="note">
        The replay uses only what was known at each moment, and the model
        retrains on the production schedule ({w.n_retrains} retrains).
        {" "}{w.n_predictions} simulated predictions
        ({w.n_low_history} low-history, counted but not scored), from
        {" "}{fmtTime(w.first_prediction)} to {fmtTime(w.last_prediction)}.
      </p>
      <table className="ledger">
        <thead>
          <tr><th>tier</th><th>n scored</th><th>model acc</th>
            <th>elo acc</th><th>model LL</th><th>elo LL</th></tr>
        </thead>
        <tbody>
          {tiers.map(([tier, m]) => (
            <tr key={tier}>
              <td>{tier}</td>
              {m.n_scored ? (
                <>
                  <td>{m.n_scored}</td>
                  <td className={metricLead(m.model_acc, m.elo_acc, true)
                    === "model" ? "ok" : ""}>{fmtPct(m.model_acc)}</td>
                  <td className={metricLead(m.model_acc, m.elo_acc, true)
                    === "elo" ? "ok" : ""}>{fmtPct(m.elo_acc)}</td>
                  <td className={metricLead(m.model_ll, m.elo_ll)
                    === "model" ? "ok" : ""}>{m.model_ll.toFixed(4)}</td>
                  <td className={metricLead(m.model_ll, m.elo_ll)
                    === "elo" ? "ok" : ""}>{m.elo_ll.toFixed(4)}</td>
                </>
              ) : (
                <td colSpan={5} className="dim">no scored rows</td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="note">
        Split by event tier (tier1 is the top circuit), never pooled.
        Correct picks is the simple score. Log loss grades the confidence
        behind each call (lower is better). Green marks each comparison's
        leader on its own. Accuracy and log loss can disagree in a tier.
        When they do, both greens stay. The backtest runs once; it only
        re-runs if the model changes, and old results stay archived.
        {data.synthetic_data && (
          <span className="badge">contains synthetic data</span>
        )}
      </p>
    </div>
  );
}

function LiveStandingClause() {
  // The claim about the live record is derived at render time, never typed
  // in: it flips with the data (ASSUMPTIONS §37). Ties and unscored states
  // fall through to the neutral phrasing.
  const { data } = useApi("/api/scoreboard");
  const standing = liveStanding(data?.summary);
  const sb = (
    <Link className="linklike" to="/scoreboard">live scoreboard</Link>
  );
  if (standing === "ahead")
    return <>, and it is currently ahead on the {sb}'s real graded
      matches.</>;
  if (standing === "behind")
    return <>, though it is currently behind on the {sb}'s real graded
      matches.</>;
  if (standing === "mixed")
    return <>, and it is currently splitting the {sb}'s real graded
      matches with Elo.</>;
  return <>. The {sb} tracks the same head-to-head as real matches
    grade.</>;
}

function BacktestSummary() {
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
      <p className="note">
        The whole system was also replayed over two years as if it had
        been live the whole time ({w.n_predictions} simulated
        predictions). Across the {t.n} scored tiers, Elo wins{" "}
        {t.eloLeads} on log loss and the model wins {t.modelLeads}. The
        long history is the tougher half of the story. It stays in full
        view and never mixes into the live numbers above.{" "}
        <Link className="linklike" to="/backtest">
          see the full backtest
        </Link>
      </p>
    </div>
  );
}

function Scoreboard({ onOpen }) {
  const { data, err } = useApi("/api/scoreboard");
  if (err) return <p className="empty">API unreachable.</p>;
  if (!data) return <p className="empty">Loading…</p>;
  const s = data.summary;
  return (
    <>
      <div className="panel">
        <div className="panel-title">
          Live scoreboard: {s.n_graded} graded, {s.n_pending} pending
        </div>
        <p className="note">
          Every row locked in before its match and graded after. This is
          the record the model lives with. Low-history rows (like TBD
          bracket slots) stay listed but are not scored, same rule as the
          backtest. The sample is small early, so do not read too much
          into it.
        </p>
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
          <p className="note">
            Scored over {s.n_scored} graded matches
            {s.n_low_history > 0 &&
              ` (${s.n_low_history} more graded but low-history, not scored)`}.
            Correct picks is the simple score. Log loss and Brier grade
            the confidence behind each pick (lower is better). Green marks
            each row's leader on its own; when accuracy and log loss
            disagree, both greens stay.
          </p>
        )}
      </div>
      {data.graded.length > 0 && (
        <div className="panel">
          <div className="panel-title">Graded matches (live ledger)</div>
          <table className="ledger">
            <thead>
              <tr><th>match</th><th>start</th><th>model</th><th>elo</th><th>result</th></tr>
            </thead>
            <tbody>
              {data.graded.map((r) => {
                const winner = r.team1_won ? r.team1_name : r.team2_name;
                const ok = (r.p_model >= 0.5) === Boolean(r.team1_won);
                return (
                  <tr key={r.match_id} className="clickable"
                      onClick={() => onOpen(r.match_id)}>
                    <td>{r.team1_name} <span className="dim">vs</span> {r.team2_name}
                      {Boolean(r.low_history) && (
                        <span className="badge" title={"Almost no history "
                          + "when this locked (often a TBD bracket slot). "
                          + "Kept in the record, not scored."}>low history</span>
                      )}
                    </td>
                    <td className="dim">{fmtTime(r.start_ts)}</td>
                    <td>{fmtPct(r.p_model)}</td>
                    <td className="dim">{fmtPct(r.p_elo)}</td>
                    <td className={ok ? "ok" : "miss"}>{winner} {ok ? "✓" : "✗"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {data.pending.length > 0 && (
        <div className="panel">
          <div className="panel-title">Pending ({data.pending.length})</div>
          {data.pending.map((r) => (
            <div className="pending-row clickable" key={r.match_id}
                 role="button" tabIndex={0}
                 onClick={() => onOpen(r.match_id)}>
              <span>{r.team1_name} <span className="dim">vs</span> {r.team2_name}</span>
              <span className="dim">{fmtTime(r.start_ts)} · model {fmtPct(r.p_model)}</span>
            </div>
          ))}
        </div>
      )}
      <MarketPicks />
      <BacktestSummary />
    </>
  );
}

function RecentResults() {
  const { data, err } = useApi("/api/results");
  if (err || !data || !data.generated_at || !data.series) return null;
  const s = data.series, m = data.map, sel = data.selected || {};
  const tiers = data.per_tier || [];
  return (
    <div className="panel">
      <div className="panel-title">
        Where the model stands (recent test window)
      </div>
      <p className="note">
        Matches split in time order: the oldest 70% trains, the next 15%
        tunes, the newest 15% stays untouched until scoring. The model
        never saw the window below. Correct picks is the simple score.
        Log loss and Brier grade the confidence behind each pick (lower
        is better). Green marks each leader on its own; when accuracy and
        log loss disagree, both greens stay.
      </p>
      <div className="mgroup">
        <div className="mgroup-title">Series
          <span className="mgroup-sub">
            what the site publishes · {s.n} held-out series
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
            one row per map played · {m.n_rows} held-out maps
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
        <span className="mgroup-sub">map grain · never pooled</span>
      </div>
      <table className="ledger">
        <thead>
          <tr><th>tier</th><th>test map rows</th><th>model acc</th>
            <th>elo acc</th><th>model LL</th><th>elo LL</th></tr>
        </thead>
        <tbody>
          {tiers.map((t) => (
            <tr key={t.tier}>
              <td>{t.tier}</td>
              {t.n_map_rows ? (
                <>
                  <td>{t.n_map_rows}</td>
                  <td className={metricLead(t.model_acc, t.elo_acc, true)
                    === "model" ? "ok" : ""}>{fmtPct(t.model_acc)}</td>
                  <td className={metricLead(t.model_acc, t.elo_acc, true)
                    === "elo" ? "ok" : ""}>{fmtPct(t.elo_acc)}</td>
                  <td className={metricLead(t.model_ll, t.elo_ll)
                    === "model" ? "ok" : ""}>{t.model_ll.toFixed(4)}</td>
                  <td className={metricLead(t.model_ll, t.elo_ll)
                    === "elo" ? "ok" : ""}>{t.elo_ll.toFixed(4)}</td>
                </>
              ) : (
                <td colSpan={5} className="dim">no test rows</td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="note">
        Slices differ in size and the small ones swing. Read them with
        that in mind.
      </p>
      </div>
      <p className="note">
        Generated {fmtTime(data.generated_at)} by scripts/evaluate.py over
        the full store ({data.store?.n_matches_usable} usable matches,
        {" "}{data.store?.window?.[0]} to {data.store?.window?.[1]}).
        Model: {sel.name} + {sel.calibration}. Every number regenerates
        from that one script. Nothing here is typed in by hand.
      </p>
      <p className="note">
        The two-year backtest is the tougher half of the story: Elo wins
        most of it, and the model does better in the recent stretch,
        which is the window above.{" "}
        <Link className="linklike" to="/backtest">see the full backtest</Link>
      </p>
    </div>
  );
}

function ModelTab() {
  const { data, err } = useApi("/api/model");
  if (err) return <p className="empty">API unreachable.</p>;
  if (!data) return <p className="empty">Loading…</p>;
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
      <div className="panel-title">Model details (live bundle)</div>
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
      <p className="note">
        The model predicts one map at a time from scraped vlr.gg history.
        Every input comes from matches that finished before the predicted
        match started. No peeking. Per-map probabilities combine into one
        series probability, calibrated on held-out data so 65% means
        about 65%.
      </p>
    </div>
    </>
  );
}

function FormDots({ recent }) {
  return (
    <span className="form">
      {recent.map((r, i) => (
        <span key={i} className={`dot ${r.won ? "w" : "l"}`}
          title={`${r.won ? "won" : "lost"} ${r.score} vs ${r.opponent} (${r.event})`} />
      ))}
    </span>
  );
}

function RatingChart({ rh, team1 }) {
  const g = buildRatingChart(rh.teams);
  if (!g) return null;
  const color = (key) => (key === team1 ? "var(--a)" : "var(--b)");
  return (
    <div className="panel">
      <div className="panel-title">Rating history (last {rh.n} matches)</div>
      <svg className="rating-chart" viewBox={`0 0 ${g.w} ${g.h}`} role="img"
        aria-label="Elo rating history for both teams leading up to this match">
        <line x1={g.padL} x2={g.w - g.padR} y1={g.midY} y2={g.midY}
          className="rc-grid" />
        <text x={g.padL - 8} y={g.midY + 4} className="rc-axis">{g.mid}</text>
        {g.lines.map((ln) => (
          <g key={ln.key}>
            <polyline points={ln.points} fill="none" stroke={color(ln.key)}
              strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
            {ln.dots.map((d, i) => (
              <circle key={i} cx={d.x} cy={d.y} r="3" fill={color(ln.key)}>
                <title>{`${ln.name}: ${d.rating} after ${d.won ? "a win"
                  : "a loss"} vs ${d.opponent}`}</title>
              </circle>
            ))}
            <text x={ln.end.x + 7} y={ln.end.y + 4} className="rc-end"
              fill={color(ln.key)}>{Math.round(ln.end.rating)}</text>
          </g>
        ))}
      </svg>
      <p className="note">
        Overall Elo (K={rh.k}) after each team's last {rh.n} completed
        matches, up to this match's start. Points are spaced by match,
        not date. Context only; the locked prediction above never moves.
      </p>
    </div>
  );
}

function MatchDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  // Real history now: back is the browser's back. A direct deep link has
  // no in-app history to return to, so fall back to the upcoming list.
  const onBack = () =>
    location.key !== "default" ? navigate(-1) : navigate("/upcoming");
  const { data, err } = useApi(`/api/match/${encodeURIComponent(id)}`);
  if (err) return <p className="empty">API unreachable.</p>;
  if (!data) return <p className="empty">Loading…</p>;
  const src = data.ledger || data.prediction;
  if (!src)
    return (
      <div className="panel">
        <button className="back" onClick={onBack}>&larr; back</button>
        <p className="empty">No record for this match.</p>
      </div>
    );
  const p = src.p_model;
  const graded = data.ledger && data.ledger.graded;
  const placeholder = Boolean(data.placeholder);
  const winner = graded
    ? (data.ledger.team1_won ? src.team1_name : src.team2_name) : null;
  const th = data.team_history || {};
  const hA = th[src.team1], hB = th[src.team2];
  const pred = data.prediction;
  return (
    <>
      <div className="panel">
        <button className="back" onClick={onBack}>&larr; back</button>
        <div className="card-top">
          <span className="event">{src.event}</span>
          <span className="when">{fmtTime(src.start_ts)} · Bo{src.best_of}</span>
        </div>
        <div className="teams big">
          <span className={`team a ${p >= 0.5 ? "fav" : ""}`}>
            <i className="dot a" />{src.team1_name}</span>
          <span className="vs">vs</span>
          <span className={`team b ${p < 0.5 ? "fav" : ""}`}>
            {src.team2_name}<i className="dot b" /></span>
        </div>
        <TugBar p={p} />
        <div className="probs">
          <span className="num a">{fmtPct(p)}</span>
          <span className="mid">
            locked in {data.ledger ? fmtTime(data.ledger.made_at) : "pre-match"}
            {" "}· Elo says {fmtPct(src.p_elo)}
            {Boolean(src.low_history) && (
              <span className="badge" title={"Almost no history when this "
                + "locked. Kept in the record, not scored."}>low history</span>
            )}
          </span>
          <span className="num b">{fmtPct(1 - p)}</span>
        </div>
        {placeholder && (
          <p className="warn">
            This was an unresolved TBD slot when the prediction locked, so
            the model compared a team to itself. The first call per match
            can never change, so it stands, flagged low-history and never
            scored. The teams that filled the slot got no fresh prediction.
            That is the cost of the freeze rule, kept on the record.
          </p>
        )}
        {graded && !placeholder && (
          <p className="note result-line">
            Result: <b>{winner}</b> won
            {data.ledger.maps_played ? ` in ${data.ledger.maps_played} maps` : ""}.
            The prediction above is exactly what was locked beforehand.
          </p>
        )}
        {!graded && data.ledger && (
          <p className="note">
            This prediction is frozen in the public ledger. It cannot
            change, no matter what happens before the match.
          </p>
        )}
      </div>
      {data.rating_history && !placeholder && (
        <RatingChart rh={data.rating_history} team1={src.team1} />
      )}
      {pred && pred.per_map && (
        <div className="panel">
          <div className="panel-title">Per-map view</div>
          <p className="note">
            Each bar is the Elo lean: {src.team1_name}'s map-specific edge
            going into the model (right favours {src.team1_name}, left
            favours {src.team2_name}). It is the one input that really
            varies by map. The calibrated percentage sits at each row's
            end; calibration maps raw scores onto a few learned levels,
            so maps often tie. The headline above is the number that
            counts.
            {data.ledger ? " It is the frozen public call. The rows are"
              + " the current model's live view and can differ." : ""}
          </p>
          {(() => {
            const leans = pred.per_map_elo || null;
            const maxLean = leans ? Math.max(
              1, ...Object.values(leans).map((x) => Math.abs(x))) : 1;
            return Object.entries(pred.per_map).map(([m, v]) => {
              const lean = leans?.[m];
              if (lean == null) {
                // Older payload without per-map Elo: plain fallback row.
                return (
                  <div className="permap" key={m}>
                    <span className="permap-name">{m}</span>
                    <TugBar p={v} />
                    <span className="permap-num">{fmtPct(v)}</span>
                  </div>
                );
              }
              const side = lean >= 0 ? "a" : "b";
              const w = Math.min(50, (Math.abs(lean) / maxLean) * 50);
              return (
                <div className="permap-row" key={m}
                  title={`Map-specific Elo edge for ${src.team1_name} on `
                    + `${m}. Negative favours ${src.team2_name}. Model `
                    + `input, before calibration.`}>
                  <span className="permap-name">{m}</span>
                  <div className="lean-bar" aria-hidden="true">
                    <span className={`lean-fill ${side}`}
                      style={side === "a"
                        ? { left: "50%", width: `${w}%` }
                        : { right: "50%", width: `${w}%` }} />
                  </div>
                  <span className={`lean-num ${side}`}>
                    {`${lean >= 0 ? "+" : ""}${Math.round(lean)} Elo`}
                  </span>
                  <span className="permap-prob">model {fmtPct(v)}</span>
                </div>
              );
            });
          })()}
          {pred.maps_dist && (
            <p className="note">
              Expected series length: {Object.entries(pred.maps_dist)
                .map(([k, v]) => `${k} maps ${fmtPct(v)}`).join(" · ")}
            </p>
          )}
        </div>
      )}
      {data.picks && data.picks.length > 0 && (
        <div className="panel">
          <div className="panel-title">Market comparison</div>
          <table className="ledger">
            <thead>
              <tr><th>market</th><th>selection</th><th>model</th>
                <th>implied</th><th>de-vig</th><th>EV</th></tr>
            </thead>
            <tbody>
              {data.picks.map((k) => (
                <tr key={`${k.market}-${k.line ?? ""}`}>
                  <td>{k.market === "maps_total" ? "map total" : "moneyline"}
                    <span className="dim"> · {k.source}</span></td>
                  <td>{k.selection}
                    {k.ev_excluded === "totals_independence_bias" &&
                      <span className="badge" title={"Map-total "
                        + "probabilities currently assume maps are "
                        + "independent; measured reality disagrees by "
                        + "about 7 points, so this EV is excluded until "
                        + "that's fixed."}>EV excluded</span>}</td>
                  <td>{fmtPct(k.p_model)}</td>
                  <td className="dim">{fmtPct(k.implied)}</td>
                  <td className="dim">{fmtPct(k.shin)}</td>
                  <td className={k.ev_excluded ? "dim"
                      : k.ev_pct >= 0 ? "ok" : "miss"}>
                    {k.ev_excluded ? "excluded"
                      : `${k.ev_pct > 0 ? "+" : ""}${k.ev_pct}%`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {(hA || hB) && (
        <div className="panel">
          <div className="panel-title">Recent form (last 5 series)</div>
          <div className="detail-grid">
            {[hA, hB].map((h, i) => h && (
              <div key={i}>
                <div className={`form-team ${i === 0 ? "a" : "b"}`}>
                  {h.name} <FormDots recent={h.recent} />
                </div>
                {h.recent.map((r, j) => (
                  <div className="pending-row" key={j}>
                    <span className={r.won ? "ok" : "miss"}>
                      {r.won ? "W" : "L"} {r.score}
                    </span>
                    <span className="dim"> vs {r.opponent}</span>
                    <span className="dim">{fmtTime(r.start_ts)}</span>
                  </div>
                ))}
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  );
}

function HeroNext({ onOpen }) {
  const { data } = useApi("/api/upcoming");
  const now = Date.now();
  const next = (data?.predictions || [])
    .filter((p) => p.team1 !== p.team2)
    .filter((p) => new Date(p.start_ts).getTime() > now)
    .sort((a, b) => new Date(a.start_ts) - new Date(b.start_ts))[0];
  if (!next) return null;
  const p = next.p_model;
  const fav = p >= 0.5 ? next.team1_name : next.team2_name;
  return (
    <div className="hero-next clickable" role="button" tabIndex={0}
      onClick={() => onOpen(next.match_id)}
      onKeyDown={(e) => e.key === "Enter" && onOpen(next.match_id)}>
      <span className="hero-next-label">next up</span>
      <span className="hero-next-teams">
        {next.team1_name} <span className="dim">vs</span> {next.team2_name}
      </span>
      <span className="dim">{fmtTime(next.start_ts)}</span>
      <span className="hero-next-prob">
        model {fmtPct(p >= 0.5 ? p : 1 - p)} {fav}
      </span>
      {next.low_history ? (
        <span className="badge" title={"Fewer than 3 recorded maps "
          + "for one or both teams, so this leans on defaults. "
          + "Trust it less."}>low history</span>
      ) : null}
    </div>
  );
}

const LAND_LINKS = [
  ["upcoming", "predictions locked before each match"],
  ["scoreboard", "the live record, graded as matches end"],
  ["model", "what it is and how it scores"],
  ["markets", "model picks vs real sportsbook prices"],
  ["backtest", "two years replayed, worst stretch included"],
];

function Landing({ onOpen }) {
  return (
    <div className="land">
      <h1 className="logo land-logo">
        v<span className="logo-accent">predict</span>
      </h1>
      <div className="land-bar" aria-hidden="true">
        <span className="land-notch" />
      </div>
      <p className="land-tag">
        Valorant win probabilities, locked before each match and graded
        in public.
      </p>
      <nav className="land-links" aria-label="site sections">
        {LAND_LINKS.map(([path, sub]) => (
          <Link className="land-link" key={path} to={`/${path}`}>
            <span className="land-link-name">
              {path === "markets" ? "market picks" : path}
            </span>
            <span className="land-link-sub">{sub}</span>
            <span className="land-link-arrow" aria-hidden="true">&rarr;</span>
          </Link>
        ))}
      </nav>
      <p className="land-copy">
        A student project that calls pro Valorant matches before they
        start, then grades itself in public against Elo and real
        sportsbook odds. Elo still wins most of the two-year backtest.
        That stays in full view.
      </p>
      <HeroNext onOpen={onOpen} />
    </div>
  );
}

function SiteHeader() {
  return (
    <header>
      <Link className="logo site-logo" to="/" title="back to the homepage">
        v<span className="logo-accent">predict</span>
      </Link>
    </header>
  );
}

function ScrollToTop() {
  // New URL, top of the new page: the behaviour every multi-page site
  // gives for free. Back/forward still land where the browser puts them.
  const { pathname } = useLocation();
  useEffect(() => { window.scrollTo(0, 0); }, [pathname]);
  return null;
}

function NotFound() {
  return (
    <div className="panel">
      <p className="empty">
        No such page.{" "}
        <Link className="linklike" to="/">back to the homepage</Link>
      </p>
    </div>
  );
}

export default function App() {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const { data: health } = useApi("/api/health");
  // Every view owns a URL now. Clicking a tab is navigation, so it always
  // lands on that tab's own default view; a match detail can't shadow it
  // (the trap in LOG entry 42), and browser back/forward, reloads, and
  // shared links all behave like any normal site. The landing page is
  // its own nav, so the header and tab bar sit on interior pages only.
  const openMatch = (id) => navigate(`/match/${encodeURIComponent(id)}`);
  const landing = pathname === "/";
  return (
    <div className="wrap">
      <ScrollToTop />
      {!landing && <SiteHeader />}
      {health?.synthetic_model && (
        <p className="warn">
          Demo model trained on made-up data. Not real predictions.
        </p>
      )}
      {!landing && (
        <nav className="tabs">
          {["upcoming", "scoreboard", "model", "markets", "backtest"]
            .map((t) => (
              <NavLink key={t} to={`/${t}`}
                className={({ isActive }) => (isActive ? "on" : "")}>
                {t}
              </NavLink>
            ))}
        </nav>
      )}
      <Routes>
        <Route path="/" element={<Landing onOpen={openMatch} />} />
        <Route path="/upcoming" element={<Upcoming onOpen={openMatch} />} />
        <Route path="/scoreboard" element={<Scoreboard onOpen={openMatch} />} />
        <Route path="/model" element={<ModelTab />} />
        <Route path="/markets" element={<MarketPicks standalone />} />
        <Route path="/backtest" element={<Backtest />} />
        <Route path="/match/:id" element={<MatchDetail />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
      <footer>
        Data scraped politely from vlr.gg (robots.txt respected, 1s+
        between requests). Predictions lock at least 5 minutes before each
        match; the first call stands. Not affiliated with Riot Games. Not
        betting advice.{" "}
        <a className="repo-link"
           href="https://github.com/ArminObar/valorant-predictor"
           target="_blank" rel="noreferrer">source on GitHub</a>
      </footer>
    </div>
  );
}
