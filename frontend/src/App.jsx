import React, { useEffect, useState } from "react";
import { fmtTime } from "./time.js";

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

function UpcomingCard({ m }) {
  const p = m.p_model;
  const fav = p >= 0.5 ? m.team1_name : m.team2_name;
  return (
    <div className="card">
      <div className="card-top">
        <span className="event">{m.event}</span>
        <span className="when">{fmtTime(m.start_ts)} · Bo{m.best_of}</span>
      </div>
      <div className="teams">
        <span className={`team a ${p >= 0.5 ? "fav" : ""}`}>{m.team1_name}</span>
        <span className="vs">vs</span>
        <span className={`team b ${p < 0.5 ? "fav" : ""}`}>{m.team2_name}</span>
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

function Upcoming() {
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
        <UpcomingCard key={m.match_id} m={m} />
      ))}
    </>
  );
}

function Metric({ label, model, elo }) {
  const better =
    model == null || elo == null ? null :
    label === "accuracy" ? model > elo : model < elo;
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
              {" "}· picks marked "extrapolation" are excluded from these
              averages
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
                        extrapolation</span>}</td>
                  <td>{fmtPct(p.p_model)}</td>
                  <td className="dim">{fmtPct(p.implied)}</td>
                  <td className="dim">{fmtPct(p.shin)}</td>
                  <td className={p.ev_pct >= 0 ? "ok" : "miss"}>
                    {p.ev_pct > 0 ? "+" : ""}{p.ev_pct}%</td>
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
  if (err || !data || !data.window) return null;
  const w = data.window;
  const tiers = Object.entries(data.per_tier || {});
  return (
    <div className="panel" id="backtest">
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
        marks the winner in each tier. The short version: Elo wins most of
        the two-year history, and the model does better in the most recent
        stretch. This backtest runs once. It only re-runs if the model
        changes, and the old result stays archived.
        {data.synthetic_data && (
          <span className="badge">contains synthetic data</span>
        )}
      </p>
    </div>
  );
}

function Scoreboard() {
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
                  <tr key={r.match_id}>
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
            <div className="pending-row" key={r.match_id}>
              <span>{r.team1_name} <span className="dim">vs</span> {r.team2_name}</span>
              <span className="dim">{fmtTime(r.start_ts)} · model {fmtPct(r.p_model)}</span>
            </div>
          ))}
        </div>
      )}
      <MarketPicks />
      <Backtest />
    </>
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
  );
}

function Intro({ go }) {
  return (
    <div className="panel">
      <div className="panel-title">What this is</div>
      <p className="note">
        This site predicts who wins pro Valorant matches, then shows its
        work. Every prediction is locked in at least 5 minutes before the
        match starts and graded in public once it ends, against Elo (a
        simple rating system that is hard to beat) and against real
        sportsbook odds.
      </p>
      <p className="note">
        Where it stands: on the most recent slice of two years of data,
        the model beats Elo at both the map level and the series level.
        Replayed over the full two years, Elo wins more of the history.
        Both views are on this site. The live scoreboard has only just
        started grading, so treat it as a record being written, not a
        verdict.
      </p>
      <nav className="intro-links">
        <button onClick={() => go("upcoming")}>see upcoming predictions</button>
        <button onClick={() => go("backtest")}>see the backtest</button>
      </nav>
    </div>
  );
}

export default function App() {
  const [tab, setTab] = useState("upcoming");
  const { data: health } = useApi("/api/health");
  const go = (where) => {
    if (where === "backtest") {
      setTab("scoreboard");
      setTimeout(() =>
        document.getElementById("backtest")?.scrollIntoView(
          { behavior: "smooth" }), 60);
    } else {
      setTab(where);
    }
  };
  return (
    <div className="wrap">
      <header>
        <div className="logo">
          v<span className="logo-accent">predict</span>
        </div>
        <div className="tagline">
          Valorant win probabilities, locked in before each match and graded
          in public.
        </div>
      </header>
      {health?.synthetic_model && (
        <p className="warn">
          This is a demo model trained on made-up data. Not real
          predictions.
        </p>
      )}
      <Intro go={go} />
      <nav>
        {["upcoming", "scoreboard", "model"].map((t) => (
          <button key={t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>
            {t}
          </button>
        ))}
      </nav>
      {tab === "upcoming" && <Upcoming />}
      {tab === "scoreboard" && <Scoreboard />}
      {tab === "model" && <ModelTab />}
      <footer>
        Data scraped politely from vlr.gg (robots.txt respected, at least 1s
        between requests). Predictions lock at least 5 minutes before each
        match, and the first call stands. Not affiliated with Riot Games.
        Not betting advice.
      </footer>
    </div>
  );
}
