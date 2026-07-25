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

function MatchDetail({ id, onBack }) {
  const { data, err } = useApi(`/api/match/${id}`);
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
          <span className={`team a ${p >= 0.5 ? "fav" : ""}`}>{src.team1_name}</span>
          <span className="vs">vs</span>
          <span className={`team b ${p < 0.5 ? "fav" : ""}`}>{src.team2_name}</span>
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
      {pred && pred.per_map && (
        <div className="panel">
          <div className="panel-title">Per-map probabilities</div>
          <p className="note">
            The model predicts one map at a time; the headline number
            averages these over the current map pool (the veto isn't known
            when the prediction locks).
          </p>
          {Object.entries(pred.per_map).map(([m, v]) => (
            <div className="permap" key={m}>
              <span className="permap-name">{m}</span>
              <TugBar p={v} />
              <span className="permap-num">{fmtPct(v)}</span>
            </div>
          ))}
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

function Hero({ go }) {
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
        <rect x="140" y="330" width="920" height="6" rx="3"
          fill="url(#hgBar)" opacity="0.55" />
        <rect x="672" y="322" width="2" height="22" fill="#e7e2d9"
          opacity="0.6" />
      </svg>
      <div className="hero-inner">
        <div className="logo hero-logo">
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
        <p className="hero-copy">
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
    </div>
  );
}

export default function App() {
  const [tab, setTab] = useState("upcoming");
  const [openMatch, setOpenMatch] = useState(null);
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
      <Hero go={go} />
      {health?.synthetic_model && (
        <p className="warn">
          This is a demo model trained on made-up data. Not real
          predictions.
        </p>
      )}
      <nav>
        {["upcoming", "scoreboard", "model"].map((t) => (
          <button key={t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>
            {t}
          </button>
        ))}
      </nav>
      {openMatch ? (
        <MatchDetail id={openMatch} onBack={() => setOpenMatch(null)} />
      ) : (
        <>
          {tab === "upcoming" && <Upcoming onOpen={setOpenMatch} />}
          {tab === "scoreboard" && <Scoreboard onOpen={setOpenMatch} />}
          {tab === "model" && <ModelTab />}
        </>
      )}
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
