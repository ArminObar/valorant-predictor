import React, { useEffect, useRef, useState } from "react";
import {
  Link, NavLink, Route, Routes,
  useLocation, useNavigate, useParams,
} from "react-router-dom";
import { fmtTime } from "./time.js";
import { buildRatingChart } from "./chart.js";
import { summarizeBacktestTiers } from "./backtestSummary.js";
import { groupByDay } from "./daygroups.js";
import { metricLead, liveStanding } from "./compare.js";
import { readTheme, storeTheme, resolveMode, applyTheme } from "./theme.js";

const fmtPct = (p) => `${(p * 100).toFixed(1)}%`;
const fmt4 = (v) => (v == null ? "n/a" : v.toFixed(4));

/* Monogram for the team tile, derived from the team name. */
const mono = (name) => {
  if (!name) return "?";
  const words = name.trim().split(/\s+/).filter(Boolean);
  const code = words.length >= 2
    ? words.map((w) => w[0]).join("").slice(0, 3)
    : name.slice(0, 3);
  return code.toUpperCase();
};

/* "in 4h" / "in 2d" countdown chip text; null once started. */
const fmtEta = (ts) => {
  const ms = new Date(ts).getTime() - Date.now();
  if (ms <= 0) return null;
  const h = Math.round(ms / 3600000);
  if (h < 1) return "soon";
  if (h < 24) return `in ${h}h`;
  return `in ${Math.round(h / 24)}d`;
};

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

/* Brand mark: the teal/ember split probability bar. */
function Mark({ size = 17 }) {
  return (
    <svg className="mark" width={size} height={size} viewBox="0 0 20 20" aria-hidden="true">
      <rect x="1" y="7" width="11" height="6" rx="1.5" fill="var(--a)" />
      <rect x="13.6" y="7" width="5.4" height="6" rx="1.5" fill="var(--b)" />
    </svg>
  );
}

function Tile({ name, side, size }) {
  return <span className={`tile ${side}${size ? ` ${size}` : ""}`}>{mono(name)}</span>;
}

/* Theme: system by default, toggle persists via theme.js. The stored
   choice is already applied pre-render by main.jsx, so this component
   only has to keep later changes in sync. */
function themeStorage() {
  try { return window.localStorage; } catch (e) { return null; }
}
function ThemeToggle() {
  const [theme, setTheme] = useState(() => readTheme(themeStorage()));
  useEffect(() => { applyTheme(document, theme); }, [theme]);
  const sysLight = window.matchMedia
    && window.matchMedia("(prefers-color-scheme: light)").matches;
  const mode = resolveMode(theme, sysLight);
  const toggle = () => {
    const next = mode === "dark" ? "light" : "dark";
    storeTheme(themeStorage(), next);
    setTheme(next);
  };
  return (
    <button className="theme-btn" onClick={toggle} title="switch theme">
      <span className={`theme-dot ${mode}`} />{theme === "system" ? "auto" : theme}
    </button>
  );
}

/* Panel title with an "about" toggle that expands the long explanation. */
const TIPS = {
  upcoming: "Win probabilities locked at least five minutes before each "
    + "match starts. Once locked, a call never changes.",
  scoreboard: "Every locked call, graded after its match finishes, with an "
    + "Elo baseline scored on the same matches.",
  model: "The exact model serving right now: what it trained on and how "
    + "its probabilities are calibrated.",
  markets: "Locked model probabilities against captured sportsbook prices, "
    + "labeled unvalidated until the preregistered pick count grades. "
    + "Not betting advice.",
  backtest: "A simulated replay of two years of history, retrained on the "
    + "production schedule. Kept apart from the live scoreboard because a "
    + "simulation is not a live record.",
};

const DaySep = ({ label, today }) => (
  <div className={"day-sep" + (today ? " today" : "")}>
    <span>{label}</span>
  </div>
);
const DayRow = ({ label, span, today }) => (
  <tr className={"day-row" + (today ? " today" : "")}>
    <td colSpan={span}>{label}</td>
  </tr>
);

function InfoTip({ tip, label = "about this section" }) {
  const [pinned, setPinned] = useState(false);
  const [hover, setHover] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!pinned) return undefined;
    const away = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setPinned(false);
    };
    const esc = (e) => { if (e.key === "Escape") setPinned(false); };
    document.addEventListener("pointerdown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("pointerdown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [pinned]);
  const open = pinned || hover;
  const focusWithin = (e) =>
    setHover(ref.current ? ref.current.contains(e.target) : false);
  const blurAway = (e) => {
    if (ref.current && !ref.current.contains(e.relatedTarget)) {
      setHover(false); setPinned(false);
    }
  };
  return (
    <span className="infotip" ref={ref}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      onFocus={focusWithin} onBlur={blurAway}>
      <button type="button" className="i-btn" aria-expanded={open}
        aria-label={label} onClick={() => setPinned(!pinned)}>i</button>
      {open && (
        <span className="infotip-pop" role="note">
          {tip}{" "}
          <Link className="linklike" to="/how">full story: how it works</Link>
        </span>
      )}
    </span>
  );
}

function TitleWithInfo({ title, badge, info }) {
  return (
    <div className="panel-title">
      {title}{badge}
      <InfoTip tip={info} />
    </div>
  );
}

function TugBar({ p, big = false }) {
  return (
    <div className={`tug${big ? " big" : ""}`}>
      <div className="tug-fill" style={{ width: `${p * 100}%` }} />
      <div className="tug-notch" />
    </div>
  );
}

function UpcomingCard({ m, onOpen }) {
  const p = m.p_model;
  const fav = p >= 0.5 ? m.team1_name : m.team2_name;
  const eta = fmtEta(m.start_ts);
  const soon = eta && eta !== null && !eta.endsWith("d");
  return (
    <div className="card clickable" role="button" tabIndex={0}
      onClick={() => onOpen(m.match_id)}
      onKeyDown={(e) => e.key === "Enter" && onOpen(m.match_id)}>
      <div className="card-top">
        <span className="event">{m.event}</span>
        <span className="when">
          {eta && <span className={`eta${soon ? " soon" : ""}`}>{eta}</span>}
          {fmtTime(m.start_ts)} &middot; Bo{m.best_of}
        </span>
      </div>
      <div className="teams">
        <span className={`team a ${p >= 0.5 ? "fav" : ""}`}>
          <Tile name={m.team1_name} side="a" />{m.team1_name}</span>
        <span className="vs">vs</span>
        <span className={`team b ${p < 0.5 ? "fav" : ""}`}>
          {m.team2_name}<Tile name={m.team2_name} side="b" /></span>
      </div>
      <TugBar p={p} />
      <div className="probs">
        <span className="num a">{fmtPct(p)}</span>
        <span className="mid">
          pick <b>{fav}</b> &middot; Elo {fmtPct(m.p_elo)}
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
  if (!data) return <p className="empty">Loading&hellip;</p>;
  if (!data.predictions.length)
    return (
      <p className="empty">
        No upcoming predictions right now. New ones appear after the next
        refresh cycle.
      </p>
    );
  return (
    <>
      <div className="page-head">
        <h1>Upcoming<InfoTip tip={TIPS.upcoming} label="about upcoming" /></h1>
        <span className="page-sub">{data.predictions.length} locked predictions</span>
      </div>
      <p className="note">
        Locked at least five minutes before start. Frozen after.
        Model {data.model_version}, generated {fmtTime(data.generated_at)}.
      </p>
      {groupByDay(data.predictions, { dir: "asc" }).map((g) => (
        <React.Fragment key={g.key}>
          <DaySep label={g.label} today={g.isToday} />
          {g.rows.map((m) => (
            <UpcomingCard key={m.match_id} m={m} onOpen={onOpen} />
          ))}
        </React.Fragment>
      ))}
    </>
  );
}

function Metric({ label, model, elo, higher = false, pct = false }) {
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

/* Winner values in tier tables render as accent pills. */
const Lead = ({ win, children }) =>
  win ? <span className="pill">{children}</span> : children;

function MarketPicks({ standalone = false }) {
  const { data, err } = useApi("/api/markets");
  if (err) return standalone
    ? <p className="empty">API unreachable.</p> : null;
  if (!data) return standalone
    ? <p className="empty">Loading&hellip;</p> : null;
  const gate = data.gate || {};
  const s = data.summary;
  const picks = data.picks || [];
  return (
    <div className="panel">
      <TitleWithInfo title="Market picks: model vs real odds"
        info={TIPS.markets} />
      <p className="note">Locked model probability vs the captured price. Not betting advice.</p>
      {!gate.ev_validated && (
        <p className="warn">
          EV stays unvalidated until {gate.required} market-covered picks
          grade ({gate.n_graded} so far).
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
              {s.avg_ev_pct != null && <> &middot; avg EV {s.avg_ev_pct}%</>}
              {s.avg_clv_pct != null && <> &middot; avg CLV {s.avg_clv_pct}% &middot;
                beat close {fmtPct(s.beat_close_rate)}</>}
              . Flagged picks sit outside these averages.
            </p>
          )}
          <div className="table-scroll">
          <table className="ledger">
            <thead>
              <tr><th>match</th><th>selection</th><th className="num">model</th>
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
                  <td>{p.selection}
                    {p.source && <span className="badge dim">{p.source}</span>}
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
                      : `${p.ev_pct > 0 ? "+" : ""}${p.ev_pct}%`}</td>
                  <td className={p.graded ? (p.won ? "ok" : "miss") : "dim"}>
                    {p.graded ? (p.won ? "won \u2713" : "lost \u2717") : "pending"}
                    {p.graded && p.clv_pct != null &&
                      <span className="dim"> &middot; CLV {p.clv_pct > 0 ? "+" : ""}
                        {p.clv_pct}%</span>}
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

function Backtest() {
  const { data, err } = useApi("/api/backtest");
  if (err) return <p className="empty">API unreachable.</p>;
  if (!data) return <p className="empty">Loading&hellip;</p>;
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
      <TitleWithInfo title="Backtest: the system replayed over two years"
        badge={<span className="badge" title={"Computed after the fact from "
          + "stored data. You can't verify it the way you can the live "
          + "scoreboard, which is why the two are kept apart."}>
          simulated</span>}
        info={TIPS.backtest} />
      <p className="note">
        Two years replayed, worst stretch included. {w.n_predictions} simulated
        predictions, {w.n_retrains} retrains,
        {" "}{fmtTime(w.first_prediction)} to {fmtTime(w.last_prediction)}.
        Elo wins most of this history<LiveStandingClause />
      </p>
      <div className="table-scroll">
      <table className="ledger">
        <thead>
          <tr><th>tier</th><th className="num">n scored</th>
            <th className="num sep">model acc</th><th className="num">elo acc</th>
            <th className="num sep">model LL</th><th className="num">elo LL</th></tr>
        </thead>
        <tbody>
          {tiers.map(([tier, m]) => {
            const acc = metricLead(m.model_acc, m.elo_acc, true);
            const ll = metricLead(m.model_ll, m.elo_ll);
            return (
              <tr key={tier}>
                <td>{tier}</td>
                {m.n_scored ? (
                  <>
                    <td className="num">{m.n_scored}</td>
                    <td className="num sep"><Lead win={acc === "model"}>{fmtPct(m.model_acc)}</Lead></td>
                    <td className="num dim"><Lead win={acc === "elo"}>{fmtPct(m.elo_acc)}</Lead></td>
                    <td className="num sep"><Lead win={ll === "model"}>{m.model_ll.toFixed(4)}</Lead></td>
                    <td className="num dim"><Lead win={ll === "elo"}>{m.elo_ll.toFixed(4)}</Lead></td>
                  </>
                ) : (
                  <td colSpan={5} className="dim">no scored rows</td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
      </div>
      <p className="note" style={{ margin: 0 }}>
        tier1 is the top circuit, never pooled. Lower is better for log loss.
        The accent marks each comparison's leader; accuracy and log loss can
        disagree, and both marks stay.
        {data.synthetic_data && (
          <span className="badge">contains synthetic data</span>
        )}
      </p>
    </div>
  );
}

function LiveStandingClause() {
  const { data } = useApi("/api/scoreboard");
  const standing = liveStanding(data?.summary);
  const sb = (
    <Link className="linklike" to="/scoreboard">live scoreboard</Link>
  );
  if (standing === "ahead")
    return <>; the model is currently ahead on the {sb}.</>;
  if (standing === "behind")
    return <>; the model is currently behind on the {sb}.</>;
  if (standing === "mixed")
    return <>; the model is currently splitting the {sb} with Elo.</>;
  return <>. The {sb} tracks the same head-to-head live.</>;
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
      <p className="note" style={{ margin: 0 }}>
        Two years replayed as if live: {w.n_predictions} simulated
        predictions, worst stretches included, nothing trimmed to flatter
        the model. Elo wins {t.eloLeads} of {t.n} tiers on log loss.
        It never mixes into the live numbers above.{" "}
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
  if (!data) return <p className="empty">Loading&hellip;</p>;
  const s = data.summary;
  return (
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
                        <span className="badge" title={"Almost no history "
                          + "when this locked (often a TBD bracket slot). "
                          + "Kept in the record, not scored."}>low history</span>
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
          <div className="panel-title">Pending ({data.pending.length})</div>
          {groupByDay(data.pending, { dir: "asc" }).map((g) => (
            <React.Fragment key={g.key}>
              <DaySep label={g.label} today={g.isToday} />
              {g.rows.map((r) => (
            <div className="pending-row clickable" key={r.match_id}
                 role="button" tabIndex={0}
                 onClick={() => onOpen(r.match_id)}>
              <span>{r.team1_name} <span className="dim">vs</span> {r.team2_name}</span>
              <span className="dim">{fmtTime(r.start_ts)} &middot; model {fmtPct(r.p_model)}</span>
            </div>
              ))}
            </React.Fragment>
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

function ModelTab() {
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
      <div className="rc-legend">
        {g.lines.map((ln) => (
          <span key={ln.key} style={{ color: color(ln.key) }}>
            <span className="sw" style={{ background: color(ln.key) }} />{ln.name}
          </span>
        ))}
      </div>
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
              <circle key={i} cx={d.x} cy={d.y} r="2.5" fill={color(ln.key)}>
                <title>{`${ln.name}: ${d.rating} after ${d.won ? "a win"
                  : "a loss"} vs ${d.opponent}`}</title>
              </circle>
            ))}
            <text x={ln.end.x + 7} y={ln.end.y + 4} className="rc-end"
              fill={color(ln.key)}>{Math.round(ln.end.rating)}</text>
          </g>
        ))}
      </svg>
      <p className="note" style={{ margin: 0 }}>
        Elo (K={rh.k}) after each of the last {rh.n} matches. Context only;
        the locked call never moves.
      </p>
    </div>
  );
}

function MatchDetail() {
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
    <div className="hero-next" role="button" tabIndex={0}
      onClick={() => onOpen(next.match_id)}
      onKeyDown={(e) => e.key === "Enter" && onOpen(next.match_id)}>
      <span className="hero-next-top">
        <span className="hero-next-label">
          <span className="hero-next-dot" />next up</span>
        <span>{fmtTime(next.start_ts)}</span>
      </span>
      <span className="hero-next-teams">
        <Tile name={next.team1_name} side="a" size="sm" />
        {next.team1_name} <span className="dim">vs</span> {next.team2_name}
        <Tile name={next.team2_name} side="b" size="sm" />
      </span>
      <span className="hero-next-prob">
        {fmtPct(p >= 0.5 ? p : 1 - p)} {mono(fav)}
      </span>
    </div>
  );
}

function HowItWorks() {
  return (
    <div className="how">
      <div className="page-head"><h1>How it works</h1></div>
      <div className="panel">
        <div className="panel-title">The idea</div>
        <p>
          vpredict makes win probability calls on professional Valorant
          matches before they start, in public, and keeps score. Every
          number on this site is generated by the system from stored data.
          Nothing is typed in by hand. This page explains the machinery in
          plain language.
        </p>
      </div>
      <div className="panel">
        <div className="panel-title">Where the data comes from</div>
        <p>
          A small crawler reads vlr.gg, the community results site. It
          honors their robots.txt, waits at least 1.1 seconds between
          requests, and runs single file. Every fetched page is cached to
          disk, so nothing is downloaded twice. The store reaches back
          about two years and grows as matches finish.
        </p>
        <p>
          Match pages provide the raw material: map scores, attack and
          defense splits, first kills, and pistol rounds. That is what the
          features are built from.
        </p>
      </div>
      <div className="panel">
        <div className="panel-title">How predictions are made</div>
        <p>
          For each map, the model looks at the difference between the two
          teams as of that moment: recent round share, attack and defense
          efficiency, first kills, pistol rounds, rest days, roster
          stability, and Elo ratings overall and per map.
        </p>
        <p>
          One rule sits above everything. A feature may only use matches
          that finished before the match being predicted started. The same
          rule applies in training and in serving, and a test suite guards
          it. Per map probabilities are combined across the current map
          pool and pushed through the exact best-of math to produce a
          series probability.
        </p>
      </div>
      <div className="panel">
        <div className="panel-title">Training and calibration</div>
        <p>
          Splits are chronological, never shuffled. The model learns on
          the oldest matches, picks its settings on the next slice, and is
          judged once on the newest. Two candidates compete, a regularized
          logistic regression and a gradient boosted model, and validation
          decides which one ships.
        </p>
        <p>
          Calibration then adjusts the raw scores so probabilities mean
          what they say: across many matches called at 60 percent, about
          60 percent should be wins. A tuned Elo baseline is built from
          the same data as the yardstick. Beating it is the bar.
        </p>
      </div>
      <div className="panel">
        <div className="panel-title">The freeze rule</div>
        <p>
          The first accepted prediction for a match is the record. To be
          accepted it has to be made at least five minutes before the
          scheduled start. After that, nothing can change it. Not a
          retrain, not a better model, not new information. The scoreboard
          shows what the model said at the time, word for word.
        </p>
        <p>
          Without this rule a prediction site can quietly rewrite its
          history. With it, being wrong stays on the page.
        </p>
      </div>
      <div className="panel">
        <div className="panel-title">Grading</div>
        <p>
          When a match finishes, the crawler picks up the result and the
          frozen row is graded. Correct picks is the simple score. Log
          loss and Brier grade the confidence behind each pick, and they
          punish a confident miss much harder than a cautious one. Lower
          is better for both. The Elo baseline is graded at the same
          moments under the same rules.
        </p>
        <p>
          Predictions where either team had fewer than three recorded maps
          stay listed but are not scored. Those calls lean on defaults and
          would only add noise.
        </p>
      </div>
      <div className="panel">
        <div className="panel-title">The backtest, and why it stays separate</div>
        <p>
          The backtest replays the full two years of history. It walks
          forward through time, retrains on the production schedule, and
          predicts each match using only what was knowable at that moment.
          It answers one question: what would this system have done.
        </p>
        <p>
          It is still a simulation, computed after the fact. So it never
          mixes with the live scoreboard, which holds only calls made in
          real time before real matches. The full backtest is shown per
          tier, including the stretches where the baseline wins. Nothing
          is trimmed to flatter the model.
        </p>
      </div>
      <div className="panel">
        <div className="panel-title">Market picks</div>
        <p>
          Sportsbooks price some of the matches the model predicts. For
          those, the locked probability is compared with the captured
          price. EV is the locked probability times the decimal price,
          minus one. Positive means the price looked too generous against
          the model's view.
        </p>
        <p>
          The de-vig column strips the bookmaker's margin with Shin's
          method to show a fair probability. When more than one book
          priced a match, the pick takes the best captured price and names
          the book. Closing line value compares the entry price to the
          same book's closing price.
        </p>
        <p>
          All of it stays labeled unvalidated until a preregistered number
          of picks has graded, a threshold set before the first pick and
          never moved. Map totals are excluded from EV for now because
          their probabilities carry a measured bias. None of this is
          betting advice. It is a measurement of the model.
        </p>
      </div>
      <div className="panel">
        <div className="panel-title">The honesty rules</div>
        <p>
          A few rules hold everything together. Numbers are computed by
          scripts from stored data, never typed in. Evaluation is
          chronological only, with no peeking at the future, and the test
          window is read once. Findings that make the model look bad stay
          on record instead of being patched away.
        </p>
        <p>
          The code, the assumptions, and the bug log are public.{" "}
          <a className="linklike"
             href="https://github.com/ArminObar/valorant-predictor"
             target="_blank" rel="noreferrer">Read the source on GitHub.</a>
        </p>
      </div>
    </div>
  );
}

const LAND_LINKS = [
  ["upcoming", "upcoming"],
  ["scoreboard", "scoreboard"],
  ["model", "model"],
  ["markets", "market picks"],
  ["backtest", "backtest"],
];

function Landing({ onOpen }) {
  return (
    <div className="land">
      <div className="land-top"><ThemeToggle /></div>
      <div className="land-brand">
        <Mark size={38} />
        <h1 className="logo land-logo">
          <span className="logo-accent">v</span>predict
        </h1>
      </div>
      <div className="land-bar" aria-hidden="true" />
      <nav className="land-links" aria-label="site sections">
        {LAND_LINKS.map(([path, label], i) => (
          <Link className="land-link" key={path} to={`/${path}`}>
            <span className="land-num">{String(i + 1).padStart(2, "0")}</span>
            <span className="land-link-name">{label}</span>
            <span className="land-link-arrow" aria-hidden="true">&rarr;</span>
          </Link>
        ))}
      </nav>
      <Link className="land-how" to="/how">
        new here? read how it works &rarr;
      </Link>
      <HeroNext onOpen={onOpen} />
    </div>
  );
}

function SiteHeader() {
  return (
    <header>
      <Link className="logo site-logo" to="/" title="back to the homepage">
        <Mark size={17} /><span><span className="logo-accent">v</span>predict</span>
      </Link>
      <ThemeToggle />
    </header>
  );
}

function ScrollToTop() {
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
  const openMatch = (id) => navigate(`/match/${encodeURIComponent(id)}`);
  const landing = pathname === "/";
  if (landing) {
    return (
      <>
        <Landing onOpen={openMatch} />
        {health?.synthetic_model && (
          <p className="warn wrap">
            Demo model trained on made-up data. Not real predictions.
          </p>
        )}
      </>
    );
  }
  return (
    <>
      <div className="wrap">
        <ScrollToTop />
        <SiteHeader />
        {health?.synthetic_model && (
          <p className="warn">
            Demo model trained on made-up data. Not real predictions.
          </p>
        )}
        <nav className="tabs">
          {["upcoming", "scoreboard", "model", "markets", "backtest"]
            .map((t) => (
              <NavLink key={t} to={`/${t}`}
                className={({ isActive }) => (isActive ? "on" : "")}>
                {t}
              </NavLink>
            ))}
        </nav>
        <Routes>
          <Route path="/" element={<Landing onOpen={openMatch} />} />
          <Route path="/upcoming" element={<Upcoming onOpen={openMatch} />} />
          <Route path="/scoreboard" element={<Scoreboard onOpen={openMatch} />} />
          <Route path="/model" element={<ModelTab />} />
          <Route path="/markets" element={<MarketPicks standalone />} />
          <Route path="/backtest" element={<Backtest />} />
          <Route path="/how" element={<HowItWorks />} />
          <Route path="/match/:id" element={<MatchDetail />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </div>
      <footer>
        Data from vlr.gg. Predictions lock before each match; the first call
        stands. Not affiliated with Riot Games. Not betting advice.{" "}
        <Link className="repo-link" to="/how">how it works</Link>{" \u00b7 "}
        <a className="repo-link"
           href="https://github.com/ArminObar/valorant-predictor"
           target="_blank" rel="noreferrer">source on GitHub</a>
      </footer>
    </>
  );
}
