import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import {
  Link, NavLink, Route, Routes,
  useLocation, useNavigate, useParams,
} from "react-router-dom";
import { fmtTime } from "./time.js";
import { InfoTip, TIPS } from "./components/InfoTip.jsx";
import { Mark } from "./components/Mark.jsx";
import { ThemeToggle } from "./components/ThemeToggle.jsx";
import { useApi, fmtPct } from "./lib/useApi.js";
import { Landing } from "./pages/Landing.jsx";
import { Upcoming } from "./pages/Upcoming.jsx";
import { Scoreboard } from "./pages/Scoreboard.jsx";
import { ModelTab } from "./pages/ModelTab.jsx";
import { MarketPicks } from "./pages/MarketPicks.jsx";
import { Backtest } from "./pages/Backtest.jsx";
import { MatchDetail } from "./pages/MatchDetail.jsx";
import { HowItWorks } from "./pages/HowItWorks.jsx";
import { NotFound } from "./pages/NotFound.jsx";
import { groupByDay } from "./daygroups.js";
import { metricLead, liveStanding } from "./compare.js";
import { readTheme, storeTheme, resolveMode, applyTheme } from "./theme.js";

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


function Tile({ name, side, size }) {
  return <span className={`tile ${side}${size ? ` ${size}` : ""}`}>{mono(name)}</span>;
}

/* Theme: system by default, toggle persists via theme.js. The stored
   choice is already applied pre-render by main.jsx, so this component
   only has to keep later changes in sync. */
function themeStorage() {
  try { return window.localStorage; } catch (e) { return null; }
}




function TugBar({ p, big = false }) {
  return (
    <div className={`tug${big ? " big" : ""}`}>
      <div className="tug-fill" style={{ width: `${p * 100}%` }} />
      <div className="tug-notch" />
    </div>
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

export default App;
