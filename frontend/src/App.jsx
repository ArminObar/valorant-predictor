import React, { useEffect, useState } from "react";

const fmtPct = (p) => `${(p * 100).toFixed(1)}%`;
const fmt4 = (v) => (v == null ? "—" : v.toFixed(4));
const fmtTime = (iso) =>
  new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });

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

function Scoreboard() {
  const { data, err } = useApi("/api/scoreboard");
  if (err) return <p className="empty">API unreachable.</p>;
  if (!data) return <p className="empty">Loading…</p>;
  const s = data.summary;
  return (
    <>
      <div className="panel">
        <div className="panel-title">
          Called in advance · {s.n_graded} graded · {s.n_pending} pending
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
