import React from "react";
import { fmtPct } from "../lib/useApi.js";
import { metricLead } from "../compare.js";

export const fmt4 = (v) => (v == null ? "n/a" : v.toFixed(4));

/* Monogram for the team tile, derived from the team name. */

export const mono = (name) => {
  if (!name) return "?";
  const words = name.trim().split(/\s+/).filter(Boolean);
  const code = words.length >= 2
    ? words.map((w) => w[0]).join("").slice(0, 3)
    : name.slice(0, 3);
  return code.toUpperCase();
};

/* "in 4h" / "in 2d" countdown chip text; null once started. */

export const fmtEta = (ts) => {
  const ms = new Date(ts).getTime() - Date.now();
  if (ms <= 0) return null;
  const h = Math.round(ms / 3600000);
  if (h < 1) return "soon";
  if (h < 24) return `in ${h}h`;
  return `in ${Math.round(h / 24)}d`;
};

export function Tile({ name, side, size }) {
  return <span className={`tile ${side}${size ? ` ${size}` : ""}`}>{mono(name)}</span>;
}

/* Theme: system by default, toggle persists via theme.js. The stored
   choice is already applied pre-render by main.jsx, so this component
   only has to keep later changes in sync. */

export function TugBar({ p, big = false }) {
  return (
    <div className={`tug${big ? " big" : ""}`}>
      <div className="tug-fill" style={{ width: `${p * 100}%` }} />
      <div className="tug-notch" />
    </div>
  );
}

export function Metric({ label, model, elo, higher = false, pct = false }) {
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

export const Lead = ({ win, children }) =>
  win ? <span className="pill">{children}</span> : children;

export function FormDots({ recent }) {
  return (
    <span className="form">
      {recent.map((r, i) => (
        <span key={i} className={`dot ${r.won ? "w" : "l"}`}
          title={`${r.won ? "won" : "lost"} ${r.score} vs ${r.opponent} (${r.event})`} />
      ))}
    </span>
  );
}

