import React, { useEffect, useRef } from "react";
import { buildRatingChart } from "../chart.js";

export function RatingChart({ rh, team1 }) {
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

