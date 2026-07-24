import React, { useEffect, useState } from "react";
import { fmtTime } from "./time.js";

const fmtPct = (p) => `${(p * 100).toFixed(1)}%`;
const fmt4 = (v) => (v == null ? "—" : v.toFixed(4));

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
          model favours <b>{fav}</b> · Elo says {fmtPct(m.p_elo)}
          {m.low_history ? <span className="badge">low history</span> : null}
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
        No predictions logged yet. Run <code>python scripts/predict_upcoming.py --crawl</code>.
      </p>
    );
  return (
    <>
      <p className="note">
        Generated {fmtTime(data.generated_at)} · model {data.model_version} ·
        every prediction below is frozen in the ledger at least 5 minutes
        before match start.
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
        Market picks · LIVE — frozen ledger vs captured odds
      </div>
      {!gate.ev_validated && (
        <p className="warn">
          EV unvalidated — {gate.n_graded}/{gate.required} graded
          market-covered picks. The threshold was registered before the
          first pick graded; numbers below are provisional until it is met.
        </p>
      )}
      {picks.length === 0 ? (
        <p className="empty">
          No market-covered picks yet. They appear once a captured price
          links to a frozen prediction (odds capture runs off-site every
          10 minutes).
        </p>
      ) : (
        <>
          {s && s.n_graded > 0 && (
            <p className="note">
              {s.n_graded} graded · win rate {fmtPct(s.win_rate)}
              {s.avg_ev_pct != null && <> · avg EV {s.avg_ev_pct}%</>}
              {s.avg_clv_pct != null && <> · avg CLV {s.avg_clv_pct}% ·
                beat close {fmtPct(s.beat_close_rate)}</>}
              {" "}· extrapolated picks are labeled and excluded from these
              aggregates
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
                      <span className="badge">extrapolation</span>}</td>
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
            EV = frozen model probability × raw entry price − 1. De-vig
            column is Shin; the multiplicative sensitivity is in the data.
            Series moneyline and map totals only — nothing else is scored.
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
    <div className="panel">
      <div className="panel-title">
        Backtest — simulated walk-forward
        <span className="badge">simulated · not independently verifiable</span>
      </div>
      <p className="note">
        The live system replayed over history, once: the same pre-veto
        pool-mean quantity the ledger freezes, called at the last legal
        moment, retrained on the production cadence
        ({w.n_retrains} retrains) with the production selection policy.
        {" "}{w.n_predictions} simulated predictions
        ({w.n_low_history} low-history, counted but not scored) from{" "}
        {fmtTime(w.first_prediction)} to {fmtTime(w.last_prediction)}.
        Kept strictly separate from the LIVE frozen ledger above — the two
        are never merged into one number.
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
        Metrics per event tier only, over graded non-low-history rows.
        Green marks the lower (better) log loss per tier. Run-once: this
        result is re-generated only when the model changes, and the prior
        result stays archived.
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
          LIVE — frozen ledger · called in advance · {s.n_graded} graded
          · {s.n_pending} pending
        </div>
        {s.n_graded === 0 ? (
          <p className="empty">
            Nothing graded yet — the scoreboard fills in as predicted matches
            finish. This page is the honest record either way.
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
      </div>
      <MarketPicks />
      <Backtest />
      {data.graded.length > 0 && (
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
                  <td>{r.team1_name} <span className="dim">vs</span> {r.team2_name}</td>
                  <td className="dim">{fmtTime(r.start_ts)}</td>
                  <td>{fmtPct(r.p_model)}</td>
                  <td className="dim">{fmtPct(r.p_elo)}</td>
                  <td className={ok ? "ok" : "miss"}>{winner} {ok ? "✓" : "✗"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
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
      <div className="panel-title">Model card (live bundle)</div>
      {data.synthetic_data && (
        <p className="warn">This bundle was trained on SYNTHETIC demo data.</p>
      )}
      <table className="kv">
        <tbody>
          {rows.map(([k, v]) => (
            <tr key={k}><td className="dim">{k}</td><td>{String(v ?? "—")}</td></tr>
          ))}
        </tbody>
      </table>
      <p className="note">
        Trained at map grain on vlr.gg history with leakage-safe as-of features;
        chronological splits; probabilities Platt-calibrated on validation.
        Series probabilities aggregate per-map predictions over the current
        pool with uniform weights.
      </p>
    </div>
  );
}

export default function App() {
  const [tab, setTab] = useState("upcoming");
  const { data: health } = useApi("/api/health");
  return (
    <div className="wrap">
      <header>
        <div className="logo">
          v<span className="logo-accent">predict</span>
        </div>
        <div className="tagline">
          Valorant win probabilities, logged before the match — graded against Elo, in public.
        </div>
      </header>
      {health?.synthetic_model && (
        <p className="warn">Serving a SYNTHETIC-data demo model — not real predictions.</p>
      )}
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
        Data scraped politely from vlr.gg (robots.txt respected, ≥1s spacing).
        Predictions freeze ≥5 min pre-match; the first call stands. Not affiliated
        with Riot Games.
      </footer>
    </div>
  );
}
