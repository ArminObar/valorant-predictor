import React from "react";
import { useParams, Link } from "react-router-dom";
import { useApi, fmtPct } from "../lib/useApi.js";
import { fmtTime } from "../time.js";

export function MatchDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const onBack = () =>
    location.key !== "default" ? navigate(-1) : navigate("/upcoming");
  const { data, err } = useApi(`/api/match/${encodeURIComponent(id)}`);
  if (err) return <p className="empty">API unreachable.</p>;
  if (!data) return <p className="empty">Loading&hellip;</p>;
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
          <span className="when">{fmtTime(src.start_ts)} &middot; Bo{src.best_of}</span>
        </div>
        <div className="teams big">
          <span className={`team a ${p >= 0.5 ? "fav" : ""}`}>
            <Tile name={src.team1_name} side="a" size="lg" />{src.team1_name}</span>
          <span className="vs">vs</span>
          <span className={`team b ${p < 0.5 ? "fav" : ""}`}>
            {src.team2_name}<Tile name={src.team2_name} side="b" size="lg" /></span>
        </div>
        <TugBar p={p} big />
        <div className="probs big">
          <span className="num a">{fmtPct(p)}</span>
          <span className="mid">
            locked {data.ledger ? fmtTime(data.ledger.made_at) : "pre-match"}
            {" "}&middot; Elo {fmtPct(src.p_elo)}
            {Boolean(src.low_history) && (
              <span className="badge" title={"Almost no history when this "
                + "locked. Kept in the record, not scored."}>low history</span>
            )}
          </span>
          <span className="num b">{fmtPct(1 - p)}</span>
        </div>
        {placeholder && (
          <p className="warn" style={{ margin: "12px 0 0" }}>
            This was an unresolved TBD slot when the prediction locked, so
            the model compared a team to itself. The first call per match
            never changes, so it stands, flagged low-history and never
            scored.
          </p>
        )}
        {graded && !placeholder && (
          <p className="note result-line" style={{ margin: "12px 0 0" }}>
            Result: <b>{winner}</b> won
            {data.ledger.maps_played ? ` in ${data.ledger.maps_played} maps` : ""}.
            The prediction above is exactly what was locked beforehand.
          </p>
        )}
        {!graded && data.ledger && (
          <p className="note" style={{ margin: "12px 0 0" }}>
            Frozen in the public ledger. It cannot change.
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
            Each bar is the map's Elo lean. Right favours {src.team1_name},
            left favours {src.team2_name}. The headline above is the call.
            {data.ledger ? " The headline is the frozen public call; these"
              + " rows are the current model's live view and can differ." : ""}
          </p>
          {(() => {
            const leans = pred.per_map_elo || null;
            const maxLean = leans ? Math.max(
              1, ...Object.values(leans).map((x) => Math.abs(x))) : 1;
            return Object.entries(pred.per_map).map(([m, v]) => {
              const lean = leans?.[m];
              if (lean == null) {
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
                    + `${m}. Negative favours ${src.team2_name}.`}>
                  <span className="permap-name">{m}</span>
                  <div className="lean-bar" aria-hidden="true">
                    <span className={`lean-fill ${side}`}
                      style={{ width: `${w}%` }} />
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
            <p className="note" style={{ margin: "12px 0 0" }}>
              Expected series length: {Object.entries(pred.maps_dist)
                .map(([k, v]) => `${k} maps ${fmtPct(v)}`).join(" \u00b7 ")}
            </p>
          )}
        </div>
      )}
      {data.picks && data.picks.length > 0 && (
        <div className="panel">
          <div className="panel-title">Market comparison</div>
          <div className="table-scroll">
          <table className="ledger">
            <thead>
              <tr><th>market</th><th>selection</th><th className="num">model</th>
                <th className="num">implied</th><th className="num">de-vig (cons)</th>
                <th className="num">EV</th></tr>
            </thead>
            <tbody>
              {data.picks.map((k) => (
                <tr key={`${k.market}-${k.line ?? ""}`}>
                  <td>{k.market === "maps_total" ? "map total" : "moneyline"}
                    <span className="dim"> &middot; {k.source}</span></td>
                  <td>{k.selection}
                    {k.source && <span className="badge dim">{k.source}</span>}
                    {k.ev_excluded === "totals_independence_bias" &&
                      <span className="badge" title={"Map totals assume "
                        + "maps are independent. Measured reality disagrees "
                        + "by about 7 points, so this EV is excluded until "
                        + "that is fixed."}>EV excluded</span>}</td>
                  <td className="num">{fmtPct(k.p_model)}</td>
                  <td className="num dim">{fmtPct(k.implied)}</td>
                  <td className="num dim">{fmtPct(k.shin_consensus ?? k.shin)}</td>
                  <td className={`num ${k.ev_excluded ? "dim"
                      : k.ev_pct >= 0 ? "ok" : "miss"}`}>
                    {k.ev_excluded ? "excluded"
                      : `${k.ev_pct > 0 ? "+" : ""}${k.ev_pct}%`}</td>
                </tr>
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
