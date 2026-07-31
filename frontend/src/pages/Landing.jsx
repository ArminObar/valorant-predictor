import React from "react";
import { Link } from "react-router-dom";
import { Mark } from "../components/Mark.jsx";
import { ThemeToggle } from "../components/ThemeToggle.jsx";
import { useApi, fmtPct } from "../lib/useApi.js";
import { fmtTime } from "../time.js";

export const LAND_LINKS = [
  ["upcoming", "upcoming"],
  ["scoreboard", "scoreboard"],
  ["model", "model"],
  ["markets", "market picks"],
  ["backtest", "backtest"],
  ["how", "how it works"],
];


export function HeroNext({ onOpen }) {
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


export function Landing({ onOpen }) {
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
      <HeroNext onOpen={onOpen} />
    </div>
  );
}
