import React, { useEffect, useState } from "react";
import {
  Link, NavLink, Navigate, Route, Routes,
  useLocation, useNavigate, useParams,
} from "react-router-dom";
import { fmtTime } from "./time.js";
import { buildRatingChart } from "./chart.js";
import { summarizeBacktestTiers } from "./backtestSummary.js";

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
            <span className="badge" title={"One or both teams have fewer "
              + "than 3 recorded maps, so this prediction leans on "
              + "defaults. Extra doubt advised."}>low history</span>
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
        Matches that haven't started yet. Each prediction is locked in
        ("frozen") at least 5 minutes before the match, so it can't be
        changed after the fact. Generated {fmtTime(data.generated_at)} by
        model {data.model_version}.
      </p>
      {data.predictions.map((m) => (
        <UpcomingCard key={m.match_id} m={m} onOpen={onOpen} />
      ))}
    </>
  );
}

function Metric({ label, model, elo }) {
  const better =
    model == null || elo == null ? null :
    label.includes("accuracy") ? model > elo : model < elo;
  return (
    <div className="metric">
      <div className="metric-label">{label}</div>
      <div className={`metric-val ${better === true ? "win" : ""}`}>{fmt4(model)}</div>
      <div className={`metric-val elo ${better === false ? "win" : ""}`}>{fmt4(elo)}</div>
    </div>
  );
}

function MarketPicks() {
  const { data, err } = useApi("/api/markets");
  if (err || !data) return null;
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
        locked-in probability to their price. EV is the expected profit
        per $1 staked if our probability is right; "de-vig" means the
        bookmaker's built-in margin has been removed from their implied
        probability. Live rows only. Not betting advice.
      </p>
      {!gate.ev_validated && (
        <p className="warn">
          EV numbers are unvalidated until {gate.required} market-covered
          picks have graded ({gate.n_graded} so far). That threshold was
          set before the first pick graded, so it can't be moved to
          flatter the results.
        </p>
      )}
      {picks.length === 0 ? (
        <p className="empty">
          No market-covered picks yet. They appear once a captured
          sportsbook price matches up with a frozen prediction (prices are
          captured every 10 minutes, off-site).
        </p>
      ) : (
        <>
          {s && s.n_graded > 0 && (
            <p className="note">
              {s.n_graded} graded · win rate {fmtPct(s.win_rate)}
              {s.avg_ev_pct != null && <> · avg EV {s.avg_ev_pct}%</>}
              {s.avg_clv_pct != null && <> · avg CLV {s.avg_clv_pct}% ·
                beat close {fmtPct(s.beat_close_rate)}</>}
              {" "}· picks marked "extrapolation" or "EV excluded" are
              left out of these averages (map totals are excluded for now:
              their probabilities carry a known bias we've measured and
              not yet fixed)
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
                      <span className="badge" title={"Our probability is "
                        + "outside the range where calibration was checked "
                        + "(15% to 88%), so trust it less."}>
                        extrapolation</span>}
                    {p.ev_excluded === "totals_independence_bias" &&
                      <span className="badge" title={"Map-total "
                        + "probabilities currently assume maps are "
                        + "independent, and measured reality says they "
                        + "aren't (2-0s happen about 7 points more often "
                        + "than assumed). The EV here would be a known-"
                        + "biased number, so it's excluded until that's "
                        + "fixed."}>EV excluded</span>}</td>
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
            EV = our locked-in probability times the price at capture,
            minus 1. Positive means the price looked better than our
            probability said it should be. The de-vig column uses Shin's
            method. Only match winners and total-maps bets are scored,
            nothing else.
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
        We re-ran the whole system over the past two years as if it had
        been live the entire time: every prediction uses only information
        that existed at that moment, and the model retrains on the real
        production schedule ({w.n_retrains} retrains).
        {" "}{w.n_predictions} simulated predictions
        ({w.n_low_history} of them low-history, counted but not scored)
        from {fmtTime(w.first_prediction)} to {fmtTime(w.last_prediction)}.
        Because it's simulated, it is kept strictly separate from the live
        scoreboard above. The two are never mixed into one number.
      </p>
      <table className="ledger">
        <thead>
          <tr><th>tier</th><th>n scored</th><th>model LL</th>
            <th>model acc</th><th>elo LL</th><th>elo acc</th></tr>
        </thead>
        <tbody>
          {tiers.map(([tier, m]) => (
            <tr key={tier}>
              <td>{tier}</td>
              {m.n_scored ? (
                <>
                  <td>{m.n_scored}</td>
                  <td className={m.model_ll < m.elo_ll ? "ok" : ""}>
                    {m.model_ll.toFixed(4)}</td>
                  <td>{fmtPct(m.model_acc)}</td>
                  <td className={m.elo_ll < m.model_ll ? "ok" : ""}>
                    {m.elo_ll.toFixed(4)}</td>
                  <td>{fmtPct(m.elo_acc)}</td>
                </>
              ) : (
                <td colSpan={5} className="dim">no scored rows</td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="note">
        Results are split by event tier (tier1 is the top pro circuit) and
        never pooled into one number. Lower log loss is better; green
        marks the winner in each tier. The short version: replayed
        honestly across its full history, including the early data-starved
        era, Elo wins most of it and the model does better in the most
        recent stretch. This backtest runs once. It only re-runs if the model
        changes, and the old result stays archived.
        {data.synthetic_data && (
          <span className="badge">contains synthetic data</span>
        )}
      </p>
    </div>
  );
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
          + "stored data. You can't verify it the way you can the live "
          + "scoreboard above, which is why the two are kept apart."}>
          simulated</span>
      </div>
      <p className="note">
        The whole system was also replayed over two years of history as if
        it had been live the entire time ({w.n_predictions} simulated
        predictions). Across the {t.n} scored event tiers, Elo wins{" "}
        {t.eloLeads} on log loss and the model wins {t.modelLeads} — the
        long history is the tougher half of the story, and it stays in
        full view, never mixed into the live numbers above.{" "}
        <Link className="linklike" to="/backtest">
          see the full per-tier backtest
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
          Every row here was locked in before its match started, then graded
          when the match ended. This is the record the model has to live
          with. Rows marked "low history" (like unresolved TBD bracket
          slots) stay in the record but are not scored, the same rule the
          backtest uses. The sample grows as pending matches finish; be
          careful reading much into small counts.
        </p>
        {s.n_scored === 0 ? (
          <p className="empty">
            {s.n_graded > 0
              ? `${s.n_graded} graded so far, all low-history, so nothing is
                 scored yet. The scoreboard fills in as predicted matches
                 finish, and this page is the honest record either way.`
              : `Nothing graded yet. The scoreboard fills in as predicted
                 matches finish, and this page is the honest record either
                 way.`}
          </p>
        ) : (
          <div className="metrics">
            <div className="metric head">
              <div className="metric-label" />
              <div className="metric-val">model</div>
              <div className="metric-val elo">elo</div>
            </div>
            <Metric label="log loss" model={s.model.log_loss} elo={s.elo.log_loss} />
            <Metric label="brier" model={s.model.brier} elo={s.elo.brier} />
            <Metric label="accuracy" model={s.model.accuracy} elo={s.elo.accuracy} />
          </div>
        )}
        {s.n_scored > 0 && (
          <p className="note">
            Scored over {s.n_scored} graded matches
            {s.n_low_history > 0 &&
              ` (${s.n_low_history} more graded but low-history, not scored)`}.
            Log loss and Brier measure how good the probabilities are
            (lower is better). Accuracy just counts correct picks (higher
            is better). Green marks whichever side is ahead.
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
                        <span className="badge" title={"One or both teams "
                          + "had almost no history when this was locked in "
                          + "(often an unresolved TBD bracket slot). Kept "
                          + "in the record, not scored."}>low history</span>
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
        Matches are split in time order: the oldest 70 percent trains the
        model, the next 15 percent tunes it, and the newest 15 percent is
        held out untouched until scoring. The numbers below are that
        held-out window; the model never saw these matches while training
        or tuning. Log loss and Brier score the probabilities (lower is
        better), accuracy counts correct picks (higher is better), and
        green marks whichever side is ahead. The series line is the one
        the site actually publishes.
      </p>
      <div className="metrics">
        <div className="metric head">
          <div className="metric-label" />
          <div className="metric-val">model</div>
          <div className="metric-val elo">elo</div>
        </div>
        <Metric label={`series log loss (${s.n} series)`}
          model={s.model.log_loss} elo={s.elo.log_loss} />
        <Metric label="series brier" model={s.model.brier} elo={s.elo.brier} />
        <Metric label="series accuracy"
          model={s.model.accuracy} elo={s.elo.accuracy} />
        <Metric label={`map log loss (${m.n_rows} maps)`}
          model={m.model.log_loss} elo={m.elo.log_loss} />
        <Metric label="map brier" model={m.model.brier} elo={m.elo.brier} />
        <Metric label="map accuracy"
          model={m.model.accuracy} elo={m.elo.accuracy} />
      </div>
      <table className="ledger">
        <thead>
          <tr><th>tier</th><th>test map rows</th><th>model LL</th>
            <th>model acc</th><th>elo LL</th><th>elo acc</th></tr>
        </thead>
        <tbody>
          {tiers.map((t) => (
            <tr key={t.tier}>
              <td>{t.tier}</td>
              {t.n_map_rows ? (
                <>
                  <td>{t.n_map_rows}</td>
                  <td className={t.model_ll < t.elo_ll ? "ok" : ""}>
                    {t.model_ll.toFixed(4)}</td>
                  <td>{fmtPct(t.model_acc)}</td>
                  <td className={t.elo_ll < t.model_ll ? "ok" : ""}>
                    {t.elo_ll.toFixed(4)}</td>
                  <td>{fmtPct(t.elo_acc)}</td>
                </>
              ) : (
                <td colSpan={5} className="dim">no test rows</td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="note">
        Split by event tier, never pooled into one number. The slices are
        different sizes and the small ones move around; read them with
        that in mind.
      </p>
      <p className="note">
        Generated {fmtTime(data.generated_at)} by scripts/evaluate.py over
        the full store ({data.store?.n_matches_usable} usable matches,
        {" "}{data.store?.window?.[0]} to {data.store?.window?.[1]}).
        Model evaluated: {sel.name} + {sel.calibration}. Every number
        here regenerates from that one script; nothing on this page is
        typed in by hand.
      </p>
      <p className="note">
        The two-year backtest tells the tougher half of the story: the
        whole system replayed honestly across its full history, including
        the early data-starved era when the model had almost nothing to
        learn from. Elo wins most of that history and the model does
        better in the recent stretch, which is the window above.{" "}
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
        The model predicts one map at a time, trained on scraped vlr.gg
        history. Every stat it uses comes only from matches that had
        already finished before the match being predicted started (no
        peeking at the future). Per-map probabilities get combined into
        one series probability, and everything is calibrated on held-out
        data so that "65%" is meant to come true about 65% of the time.
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
        Overall Elo (K={rh.k}) after each of each team's last {rh.n}
        completed matches, up to this match's start. Points are evenly
        spaced by match, not by date. This is the same rating family the
        Elo comparison uses; it is history for context, and the locked
        prediction above never moves.
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
              <span className="badge" title={"One or both teams had almost "
                + "no history when this was locked in. Kept in the record, "
                + "not scored."}>low history</span>
            )}
          </span>
          <span className="num b">{fmtPct(1 - p)}</span>
        </div>
        {placeholder && (
          <p className="warn">
            This was an unresolved bracket slot ("TBD") when the prediction
            locked, so the model was effectively comparing a team to
            itself. The frozen call stands because the first call per match
            can never be changed, but it is flagged low-history and not
            scored anywhere. The teams that eventually played this slot
            never got a fresh prediction here; that is the cost of the
            freeze rule, kept on the record rather than papered over.
          </p>
        )}
        {graded && !placeholder && (
          <p className="note result-line">
            Result: <b>{winner}</b> won
            {data.ledger.maps_played ? ` in ${data.ledger.maps_played} maps` : ""}.
            The prediction above is exactly what was locked in beforehand.
          </p>
        )}
        {!graded && data.ledger && (
          <p className="note">
            This prediction is frozen in the public ledger. It cannot change,
            whatever happens between now and the match.
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
            Each bar is the Elo lean: {src.team1_name}'s map-specific
            strength edge going into the model, the one signal that
            actually varies map to map (right of center favours{" "}
            {src.team1_name}, left favours {src.team2_name}). The model's
            calibrated percentage sits at the end of each row; calibration
            maps raw scores onto a small set of levels learned from
            held-out results, so those percentages often tie across maps.
            The headline above remains the number that counts.
            {data.ledger ? " It is the frozen public call; the rows below"
              + " are the current model's live view and can differ from"
              + " it." : ""}
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
                    + `${m} (negative favours ${src.team2_name}). This is `
                    + `the model's per-map input, before calibration.`}>
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

function HeroStats() {
  const { data } = useApi("/api/results");
  if (!data || !data.generated_at || !data.series) {
    return (
      <p className="hero-copy">
        Where it stands: on the most recent slice of two years of data,
        the model beats Elo at both the map level and the series level.
        Replayed over the full two years, Elo wins more of the history.
        Both views are on this site.
      </p>
    );
  }
  const s = data.series, m = data.map;
  return (
    <div className="hero-stats">
      <div className="hero-stats-title">
        Recent test window: {s.n} held-out series the model never trained
        or tuned on
      </div>
      <div className="metrics">
        <div className="metric head">
          <div className="metric-label" />
          <div className="metric-val">model</div>
          <div className="metric-val elo">elo</div>
        </div>
        <Metric label="series log loss"
          model={s.model.log_loss} elo={s.elo.log_loss} />
        <Metric label="series accuracy"
          model={s.model.accuracy} elo={s.elo.accuracy} />
        <Metric label="map log loss"
          model={m.model.log_loss} elo={m.elo.log_loss} />
      </div>
      <p className="hero-stats-note">
        Lower log loss is better; higher accuracy is better; green marks
        the winner. Full table, per-tier numbers, and where these come
        from are in the model tab.
      </p>
    </div>
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
        <span className="badge" title={"One or both teams have fewer "
          + "than 3 recorded maps, so this prediction leans on "
          + "defaults. Extra doubt advised."}>low history</span>
      ) : null}
    </div>
  );
}

function Hero({ onOpen, onHome }) {
  return (
    <div className="hero">
      <svg className="hero-bg" viewBox="0 0 1200 420" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
        <defs>
          <linearGradient id="hgA" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#37b3a8" stopOpacity="0.16" />
            <stop offset="1" stopColor="#37b3a8" stopOpacity="0.02" />
          </linearGradient>
          <linearGradient id="hgB" x1="1" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#e06a4e" stopOpacity="0.14" />
            <stop offset="1" stopColor="#e06a4e" stopOpacity="0.02" />
          </linearGradient>
          <linearGradient id="hgBar" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0" stopColor="#37b3a8" />
            <stop offset="0.58" stopColor="#37b3a8" />
            <stop offset="0.58" stopColor="#e06a4e" />
            <stop offset="1" stopColor="#e06a4e" />
          </linearGradient>
        </defs>
        <polygon points="0,0 560,0 260,420 0,420" fill="url(#hgA)" />
        <polygon points="1200,0 700,0 980,420 1200,420" fill="url(#hgB)" />
        <g stroke="#37b3a8" strokeOpacity="0.10" strokeWidth="1">
          <path d="M-40,90 L1240,30" /><path d="M-40,180 L1240,120" />
          <path d="M-40,270 L1240,210" /><path d="M-40,360 L1240,300" />
        </g>
        <g stroke="#e06a4e" strokeOpacity="0.08" strokeWidth="1">
          <path d="M-40,60 L1240,150" /><path d="M-40,150 L1240,240" />
          <path d="M-40,240 L1240,330" /><path d="M-40,330 L1240,420" />
        </g>
      </svg>
      <div className="hero-bar" aria-hidden="true">
        <span className="hero-bar-notch" />
      </div>
      <div className="hero-inner">
        <div className="logo hero-logo clickable" role="button" tabIndex={0}
          title="back to the homepage"
          onClick={onHome}
          onKeyDown={(e) => e.key === "Enter" && onHome()}>
          v<span className="logo-accent">predict</span>
        </div>
        <div className="tagline hero-tagline">
          Valorant win probabilities, locked in before each match and graded
          in public.
        </div>
        <p className="hero-copy">
          This site predicts who wins pro Valorant matches, then shows its
          work. Every prediction is locked in at least 5 minutes before the
          match starts and graded in public once it ends, against Elo (a
          simple rating system that is hard to beat) and against real
          sportsbook odds.
        </p>
        <HeroStats />
        <p className="hero-copy">
          Replayed over the full two years of history, including the
          early data-starved era when the model had almost nothing to
          learn from, Elo wins more of it. That backtest is kept in full
          view, one click away. The live scoreboard has only just started
          grading, so treat it as a record being written, not a verdict.
        </p>
        <nav className="intro-links">
          <Link to="/upcoming">see upcoming predictions</Link>
          <Link to="/backtest">see the backtest</Link>
        </nav>
        <HeroNext onOpen={onOpen} />
      </div>
    </div>
  );
}

function ScrollToTop() {
  // New URL, top of the new page — the behaviour every multi-page site
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
        <Link className="linklike" to="/upcoming">back to upcoming</Link>
      </p>
    </div>
  );
}

export default function App() {
  const navigate = useNavigate();
  const { data: health } = useApi("/api/health");
  // Every view owns a URL now. Clicking a tab is navigation, so it always
  // lands on that tab's own default view — a match detail can't shadow it
  // (the trap in LOG entry 42) — and browser back/forward, reloads, and
  // shared links all behave like any normal site.
  const openMatch = (id) => navigate(`/match/${encodeURIComponent(id)}`);
  const goHome = () => {
    navigate("/upcoming");
    window.scrollTo({ top: 0, behavior: "smooth" });
  };
  return (
    <div className="wrap">
      <ScrollToTop />
      <Hero onOpen={openMatch} onHome={goHome} />
      {health?.synthetic_model && (
        <p className="warn">
          This is a demo model trained on made-up data. Not real
          predictions.
        </p>
      )}
      <nav className="tabs">
        {["upcoming", "scoreboard", "model", "backtest"].map((t) => (
          <NavLink key={t} to={`/${t}`}
            className={({ isActive }) => (isActive ? "on" : "")}>
            {t}
          </NavLink>
        ))}
      </nav>
      <Routes>
        <Route path="/" element={<Navigate to="/upcoming" replace />} />
        <Route path="/upcoming" element={<Upcoming onOpen={openMatch} />} />
        <Route path="/scoreboard" element={<Scoreboard onOpen={openMatch} />} />
        <Route path="/model" element={<ModelTab />} />
        <Route path="/backtest" element={<Backtest />} />
        <Route path="/match/:id" element={<MatchDetail />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
      <footer>
        Data scraped politely from vlr.gg (robots.txt respected, at least 1s
        between requests). Predictions lock at least 5 minutes before each
        match, and the first call stands. Not affiliated with Riot Games.
        Not betting advice.{" "}
        <a className="repo-link"
           href="https://github.com/ArminObar/valorant-predictor"
           target="_blank" rel="noreferrer">source on GitHub</a>
      </footer>
    </div>
  );
}
